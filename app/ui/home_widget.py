"""
home_widget.py — Schermata Home (Stato 0).

Layout (design system "Studio"):
  ┌──────────────────────────────────────────────┐
  │  [DepsBanner — solo se dipendenze mancano]   │
  ├──────────────────────────────────────────────┤
  │  eyebrow "TRASCRIZIONE"                      │
  │  Titolo grande 30px                          │
  │  Sottotitolo descrittivo                     │
  ├──────────────────────────────────────────────┤
  │  DropZone  (idle / hover / loaded / error)   │
  ├──────────────────────────────────────────────┤
  │  Settings card (grid 4 col)                  │
  │   Modello | Lingua | VAD | Alta precisione   │
  ├──────────────────────────────────────────────┤
  │  Action row: stima  ·  [Avvia]               │
  ├──────────────────────────────────────────────┤
  │  [Recenti — solo se ci sono file]            │
  └──────────────────────────────────────────────┘

Tema chiaro/scuro: i colori vengono letti da theme.c() e ri-applicati su
theme_changed via _apply_palette().

Segnali:
  start_requested(source_path, settings) → avvio trascrizione
  open_requested(path)                   → file SRT/.v2srt trascinato sulla drop zone
"""

from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QFileDialog, QScrollArea, QStackedLayout,
)

from core.constants import (
    SUPPORTED_AUDIO_EXTS, SUPPORTED_MEDIA_EXTS, SUPPORTED_SUBTITLE_EXTS,
)
from ui.prefs import RECENT_KEY, add_recent, read_list
from ui.widgets import DepsBanner, ElidedLabel, SwitchPill, ToggleSwitch, fmt_size
from ui import icons, theme
import platform_support


_SHOWN_RECENTS = 3

# Filtro del dialog: le estensioni accettate vengono da core.constants
_MEDIA_GLOB = " ".join(f"*{e}" for e in sorted(SUPPORTED_MEDIA_EXTS))
FILE_FILTER_MEDIA = f"File video o audio ({_MEDIA_GLOB});;Tutti i file (*.*)"
_FORMATS_HINT = "MP4, MOV, MKV, WAV, MP3, M4A, FLAC…"


def _is_media(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_MEDIA_EXTS


def _is_subtitle(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUBTITLE_EXTS


def _combo_ss() -> str:
    c = theme.c
    return (
        f"QComboBox {{ background: {c('card_2')}; border: 1px solid transparent; border-radius: 4px;"
        f" color: {c('text')}; padding: 5px 10px; font-size: 13px; font-weight: 500; min-height: 22px; }}"
        f"QComboBox:hover {{ border-color: {c('line_2')}; }}"
        f"QComboBox:focus {{ border: 2px solid {c('focus')}; }}"
        "QComboBox::drop-down { border: none; width: 22px; }"
        f"{theme.combo_arrow_rule()}"
        f"QComboBox QAbstractItemView {{ background: {c('card')}; border: 1px solid {c('line_2')};"
        f" color: {c('text')}; selection-background-color: {c('acc_fill')};"
        f" selection-color: {c('acc_ink')}; border-radius: 4px; }}"
    )


class HomeWidget(QWidget):
    """Schermata iniziale: drag&drop + impostazioni + avvia."""

    start_requested = Signal(str, dict)   # (source_path, settings)
    open_requested  = Signal(str)         # SRT / .v2srt da aprire nell'editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._source_path: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Scroll area ───────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        root.addWidget(scroll)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        scroll.setWidget(inner)

        lay = QVBoxLayout(inner)
        lay.setContentsMargins(48, 40, 48, 40)
        lay.setSpacing(0)
        lay.addStretch(1)

        # contenuto centrato a max 780px
        content = QWidget()
        content.setMaximumWidth(780)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ── Banner dipendenze ─────────────────────────────────────────────────
        self.deps_banner = DepsBanner()
        cl.addWidget(self.deps_banner)
        cl.addSpacing(8)

        # ── Header ───────────────────────────────────────────────────────────
        self._eyebrow = QLabel("Trascrizione")
        cl.addWidget(self._eyebrow)
        cl.addSpacing(10)

        self._title = QLabel("Trasforma il tuo video in sottotitoli SRT.")
        self._title.setWordWrap(True)
        cl.addWidget(self._title)
        cl.addSpacing(10)

        self._sub = QLabel(
            "Trascrizione automatica in italiano, interamente in locale sul tuo computer. "
            "Trascina un file, scegli il modello e ottieni sottotitoli pronti da rifinire "
            "nell'editor."
        )
        self._sub.setWordWrap(True)
        cl.addWidget(self._sub)
        cl.addSpacing(24)

        # ── DropZone ──────────────────────────────────────────────────────────
        self.drop = _DesignDropZone()
        self.drop.file_selected.connect(self._on_file_selected)
        self.drop.file_error.connect(self._on_file_error)
        self.drop.open_requested.connect(self.open_requested)
        cl.addWidget(self.drop)
        cl.addSpacing(16)

        # ── Settings card ─────────────────────────────────────────────────────
        self._settings_card = self._build_settings_card()
        cl.addWidget(self._settings_card)
        cl.addSpacing(20)

        # ── Action row ────────────────────────────────────────────────────────
        ar = QHBoxLayout()
        ar.setSpacing(12)
        self._estimate_lbl = QLabel("Stima: –")
        self._estimate_lbl.setWordWrap(True)
        ar.addWidget(self._estimate_lbl, 1)
        self.start_btn = QPushButton("Avvia trascrizione")
        self.start_btn.setObjectName("primary")
        self._start_icon = icons.bind_icon(self.start_btn, "play", "acc_ink")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setMinimumWidth(200)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setToolTip("Avvia la trascrizione  (Invio)")
        self.start_btn.clicked.connect(self._on_start)
        ar.addWidget(self.start_btn)
        cl.addLayout(ar)
        cl.addSpacing(24)

        # ── Recenti ───────────────────────────────────────────────────────────
        self._recents_widget = _RecentsWidget()
        self._recents_widget.file_selected.connect(self._on_file_selected)
        cl.addWidget(self._recents_widget)

        # centra content
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(content, 0)
        center_row.addStretch(1)
        lay.addLayout(center_row)
        lay.addStretch(1)

        # Ordine di tab: file → impostazioni → avvio → recenti
        chain = [self.drop, self.model_combo, self.lang_combo, self.vad_toggle,
                 self.accuracy_toggle, self.start_btn]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

        self._apply_palette()
        self._set_start_btn_state(False)
        self._refresh_recents()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ── Sfondo piatto ─────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.qcolor("bg"))
        p.end()

    def keyPressEvent(self, event):
        # Invio avvia la trascrizione (azione principale della schermata)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.start_btn.isEnabled():
            self._on_start()
            return
        super().keyPressEvent(event)

    # ── Tema ────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        self.drop._apply_palette()
        self._recents_widget._apply_palette()
        ss = _combo_ss()
        self.model_combo.setStyleSheet(ss)
        self.lang_combo.setStyleSheet(ss)
        self.vad_toggle._apply_palette()
        self.accuracy_toggle._apply_palette()
        self._set_start_btn_state(self._source_path is not None)
        self.update()

    def _apply_palette(self):
        c = theme.c
        self._eyebrow.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {c('muted')};"
            " background: transparent;"
        )
        self._title.setStyleSheet(
            f"font-size: 30px; font-weight: 600; color: {c('text')};"
            " background: transparent;"
        )
        self._sub.setStyleSheet(f"font-size: 14.5px; color: {c('dim')}; background: transparent;")
        self._estimate_lbl.setStyleSheet(
            f"font-size: 12px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._settings_card.setStyleSheet(
            f"QFrame#settingsCard {{ background-color: {c('card')};"
            f" border: 1px solid {c('card_border')}; border-radius: 4px; }}"
        )
        self._head_lbl.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {c('muted')};"
            " background: transparent;"
        )
        self._preset_lbl.setStyleSheet(
            f"font-size: 11px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        for lbl in self._field_labels:
            lbl.setStyleSheet(
                f"font-size: 10px; font-weight: 600; color: {c('muted')};"
                " background: transparent;"
            )

    # ── Settings card ─────────────────────────────────────────────────────────

    def _build_settings_card(self) -> QFrame:
        from engine import MODELS, DEFAULT_MODEL
        self._models = MODELS
        self._model_keys = list(MODELS.keys())

        card = QFrame()
        card.setObjectName("settingsCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        # header row: titolo a sinistra, riepilogo impostazioni a destra
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        self._head_lbl = QLabel("Impostazioni di trascrizione")
        head_row.addWidget(self._head_lbl)
        head_row.addStretch()
        self._preset_lbl = ElidedLabel("", Qt.ElideRight)
        self._preset_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head_row.addWidget(self._preset_lbl, 1)
        lay.addLayout(head_row)

        # grid 4 col: Modello | Lingua | VAD | Alta precisione
        grid = QHBoxLayout()
        grid.setSpacing(14)

        self._field_labels = []
        ss = _combo_ss()

        col_m = self._col("Modello Whisper")
        self.model_combo = QComboBox()
        self.model_combo.setAccessibleName("Modello Whisper")
        self.model_combo.setStyleSheet(ss)
        for k in self._model_keys:
            self.model_combo.addItem(self._models[k]["label"].rstrip(" ★").rstrip(), k)
        self.model_combo.setCurrentIndex(self._model_keys.index(DEFAULT_MODEL))
        self.model_combo.currentIndexChanged.connect(self._update_estimate)
        self.model_combo.currentIndexChanged.connect(self._update_preset_label)
        col_m.addWidget(self.model_combo)
        grid.addLayout(col_m, 2)

        col_l = self._col("Lingua")
        self.lang_combo = QComboBox()
        self.lang_combo.setAccessibleName("Lingua dell'audio")
        self.lang_combo.setStyleSheet(ss)
        for label, code in (("Italiano", "it"), ("Inglese", "en"), ("Spagnolo", "es"),
                            ("Francese", "fr"), ("Tedesco", "de"),
                            ("Rilevamento automatico", "auto")):
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentIndexChanged.connect(self._update_preset_label)
        col_l.addWidget(self.lang_combo)
        grid.addLayout(col_l, 2)

        col_v = self._col("Filtro VAD")
        self.vad_toggle = _ToggleSwitch("Attivo", "Disattivo", name="Filtro VAD")
        self.vad_toggle.setToolTip("Salta i tratti senza parlato (consigliato)")
        self.vad_toggle.setChecked(True)
        self.vad_toggle.toggled.connect(self._update_preset_label)
        col_v.addWidget(self.vad_toggle)
        col_v.addStretch()
        grid.addLayout(col_v, 1)

        col_hp = self._col("Alta precisione")
        self.accuracy_toggle = _ToggleSwitch("Attiva", "Standard", name="Alta precisione")
        self.accuracy_toggle.setChecked(False)
        self.accuracy_toggle.setToolTip(
            "Allineamento fonetico delle parole con WhisperX: tempi più precisi, più lento."
        )
        self.accuracy_toggle.toggled.connect(self._update_preset_label)
        self._apply_accuracy_availability()
        col_hp.addWidget(self.accuracy_toggle)
        col_hp.addStretch()
        grid.addLayout(col_hp, 1)

        # beam_spin non visibile: valore di default letto da _get_settings()
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 15)
        self.beam_spin.setValue(5)
        self.beam_spin.hide()

        lay.addLayout(grid)
        self._update_preset_label()
        return card

    def _apply_accuracy_availability(self):
        """Disattiva "Alta precisione" se WhisperX non è utilizzabile, spiegando perché."""
        try:
            from engine import high_accuracy_unavailable_reason
            reason = high_accuracy_unavailable_reason()
        except Exception as exc:  # noqa: BLE001 — engine non importabile: opzione non usabile
            reason = f"motore di trascrizione non disponibile ({exc})"
        if reason:
            self.accuracy_toggle.set_unavailable(
                "Non disp.",
                f"Alta precisione non disponibile: {reason}.\n"
                "La trascrizione usa la modalità standard.",
            )

    def _update_preset_label(self):
        """Riepilogo inline delle impostazioni correnti (nell'header della card)."""
        parts = [self.lang_combo.currentText()]
        model_key = self.model_combo.currentData()
        if model_key:
            parts.append(str(model_key))
        parts.append("VAD attivo" if self.vad_toggle.isChecked() else "VAD disattivo")
        parts.append("alta precisione" if self.accuracy_toggle.isChecked() else "standard")
        self._preset_lbl.setText("  ·  ".join(parts))

    def _col(self, label: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)
        lbl = QLabel(label)
        self._field_labels.append(lbl)
        col.addWidget(lbl)
        return col

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_file_selected(self, path: str):
        if not _is_media(path) or not os.path.isfile(path):
            self._on_file_error(Path(path).suffix.lstrip(".").lower())
            return
        self._source_path = path
        self.drop.show_loaded(path)
        self._set_start_btn_state(True)
        self._update_estimate()
        self._add_to_recents(path)
        self._refresh_recents()

    def _set_start_btn_state(self, enabled: bool):
        c = theme.c
        if enabled:
            self.start_btn.setEnabled(True)
            self.start_btn.setText("Avvia trascrizione")
            self._start_icon.set_icon("play", "acc_ink")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                f"  background-color: {c('acc_fill')};"
                f"  color: {c('acc_ink')};"
                "  border: none;"
                "  border-radius: 4px;"
                "  font-size: 14px;"
                "  font-weight: 600;"
                "  padding: 0 22px;"
                "  min-height: 44px;"
                "}"
                f"QPushButton:hover {{ background-color: {c('acc_fill_h')}; }}"
                f"QPushButton:pressed {{ background-color: {c('acc_fill_d')}; }}"
                + theme.focus_rule("QPushButton", 8)
            )
        else:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("Avvia trascrizione")
            self._start_icon.set_icon("play", "muted")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                f"  background-color: {c('card')};"
                f"  color: {c('muted')};"
                f"  border: 1px solid {c('line')};"
                "  border-radius: 4px;"
                "  font-size: 14px;"
                "  font-weight: 500;"
                "  padding: 0 22px;"
                "  min-height: 44px;"
                "}"
            )

    def _on_file_error(self, ext: str):
        self.drop.show_error(ext)
        self._source_path = None
        self._set_start_btn_state(False)
        self._estimate_lbl.setText(
            f"Formato .{ext} non supportato" if ext else "Formato non supportato"
        )

    def _on_start(self):
        if not self._source_path:
            return
        self.start_requested.emit(self._source_path, self._get_settings())

    def _get_settings(self) -> dict:
        return {
            "model_size":    self.model_combo.currentData(),
            "language":      self.lang_combo.currentData(),
            "vad_filter":    self.vad_toggle.isChecked(),
            "denoise":       True,
            "high_accuracy": self.accuracy_toggle.isEnabled() and self.accuracy_toggle.isChecked(),
            "beam_size":     self.beam_spin.value(),
        }

    def _update_estimate(self):
        if not self._source_path:
            self._estimate_lbl.setText("Stima: –")
            return
        try:
            size_mb = os.path.getsize(self._source_path) / (1024 * 1024)
            model_key = self.model_combo.currentData() or "large-v3"
            factor = {
                "tiny": 0.15, "base": 0.25, "small": 0.4,
                "medium": 0.65, "large-v2": 1.0, "large-v3": 1.0,
            }.get(model_key, 1.0)
            mins = max(1, int(size_mb * factor / 100 * 1.5))
            srt_kb = max(1, int(size_mb * 0.05))
            self._estimate_lbl.setText(
                f"Stima: ~ {mins}–{mins * 2} min di lavoro  ·  output ~ {srt_kb} KB .srt"
            )
        except OSError:
            self._estimate_lbl.setText("Stima: –")

    # ── Recenti ───────────────────────────────────────────────────────────────
    # Un'unica lista ("recent_files", condivisa con File → Apri recenti): la Home
    # mostra i file multimediali ancora esistenti.

    def _add_to_recents(self, path: str):
        add_recent(QSettings("VideoSRT", "v2"), path)

    def _refresh_recents(self):
        recents = [
            str(r) for r in read_list(QSettings("VideoSRT", "v2"), RECENT_KEY)
            if _is_media(str(r)) and os.path.isfile(str(r))
        ]
        self._recents_widget.set_recents(recents[:_SHOWN_RECENTS])

    # ── API pubblica ──────────────────────────────────────────────────────────

    def set_deps_status(self, ffmpeg_ok: bool, model_ok: bool):
        self.deps_banner.set_status(ffmpeg_ok, model_ok)

    def preload_file(self, path: str):
        """Pre-carica un file (es. da File → Apri); estensioni non media → errore visibile."""
        self._on_file_selected(path)

    def reset(self):
        self._source_path = None
        self.drop.reset()
        self._set_start_btn_state(False)
        self._estimate_lbl.setText("Stima: –")
        self._refresh_recents()


# ── _DesignDropZone ───────────────────────────────────────────────────────────

class _DesignDropZone(QWidget):
    """
    Drop zone con widget fissi (uno per stato, nessun rebuild). Accetta click,
    Invio/Spazio da tastiera e drag & drop; i formati non supportati vengono
    rifiutati con un messaggio visibile.
    """

    file_selected  = Signal(str)
    file_error     = Signal(str)   # estensione rifiutata (senza punto)
    open_requested = Signal(str)   # SRT / .v2srt: da aprire nell'editor

    _IDLE   = "idle"
    _HOVER  = "hover"
    _LOADED = "loaded"
    _ERROR  = "error"

    # Altezze minime di progetto; quella effettiva segue il contenuto (font grandi)
    _H_NORMAL = 196
    _H_LOADED = 78

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self._IDLE
        self._file_path: str | None = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Scegli il file video o audio da trascrivere")
        self.setAccessibleDescription("Invio o Spazio per sfogliare; oppure trascina qui un file")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        stack = QStackedLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackOne)

        def _state_page(spacing: int = 10) -> tuple:
            w = QWidget()
            lay = QVBoxLayout(w)
            # solo centratura verticale: le etichette a capo usano tutta la larghezza
            lay.setAlignment(Qt.AlignVCenter)
            lay.setSpacing(spacing)
            lay.setContentsMargins(24, 16, 24, 16)
            return w, lay

        def _icon(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(56, 56)
            return lbl

        def _centered(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            return lbl

        # ── Idle ──────────────────────────────────────────────────────────────
        self._w_idle, lay_idle = _state_page()
        self._idle_icon = _icon("")
        lay_idle.addWidget(self._idle_icon, 0, Qt.AlignCenter)
        self._idle_t1 = _centered("Trascina qui un file video o audio")
        lay_idle.addWidget(self._idle_t1)
        self._idle_t2 = _centered(
            f"oppure clicca o premi  {platform_support.shortcut_label('Ctrl+O')}  per scegliere"
            f"  ·  {_FORMATS_HINT}"
        )
        lay_idle.addWidget(self._idle_t2)

        # ── Hover ─────────────────────────────────────────────────────────────
        self._w_hover, lay_hover = _state_page()
        self._hover_icon = _icon("")
        lay_hover.addWidget(self._hover_icon, 0, Qt.AlignCenter)
        self._hover_t1 = _centered("Rilascia per caricare")
        lay_hover.addWidget(self._hover_t1)

        # ── Error ─────────────────────────────────────────────────────────────
        self._w_error, lay_error = _state_page()
        self._err_icon = _icon("")
        lay_error.addWidget(self._err_icon, 0, Qt.AlignCenter)
        self._err_t1 = _centered("Formato non supportato")
        lay_error.addWidget(self._err_t1)
        self._err_t2 = _centered(f"Usa un file video o audio: {_FORMATS_HINT}")
        lay_error.addWidget(self._err_t2)

        # ── Loaded ────────────────────────────────────────────────────────────
        self._w_loaded = QWidget()
        lay_loaded = QHBoxLayout(self._w_loaded)
        lay_loaded.setSpacing(14)
        lay_loaded.setContentsMargins(20, 12, 20, 12)
        lay_loaded.setAlignment(Qt.AlignVCenter)

        self._loaded_icon = QLabel()
        self._loaded_icon.setAlignment(Qt.AlignCenter)
        self._loaded_icon.setFixedSize(46, 46)
        lay_loaded.addWidget(self._loaded_icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        self._loaded_name = ElidedLabel("")
        self._loaded_detail = QLabel("")
        info_col.addWidget(self._loaded_name)
        info_col.addWidget(self._loaded_detail)
        lay_loaded.addLayout(info_col, 1)

        self._change_btn = QPushButton("Cambia")
        self._change_btn.setMinimumHeight(32)
        self._change_btn.setCursor(Qt.PointingHandCursor)
        self._change_btn.setAccessibleName("Cambia file")
        self._change_btn.clicked.connect(self._open_dialog)
        lay_loaded.addWidget(self._change_btn)

        for w in (self._w_idle, self._w_hover, self._w_error, self._w_loaded):
            stack.addWidget(w)
        self._stack = stack
        self._set_state(self._IDLE)

        self._apply_palette()

    def _apply_palette(self):
        c = theme.c
        self._idle_icon.setStyleSheet(
            f"background: {c('raise')}; border: none; border-radius: 4px;"
        )
        self._idle_icon.setPixmap(icons.pixmap("import", theme.qcolor("dim"), 28))
        self._idle_t1.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {c('text')}; background: transparent;")
        self._idle_t2.setStyleSheet(
            f"font-size: 12px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._hover_icon.setStyleSheet(
            f"background: {c('acc_soft_2')}; border: 1px solid {c('acc')}; border-radius: 4px;"
        )
        self._hover_icon.setPixmap(icons.pixmap("import", theme.qcolor("acc"), 28))
        self._hover_t1.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {c('text')}; background: transparent;")
        self._err_icon.setStyleSheet(
            f"background: {c('err_soft')}; border: 1px solid {c('err')}; border-radius: 4px;"
        )
        self._err_icon.setPixmap(icons.pixmap("alert", theme.qcolor("err"), 28))
        self._err_t1.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {c('err')}; background: transparent;")
        self._err_t2.setStyleSheet(f"font-size: 12px; color: {c('muted')}; background: transparent;")
        self._loaded_icon.setStyleSheet(
            f"background: {c('raise')}; border: none; border-radius: 4px;"
        )
        self._loaded_icon.setPixmap(icons.pixmap("video", theme.qcolor("dim"), 24))
        self._loaded_name.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {c('text')}; background: transparent;"
        )
        self._loaded_detail.setStyleSheet(
            f"font-size: 12px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._change_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {c('line_2')};"
            f" border-radius: 4px; color: {c('dim')}; font-size: 12.5px; font-weight: 500; padding: 4px 13px; }}"
            f"QPushButton:hover {{ background: {c('card_2')}; border-color: {c('line_2')}; color: {c('text')}; }}"
            f"QPushButton:pressed {{ background: {c('card')}; }}"
            + theme.focus_rule("QPushButton", 7)
        )
        self.update()

    def _set_state(self, state: str):
        self._state = state
        page = {self._IDLE: self._w_idle, self._HOVER: self._w_hover,
                self._ERROR: self._w_error, self._LOADED: self._w_loaded}[state]
        self._stack.setCurrentWidget(page)
        base = self._H_LOADED if state == self._LOADED else self._H_NORMAL
        # Altezza dal contenuto: con font grandi il testo non viene tagliato
        self.setFixedHeight(max(base, page.sizeHint().height() + 8))
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)

        border = {self._IDLE: "line_2", self._HOVER: "acc", self._LOADED: "line_2",
                  self._ERROR: "err"}[self._state]
        p.setBrush(theme.qcolor("acc_soft" if self._state == self._HOVER else "card"))
        pen = QPen(theme.qcolor(border))
        if self._state != self._LOADED:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r, 6, 6)

        if self.hasFocus():
            # Anello di focus da tastiera
            focus_pen = QPen(theme.qcolor("focus"))
            focus_pen.setWidth(2)
            p.setPen(focus_pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 4, 4)
        p.end()

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._open_dialog()
            return
        super().keyPressEvent(event)

    # ── Drag & drop ───────────────────────────────────────────────────────────

    @staticmethod
    def _local_paths(mime) -> list:
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, e):
        paths = self._local_paths(e.mimeData())
        if not paths:
            e.ignore()
            return
        # Si accetta sempre un drop di file: quelli non supportati vengono rifiutati
        # al rilascio con un messaggio, invece di ignorarli in silenzio.
        e.acceptProposedAction()
        if any(_is_media(p) or _is_subtitle(p) for p in paths):
            self._set_state(self._HOVER)
        else:
            self._err_t1.setText(f"Formato .{Path(paths[0]).suffix.lstrip('.').lower()} "
                                 "non supportato")
            self._set_state(self._ERROR)

    def dragLeaveEvent(self, e):
        self._set_state(self._LOADED if self._file_path else self._IDLE)

    def dropEvent(self, e):
        paths = self._local_paths(e.mimeData())
        if not paths:
            self.dragLeaveEvent(e)
            return
        e.acceptProposedAction()
        media = next((p for p in paths if _is_media(p) and os.path.isfile(p)), None)
        if media:
            self.file_selected.emit(media)
            return
        subtitle = next((p for p in paths if _is_subtitle(p) and os.path.isfile(p)), None)
        if subtitle:
            self.dragLeaveEvent(e)
            self.open_requested.emit(subtitle)
            return
        self.file_error.emit(Path(paths[0]).suffix.lstrip(".").lower())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._open_dialog()

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona un file video o audio", "", FILE_FILTER_MEDIA
        )
        if path:
            if _is_media(path):
                self.file_selected.emit(path)
            else:
                self.file_error.emit(Path(path).suffix.lstrip(".").lower())

    # ── API ───────────────────────────────────────────────────────────────────

    def show_loaded(self, path: str):
        self._file_path = path
        self._loaded_name.setText(Path(path).name)
        self._loaded_name.set_full_tooltip(path)
        ext = Path(path).suffix.upper().lstrip(".")
        self._loaded_detail.setText(f"{fmt_size(path)}  ·  {ext}")
        self.setAccessibleName(f"File selezionato: {Path(path).name}. Invio per cambiarlo")
        self._set_state(self._LOADED)

    def show_error(self, ext: str):
        self._file_path = None
        self._err_t1.setText(f"Formato .{ext} non supportato" if ext else "Formato non supportato")
        self._set_state(self._ERROR)

    def reset(self):
        self._file_path = None
        self.setAccessibleName("Scegli il file video o audio da trascrivere")
        self._set_state(self._IDLE)


# ── Interruttore: ToggleSwitch vive in ui.widgets (alias storici qui sotto) ──

_ToggleSwitch = ToggleSwitch
_SwitchPill = SwitchPill

# ── _RecentsWidget ────────────────────────────────────────────────────────────

class _RecentCard(QFrame):
    """Scheda di un file recente: cliccabile e attivabile da tastiera (Invio/Spazio)."""

    activated = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self.setObjectName("recentCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"Apri recente: {Path(path).name}")
        self.setToolTip(path)
        self.setMinimumHeight(max(54, self.fontMetrics().height() * 2 + 22))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 8, 13, 8)
        lay.setSpacing(11)

        self._ic = QLabel()
        self._ic.setFixedSize(32, 32)
        self._ic.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._ic)

        info = QVBoxLayout()
        info.setSpacing(2)
        self._name = ElidedLabel(Path(path).name)
        self._name.set_full_tooltip(path)
        self._meta = QLabel(fmt_size(path))
        info.addWidget(self._name)
        info.addWidget(self._meta)
        lay.addLayout(info, 1)
        self.apply_palette()

    def _icon_name(self) -> str:
        ext = Path(self._path).suffix.lower()
        if ext in SUPPORTED_SUBTITLE_EXTS:
            return "document"
        return "audio" if ext in SUPPORTED_AUDIO_EXTS else "video"

    def apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"QFrame#recentCard {{ background: {c('card')}; border: 1px solid {c('card_border')};"
            " border-radius: 4px; }"
            f"QFrame#recentCard:hover {{ border-color: {c('acc')}; background: {c('card_2')}; }}"
            f"QFrame#recentCard:focus {{ border: 2px solid {c('focus')}; }}"
        )
        self._ic.setStyleSheet(
            f"background: {c('raise')}; border: none; border-radius: 4px;"
        )
        self._ic.setPixmap(icons.pixmap(self._icon_name(), theme.qcolor("dim"), 16))
        self._name.setStyleSheet(
            f"font-size: 12.5px; font-weight: 500; color: {c('text')};"
            " background: transparent; border: none;"
        )
        self._meta.setStyleSheet(
            f"font-size: 11px; color: {c('muted')}; background: transparent; border: none;"
            f" font-family: {theme.FONT_MONO};"
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self._path)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit(self._path)
            return
        super().keyPressEvent(e)


class _RecentsWidget(QWidget):
    """Riga file recenti — visibile solo se ci sono file."""

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self.setVisible(False)
        self.setStyleSheet("background: transparent;")
        self._paths: list = []

        self._title = QLabel("Recenti")
        self._lay.addWidget(self._title)
        self._row = QHBoxLayout()
        self._row.setSpacing(12)
        self._lay.addLayout(self._row)
        self._cards: list = []
        self._apply_palette()

    def _apply_palette(self):
        self._title.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {theme.c('muted')};"
            " background: transparent;"
        )
        for card in self._cards:
            card.apply_palette()

    def set_recents(self, paths: list):
        self._paths = list(paths)
        for card in self._cards:
            self._row.removeWidget(card)
            card.deleteLater()
        self._cards = []
        for path in self._paths:
            card = _RecentCard(path)
            card.activated.connect(self.file_selected)
            self._row.addWidget(card, 1)
            self._cards.append(card)
        self.setVisible(bool(self._paths))
