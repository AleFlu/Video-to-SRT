"""
home_widget.py — Schermata Home (Stato 0).

Layout (design system Palette A):
  ┌──────────────────────────────────────────────┐
  │  [DepsBanner — solo se dipendenze mancano]   │
  ├──────────────────────────────────────────────┤
  │  eyebrow "TRASCRIZIONE"                      │
  │  Titolo grande 28px                          │
  │  Sottotitolo descrittivo                     │
  ├──────────────────────────────────────────────┤
  │  DropZone  (idle / hover / loaded / error)   │
  ├──────────────────────────────────────────────┤
  │  Settings card (grid 4 col)                  │
  │   Modello | Beam | VAD | Alta precisione     │
  ├──────────────────────────────────────────────┤
  │  Action row: stima  ·  [Avvia]               │
  ├──────────────────────────────────────────────┤
  │  [Recenti — solo se QSettings ha file]       │
  └──────────────────────────────────────────────┘

Segnale start_requested(source_path, settings) → MainWindow.
"""

from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QFileDialog, QScrollArea,
)

from ui.source_panel import DepsBanner, SUPPORTED_EXTS, FILE_FILTERS, fmt_size
from ui.theme import AuroraMixin


_MAX_RECENTS = 5


class HomeWidget(AuroraMixin, QWidget):
    """Schermata iniziale: drag&drop + impostazioni + avvia."""

    start_requested = Signal(str, dict)   # (source_path, settings)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._source_path: str | None = None
        self._aurora_init()

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
        lay.setContentsMargins(80, 48, 80, 48)
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
        eyebrow = QLabel("TRASCRIZIONE")
        eyebrow.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #6c727f;"
            " letter-spacing: 1.5px; background: transparent;"
        )
        cl.addWidget(eyebrow)
        cl.addSpacing(8)

        title = QLabel("Trasforma il tuo video in sottotitoli SRT.")
        title.setStyleSheet(
            "font-size: 28px; font-weight: 600; color: #e8eaf0;"
            " letter-spacing: -0.5px; background: transparent;"
        )
        title.setWordWrap(True)
        cl.addWidget(title)
        cl.addSpacing(8)

        sub = QLabel(
            "Trascina un file video o audio. La trascrizione avviene in locale, "
            "in italiano, con il modello Whisper selezionato."
        )
        sub.setStyleSheet("font-size: 14px; color: #a8aebb; background: transparent;")
        sub.setWordWrap(True)
        cl.addWidget(sub)
        cl.addSpacing(24)

        # ── DropZone ──────────────────────────────────────────────────────────
        self.drop = _DesignDropZone()
        self.drop.file_selected.connect(self._on_file_selected)
        self.drop.file_error.connect(self._on_file_error)
        cl.addWidget(self.drop)
        cl.addSpacing(12)

        # ── Settings card ─────────────────────────────────────────────────────
        self._settings_card = self._build_settings_card()
        cl.addWidget(self._settings_card)
        cl.addSpacing(16)

        # ── Action row ────────────────────────────────────────────────────────
        ar = QHBoxLayout()
        ar.setSpacing(12)
        self._estimate_lbl = QLabel("Stima: –")
        self._estimate_lbl.setStyleSheet("font-size: 12px; color: #6c727f; background: transparent;")
        ar.addWidget(self._estimate_lbl)
        ar.addStretch(1)
        self._preview_btn = QPushButton("Anteprima impostazioni")
        self._preview_btn.setObjectName("secondary")
        self._preview_btn.setMinimumHeight(44)
        self._preview_btn.setCursor(Qt.PointingHandCursor)
        self._preview_btn.clicked.connect(self._on_preview_settings)
        ar.addWidget(self._preview_btn)
        self.start_btn = QPushButton("Avvia trascrizione")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setMinimumWidth(200)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        self._set_start_btn_state(False)
        ar.addWidget(self.start_btn)
        cl.addLayout(ar)
        cl.addSpacing(24)

        # ── Recenti ───────────────────────────────────────────────────────────
        self._recents_widget = _RecentsWidget()
        self._recents_widget.file_selected.connect(self._on_file_selected)
        cl.addWidget(self._recents_widget)
        self._refresh_recents()

        # centra content
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(content, 0)
        center_row.addStretch(1)
        lay.addLayout(center_row)
        lay.addStretch(1)

    # ── Aurora ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        self._aurora_paint(p)
        p.end()

    # ── Settings card ─────────────────────────────────────────────────────────

    def _build_settings_card(self) -> QFrame:
        from engine import MODELS, DEFAULT_MODEL
        self._models = MODELS
        self._model_keys = list(MODELS.keys())

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #1a1d24; border: none; border-radius: 11px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        # header row: titolo a sinistra, riepilogo preset a destra
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head = QLabel("IMPOSTAZIONI DI TRASCRIZIONE")
        head.setStyleSheet(
            "font-size: 10px; font-weight: 600; color: #6c727f;"
            " letter-spacing: 1.2px; background: transparent;"
        )
        head_row.addWidget(head)
        head_row.addStretch()
        self._preset_lbl = QLabel("")
        self._preset_lbl.setStyleSheet(
            "font-size: 10px; color: #4a4f5a; background: transparent;"
        )
        head_row.addWidget(self._preset_lbl)
        lay.addLayout(head_row)

        # grid 4 col: Modello | Lingua | VAD | Alta precisione
        grid = QHBoxLayout()
        grid.setSpacing(14)

        _combo_ss = (
            "QComboBox { background: #1f232c; border: none; border-radius: 7px;"
            " color: #e8eaf0; padding: 5px 10px; font-size: 13px; font-weight: 500; min-height: 32px; }"
            "QComboBox::drop-down { border: none; width: 22px; }"
            "QComboBox::down-arrow { border-left: 4px solid transparent;"
            " border-right: 4px solid transparent; border-top: 5px solid #6c727f; margin-right: 8px; }"
            "QComboBox QAbstractItemView { background: #1a1d24; border: 1px solid #262a33;"
            " color: #e8eaf0; selection-background-color: #3f6fd8; border-radius: 7px; }"
        )

        # Modello
        col_m = self._col("MODELLO WHISPER")
        self.model_combo = QComboBox()
        self.model_combo.setStyleSheet(_combo_ss)
        for k in self._model_keys:
            self.model_combo.addItem(self._models[k]["label"], k)
        self.model_combo.setCurrentIndex(self._model_keys.index(DEFAULT_MODEL))
        self.model_combo.currentIndexChanged.connect(self._update_estimate)
        self.model_combo.currentIndexChanged.connect(self._update_preset_label)
        col_m.addWidget(self.model_combo)
        grid.addLayout(col_m, 2)

        # Lingua
        col_l = self._col("LINGUA")
        self.lang_combo = QComboBox()
        self.lang_combo.setStyleSheet(_combo_ss)
        self.lang_combo.addItem("Italiano  auto", "it")
        self.lang_combo.addItem("English  auto", "en")
        self.lang_combo.addItem("Español  auto", "es")
        self.lang_combo.addItem("Français  auto", "fr")
        self.lang_combo.addItem("Deutsch  auto", "de")
        self.lang_combo.addItem("Auto-detect", "auto")
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentIndexChanged.connect(self._update_preset_label)
        col_l.addWidget(self.lang_combo)
        grid.addLayout(col_l, 2)

        # VAD
        col_v = self._col("FILTRO VAD")
        self.vad_toggle = _ToggleSwitch("Attivo", "Disattivo")
        self.vad_toggle.setChecked(True)
        self.vad_toggle.toggled.connect(self._update_preset_label)
        col_v.addWidget(self.vad_toggle)
        col_v.addStretch()
        grid.addLayout(col_v, 1)

        # Alta precisione
        col_hp = self._col("ALTA PRECISIONE")
        self.accuracy_toggle = _ToggleSwitch("Attiva", "Standard")
        self.accuracy_toggle.setChecked(False)
        self.accuracy_toggle.setToolTip(
            "Usa WhisperX con allineamento fonetico.\nRichiede: pip install whisperx"
        )
        self.accuracy_toggle.toggled.connect(self._update_preset_label)
        col_hp.addWidget(self.accuracy_toggle)
        col_hp.addStretch()
        grid.addLayout(col_hp, 1)

        # beam_spin non visibile ma mantenuto per compatibilità con _get_settings()
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 15)
        self.beam_spin.setValue(5)
        self.beam_spin.hide()

        lay.addLayout(grid)
        self._update_preset_label()
        return card

    def _update_preset_label(self):
        """Aggiorna il testo riepilogo preset nell'header della card."""
        active = 0
        parts = []
        model_key = self.model_combo.currentData() if hasattr(self, "model_combo") else ""
        if self.vad_toggle.isChecked():
            active += 1
        if self.accuracy_toggle.isChecked():
            active += 1
            parts.append("Alta qualità")
        else:
            parts.append("Standard")
        lang_text = self.lang_combo.currentText().split()[0] if hasattr(self, "lang_combo") else "Italiano"
        parts.insert(0, lang_text)
        active += 1  # lingua sempre attiva
        preset = "  ·  ".join(parts)
        self._preset_lbl.setText(f'{active} attive  ·  preset "{preset}"')

    def _col(self, label: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "font-size: 10px; font-weight: 600; color: #6c727f;"
            " letter-spacing: 1px; background: transparent;"
        )
        col.addWidget(lbl)
        return col

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_file_selected(self, path: str):
        self._source_path = path
        self.drop.show_loaded(path)
        self._set_start_btn_state(True)
        self._update_estimate()
        self._add_to_recents(path)
        self._refresh_recents()

    def _set_start_btn_state(self, enabled: bool):
        if enabled:
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶  Avvia trascrizione")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #5b8cff;"
                "  color: #ffffff;"
                "  border: none;"
                "  border-radius: 9px;"
                "  font-size: 14px;"
                "  font-weight: 600;"
                "  padding: 0 22px;"
                "  min-height: 44px;"
                "}"
                "QPushButton:hover { background-color: #7aa2ff; }"
                "QPushButton:pressed { background-color: #3f6fd8; }"
            )
        else:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("Avvia trascrizione")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #1a1d24;"
                "  color: #6c727f;"
                "  border: 1px solid #2f343e;"
                "  border-radius: 9px;"
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
        self._estimate_lbl.setText("Formato non supportato")

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
            "high_accuracy": self.accuracy_toggle.isChecked(),
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
            size_str = fmt_size(self._source_path)
            srt_kb = max(1, int(size_mb * 0.05))
            self._estimate_lbl.setText(
                f"Stima: ~ {mins}–{mins * 2} min di lavoro  ·  output ~ {srt_kb} KB .srt"
            )
        except OSError:
            self._estimate_lbl.setText("Stima: –")

    def _on_preview_settings(self):
        from PySide6.QtWidgets import QMessageBox
        s = self._get_settings()
        model_lbl = self._models.get(s["model_size"], {}).get("label", s["model_size"])
        lang = self.lang_combo.currentText()
        vad = "Attivo" if s["vad_filter"] else "Disattivo"
        prec = "Alta qualità" if s["high_accuracy"] else "Standard"
        QMessageBox.information(
            self, "Impostazioni di trascrizione",
            f"Modello:        {model_lbl}\n"
            f"Lingua:          {lang}\n"
            f"Filtro VAD:    {vad}\n"
            f"Precisione:    {prec}\n"
            f"Beam size:    {s['beam_size']}",
        )

    # ── Recenti ───────────────────────────────────────────────────────────────

    def _add_to_recents(self, path: str):
        s = QSettings("VideoSRT", "v2")
        recents: list = s.value("recents", []) or []
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        recents = [r for r in recents if os.path.isfile(r)][:_MAX_RECENTS]
        s.setValue("recents", recents)

    def _refresh_recents(self):
        s = QSettings("VideoSRT", "v2")
        recents: list = s.value("recents", []) or []
        recents = [r for r in recents if os.path.isfile(r)][:_MAX_RECENTS]
        self._recents_widget.set_recents(recents)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def set_deps_status(self, ffmpeg_ok: bool, model_ok: bool):
        self.deps_banner.set_status(ffmpeg_ok, model_ok)

    def preload_file(self, path: str):
        self._on_file_selected(path)

    def reset(self):
        self._source_path = None
        self.drop.reset()
        self._set_start_btn_state(False)
        self._estimate_lbl.setText("Stima: –")
        self._refresh_recents()


# ── _DesignDropZone ───────────────────────────────────────────────────────────

class _DesignDropZone(QWidget):
    """Drop zone con widget fissi — nessun rebuild, nessuna sovrapposizione."""

    file_selected = Signal(str)
    file_error    = Signal(str)

    _IDLE   = "idle"
    _HOVER  = "hover"
    _LOADED = "loaded"
    _ERROR  = "error"

    _H_NORMAL = 180
    _H_LOADED = 72

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self._IDLE
        self._file_path: str | None = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(self._H_NORMAL)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Stack: un QWidget per stato, sempre presenti, show/hide
        from PySide6.QtWidgets import QStackedLayout
        stack = QStackedLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackOne)

        # ── Idle ──────────────────────────────────────────────────────────────
        self._w_idle = QWidget()
        self._w_idle.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        lay_idle = QVBoxLayout(self._w_idle)
        lay_idle.setAlignment(Qt.AlignCenter)
        lay_idle.setSpacing(8)
        lay_idle.setContentsMargins(24, 0, 24, 0)

        idle_icon = QLabel("↓")
        idle_icon.setAlignment(Qt.AlignCenter)
        idle_icon.setFixedSize(52, 52)
        idle_icon.setStyleSheet(
            "font-size: 22px; color: #6c727f; background: #1f232c;"
            " border: 1px solid #2f343e; border-radius: 12px;"
        )
        lay_idle.addWidget(idle_icon, 0, Qt.AlignCenter)
        t1 = QLabel("Trascina qui un file video o audio")
        t1.setAlignment(Qt.AlignCenter)
        t1.setStyleSheet("font-size: 15px; font-weight: 600; color: #e8eaf0; background: transparent;")
        lay_idle.addWidget(t1)
        t2 = QLabel("oppure  ⌘O  per scegliere  ·  MP4, MOV, MKV, WAV, MP3 fino a 4 GB")
        t2.setAlignment(Qt.AlignCenter)
        t2.setStyleSheet(
            "font-size: 12px; color: #6c727f; background: transparent;"
            " font-family: 'SF Mono', 'Menlo', monospace;"
        )
        lay_idle.addWidget(t2)

        # ── Hover ─────────────────────────────────────────────────────────────
        self._w_hover = QWidget()
        lay_hover = QVBoxLayout(self._w_hover)
        lay_hover.setAlignment(Qt.AlignCenter)
        lay_hover.setSpacing(8)
        lay_hover.setContentsMargins(24, 0, 24, 0)
        hover_icon = QLabel("↓")
        hover_icon.setAlignment(Qt.AlignCenter)
        hover_icon.setFixedSize(52, 52)
        hover_icon.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #5b8cff;"
            " background: rgba(91,140,255,0.22); border: 1px solid rgba(91,140,255,0.5); border-radius: 12px;"
        )
        lay_hover.addWidget(hover_icon, 0, Qt.AlignCenter)
        hover_t1 = QLabel("Rilascia per caricare")
        hover_t1.setAlignment(Qt.AlignCenter)
        hover_t1.setStyleSheet("font-size: 15px; font-weight: 600; color: #e8eaf0; background: transparent;")
        lay_hover.addWidget(hover_t1)

        # ── Error ─────────────────────────────────────────────────────────────
        self._w_error = QWidget()
        lay_error = QVBoxLayout(self._w_error)
        lay_error.setAlignment(Qt.AlignCenter)
        lay_error.setSpacing(8)
        lay_error.setContentsMargins(24, 0, 24, 0)
        err_icon = QLabel("!")
        err_icon.setAlignment(Qt.AlignCenter)
        err_icon.setFixedSize(52, 52)
        err_icon.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #ef5e6c;"
            " background: rgba(239,94,108,0.14); border: 1px solid rgba(239,94,108,0.36); border-radius: 12px;"
        )
        lay_error.addWidget(err_icon, 0, Qt.AlignCenter)
        err_t1 = QLabel("Formato non supportato")
        err_t1.setAlignment(Qt.AlignCenter)
        err_t1.setStyleSheet("font-size: 15px; font-weight: 600; color: #ef5e6c; background: transparent;")
        lay_error.addWidget(err_t1)
        err_t2 = QLabel("Usa MP4, MOV, MKV, WAV o MP3.")
        err_t2.setAlignment(Qt.AlignCenter)
        err_t2.setStyleSheet("font-size: 12px; color: #6c727f; background: transparent;")
        lay_error.addWidget(err_t2)

        # ── Loaded ────────────────────────────────────────────────────────────
        self._w_loaded = QWidget()
        lay_loaded = QHBoxLayout(self._w_loaded)
        lay_loaded.setSpacing(14)
        lay_loaded.setContentsMargins(20, 0, 20, 0)
        lay_loaded.setAlignment(Qt.AlignVCenter)

        self._loaded_icon = QLabel("▶")
        self._loaded_icon.setAlignment(Qt.AlignCenter)
        self._loaded_icon.setFixedSize(46, 46)
        self._loaded_icon.setStyleSheet(
            "font-size: 18px; color: #9097a4; background: #1f232c;"
            " border: 1px solid #2f343e; border-radius: 10px;"
        )
        lay_loaded.addWidget(self._loaded_icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        self._loaded_name = QLabel("")
        self._loaded_name.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #e8eaf0; background: transparent;"
        )
        self._loaded_detail = QLabel("")
        self._loaded_detail.setStyleSheet(
            "font-size: 11px; color: #6c727f; background: transparent;"
            " font-family: 'SF Mono', 'Menlo', monospace;"
        )
        info_col.addWidget(self._loaded_name)
        info_col.addWidget(self._loaded_detail)
        lay_loaded.addLayout(info_col, 1)

        change_btn = QPushButton("Cambia")
        change_btn.setFixedHeight(30)
        change_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #2f343e;"
            " border-radius: 7px; color: #a8aebb; font-size: 12px; font-weight: 500; padding: 0 14px; }"
            "QPushButton:hover { background: #2a3040; border-color: #4a5168; color: #ffffff; }"
            "QPushButton:pressed { background: #1a1d24; }"
        )
        change_btn.setCursor(Qt.PointingHandCursor)
        change_btn.clicked.connect(self._open_dialog)
        lay_loaded.addWidget(change_btn)

        # Aggiungi tutti al stack
        stack.addWidget(self._w_idle)    # index 0
        stack.addWidget(self._w_hover)   # index 1
        stack.addWidget(self._w_error)   # index 2
        stack.addWidget(self._w_loaded)  # index 3
        self._stack = stack
        self._stack.setCurrentIndex(0)


    def _set_state(self, state: str):
        self._state = state
        idx = {self._IDLE: 0, self._HOVER: 1, self._ERROR: 2, self._LOADED: 3}[state]
        self._stack.setCurrentIndex(idx)
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)

        if self._state == self._IDLE:
            p.setBrush(QColor("#1a1d24"))
            pen = QPen(QColor("#2f343e"))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 12, 12)

        elif self._state == self._HOVER:
            p.setBrush(QColor("#1f232c"))
            pen = QPen(QColor("#5b8cff"))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 12, 12)
            glow_pen = QPen(QColor(91, 140, 255, 45))
            glow_pen.setWidth(6)
            p.setPen(glow_pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 14, 14)

        elif self._state == self._LOADED:
            p.setBrush(QColor("#1a1d24"))
            p.setPen(QPen(QColor("#262a33")))
            p.drawRoundedRect(r, 12, 12)

        elif self._state == self._ERROR:
            p.setBrush(QColor("#1a1d24"))
            pen = QPen(QColor(239, 94, 108, 130))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 12, 12)

        p.end()

    # ── Drag & drop ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            path = e.mimeData().urls()[0].toLocalFile()
            if Path(path).suffix.lower() in SUPPORTED_EXTS:
                e.acceptProposedAction()
                self.setFixedHeight(self._H_NORMAL)
                self._set_state(self._HOVER)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        if self._file_path:
            self.setFixedHeight(self._H_LOADED)
            self._set_state(self._LOADED)
        else:
            self.setFixedHeight(self._H_NORMAL)
            self._set_state(self._IDLE)

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if not urls:
            self.dragLeaveEvent(e)
            return
        path = urls[0].toLocalFile()
        ext = Path(path).suffix.lower()
        if ext in SUPPORTED_EXTS and os.path.isfile(path):
            self.file_selected.emit(path)
            e.acceptProposedAction()
        else:
            self.file_error.emit(ext.lstrip("."))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._open_dialog()

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona un file video o audio", "", FILE_FILTERS
        )
        if path:
            ext = Path(path).suffix.lower()
            if ext in SUPPORTED_EXTS:
                self.file_selected.emit(path)
            else:
                self.file_error.emit(ext.lstrip("."))

    # ── API ───────────────────────────────────────────────────────────────────

    def show_loaded(self, path: str):
        self._file_path = path
        self._loaded_name.setText(Path(path).name)
        ext = Path(path).suffix.upper().lstrip(".")
        self._loaded_detail.setText(f"{fmt_size(path)}  ·  {ext}")
        self.setFixedHeight(self._H_LOADED)
        self._set_state(self._LOADED)

    def show_error(self, ext: str):
        self._file_path = None
        self.setFixedHeight(self._H_NORMAL)
        self._set_state(self._ERROR)

    def reset(self):
        self._file_path = None
        self.setFixedHeight(self._H_NORMAL)
        self._set_state(self._IDLE)


# ── _ToggleSwitch ─────────────────────────────────────────────────────────────

class _ToggleSwitch(QWidget):
    """Toggle switch stile design — row con pill + label."""

    toggled = Signal(bool)

    def __init__(self, label_on: str = "Attivo", label_off: str = "Disattivo", parent=None):
        super().__init__(parent)
        self._checked = False
        self._on = label_on
        self._off = label_off
        self.setCursor(Qt.PointingHandCursor)
        # altezza fissa — non cambia mai al toggle
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "QWidget { background: #1f232c; border: none; border-radius: 7px; }"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._pill = _SwitchPill()
        lay.addWidget(self._pill)

        # larghezza fissa per la label — evita resize del layout al cambio testo
        max_w = max(len(label_on), len(label_off)) * 8 + 8
        self._lbl = QLabel(self._off)
        self._lbl.setFixedWidth(max_w)
        self._lbl.setStyleSheet(
            "font-size: 12px; font-weight: 500; color: #e8eaf0;"
            " background: transparent; border: none;"
        )
        lay.addWidget(self._lbl)
        lay.addStretch()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self._pill.set_on(val)
        self._lbl.setText(self._on if val else self._off)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)


class _SwitchPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self.setFixedSize(30, 18)

    def set_on(self, val: bool):
        self._on = val
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#5b8cff") if self._on else QColor("#0e1014"))
        p.setPen(QPen(QColor("#5b8cff") if self._on else QColor("#2f343e")))
        p.drawRoundedRect(0, 0, 30, 18, 9, 9)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff") if self._on else QColor("#6c727f"))
        x = 13 if self._on else 1
        p.drawEllipse(x, 1, 14, 14)
        p.end()


# ── _RecentsWidget ────────────────────────────────────────────────────────────

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

    def set_recents(self, paths: list):
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        if not paths:
            self.setVisible(False)
            return

        lbl = QLabel("RECENTI")
        lbl.setStyleSheet(
            "font-size: 10px; font-weight: 600; color: #6c727f;"
            " letter-spacing: 1.2px; background: transparent;"
        )
        self._lay.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        for path in paths[:3]:
            row.addWidget(self._make_card(path), 1)
        self._lay.addLayout(row)
        self.setVisible(True)

    def _make_card(self, path: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1a1d24; border: 1px solid #262a33; border-radius: 9px; }"
            "QFrame:hover { border-color: #3a404e; background: #1f232c; }"
        )
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedHeight(52)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        ic = QLabel("▦")
        ic.setFixedSize(30, 30)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(
            "background: #1f232c; border: 1px solid #2f343e; border-radius: 7px;"
            " color: #9097a4; font-size: 14px;"
        )
        lay.addWidget(ic)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(Path(path).name)
        name.setStyleSheet("font-size: 12px; font-weight: 500; color: #e8eaf0; background: transparent;")
        try:
            size_str = fmt_size(path)
        except Exception:
            size_str = ""
        meta = QLabel(size_str)
        meta.setStyleSheet(
            "font-size: 10px; color: #6c727f; background: transparent;"
            " font-family: 'SF Mono', 'Menlo', monospace;"
        )
        info.addWidget(name)
        info.addWidget(meta)
        lay.addLayout(info, 1)

        card.mousePressEvent = lambda e, p=path: self.file_selected.emit(p)
        return card
