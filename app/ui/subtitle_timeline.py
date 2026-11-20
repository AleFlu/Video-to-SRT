"""
subtitle_timeline.py — Pannello timeline sottotitoli (A2).

Estrae la logica di tabella + toolbar da editor_panel.py in un widget
autonomo. Pensato per vivere nel pannello inferiore del layout DaVinci.

API pubblica:
  load_subtitles(subtitles)
  get_subtitles() → list[Subtitle]
  is_modified() → bool
  mark_saved() / mark_modified()
  set_player(player) / set_loop(bool)

Il QUndoStack è interno (uno per progetto). Le scorciatoie globali (undo, dividi,
trova, esporta…) NON sono registrate qui: appartengono alle azioni di menu della
MainWindow, che le inoltrano al progetto attivo. Qui restano solo le QShortcut
di riproduzione, attive solo quando la timeline è visibile.
"""

from __future__ import annotations
import bisect
import logging
from typing import List, Optional

from PySide6.QtCore import (
    Qt, Signal, QByteArray, QEvent, QModelIndex, QObject, QRect, QSettings, QSize, QTimer,
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QFont, QFontMetrics, QKeySequence, QPainter, QUndoStack, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QMainWindow, QTableView,
    QToolBar, QToolButton, QHeaderView, QAbstractItemView, QStyle, QStyledItemDelegate,
    QPushButton, QSizePolicy, QMenu, QLineEdit, QFileDialog, QLabel, QStackedLayout,
)

from core.subtitle_model import Subtitle
from core.subtitle_table_model import (
    SubtitleTableModel, COL_INDEX, COL_START, COL_END, COL_DUR, COL_CPS, COL_TEXT,
    ISSUE_EMPTY, ISSUE_END_BEFORE_START, ISSUE_OVERLAP, ISSUE_TOO_FAST, ISSUE_TOO_SHORT,
)
from core.transcription_config import active_readability
from core.undo_commands import (
    EditFieldCommand, DeleteSubtitleCommand,
    SplitSubtitleCommand, MergeWithNextCommand, ReplaceAllCommand
)
from core.audio_player import AudioPlayer

from ui.inspector_widget import InspectorWidget
from ui.find_replace_dialog import FindReplaceDialog
from ui.transport_bar import RATE_STEPS
from ui.widgets import focus_owns_key, forward_key, protect_extension_buttons
from ui import icons, theme
import platform_support

_sl = platform_support.shortcut_label

# Misure del mockup (px)
_TOOLBAR_HEIGHT = 42
_BTN_HEIGHT = 28
_SEARCH_WIDTH = 250
_SEARCH_WIDTH_COMPACT = 150
_SEARCH_WIDTH_MIN = 120
# Livelli di compattezza della toolbar quando la finestra è stretta: prima spariscono le
# scorciatoie disegnate, poi i testi (resta l'icona, il nome è nel tooltip), infine la
# ricerca si accorcia. Così ricerca ed Esporta non finiscono mai nel menu di overflow.
TOOLBAR_LEVELS = 5
_ROW_HEIGHT = 34
_HINT_PAD = 9    # padding laterale dei pulsanti
_HINT_GAP = 6    # spazio tra testo e scorciatoia

# Ritardo con cui si raggruppano gli aggiornamenti O(N) (status, overlay preview)
SYNC_DEBOUNCE_MS = 50

# Tasti di riproduzione (QShortcut della timeline): (nome, sequenza, metodo)
PLAYBACK_KEYS = (
    ("play_pause", "Space", "_shortcut_play_pause"),
    ("pause", "K", "_jkl_k"),
    ("rewind", "J", "_jkl_j"),
    ("forward", "L", "_jkl_l"),
    ("seek_back", "Left", "_seek_back"),
    ("seek_forward", "Right", "_seek_forward"),
    ("prev_subtitle", "Shift+Left", "_go_prev_sub"),
    ("next_subtitle", "Shift+Right", "_go_next_sub"),
)

# Nome colore del modello → token del tema
_MODEL_COLOR_TOKENS = {
    "row_error_bg":   "row_error_bg",
    "row_warning_bg": "row_warning_bg",
    "cps_error_fg":   "err",
    "cps_warning_fg": "warn",
    "index_fg":       "muted",
}


def theme_color_provider(name: str) -> Optional[QColor]:
    """Provider colori per SubtitleTableModel basato sui token del tema corrente."""
    token = _MODEL_COLOR_TOKENS.get(name)
    return theme.qcolor(token) if token else None

logger = logging.getLogger(__name__)


# ── Parole d'avviso della cella Testo ─────────────────────────────────────────
# codice problema del modello → (parola breve, token colore). Il rosso è anche il
# colore del CPS oltre il massimo; il giallo segnala gli avvisi.
_ISSUE_WORDS = {
    ISSUE_EMPTY:            ("vuoto", "err"),
    ISSUE_END_BEFORE_START: ("tempi errati", "err"),
    ISSUE_OVERLAP:          ("sovrapposto", "err"),
    ISSUE_TOO_FAST:         ("troppo veloce", "err"),
    ISSUE_TOO_SHORT:        ("troppo breve", "warn"),
}
# Ordine di precedenza quando una riga ha più problemi (ne compare uno solo)
_ISSUE_PRIORITY = (ISSUE_EMPTY, ISSUE_END_BEFORE_START, ISSUE_OVERLAP,
                   ISSUE_TOO_FAST, ISSUE_TOO_SHORT)


def issue_word(codes, cps: Optional[float] = None) -> Optional[tuple]:
    """
    Parola breve (e token colore) per i problemi di una riga, ricavata dai codici di
    `SubtitleTableModel.row_issue_codes`. Senza codici, un CPS sopra la soglia di
    avviso ma sotto il massimo dà "veloce". None se la riga è a posto.
    """
    for code in _ISSUE_PRIORITY:
        if code in codes:
            return _ISSUE_WORDS[code]
    if cps is not None and cps > active_readability().warn_cps:
        return ("veloce", "warn")
    return None


# ── Suggerimenti di scorciatoia (mono, a destra del testo) ────────────────────

def _hint_font() -> QFont:
    f = QFont(platform_support.mono_font_family())
    f.setPixelSize(11)
    return f


def _hint_width(hint: str) -> int:
    return QFontMetrics(_hint_font()).horizontalAdvance(hint) if hint else 0


def _paint_hint(widget: QWidget, hint: str) -> None:
    """Disegna la scorciatoia mono da 11 px allineata a destra del pulsante."""
    if not hint:
        return
    active = widget.underMouse() or (isinstance(widget, QAbstractButton) and widget.isChecked())
    if not widget.isEnabled():
        token = "faint"
    else:
        token = "dim" if active else "label"   # `label` non va su sfondi rialzati
    p = QPainter(widget)
    try:
        p.setFont(_hint_font())
        p.setPen(theme.qcolor(token))
        p.drawText(QRect(0, 0, widget.width() - _HINT_PAD, widget.height()),
                   Qt.AlignRight | Qt.AlignVCenter, hint)
    finally:
        p.end()


class _HintButton(QPushButton):
    """Pulsante della toolbar: icona + testo e, a destra, la scorciatoia in mono."""

    def __init__(self, text: str, hint: str = "", parent=None):
        super().__init__(text, parent)
        self._hint = hint
        self._full_text = text
        self._show_hint = True
        self.setObjectName("tbButton")

    def hint(self) -> str:
        return self._hint if self._show_hint else ""

    def set_compact(self, level: int) -> None:
        """0 completo · 1 senza scorciatoia · 2+ solo icona."""
        self._show_hint = level < 1
        self.setText(self._full_text if level < 2 else "")

    def paintEvent(self, event):  # noqa: N802 (override Qt)
        super().paintEvent(event)
        _paint_hint(self, self.hint())


class _HintToolButton(QToolButton):
    """Come `_HintButton`, per l'azione dell'Ispettore (QToolButton con azione di default)."""

    def __init__(self, hint: str = "", parent=None):
        super().__init__(parent)
        self._hint = hint
        self._show_hint = True
        self.setObjectName("tbInspector")

    def hint(self) -> str:
        return self._hint if self._show_hint else ""

    def set_compact(self, level: int) -> None:
        self._show_hint = level < 1
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if level < 2
                                else Qt.ToolButtonIconOnly)

    def paintEvent(self, event):  # noqa: N802 (override Qt)
        super().paintEvent(event)
        _paint_hint(self, self.hint())


class _ToolbarFitter(QObject):
    """Al ridimensionamento della toolbar sceglie quanto compattarla (vedi fit_toolbar)."""

    def __init__(self, timeline: "SubtitleTimeline"):
        super().__init__(timeline)
        self._timeline = timeline

    def eventFilter(self, obj, event):  # noqa: N802 (override Qt)
        if event.type() in (QEvent.Resize, QEvent.Show):
            self._timeline.fit_toolbar()
        return False


class _SearchField(QLineEdit):
    """Campo di ricerca della toolbar: icona a sinistra e scorciatoia a destra (se vuoto)."""

    def __init__(self, hint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("tbSearch")
        self._hint_lbl = QLabel(hint, self)
        self._hint_lbl.setObjectName("tbSearchHint")
        self._hint_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.textChanged.connect(self._sync_hint)
        self._watched: set = set()      # pulsantini interni già sorvegliati
        self._centering = False

    def _sync_hint(self, text: str) -> None:
        self._hint_lbl.setVisible(not text)

    def _center_side_buttons(self) -> None:
        """Centra in verticale i pulsantini interni di Qt (lente, cancella): Qt li mette
        qualche px sotto il centro nei campi più bassi del suo pulsante (26–28 px) e li
        riposiziona da sé (testo, compattazione della toolbar): li si ricentra a ogni
        spostamento."""
        if self._centering:
            return
        self._centering = True
        try:
            for b in self.findChildren(QToolButton, options=Qt.FindDirectChildrenOnly):
                if b not in self._watched:
                    self._watched.add(b)
                    b.installEventFilter(self)
                h = min(b.height(), self.height())
                y = (self.height() - h) // 2
                if (b.y(), b.height()) != (y, h):
                    b.setGeometry(b.x(), y, b.width(), h)
        finally:
            self._centering = False

    def eventFilter(self, obj, event):  # noqa: N802 (override Qt)
        if obj in self._watched and event.type() in (QEvent.Move, QEvent.Resize,
                                                     QEvent.Show):
            self._center_side_buttons()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        w = self._hint_lbl.sizeHint().width()
        self._hint_lbl.setGeometry(self.width() - w - 8, 0, w, self.height())
        self._center_side_buttons()

    def actionEvent(self, event):  # noqa: N802 (override Qt)
        super().actionEvent(event)
        self._center_side_buttons()

    def sizeHint(self):  # noqa: N802 (override Qt)
        return QSize(_SEARCH_WIDTH, _BTN_HEIGHT)


# ── Delegato della tabella: solo disegno (l'editing resta quello di default) ──

class _TableDelegate(QStyledItemDelegate):
    """
    Disegna le celle come nel mockup: solo la linea sotto la riga, numeri in mono,
    riga selezionata su `sel` con barra d'accento da 2 px a sinistra e, nella colonna
    Testo, la parola d'avviso a destra nel colore della gravità.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mono = QFont(platform_support.mono_font_family())
        self._mono.setPixelSize(13)
        self._ui = QFont(platform_support.ui_font_family())
        self._ui.setPixelSize(13)
        self._small = QFont(platform_support.ui_font_family())
        self._small.setPixelSize(11)

    def paint(self, painter, option, index):  # noqa: N802 (override Qt)
        painter.save()
        try:
            self._paint_cell(painter, option, index)
        finally:
            painter.restore()

    def _paint_cell(self, painter, option, index):
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        col = index.column()

        if selected:
            painter.fillRect(rect, theme.qcolor("sel"))
        else:
            tint = index.data(Qt.BackgroundRole)
            if isinstance(tint, QBrush):
                painter.fillRect(rect, tint)
        painter.fillRect(rect.x(), rect.bottom(), rect.width(), 1, theme.qcolor("line"))
        if selected and col == COL_INDEX:
            painter.fillRect(rect.x(), rect.y(), 2, rect.height(), theme.qcolor("acc"))

        text = str(index.data(Qt.DisplayRole) if index.data(Qt.DisplayRole) is not None else "")
        inner = rect.adjusted(10, 0, -10, 0)
        if col == COL_TEXT:
            self._paint_text_cell(painter, inner, index, text, selected)
            return

        painter.setFont(self._mono)
        if col == COL_INDEX:
            color = theme.qcolor("dim" if selected else "muted")
        elif col == COL_DUR:
            color = theme.qcolor("dim")
        elif col == COL_CPS:
            fg = index.data(Qt.ForegroundRole)
            color = fg.color() if isinstance(fg, QBrush) else theme.qcolor("text")
        else:
            color = theme.qcolor("text")
        painter.setPen(color)
        elided = painter.fontMetrics().elidedText(text, Qt.ElideRight, inner.width())
        painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter, elided)

    def _paint_text_cell(self, painter, inner, index, text, selected):
        model = index.model()
        word = None
        try:
            sub = model.subtitle_at(index.row())
            cps = (len(sub.text.strip()) / sub.duration
                   if sub is not None and sub.duration > 0 and sub.text.strip() else None)
            word = issue_word(model.row_issue_codes(index.row()), cps)
        except AttributeError:   # modello diverso da SubtitleTableModel: nessuna parola
            pass

        text_w = inner.width()
        if word is not None:
            painter.setFont(self._small)
            word_w = painter.fontMetrics().horizontalAdvance(word[0])
            painter.setPen(theme.qcolor(word[1]))
            painter.drawText(inner, Qt.AlignRight | Qt.AlignVCenter, word[0])
            text_w = max(0, inner.width() - word_w - 8)

        painter.setFont(self._ui)
        flat = text.replace("\n", " ")
        if flat.strip():
            painter.setPen(theme.qcolor("text"))
            shown = flat
        else:
            painter.setPen(theme.qcolor("dim" if selected else "label"))
            shown = "Testo vuoto"
        elided = painter.fontMetrics().elidedText(shown, Qt.ElideRight, text_w)
        painter.drawText(QRect(inner.x(), inner.y(), text_w, inner.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, elided)


class SubtitleTimeline(QWidget):
    """
    Timeline sottotitoli con toolbar compatta integrata.
    Usa un QMainWindow interno per supportare il QDockWidget dell'Inspector.
    """

    subtitles_changed = Signal()
    jkl_pressed = Signal(str)   # "J" | "K" | "L"
    status_text = Signal(str)   # testo per la status bar esterna
    import_requested = Signal(str)   # path scelto con "+ Importa" (gestito da ProjectWidget)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.model = SubtitleTableModel()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(500)

        self.model.set_color_provider(theme_color_provider)

        self._find_dialog: FindReplaceDialog | None = None

        # Player: quello della preview, collegato da WorkspaceWidget con set_player().
        self.player: AudioPlayer | None = None
        self._loop = False

        # Indice ordinato per inizio (bisect) per trovare il sottotitolo al playhead
        self._time_index: list | None = None   # [(start, end, row)] ordinati
        self._time_starts: list = []

        # Aggiornamento status raggruppato (debounce)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(SYNC_DEBOUNCE_MS)
        self._status_timer.timeout.connect(self._update_status)

        # Layout radice — QMainWindow interno per QDockWidget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._root_layout = layout

        self._inner = QMainWindow()
        self._inner.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks
        )
        layout.addWidget(self._inner)

        # Stato vuoto: tabella senza righe (es. tutti i sottotitoli eliminati)
        self._empty_lbl = QLabel(
            "Nessun sottotitolo.\nImporta un file SRT o annulla l'ultima eliminazione "
            f"({_sl('Ctrl+Z')})."
        )
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setWordWrap(True)

        self._build_toolbar()
        layout.insertWidget(0, self._toolbar)

        # TableView
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(False)
        self.view.setShowGrid(False)
        self.view.setItemDelegate(_TableDelegate(self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.view.verticalHeader().setVisible(False)
        # Tab esce dalla tabella (non salta di cella in cella: nessuna trappola per la
        # tastiera); ↑/↓ cambiano riga, F2/Invio modificano la cella
        self.view.setTabKeyNavigation(False)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideRight)
        # Righe da 34 px (mockup); almeno una riga di testo con font grandi / HiDPI
        line_h = self.view.fontMetrics().lineSpacing()
        self.view.verticalHeader().setDefaultSectionSize(max(_ROW_HEIGHT, line_h + 12))
        self.view.setAccessibleName("Elenco sottotitoli")

        self._setup_header()

        central = QWidget()
        self._central_stack = QStackedLayout(central)
        self._central_stack.addWidget(self.view)
        self._central_stack.addWidget(self._empty_lbl)
        self._inner.setCentralWidget(central)

        # Inspector: istanza unica, collegata qui all'undo stack (_wire). WorkspaceWidget
        # si limita a inserirla nel proprio splitter.
        self.inspector = InspectorWidget()
        self.inspector.bind_model(self.model)

        # Nessuna status bar interna — evita il doppio footer con QStatusBar di MainWindow.
        # Lo stato viene emesso via status_text signal.

        self._wire()

    # ---- Intestazione tabella: larghezze colonne persistite ----

    _HEADER_KEY = "subtitle_table_header"

    def _apply_header_modes(self):
        h = self.view.horizontalHeader()
        for col in (COL_INDEX, COL_START, COL_END, COL_DUR, COL_CPS):
            h.setSectionResizeMode(col, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        h.setStretchLastSection(True)
        h.setSectionsMovable(False)
        # allineamento e altezza anche dopo restoreState (lo stato salvato li include)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setFixedHeight(30)

    def _setup_header(self):
        """Colonne ridimensionabili (testo elastico); larghezze ripristinate dalle preferenze."""
        h = self.view.horizontalHeader()
        self._apply_header_modes()
        fm = self.view.fontMetrics()
        # Larghezze del mockup (52 / 108 / 108 / 84 / 70), allargate se il testo non ci sta
        samples = {COL_INDEX: ("0000", 52), COL_START: ("00:00.000", 108),
                   COL_END: ("00:00.000", 108), COL_DUR: ("00,00 s", 84), COL_CPS: ("000,0", 70)}
        for col, (sample, width) in samples.items():
            h.resizeSection(col, max(width, fm.horizontalAdvance(sample) + 24))
        self._restore_header_state()

        self._header_timer = QTimer(self)
        self._header_timer.setSingleShot(True)
        self._header_timer.setInterval(400)
        self._header_timer.timeout.connect(self._save_header_state)
        h.sectionResized.connect(self._schedule_header_save)

    def _schedule_header_save(self, *_a):
        self._header_timer.start()

    def _save_header_state(self):
        try:
            QSettings("VideoSRT", "v2").setValue(
                self._HEADER_KEY, self.view.horizontalHeader().saveState())
        except Exception:  # noqa: BLE001
            logger.warning("Salvataggio larghezze colonne fallito", exc_info=True)

    def _restore_header_state(self):
        """Ripristina lo stato salvato; uno stato assente, vecchio o invalido è ignorato."""
        h = self.view.horizontalHeader()
        try:
            state = QSettings("VideoSRT", "v2").value(self._HEADER_KEY)
            if isinstance(state, (bytes, bytearray)):
                state = QByteArray(bytes(state))
            if isinstance(state, QByteArray) and not state.isEmpty():
                h.restoreState(state)
        except Exception:  # noqa: BLE001
            logger.warning("Larghezze colonne salvate non valide: ignorate", exc_info=True)
        # uno stato vecchio non deve nascondere colonne né cambiare le modalità
        for col in range(h.count()):
            h.setSectionHidden(col, False)
        self._apply_header_modes()

    # ---- Toolbar ----

    def _build_toolbar(self):
        self._tb_buttons = []   # pulsanti con icona + testo + scorciatoia da ri-tematizzare

        tb = QToolBar("TimelineToolbar", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setFixedHeight(_TOOLBAR_HEIGHT)
        # Il pulsante "»" di overflow non deve usare l'icona di sistema (crash su macOS)
        protect_extension_buttons(tb)

        # ── Undo / Redo ────────────────────────────────────────────────────────
        # Nessuna scorciatoia qui: Ctrl+Z / redo sono le azioni del menu Modifica
        # (QUndoGroup della MainWindow), altrimenti sarebbero ambigue.
        # Azioni del toolbar: solo icona, nome accessibile e tooltip completi
        self.act_undo = QAction("Annulla", self)
        icons.bind_icon(self.act_undo, "undo", "dim")
        self.act_undo.triggered.connect(self.undo_stack.undo)
        self.act_undo.setEnabled(False)
        self.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)
        self.act_redo = QAction("Ripeti", self)
        icons.bind_icon(self.act_redo, "redo", "dim")
        self.act_redo.triggered.connect(self.undo_stack.redo)
        self.act_redo.setEnabled(False)
        self.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)
        self.undo_stack.undoTextChanged.connect(self._sync_undo_tips)
        self.undo_stack.redoTextChanged.connect(self._sync_undo_tips)
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        for act, label in ((self.act_undo, "Annulla"), (self.act_redo, "Ripeti")):
            btn = tb.widgetForAction(act)
            if btn is not None:
                btn.setAccessibleName(label)
                btn.setFocusPolicy(Qt.TabFocus)   # la toolbar li crea fuori dalla catena di Tab
        self._sync_undo_tips()
        tb.addSeparator()

        # ── Operazioni sottotitoli ─────────────────────────────────────────────
        # Le scorciatoie indicate nei tooltip sono registrate dalla MainWindow.
        # Il suggerimento mono a destra è solo disegnato: nome accessibile = solo il nome.
        def _tb_btn(text, name, tooltip, icon_name, hint=""):
            b = _HintButton(text, hint)
            icons.bind_icon(b, icon_name, "text")
            b.setToolTip(tooltip)
            b.setAccessibleName(name)
            b.setCursor(Qt.PointingHandCursor)
            self._tb_buttons.append(b)
            return b

        btn_split = _tb_btn("Dividi", "Dividi",
                            f"Dividi sottotitolo al cursore  {_sl('Ctrl+K')}", "split",
                            _sl("Ctrl+K"))
        btn_split.clicked.connect(self._split_current)
        tb.addWidget(btn_split)

        btn_merge = _tb_btn("Unisci", "Unisci", f"Unisci al successivo  {_sl('Ctrl+M')}", "merge",
                            _sl("Ctrl+M"))
        btn_merge.clicked.connect(self._merge_next)
        tb.addWidget(btn_merge)

        btn_del = _tb_btn("Elimina", "Elimina",
                          f"Elimina selezionati  {_sl('Ctrl+Shift+K')}  ·  Canc", "trash",
                          _sl("Ctrl+Shift+K"))
        btn_del.clicked.connect(self._delete_selected)
        tb.addWidget(btn_del)

        tb.addSeparator()

        # ── Importa ────────────────────────────────────────────────────────────
        btn_import = _tb_btn("Importa", "Importa", "Importa file SRT o progetto .v2srt", "import")
        btn_import.clicked.connect(self._import_file)
        tb.addWidget(btn_import)

        # ── Trova e sostituisci ────────────────────────────────────────────────
        self.btn_find_replace = _tb_btn(
            "Sostituisci", "Trova e sostituisci", f"Trova e sostituisci  {_sl('Ctrl+Alt+F')}",
            "replace", _sl("Ctrl+Alt+F"),
        )
        self.btn_find_replace.clicked.connect(self.open_find_replace)
        tb.addWidget(self.btn_find_replace)

        tb.addSeparator()

        # ── Inspector toggle ───────────────────────────────────────────────────
        self.act_toggle_insp = QAction("Ispettore", self)
        icons.bind_icon(self.act_toggle_insp, "panel_right", "text")
        self.act_toggle_insp.setCheckable(True)
        self.act_toggle_insp.setChecked(True)
        self.act_toggle_insp.setToolTip(f"Mostra/nascondi Ispettore  {_sl('Ctrl+I')}")
        # Il toggle_insp ora controlla l'inspector esterno — segnale gestito da workspace.
        # Acceso = sfondo `raise` (QToolButton:checked); il suggerimento ⌘I è disegnato a destra.
        self._insp_btn = _HintToolButton(_sl("Ctrl+I"))
        self._insp_btn.setDefaultAction(self.act_toggle_insp)
        self._insp_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._insp_btn.setIconSize(QSize(16, 16))
        self._insp_btn.setCursor(Qt.PointingHandCursor)
        tb.addWidget(self._insp_btn)

        # ── Spacer ────────────────────────────────────────────────────────────
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # ── Ricerca inline ────────────────────────────────────────────────────
        self._search_box = _SearchField(_sl("Ctrl+F"))
        self._search_box.setPlaceholderText("Cerca sottotitolo…")
        self._search_box.setAccessibleName("Cerca nei sottotitoli")
        self._search_box.setFixedSize(_SEARCH_WIDTH, _BTN_HEIGHT)
        self._search_box.setClearButtonEnabled(True)
        self._search_icon = QAction(self._search_box)
        icons.bind_icon(self._search_icon, "search", "dim")
        self._search_box.addAction(self._search_icon, QLineEdit.LeadingPosition)
        self._search_box.textChanged.connect(self._on_search)
        self._search_box.returnPressed.connect(self._on_search_next)
        self._search_box.setToolTip(f"Cerca nel testo  {_sl('Ctrl+F')}")
        tb.addWidget(self._search_box)
        self._search_idx = -1   # indice corrente ricerca

        # ── Esporta (btn + freccia dropdown, separati da 1 px) ────────────────
        split = QWidget()
        split.setStyleSheet("background: transparent;")
        split_lay = QHBoxLayout(split)
        split_lay.setContentsMargins(8, 0, 0, 0)
        split_lay.setSpacing(1)

        self._export_btn = QPushButton("Esporta SRT")
        icons.bind_icon(self._export_btn, "export", "acc_ink")
        self._export_btn.setToolTip(f"Esporta SRT  {_sl('Ctrl+S')}")
        self._export_btn.setAccessibleName("Esporta SRT")
        self._export_btn.setCursor(Qt.PointingHandCursor)
        split_lay.addWidget(self._export_btn)

        self._export_arrow = QPushButton()
        icons.bind_icon(self._export_arrow, "chevron_down", "acc_ink", 14)
        self._export_arrow.setToolTip("Scegli formato di esportazione")
        self._export_arrow.setAccessibleName("Altri formati di esportazione")
        self._export_arrow.setFixedWidth(28)
        self._export_arrow.setCursor(Qt.PointingHandCursor)
        self._export_arrow.clicked.connect(self._show_export_menu)
        split_lay.addWidget(self._export_arrow)
        tb.addWidget(split)

        # ── Actions ────────────────────────────────────────────────────────────
        self.act_export = QAction("Esporta SRT", self)
        self._export_btn.clicked.connect(self.act_export.trigger)

        self.act_export_vtt   = QAction("Esporta VTT…", self)
        self.act_export_txt   = QAction("Esporta TXT…", self)
        self.act_export_ass   = QAction("Esporta ASS…", self)
        self.act_export_v2srt = QAction("Salva progetto .v2srt…", self)

        # Azioni senza scorciatoia: la MainWindow le invoca sul progetto attivo
        self.act_split  = QAction("Dividi", self)
        self.act_split.triggered.connect(self._split_current)
        self.act_merge  = QAction("Unisci", self)
        self.act_merge.triggered.connect(self._merge_next)
        self.act_delete = QAction("Elimina", self)
        self.act_delete.triggered.connect(self._delete_selected)
        self.act_find   = QAction("Trova", self)
        self.act_find.triggered.connect(self.focus_search)
        self.act_find_replace = QAction("Trova e sostituisci…", self)
        self.act_find_replace.triggered.connect(self.open_find_replace)

        self._toolbar = tb
        self._toolbar_level = 0
        self._fitting_toolbar = False
        self._toolbar_fitter = _ToolbarFitter(self)
        tb.installEventFilter(self._toolbar_fitter)
        self._apply_toolbar_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_toolbar_palette)

    def toolbar(self) -> QToolBar:
        """La toolbar (42 px) dell'editor."""
        return self._toolbar

    def focus_chain(self) -> list:
        """Controlli nell'ordine di Tab: toolbar (sinistra → destra), ricerca, tabella, inspector."""
        tb = self._toolbar
        chain = [tb.widgetForAction(self.act_undo), tb.widgetForAction(self.act_redo),
                 *self._tb_buttons, self._insp_btn, self._search_box,
                 self._export_btn, self._export_arrow, self.view]
        chain += self.inspector.focus_chain()
        return [w for w in chain if w is not None]

    def detach_toolbar(self) -> QToolBar:
        """
        Stacca la toolbar dal widget e la restituisce: il workspace la mette a tutta
        larghezza sopra tabella e ispettore. Gli oggetti e i collegamenti restano gli stessi.
        """
        self._root_layout.removeWidget(self._toolbar)
        self._toolbar.setParent(None)
        return self._toolbar

    def _sync_undo_tips(self, *_):
        u, r = self.undo_stack.undoText(), self.undo_stack.redoText()
        self.act_undo.setToolTip(f"Annulla{(' ' + u) if u else ''}  {_sl('Ctrl+Z')}")
        self.act_redo.setToolTip(f"Ripeti{(' ' + r) if r else ''}  {_sl('Ctrl+Shift+Z')}")

    def _apply_toolbar_palette(self):
        c = theme.c
        self._toolbar.setStyleSheet(
            "QToolBar {"
            f"  background: {c('bg')};"
            "  border: none;"
            f"  border-bottom: 1px solid {c('line')};"
            "  spacing: 2px;"
            "  padding: 0 8px;"
            "}"
            "QToolBar::separator {"
            f"  background: {c('line')};"
            "  width: 1px;"
            "  height: 18px;"
            "  margin: 0 6px;"
            "}"
            # undo / redo: solo icona 28x28
            "QToolBar QToolButton {"
            "  background: transparent; border: 1px solid transparent; border-radius: 4px;"
            "  padding: 0; min-width: 26px; min-height: 26px;"
            "}"
            f"QToolBar QToolButton:hover {{ background: {c('raise')}; }}"
            f"QToolBar QToolButton:checked {{ background: {c('raise')}; }}"
            + theme.focus_rule("QToolBar QToolButton", 4)
            # campo di ricerca
            + f"QLineEdit#tbSearch {{ background: {c('bg')}; border: 1px solid {c('line')};"
            f" border-radius: 4px; color: {c('text')}; font-size: 13px; padding: 0 8px; }}"
            f"QLineEdit#tbSearch:focus {{ border-color: {c('focus')}; }}"
            f"QLabel#tbSearchHint {{ color: {c('label')}; background: transparent;"
            f" font-family: {theme.FONT_MONO}; font-size: 11px; }}"
        )
        for b in self._tb_buttons:
            right = _HINT_PAD + (_HINT_GAP + _hint_width(b.hint()) if b.hint() else 0)
            b.setStyleSheet(
                "QPushButton {"
                "  background: transparent;"
                "  border: 1px solid transparent;"
                "  border-radius: 4px;"
                f"  color: {c('text')};"
                "  font-size: 13px;"
                "  font-weight: 400;"
                f"  padding: 0 {right}px 0 {_HINT_PAD}px;"
                f"  min-height: {_BTN_HEIGHT - 2}px;"
                "}"
                f"QPushButton:hover {{ background: {c('raise')}; color: {c('text')}; }}"
                f"QPushButton:pressed {{ background: {c('raise')}; }}"
                f"QPushButton:disabled {{ color: {c('faint')}; }}"
                + theme.focus_rule("QPushButton", 4)
            )
        insp_hint = self._insp_btn.hint()
        right = _HINT_PAD + (_HINT_GAP + _hint_width(insp_hint) if insp_hint else 0)
        self._insp_btn.setStyleSheet(
            "QToolButton#tbInspector {"
            f"  color: {c('text')}; padding: 0 {right}px 0 {_HINT_PAD}px;"
            "  background: transparent; border: 1px solid transparent; border-radius: 4px;"
            f"  min-height: {_BTN_HEIGHT - 2}px; font-size: 13px;"
            "}"
            f"QToolButton#tbInspector:hover {{ background: {c('raise')}; }}"
            f"QToolButton#tbInspector:checked {{ background: {c('raise')}; }}"
            + theme.focus_rule("QToolButton#tbInspector", 4)
        )
        # Esporta: primario con angoli esterni a 4 px, freccia attaccata (1 px di stacco)
        self._export_btn.setStyleSheet(
            "QPushButton {"
            f"  background: {c('acc_fill')}; color: {c('acc_ink')}; font-weight: 600;"
            "  font-size: 13px; border: 1px solid transparent; border-radius: 4px;"
            "  border-top-right-radius: 0; border-bottom-right-radius: 0; padding: 0 8px;"
            f"  min-height: {_BTN_HEIGHT - 2}px;"
            "}"
            f"QPushButton:hover {{ background: {c('acc_fill_h')}; }}"
            f"QPushButton:pressed {{ background: {c('acc_fill_d')}; }}"
            + theme.focus_rule_on_accent("QPushButton")
        )
        self._export_arrow.setStyleSheet(
            "QPushButton {"
            f"  background: {c('acc_fill')}; color: {c('acc_ink')};"
            "  border: 1px solid transparent; border-radius: 4px; border-top-left-radius: 0;"
            f"  border-bottom-left-radius: 0; padding: 0; min-height: {_BTN_HEIGHT - 2}px;"
            "}"
            f"QPushButton:hover {{ background: {c('acc_fill_h')}; }}"
            + theme.focus_rule_on_accent("QPushButton")
        )
        self._empty_lbl.setStyleSheet(
            f"color: {c('dim')}; font-size: 13px; background: {c('bg')};"
        )

    def _show_export_menu(self):
        c = theme.c
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {c('panel')}; border: 1px solid {c('line_2')}; border-radius: 4px; padding: 4px; }}"
            f"QMenu::item {{ color: {c('text')}; padding: 6px 20px; font-size: 13px; border-radius: 3px; }}"
            f"QMenu::item:selected {{ background: {c('raise')}; color: {c('text')}; }}"
            f"QMenu::separator {{ height: 1px; background: {c('line')}; margin: 3px 6px; }}"
        )
        menu.addAction(self.act_export)
        menu.addSeparator()
        menu.addAction(self.act_export_vtt)
        menu.addAction(self.act_export_txt)
        menu.addAction(self.act_export_ass)
        menu.addSeparator()
        menu.addAction(self.act_export_v2srt)
        pos = self._export_arrow.mapToGlobal(self._export_arrow.rect().bottomLeft())
        menu.exec(pos)

    # ---- Ricerca inline ----

    def focus_search(self):
        """Porta il focus sulla casella di ricerca inline (se la finestra è così stretta
        che la casella non si vede, apre Trova e sostituisci)."""
        if not self._search_box.isVisible() and self._toolbar.isVisible():
            self.open_find_replace()
            return
        self._search_box.setFocus()
        self._search_box.selectAll()

    def toolbar_level(self) -> int:
        return self._toolbar_level

    def fit_toolbar(self) -> None:
        """Sceglie il livello di compattezza più basso con cui la toolbar ci sta tutta."""
        tb = self._toolbar
        if self._fitting_toolbar or tb.width() <= 0:
            return
        self._fitting_toolbar = True
        try:
            for level in range(TOOLBAR_LEVELS):
                self._apply_toolbar_level(level)
                if tb.sizeHint().width() <= tb.width():
                    break
        finally:
            self._fitting_toolbar = False

    def _apply_toolbar_level(self, level: int) -> None:
        if level == self._toolbar_level:
            return
        self._toolbar_level = level
        for b in (*self._tb_buttons, self._insp_btn):
            b.set_compact(level)
        self._search_box.setFixedWidth(
            _SEARCH_WIDTH if level < 3 else _SEARCH_WIDTH_COMPACT if level < 4
            else _SEARCH_WIDTH_MIN)
        # ultimo livello: Esporta solo icona (nome accessibile e tooltip restano)
        self._export_btn.setText("" if level >= 4 else "Esporta SRT")
        self._apply_toolbar_palette()
        self._toolbar.layout().invalidate()

    def _on_search(self, text: str):
        self._search_idx = -1
        if text:
            self._do_search(text, forward=True)

    def _on_search_next(self):
        text = self._search_box.text()
        if text:
            self._do_search(text, forward=True)

    def _do_search(self, text: str, forward: bool = True):
        n = self.model.rowCount()
        if n == 0:
            return
        start = (self._search_idx + 1) % n if forward else (self._search_idx - 1) % n
        for i in range(n):
            row = (start + i) % n
            sub = self.model.subtitle_at(row)
            if sub and text.lower() in sub.text.lower():
                self._search_idx = row
                self.view.selectRow(row)
                self.view.scrollTo(
                    self.model.index(row, COL_TEXT),
                    QAbstractItemView.PositionAtCenter
                )
                return

    # ---- Importa file ----

    def _import_file(self):
        """
        Sceglie il file e lo inoltra con `import_requested`: il caricamento (con la
        conferma se l'editor è modificato) è fatto da ProjectWidget.open_path.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "Importa file",
            "",
            "File supportati (*.srt *.v2srt);;"
            "SRT (*.srt);;"
            "Progetto V2SRT (*.v2srt)"
        )
        if path:
            self.import_requested.emit(path)

    # ---- Wiring ----

    def _wire(self):
        self.model.set_edit_handler(self._handle_table_edit)

        self.inspector.text_committed.connect(self._on_insp_text)
        self.inspector.start_committed.connect(self._on_insp_start)
        self.inspector.end_committed.connect(self._on_insp_end)
        self.inspector.shift_requested.connect(self._on_insp_shift)

        self.view.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self.view.clicked.connect(self._on_cell_clicked)

        # dataModified copre già inserimenti/rimozioni/reset (il modello lo emette
        # dopo ogni modifica): un solo aggancio, poi debounce.
        self.model.dataModified.connect(self._invalidate_time_index)
        self.model.dataModified.connect(self._schedule_status)
        self.model.dataModified.connect(self.subtitles_changed)
        self.undo_stack.cleanChanged.connect(self._schedule_status)

        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

        # Canc / Backspace sulla tabella eliminano le righe selezionate
        for key in (Qt.Key_Delete, Qt.Key_Backspace):
            sc = QShortcut(QKeySequence(key), self.view)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self._delete_selected)

        # Shortcut playback NLE: attive solo con l'editor visibile (contesto finestra,
        # genitore = timeline). Il tasto torna al widget col focus se è suo (vedi
        # `_on_playback_shortcut`): si scrive nei campi, Spazio preme i pulsanti.
        self._playback_shortcuts: dict = {}
        for name, seq, method in PLAYBACK_KEYS:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setObjectName(f"playback_{name}")
            sc.activated.connect(self._on_playback_shortcut)
            self._playback_shortcuts[sc.objectName()] = (seq, method)

    # ---- API pubblica ----

    def load_subtitles(self, subtitles: List[Subtitle]):
        self.undo_stack.clear()
        self.model.set_subtitles(subtitles)
        if subtitles:
            self.view.selectRow(0)
        self._update_status()

    def get_subtitles(self) -> List[Subtitle]:
        return self.model.subtitles()

    def is_modified(self) -> bool:
        return not self.undo_stack.isClean()

    def mark_saved(self):
        self.undo_stack.setClean()
        self._update_status()

    def mark_modified(self):
        """Segna il contenuto come non salvato (es. sessione ripristinata da autosave)."""
        self.undo_stack.resetClean()
        self._update_status()

    def set_player(self, player: AudioPlayer):
        """Collega il player condiviso della preview (una sola connessione ai tick)."""
        if player is self.player:
            return
        if self.player is not None:
            try:
                self.player.position_changed.disconnect(self._on_player_pos)
                self.player.seeked.disconnect(self._on_user_seek)
            except (RuntimeError, TypeError):
                pass
        self.player = player
        # seeked arriva PRIMA di position_changed: la selezione segue il click dell'utente
        # anche quando il follow della riproduzione è sospeso (vedi _on_user_seek)
        self.player.seeked.connect(self._on_user_seek)
        self.player.position_changed.connect(self._on_player_pos)

    def set_loop(self, on: bool):
        """Loop sul sottotitolo corrente: a fine sottotitolo il player torna al suo inizio."""
        self._loop = bool(on)
        if self._loop and self.player is not None:
            sub = self.model.subtitle_at(self._current_row())
            if sub is not None:
                pos = self.player.position()
                if not (sub.start * 1000 <= pos < sub.end * 1000):
                    self.player.seek(int(sub.start * 1000))

    def is_looping(self) -> bool:
        return self._loop

    # ---- Tema ----

    def _on_theme_changed(self, _name=None):
        # Riemette dataChanged su tutte le righe: i colori del provider seguono il tema
        self.model.set_color_provider(theme_color_provider)
        self.view.viewport().update()

    # ---- Selezione → Inspector ----

    def _on_row_changed(self, current: QModelIndex, _prev: QModelIndex):
        row = current.row() if current.isValid() else None
        self.inspector.show_row(row)

    def _on_cell_clicked(self, index: QModelIndex):
        """
        Click singolo su cella:
          - Shift/Ctrl/Cmd premuti → solo selezione multipla (nessun editing, nessun seek)
          - Colonna TESTO → entra subito in editing (nessun seek)
          - Altre colonne  → seek player all'inizio del sottotitolo
        Se la view è già in EditingState non fa nulla.
        """
        if self.view.state() == QAbstractItemView.State.EditingState:
            return
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.MetaModifier):
            return

        if index.column() == COL_TEXT:
            self.view.edit(index)
            return

        sub = self.model.subtitle_at(index.row())
        if sub is not None and self.player is not None:
            self.player.seek(int(sub.start * 1000))

    # ---- Edit handler ----

    def _handle_table_edit(self, row: int, col: int, value) -> bool:
        sub = self.model.subtitle_at(row)
        if sub is None:
            return False
        if col == COL_TEXT:
            new_text = str(value).strip()
            if new_text == sub.text:
                return False
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_TEXT, sub.text, new_text, "Modifica testo"))
            return True
        if col in (COL_START, COL_END):
            from core.subtitle_table_model import parse_timestamp
            new_val = parse_timestamp(str(value))
            if new_val is None:
                return False
            old_val = sub.start if col == COL_START else sub.end
            if abs(new_val - old_val) < 0.0005:
                return False
            label = "Modifica inizio" if col == COL_START else "Modifica fine"
            self.undo_stack.push(EditFieldCommand(
                self.model, row, col, f"{old_val:.3f}", f"{new_val:.3f}", label
            ))
            return True
        return False

    # ---- Inspector handlers ----

    def _on_insp_text(self, row: int, new_text: str):
        sub = self.model.subtitle_at(row)
        if sub and sub.text != new_text:
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_TEXT, sub.text, new_text, "Modifica testo"))

    def _on_insp_start(self, row: int, new_val: float):
        sub = self.model.subtitle_at(row)
        if sub and abs(new_val - sub.start) >= 0.0005:
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_START, f"{sub.start:.3f}", f"{new_val:.3f}", "Modifica inizio"))

    def _on_insp_end(self, row: int, new_val: float):
        sub = self.model.subtitle_at(row)
        if sub and abs(new_val - sub.end) >= 0.0005:
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_END, f"{sub.end:.3f}", f"{new_val:.3f}", "Modifica fine"))

    def _on_insp_shift(self, row: int, delta: float):
        sub = self.model.subtitle_at(row)
        if sub is None:
            return
        new_start = max(0.0, sub.start + delta)
        new_end   = max(0.0, sub.end   + delta)
        if abs(new_start - sub.start) < 0.0005:
            return
        self.undo_stack.beginMacro(f"Sposta {delta*1000:+.0f}ms")
        self.undo_stack.push(EditFieldCommand(self.model, row, COL_START, f"{sub.start:.3f}", f"{new_start:.3f}", "Sposta inizio"))
        self.undo_stack.push(EditFieldCommand(self.model, row, COL_END,   f"{sub.end:.3f}",   f"{new_end:.3f}",   "Sposta fine"))
        self.undo_stack.endMacro()

    # ---- Toolbar actions ----

    def _current_row(self) -> int:
        idx = self.view.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _split_current(self):
        row = self._current_row()
        if row < 0:
            return
        sub = self.model.subtitle_at(row)
        if sub is None or len(sub.text) < 3:
            return
        pos = len(sub.text) // 2
        try:
            if self.inspector.text_edit.hasFocus():
                p = self.inspector.text_edit.textCursor().position()
                if 0 < p < len(sub.text):
                    pos = p
        except Exception:
            pass
        self.undo_stack.push(SplitSubtitleCommand(self.model, row, pos))

    def _merge_next(self):
        row = self._current_row()
        if 0 <= row < self.model.rowCount() - 1:
            self.undo_stack.push(MergeWithNextCommand(self.model, row))

    def _delete_selected(self):
        rows = sorted({idx.row() for idx in self.view.selectionModel().selectedRows()})
        if not rows:
            r = self._current_row()
            if r >= 0:
                rows = [r]
        if not rows:
            return
        first = rows[0]
        self.undo_stack.push(DeleteSubtitleCommand(self.model, rows))
        remaining = self.model.rowCount()
        if remaining > 0:
            self.view.selectRow(min(first, remaining - 1))

    # ---- Find & Replace ----

    def open_find_replace(self):
        """Apre (o riporta in primo piano) il dialog Trova e sostituisci."""
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(self.model, self)
            self._find_dialog.match_found.connect(
                lambda r: self.view.selectRow(r) or self.view.scrollTo(
                    self.model.index(r, COL_TEXT), QAbstractItemView.PositionAtCenter
                )
            )
            self._find_dialog.replace_all_requested.connect(
                lambda reps: self.undo_stack.push(ReplaceAllCommand(self.model, reps)) if reps else None
            )
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.activateWindow()
        self._find_dialog.focus_find()

    # ---- Player ----

    def _invalidate_time_index(self):
        self._time_index = None

    def row_at_time(self, pos_s: float) -> int:
        """Riga del sottotitolo che contiene `pos_s` (bisect, O(log N)); -1 se nessuna."""
        if self._time_index is None:
            entries = sorted(
                (sub.start, sub.end, row) for row, sub in enumerate(self.model.subtitles())
            )
            self._time_index = entries
            self._time_starts = [e[0] for e in entries]
        i = bisect.bisect_right(self._time_starts, pos_s) - 1
        # Con sovrapposizioni il sottotitolo giusto può essere uno dei precedenti
        for j in range(i, max(-1, i - 3), -1):
            start, end, row = self._time_index[j]
            if start <= pos_s <= end:
                return row
        return -1

    def _follow_blocked(self) -> bool:
        """
        Il follow-playback non deve togliere il lavoro all'utente: è sospeso mentre
        un campo dell'inspector ha il focus o contiene testo non confermato, mentre
        si modifica una cella, con una selezione multipla o con il loop attivo.
        """
        if self._loop:
            return True
        if self.view.state() == QAbstractItemView.State.EditingState:
            return True
        if len(self.view.selectionModel().selectedRows()) > 1:
            return True
        fw = QApplication.focusWidget()
        if fw is not None and (fw is self.inspector or self.inspector.isAncestorOf(fw)):
            return True
        return self.inspector.has_uncommitted_text()

    def _on_player_pos(self, ms: int):
        if self.model.rowCount() == 0:
            return
        if self._loop and self.player is not None and self.player.is_playing():
            sub = self.model.subtitle_at(self._current_row())
            if sub is not None and ms >= int(sub.end * 1000):
                self.player.seek(int(sub.start * 1000))
            return
        row = self.row_at_time(ms / 1000.0)
        if row < 0 or row == self._current_row() or self._follow_blocked():
            return
        self.view.selectRow(row)
        self.view.scrollTo(self.model.index(row, COL_TEXT), QAbstractItemView.EnsureVisible)

    def _on_user_seek(self, ms: int):
        """
        Seek esplicito (click su forma d'onda o slider, J/←/→, Maiusc+←/→): la riga del
        sottotitolo che contiene la nuova posizione diventa subito quella selezionata,
        anche in pausa e anche con il focus nell'inspector o una selezione multipla
        (regole del follow della riproduzione, `_follow_blocked`, non applicate).
        Restano protetti solo l'editing di una cella e il testo non confermato
        dell'inspector. Tra due sottotitoli la selezione non cambia.
        """
        if self.model.rowCount() == 0:
            return
        if self.view.state() == QAbstractItemView.State.EditingState:
            return
        if self.inspector.has_uncommitted_text():
            return
        row = self.row_at_time(ms / 1000.0)
        if row < 0:
            return
        if row == self._current_row() and len(self.view.selectionModel().selectedRows()) <= 1:
            return
        self.view.selectRow(row)
        self.view.scrollTo(self.model.index(row, COL_TEXT), QAbstractItemView.EnsureVisible)

    # ---- Shortcut playback ----

    def _on_playback_shortcut(self):
        """
        Slot unico delle QShortcut di riproduzione. Se il widget col focus usa quel
        tasto (si scrive in un campo, Spazio su un pulsante, frecce sul volume…) il
        tasto gli viene restituito; altrimenti si esegue l'azione di riproduzione.
        """
        sc = self.sender()
        entry = self._playback_shortcuts.get(sc.objectName()) if sc is not None else None
        if entry is None:
            return
        seq, method = entry
        fw = QApplication.focusWidget()
        if focus_owns_key(fw, seq):
            # la scorciatoia è disattivata durante l'inoltro: il tasto inviato a mano
            # ripasserebbe dalla mappa delle scorciatoie e tornerebbe qui
            sc.setEnabled(False)
            try:
                forward_key(fw, seq)
            finally:
                sc.setEnabled(True)
            return
        getattr(self, method)()

    def _seek_relative(self, delta_ms: int):
        if self.player is not None:
            self.player.seek_relative(delta_ms)

    def _seek_back(self):
        """←: indietro di 1 s."""
        self._seek_relative(-1000)

    def _seek_forward(self):
        """→: avanti di 1 s."""
        self._seek_relative(1000)

    def _shortcut_play_pause(self):
        if self.player is not None:
            self.player.toggle_play_pause()

    @staticmethod
    def _step_rate(rate: float, direction: int) -> float:
        """Velocità successiva (+1) o precedente (−1) nella scala RATE_STEPS."""
        if direction > 0:
            higher = [r for r in RATE_STEPS if r > rate + 1e-6]
            return higher[0] if higher else RATE_STEPS[-1]
        lower = [r for r in RATE_STEPS if r < rate - 1e-6]
        return lower[-1] if lower else RATE_STEPS[0]

    def _shortcut_rewind(self):
        """J: da fermo indietro di 2 s; in riproduzione rallenta di un passo."""
        if self.player is None:
            return
        if self.player.is_playing():
            self.player.set_rate(self._step_rate(self.player.rate(), -1))
        else:
            self.player.seek_relative(-2000)

    def _shortcut_forward(self):
        """L: da fermo avvia; in riproduzione accelera di un passo."""
        if self.player is None:
            return
        if self.player.is_playing():
            self.player.set_rate(self._step_rate(self.player.rate(), +1))
        else:
            self.player.play()

    # ---- JKL con indicatore visivo ----

    def _jkl_j(self):
        self._shortcut_rewind()
        self.jkl_pressed.emit("J")

    def _jkl_k(self):
        """K: pausa e ritorno alla velocità normale."""
        if self.player is not None:
            self.player.pause()
            self.player.set_rate(1.0)
        self.jkl_pressed.emit("K")

    def _jkl_l(self):
        self._shortcut_forward()
        self.jkl_pressed.emit("L")

    def _go_prev_sub(self):
        n = self.model.rowCount()
        if n == 0:
            return
        row = max(0, self._current_row())
        target = max(0, row - 1)
        sub = self.model.subtitle_at(target)
        if sub:
            if self.player is not None:
                self.player.seek(int(sub.start * 1000))
            self.view.selectRow(target)

    def _go_next_sub(self):
        n = self.model.rowCount()
        if n == 0:
            return
        row = max(0, self._current_row())
        target = min(n - 1, row + 1)
        sub = self.model.subtitle_at(target)
        if sub:
            if self.player is not None:
                self.player.seek(int(sub.start * 1000))
            self.view.selectRow(target)

    # ---- Status bar ----

    def _schedule_status(self, *_):
        """Raggruppa gli aggiornamenti di stato (eliminare k righe = 1 ricalcolo)."""
        self._status_timer.start()

    def _update_status(self):
        self._status_timer.stop()
        total = self.model.rowCount()
        self._central_stack.setCurrentIndex(0 if total else 1)
        count_txt = f"{total} sottotitoli"
        if total == 0:
            issues_txt = ""
        else:
            errors = warnings = 0
            for r in range(total):   # una sola passata
                sev = self.model.row_severity(r)
                if sev == "error":
                    errors += 1
                elif sev == "warning":
                    warnings += 1
            parts = []
            if errors:
                parts.append(f"{errors} {'errore' if errors == 1 else 'errori'}")
            if warnings:
                parts.append(f"{warnings} {'avviso' if warnings == 1 else 'avvisi'}")
            if not parts:
                parts.append("nessun problema")
            issues_txt = "  ·  ".join(parts)
        mod_txt = "  ·  Modificato" if self.is_modified() else ""
        status = count_txt
        if issues_txt:
            status += f"  ·  {issues_txt}"
        status += mod_txt
        self.status_text.emit(status)
