"""
export_tab.py — ExportTab: pannello esportazione (terza tab di ProjectWidget).

Layout (mockup "Bianco e nero"):
  ┌── Fascia info 56 px: N sottotitoli · fonte · tag · badge · avviso ──────────┐
  ├── "Salva file" e "Pubblica direttamente": righe da 56 px ──┬─ Anteprima SRT ─┤
  │   (sigla, titolo, descrizione, scorciatoia, icona)         │  mono, 560 px   │
  └─────────────────────────────────────────────────────────────┴─────────────────┘

API pubblica:
  refresh(segments_raw, editor_subs, source_path, is_modified)
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLayout, QPushButton,
    QFrame, QSizePolicy, QScrollArea, QStackedWidget, QPlainTextEdit,
)

from core.constants import SUPPORTED_VIDEO_EXTS
from core.subtitle_model import Subtitle
from ui.widgets import ElidedLabel
from ui import icons, theme
import platform_support

_sl = platform_support.shortcut_label

_VIDEO_DESC = "MP4 con i sottotitoli impressi nell'immagine — per reel e social"
_VIDEO_NEEDS_SOURCE = "Serve un file video come sorgente: con un audio non c'è un'immagine"

# Misure del mockup
_INFO_HEIGHT = 56
_ROW_HEIGHT = 56
_TAG_SIZE = (64, 28)
_ASIDE_WIDTH = 560


class _ExportButton(QPushButton):
    """
    Riga di esportazione da 56 px a tutta larghezza: sigla (o icona) in un riquadro
    bordato 64×28, titolo (600) + descrizione (12 px, dim), scorciatoia mono opzionale
    e icona di scarico/copia. Il testo vive nelle label figlie: nome/descrizione
    accessibili sono espliciti. `accent` = riga principale (barra e sigla in accento).
    """

    def __init__(self, title: str, subtitle: str, tag: str = "", icon_name: str = "download",
                 hint: str = "", accent: bool = False, tag_icon: str = "", parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setObjectName("exportRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)
        self.setToolTip(subtitle)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(16)
        lay.setSizeConstraint(QLayout.SetNoConstraint)   # l'altezza fissa non va persa

        self.tag_lbl = QLabel(tag)
        self.tag_lbl.setObjectName("exportTag")
        self.tag_lbl.setAlignment(Qt.AlignCenter)
        self.tag_lbl.setFixedSize(*_TAG_SIZE)
        self._tag_icon = tag_icon
        lay.addWidget(self.tag_lbl)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("exportTitle")
        self.sub_lbl = ElidedLabel(subtitle, Qt.ElideRight)
        self.sub_lbl.setObjectName("exportDesc")
        texts.addStretch(1)
        texts.addWidget(self.title_lbl)
        texts.addWidget(self.sub_lbl)
        texts.addStretch(1)
        lay.addLayout(texts, 1)

        self.hint_lbl = QLabel(hint)
        self.hint_lbl.setObjectName("exportHint")
        self.hint_lbl.setVisible(bool(hint))
        lay.addWidget(self.hint_lbl)

        self.icon_lbl = QLabel()
        self.icon_lbl.setObjectName("exportIcon")
        self.icon_lbl.setFixedSize(16, 16)
        self._icon_name = icon_name
        lay.addWidget(self.icon_lbl)

        # dopo il layout: il layout imposterebbe da sé l'altezza minima del widget
        self.setFixedHeight(_ROW_HEIGHT)

        for w in (self.tag_lbl, self.title_lbl, self.sub_lbl, self.hint_lbl, self.icon_lbl):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.restyle()

    def restyle(self):
        """Colori dai token del tema (richiamato al cambio tema)."""
        c = theme.c
        acc = self._accent
        self.setStyleSheet(
            "QPushButton#exportRow {"
            f" background: {c('panel') if acc else 'transparent'}; border: none; border-radius: 0;"
            f" border-bottom: 1px solid {c('line')}; text-align: left; padding: 0;"
            # il QSS globale dei QPushButton impone min-height: 28 px; qui 55 + 1 di bordo
            f" min-height: {_ROW_HEIGHT - 1}px; }}"
            f"QPushButton#exportRow:hover {{ background: {c('raise')}; }}"
            f"QPushButton#exportRow:disabled QLabel#exportTitle {{ color: {c('dim')}; }}"
            + theme.focus_rule("QPushButton#exportRow", 0)
            + "QLabel { background: transparent; border: none; }"
            f"QLabel#exportTitle {{ color: {c('text')}; font-size: 13px; font-weight: 600; }}"
            f"QLabel#exportDesc {{ color: {c('dim')}; font-size: 12px; }}"
            f"QLabel#exportHint {{ color: {c('dim')}; font-family: {theme.FONT_MONO};"
            " font-size: 11px; }"
            "QLabel#exportTag {"
            f" color: {c('acc') if acc else c('text')};"
            f" border: 1px solid {c('acc') if acc else c('line')}; border-radius: 3px;"
            f" font-family: {theme.FONT_MONO}; font-size: 12px; font-weight: 500; }}"
        )
        if self._tag_icon:
            self.tag_lbl.setPixmap(icons.pixmap(self._tag_icon, theme.qcolor("dim"), 16))
        self.icon_lbl.setPixmap(icons.pixmap(self._icon_name, theme.qcolor("dim"), 16))

    def paintEvent(self, event):  # noqa: N802 (override Qt)
        super().paintEvent(event)
        if self._accent:
            p = QPainter(self)
            try:
                p.fillRect(0, 0, 2, self.height(), theme.qcolor("acc"))
            finally:
                p.end()


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("exportSection")
    return lbl


class _SrtHighlighter(QSyntaxHighlighter):
    """Anteprima SRT: numero e tempi attenuati, testo in primo piano (solo colore)."""

    def highlightBlock(self, text: str):  # noqa: N802 (override Qt)
        stripped = text.strip()
        if stripped.isdigit() or stripped.startswith("…"):
            token = "label"
        elif "-->" in text:
            token = "dim"
        else:
            token = "text"
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.qcolor(token)))
        self.setFormat(0, len(text), fmt)


# ── ExportTab ─────────────────────────────────────────────────────────────────

class ExportTab(QWidget):

    export_srt_requested  = Signal()
    export_vtt_requested  = Signal()
    export_txt_requested  = Signal()
    export_ass_requested  = Signal()
    save_v2srt_requested  = Signal()
    export_video_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._subtitles: List[Subtitle] = []
        self._source_path: str = ""
        self._is_modified: bool = False
        self._has_editor_subs: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._placeholder = _ExportPlaceholder()
        self._stack.addWidget(self._placeholder)   # 0

        self._panel = _ExportPanel()
        self._stack.addWidget(self._panel)          # 1

        # Connetti segnali
        self._panel.btn_srt.clicked.connect(self.export_srt_requested)
        self._panel.btn_vtt.clicked.connect(self.export_vtt_requested)
        self._panel.btn_txt.clicked.connect(self.export_txt_requested)
        self._panel.btn_ass.clicked.connect(self.export_ass_requested)
        self._panel.btn_v2srt.clicked.connect(self.save_v2srt_requested)
        self._panel.btn_video.clicked.connect(self.export_video_requested)

        self._stack.setCurrentIndex(0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.qcolor("bg"))
        p.end()

    # ── API pubblica ───────────────────────────────────────────────────────────

    def refresh(
        self,
        segments_raw: list,
        editor_subs: List[Subtitle],
        source_path: str,
        is_modified: bool,
    ):
        if editor_subs:
            self._subtitles = editor_subs
            self._has_editor_subs = True
        elif segments_raw:
            from core.subtitle_model import SubtitleProject
            proj = SubtitleProject()
            proj.load_from_segments(segments_raw, source_path)
            self._subtitles = proj.subtitles
            self._has_editor_subs = False
        else:
            self._subtitles = []
            self._has_editor_subs = False

        self._source_path = source_path
        self._is_modified = is_modified

        if not self._subtitles:
            self._stack.setCurrentIndex(0)
        else:
            self._panel.update_info(
                subtitles=self._subtitles,
                source_path=source_path,
                has_editor_subs=self._has_editor_subs,
                is_modified=is_modified,
            )
            self._stack.setCurrentIndex(1)

    def current_subtitles(self) -> List[Subtitle]:
        return self._subtitles


# ── Placeholder ───────────────────────────────────────────────────────────────

class _ExportPlaceholder(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setFixedSize(32, 32)
        lay.addWidget(self._icon, alignment=Qt.AlignCenter)

        self._msg = QLabel("Nessun sottotitolo da esportare")
        self._msg.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._msg)

        self._sub = QLabel("Completa una trascrizione o importa un file SRT nell'editor.")
        self._sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._sub)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    def _apply_palette(self, _name=None):
        c = theme.c
        self._icon.setStyleSheet("background: transparent; border: none;")
        self._icon.setPixmap(icons.pixmap("export", theme.qcolor("dim"), 24))
        self._msg.setStyleSheet(
            f"color: {c('dim')}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        self._sub.setStyleSheet(
            f"color: {c('label')}; font-size: 12px; background: transparent;"
        )


# ── Export panel ──────────────────────────────────────────────────────────────

class _ExportPanel(QWidget):
    _PREVIEW_BLOCKS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._rows: list = []   # righe _ExportButton, ri-tematizzabili

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Fascia informativa (56 px, panel) ──────────────────────────────────
        self._info_card = QFrame()
        self._info_card.setObjectName("exportInfo")
        info_lay = QHBoxLayout(self._info_card)
        info_lay.setContentsMargins(40, 0, 40, 0)
        info_lay.setSpacing(20)
        info_lay.setSizeConstraint(QLayout.SetNoConstraint)
        self._info_card.setFixedHeight(_INFO_HEIGHT)

        self._lbl_count = QLabel("—")
        info_lay.addWidget(self._lbl_count)

        self._lbl_source = ElidedLabel("")
        # usa la larghezza del testo (può accorciarsi solo se manca spazio)
        self._lbl_source.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        info_lay.addWidget(self._lbl_source)

        self._lbl_origin = QLabel("")
        self._lbl_origin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        info_lay.addWidget(self._lbl_origin, 0, Qt.AlignVCenter)

        # Badge: punto disegnato (6 px, colore avviso) + testo; il contenitore si mostra/nasconde
        self._badge_modified = QWidget()
        badge_lay = QHBoxLayout(self._badge_modified)
        badge_lay.setContentsMargins(0, 0, 0, 0)
        badge_lay.setSpacing(8)
        self._badge_dot = QLabel()
        self._badge_dot.setFixedSize(6, 6)
        badge_lay.addWidget(self._badge_dot, 0, Qt.AlignVCenter)
        self._badge_text = QLabel("modificato nell'editor")
        badge_lay.addWidget(self._badge_text)
        self._badge_modified.setVisible(False)
        info_lay.addWidget(self._badge_modified)
        info_lay.addStretch(1)

        # Avviso: ci sono sottotitoli ma con testo vuoto (icona + testo a destra)
        self._warn_icon = QLabel()
        self._warn_icon.setFixedSize(14, 14)
        self._warn_icon.setVisible(False)
        info_lay.addWidget(self._warn_icon)
        self._lbl_empty_warn = QLabel("")
        self._lbl_empty_warn.setVisible(False)
        info_lay.addWidget(self._lbl_empty_warn)
        outer.addWidget(self._info_card)

        # ── Corpo: colonna di sinistra + anteprima da 560 px ───────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFocusPolicy(Qt.NoFocus)   # contenitore: Tab va ai controlli, non qui
        body.addWidget(self._scroll, 1)

        content = QWidget()
        content.setObjectName("exportContent")
        self._scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(26)

        # ── Sezione: Salva file ────────────────────────────────────────────────
        self.btn_srt = self._row(
            "SRT", "SubRip Subtitle — standard universale",
            tag="SRT", hint=_sl("Ctrl+S"), accent=True)
        self.btn_vtt = self._row(
            "VTT", "WebVTT — per video HTML5 e web player", tag="VTT")
        self.btn_txt = self._row(
            "TXT", "Testo semplice — solo dialoghi, senza timing", tag="TXT")
        self.btn_ass = self._row(
            "ASS", "Advanced SubStation Alpha — stili avanzati", tag="ASS")
        self.btn_v2srt = self._row(
            "Progetto .v2srt", "Salva tutto il progetto — riapribile e modificabile",
            tag="V2SRT", hint=_sl("Ctrl+Shift+S"))
        root.addLayout(self._section(
            "Salva file", [self.btn_srt, self.btn_vtt, self.btn_txt, self.btn_ass,
                           self.btn_v2srt]))

        # ── Sezione: Video ─────────────────────────────────────────────────────
        self.btn_video = self._row(
            "Video con sottotitoli", _VIDEO_DESC, tag="MP4", icon_name="download")
        root.addLayout(self._section("Video", [self.btn_video]))

        # ── Sezione: Pubblica direttamente ────────────────────────────────────
        self._btn_youtube = self._row(
            "YouTube Studio",
            "Copia il testo SRT negli appunti — da incollare in YouTube Studio",
            icon_name="copy", tag_icon="copy")
        self._btn_youtube.clicked.connect(self._publish_youtube)
        self._btn_vimeo = self._row(
            "Vimeo", "Esporta SRT da caricare nei sottotitoli di Vimeo", tag_icon="download")
        self._btn_vimeo.clicked.connect(self._publish_vimeo)
        self._btn_premiere = self._row(
            "Premiere Pro / DaVinci",
            "Esporta SRT da importare nella timeline del montaggio", tag_icon="download")
        self._btn_premiere.clicked.connect(self._publish_premiere)
        self._btn_clipboard = self._row(
            "Copia negli appunti", "Copia tutto il testo SRT — incolla dove vuoi",
            icon_name="copy", tag_icon="copy")
        self._btn_clipboard.clicked.connect(self._publish_clipboard)
        root.addLayout(self._section(
            "Pubblica direttamente",
            [self._btn_youtube, self._btn_vimeo, self._btn_premiere, self._btn_clipboard]))
        root.addStretch(1)

        # ── Anteprima SRT (colonna destra, 560 px, panel) ──────────────────────
        self._aside = QFrame()
        self._aside.setObjectName("exportAside")
        aside_lay = QVBoxLayout(self._aside)
        aside_lay.setContentsMargins(0, 0, 0, 0)
        aside_lay.setSpacing(0)
        aside_lay.setSizeConstraint(QLayout.SetNoConstraint)
        self._aside.setFixedWidth(_ASIDE_WIDTH)

        self._aside_head = QFrame()
        self._aside_head.setObjectName("exportAsideHead")
        head_lay = QHBoxLayout(self._aside_head)
        head_lay.setContentsMargins(20, 0, 20, 0)
        head_lay.setSizeConstraint(QLayout.SetNoConstraint)
        self._aside_head.setFixedHeight(44)
        head_lay.addWidget(_section_label("Anteprima SRT"))
        aside_lay.addWidget(self._aside_head)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setAccessibleName("Anteprima SRT")
        self._preview.setMinimumHeight(self._preview.fontMetrics().lineSpacing() * 10 + 24)
        self._preview_hl = _SrtHighlighter(self._preview.document())
        aside_lay.addWidget(self._preview, 1)
        body.addWidget(self._aside)

        # Riferimento ai sottotitoli per le azioni di pubblicazione
        self._current_subs: list = []

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    def _row(self, title: str, subtitle: str, tag: str = "", icon_name: str = "download",
             hint: str = "", accent: bool = False, tag_icon: str = "") -> _ExportButton:
        b = _ExportButton(title, subtitle, tag=tag, icon_name=icon_name, hint=hint,
                          accent=accent, tag_icon=tag_icon)
        self._rows.append(b)
        return b

    def _section(self, title: str, rows: list) -> QVBoxLayout:
        """Titolo + elenco di righe sotto una linea da 1 px."""
        box = QVBoxLayout()
        box.setSpacing(8)
        box.addWidget(_section_label(title))
        frame = QFrame()
        frame.setObjectName("exportList")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for r in rows:
            lay.addWidget(r)
        box.addWidget(frame)
        return box

    # ── Tema ────────────────────────────────────────────────────────────────

    def _apply_palette(self, _name=None):
        c = theme.c
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QWidget#exportContent {{ background: {c('bg')}; }}"
            "QLabel { background: transparent; border: none; }"
            f"QLabel#exportSection {{ color: {c('text')}; font-size: 12px; font-weight: 600; }}"
            f"QFrame#exportList {{ background: transparent; border: none;"
            f" border-top: 1px solid {c('line')}; }}"
            f"QFrame#exportInfo {{ background: {c('panel')}; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
            f"QFrame#exportAside {{ background: {c('panel')}; border: none;"
            f" border-left: 1px solid {c('line')}; }}"
            f"QFrame#exportAsideHead {{ background: {c('panel')}; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
        )
        self._lbl_count.setStyleSheet(
            f"color: {c('text')}; font-family: {theme.FONT_MONO}; font-size: 15px;"
            " font-weight: 500;"
        )
        self._lbl_source.setStyleSheet(f"color: {c('dim')}; font-size: 13px;")
        self._lbl_origin.setStyleSheet(
            f"color: {c('text')}; font-size: 12px; border: 1px solid {c('line')};"
            " border-radius: 3px; padding: 2px 8px;"
        )
        self._badge_dot.setStyleSheet(
            f"background: {c('warn')}; border: none; border-radius: 3px;")
        self._badge_text.setStyleSheet(
            f"color: {c('warn')}; font-size: 12px; background: transparent;")
        self._lbl_empty_warn.setStyleSheet(f"color: {c('err')}; font-size: 12px;")
        self._warn_icon.setPixmap(icons.pixmap("alert", theme.qcolor("err"), 14))
        self._preview.setStyleSheet(
            "QPlainTextEdit {"
            f"  background: {c('panel')}; color: {c('dim')};"
            "  border: 1px solid transparent;"
            f"  font-family: {theme.FONT_MONO}; font-size: 12px;"
            "  padding: 15px 19px;"
            "}"
            # anello di focus (l'anteprima si scorre anche da tastiera)
            f"QPlainTextEdit:focus {{ border-color: {c('focus')}; }}"
        )
        self._preview_hl.rehighlight()
        for r in self._rows:
            r.restyle()

    # ── Handlers pubblicazione ─────────────────────────────────────────────────

    def _publish_youtube(self):
        """Copia negli appunti il testo formattato per YouTube caption manuale."""
        from PySide6.QtWidgets import QApplication, QMessageBox
        from core.srt_io import subtitles_to_srt
        if not self._current_subs:
            return
        text = subtitles_to_srt(self._current_subs)
        QApplication.clipboard().setText(text)
        QMessageBox.information(
            self, "YouTube Studio",
            "Testo SRT copiato negli appunti.\n\n"
            "In YouTube Studio → Sottotitoli → Aggiungi → Carica file,\n"
            "oppure incolla nel campo testo temporizzato.",
        )

    def _save_srt_as(self, title: str, default_name: str):
        """Salva l'SRT corrente dove sceglie l'utente; gli errori di scrittura sono mostrati."""
        from PySide6.QtWidgets import QMessageBox
        from core.export_formats import BY_EXT
        from core.srt_io import write_srt
        from ui.export_dialogs import ask_save_path
        if not self._current_subs:
            return
        path = ask_save_path(self, BY_EXT[".srt"], title, default_name)
        if not path:
            return
        try:
            write_srt(self._current_subs, path)
        except OSError as e:
            QMessageBox.critical(self, "Errore esportazione",
                                 f"Impossibile salvare il file:\n{e}")

    def _publish_vimeo(self):
        """Esporta SRT per l'uploader di Vimeo."""
        self._save_srt_as("Esporta per Vimeo", "sottotitoli_vimeo.srt")

    def _publish_premiere(self):
        """Esporta SRT per NLE (Premiere/DaVinci)."""
        self._save_srt_as("Esporta per NLE", "sottotitoli_nle.srt")

    def _publish_clipboard(self):
        """Copia SRT completo negli appunti."""
        from PySide6.QtWidgets import QApplication
        from core.srt_io import subtitles_to_srt
        if not self._current_subs:
            return
        QApplication.clipboard().setText(subtitles_to_srt(self._current_subs))

    # ── Update ────────────────────────────────────────────────────────────────

    def update_info(
        self,
        subtitles: list,
        source_path: str,
        has_editor_subs: bool,
        is_modified: bool,
    ):
        from core.srt_io import subtitles_to_srt
        self._current_subs = subtitles

        n = len(subtitles)
        self._lbl_count.setText(f"{n} sottotitoli")
        self._lbl_source.setText(f"Fonte: {Path(source_path).name}" if source_path else "")
        self._lbl_source.set_full_tooltip(source_path)
        self._lbl_source.setVisible(bool(source_path))
        n_empty = sum(1 for s in subtitles if not s.text.strip())
        if n_empty:
            self._lbl_empty_warn.setText(
                f"Attenzione: {n_empty} sottotitol{'o' if n_empty == 1 else 'i'} senza testo"
                + (" — l'esportazione sarebbe vuota." if n_empty == n else ".")
            )
        self._lbl_empty_warn.setVisible(bool(n_empty))
        self._warn_icon.setVisible(bool(n_empty))
        self._lbl_origin.setText(
            "Versione dell'editor" if has_editor_subs
            else "Trascrizione originale"
        )
        self._badge_modified.setVisible(has_editor_subs and is_modified)
        is_video = Path(source_path).suffix.lower() in SUPPORTED_VIDEO_EXTS
        self.btn_video.setEnabled(is_video)
        desc = _VIDEO_DESC if is_video else _VIDEO_NEEDS_SOURCE
        self.btn_video.sub_lbl.setText(desc)
        self.btn_video.setToolTip(desc)
        self.btn_video.setAccessibleDescription(desc)

        preview_subs = subtitles[:self._PREVIEW_BLOCKS]
        preview_text = subtitles_to_srt(preview_subs)
        if n > self._PREVIEW_BLOCKS:
            preview_text += f"\n… e altri {n - self._PREVIEW_BLOCKS} sottotitoli"
        self._preview.setPlainText(preview_text)
