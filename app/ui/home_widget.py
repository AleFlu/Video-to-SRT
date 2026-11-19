"""
home_widget.py — Schermata Home (Stato 0), "Bianco e nero".

Layout (mockup Home.dc.html): banco di lavoro a tutta larghezza, due colonne.
  ┌── [DepsBanner — solo se dipendenze mancano] ───────────────────────────┐
  │ Sorgente                       │  Impostazioni di trascrizione (420 px) │
  │  zona di rilascio 330 px       │   Modello Whisper  + RAM/qualità       │
  │  (o riga "file caricato")      │   Lingua · Glossario · Formato         │
  │ Recenti (Nome|Cartella|Dim.)   │   Filtro VAD · Alta precisione         │
  │                                │   riepilogo · Stima · Avvia            │
  └────────────────────────────────┴────────────────────────────────────────┘

Configurazione: i controlli mostrano le scelte di base di una TranscriptionConfig
(core.transcription_config), il glossario e il formato dei sottotitoli (Film e TV o
Reel: readability.subtitle_format e i suoi valori); gli altri parametri avanzati
(decodifica, VAD Silero, leggibilità) non hanno controlli e vengono da File → Importa
configurazione….
L'intestazione del pannello indica da dove vengono (predefiniti o nome del file
importato).

Tema chiaro/scuro: i colori vengono letti da theme.c() e ri-applicati su
theme_changed via _apply_palette().

Segnali:
  start_requested(source_path, settings) → avvio trascrizione
  open_requested(path)                   → file SRT/.v2srt trascinato sulla drop zone
"""

from __future__ import annotations
import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal, QSettings
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QLineEdit, QSpinBox, QSizePolicy,
    QBoxLayout, QFileDialog, QScrollArea, QSplitter, QStackedLayout,
)

from core.constants import (
    SUPPORTED_AUDIO_EXTS, SUPPORTED_MEDIA_EXTS, SUPPORTED_SUBTITLE_EXTS,
)
from core.transcription_config import AUTO_LANGUAGE, TranscriptionConfig, parse_glossary
from ui.prefs import RECENT_KEY, add_recent, read_list
from ui.widgets import DepsBanner, ElidedLabel, SwitchPill, ToggleSwitch, fmt_size
from ui import icons, theme
import platform_support


_SHOWN_RECENTS = 5
_PANEL_W = 420          # pannello impostazioni (larghezza iniziale)
# Bordo trascinabile tra Sorgente e Impostazioni: limiti e larghezza ricordata
SETTINGS_MIN_W = 380
SETTINGS_MAX_W = 600
SOURCE_MIN_W = 440
_SETTINGS_PANEL_W_KEY = "home/settings_width"
_DROP_H = 330           # altezza della zona di rilascio
_ROW_H = 38             # riga della tabella "Recenti"
_COL_NAME, _COL_DIR, _COL_SIZE = 12, 15, 110   # proporzioni colonne dei Recenti

# Filtro del dialog: le estensioni accettate vengono da core.constants
_MEDIA_GLOB = " ".join(f"*{e}" for e in sorted(SUPPORTED_MEDIA_EXTS))
FILE_FILTER_MEDIA = f"File video o audio ({_MEDIA_GLOB});;Tutti i file (*.*)"
_FORMATS_HINT = "MP4, MOV, MKV, WAV, MP3, M4A, FLAC…"

# Etichette dei formati mostrate sotto la zona di rilascio (gruppi: video, audio, testo)
_FORMAT_GROUPS = (
    ("MP4", "MOV", "MKV", "AVI", "WEBM"),
    ("WAV", "MP3", "M4A", "FLAC", "OGG"),
    ("SRT", "V2SRT"),
)


def _is_media(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_MEDIA_EXTS


def _is_subtitle(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUBTITLE_EXTS


def _short_dir(path: str) -> str:
    """Cartella del file con la home abbreviata in "~"."""
    parent = str(Path(path).parent)
    home = str(Path.home())
    if parent == home or parent.startswith(home + os.sep):
        return "~" + parent[len(home):]
    return parent


def _gb_text(gb: float) -> str:
    """Dimensione di un download in italiano: 1,6 GB · 480 MB."""
    if gb < 1:
        return f"{int(round(gb * 1000))} MB"
    return f"{gb:.1f} GB".replace(".", ",")


def _quality_text(stars: str) -> str:
    """"★★★★½" -> "4,5/5" (stelle intere + mezza)."""
    n = stars.count("★") + (0.5 if "½" in stars else 0.0)
    num = f"{int(n)}" if n == int(n) else f"{n:.1f}".replace(".", ",")
    return f"qualità {num}/5"


def _combo_ss() -> str:
    c = theme.c
    return (
        f"QComboBox {{ background: {c('bg')}; border: 1px solid {c('line')}; border-radius: 4px;"
        f" color: {c('text')}; padding: 0 10px; font-size: 13px; min-height: 30px; }}"
        f"QComboBox:hover {{ border-color: {c('line_2')}; }}"
        f"QComboBox:focus {{ border: 1px solid {c('focus')}; }}"
        "QComboBox::drop-down { border: none; width: 22px; }"
        f"{theme.combo_arrow_rule()}"
        f"QComboBox QAbstractItemView {{ background: {c('panel')}; border: 1px solid {c('line_2')};"
        f" color: {c('text')}; selection-background-color: {c('acc_fill')};"
        f" selection-color: {c('acc_ink')}; border-radius: 4px; }}"
    )


def _line_edit_ss() -> str:
    c = theme.c
    return (
        f"QLineEdit {{ background: {c('bg')}; border: 1px solid {c('line')}; border-radius: 4px;"
        f" color: {c('text')}; padding: 0 10px; font-size: 13px; min-height: 30px;"
        f" selection-background-color: {c('acc_fill')}; selection-color: {c('acc_ink')}; }}"
        f"QLineEdit:hover {{ border-color: {c('line_2')}; }}"
        f"QLineEdit:focus {{ border: 1px solid {c('focus')}; }}"
    )


# Formati dei sottotitoli (core.transcription_config.FORMAT_PRESETS)
FORMAT_CHOICES = (
    ("Film e TV — fino a 2 righe", "film"),
    ("Reel e social — 1 riga", "reel"),
)


class _SettingsRows(QWidget):
    """Righe delle impostazioni. Alcune descrizioni vanno a capo: l'altezza che serve dipende
    dalla larghezza (bordo trascinabile), quindi la minima si aggiorna a ogni ridimensionamento
    e la finestra non può schiacciare le righe una sull'altra."""

    min_height_changed = Signal()

    def resizeEvent(self, event):  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        lay = self.layout()
        needed = lay.totalHeightForWidth(self.width()) if lay is not None else -1
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)
            self.min_height_changed.emit()


class HomeWidget(QWidget):
    """Schermata iniziale: sorgente + recenti a sinistra, impostazioni e avvio a destra."""

    start_requested = Signal(str, dict)   # (source_path, settings)
    min_height_changed = Signal()         # le impostazioni chiedono più (o meno) altezza
    open_requested  = Signal(str)         # SRT / .v2srt da aprire nell'editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._source_path: str | None = None
        # Configurazione di partenza (parametri avanzati + valori iniziali dei controlli)
        self._config = TranscriptionConfig()
        self._config_name = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Banner dipendenze: una riga sopra le colonne, solo quando serve ───
        self._deps_wrap = QWidget()
        dl = QVBoxLayout(self._deps_wrap)
        dl.setContentsMargins(32, 14, 32, 0)
        dl.setSpacing(0)
        self.deps_banner = DepsBanner()
        dl.addWidget(self.deps_banner)
        self._deps_wrap.setVisible(False)
        root.addWidget(self._deps_wrap)

        # Sorgente | Impostazioni: il bordo si trascina (entro SETTINGS_MIN_W–SETTINGS_MAX_W
        # per le impostazioni e SOURCE_MIN_W per la sorgente); la larghezza è ricordata.
        cols = QSplitter(Qt.Horizontal)
        cols.setObjectName("homeSplit")
        cols.setChildrenCollapsible(False)
        cols.setHandleWidth(5)
        root.addWidget(cols, 1)
        self._split = cols

        # ── Colonna sinistra (scorrevole se la finestra è bassa) ──────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.NoFocus)   # contenitore: Tab va ai controlli, non qui
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        scroll.setWidget(inner)
        scroll.setMinimumWidth(SOURCE_MIN_W)
        cols.addWidget(scroll)

        left = QVBoxLayout(inner)
        left.setContentsMargins(32, 28, 32, 28)
        left.setSpacing(24)

        src_col = QVBoxLayout()
        src_col.setSpacing(10)
        src_head = QHBoxLayout()
        self._src_title = QLabel("Sorgente")
        src_head.addWidget(self._src_title)
        src_head.addStretch(1)
        self._src_note = ElidedLabel(
            "Tutto resta sul tuo computer: nessun file viene caricato in rete.", Qt.ElideRight
        )
        self._src_note.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._src_note.hide()   # frase non necessaria: resta solo il titolo
        src_head.addWidget(self._src_note, 4)
        src_col.addLayout(src_head)

        self.drop = _DesignDropZone()
        self.drop.file_selected.connect(self._on_file_selected)
        self.drop.file_error.connect(self._on_file_error)
        self.drop.open_requested.connect(self.open_requested)
        src_col.addWidget(self.drop)
        left.addLayout(src_col)

        self._recents_widget = _RecentsWidget()
        self._recents_widget.file_selected.connect(self._on_file_selected)
        left.addWidget(self._recents_widget)
        left.addStretch(1)

        # ── Pannello impostazioni (420 px) ────────────────────────────────────
        self._settings_card = self._build_settings_card()
        cols.addWidget(self._settings_card)
        cols.setStretchFactor(0, 1)
        cols.setStretchFactor(1, 0)
        cols.setSizes([10_000, self._saved_settings_width()])
        cols.splitterMoved.connect(self._on_split_moved)

        # Ordine di tab: file → impostazioni → avvio
        chain = [self.drop, self.model_combo, self.lang_combo, self.glossary_edit,
                 self.format_combo, self.vad_toggle, self.accuracy_toggle,
                 self.start_btn]
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
        self.glossary_edit.setStyleSheet(_line_edit_ss())
        self.vad_toggle._apply_palette()
        self.accuracy_toggle._apply_palette()
        self.format_combo.setStyleSheet(ss)
        self._apply_accuracy_palette()
        self._set_start_btn_state(self._source_path is not None)
        self.update()

    def _apply_palette(self):
        c = theme.c
        self._src_title.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c('text')}; background: transparent;"
        )
        self._src_note.setStyleSheet(
            f"font-size: 12px; color: {c('dim')}; background: transparent;"
        )
        self._split.setStyleSheet(
            f"QSplitter#homeSplit::handle {{ background: {c('bg')}; }}"
            f"QSplitter#homeSplit::handle:hover {{ background: {c('line_2')}; }}"
        )
        self._settings_card.setStyleSheet(
            f"QFrame#settingsCard {{ background-color: {c('panel')}; border: none;"
            f" border-left: 1px solid {c('line')}; }}"
            f"QFrame#setRow {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
            f"QFrame#setBottom {{ background: transparent; border: none;"
            f" border-top: 1px solid {c('line')}; }}"
        )
        self._head_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c('text')}; background: transparent;"
        )
        self._config_lbl.setStyleSheet(
            f"font-size: 12px; color: {c('dim')}; background: transparent;"
        )
        for lbl in self._field_labels:
            lbl.setStyleSheet(
                f"font-size: 11px; font-weight: 500; color: {c('label')};"
                " background: transparent;"
            )
        mono = (f"font-size: 11px; color: {c('dim')}; background: transparent;"
                f" font-family: {theme.FONT_MONO};")
        self._model_hint.setStyleSheet(mono)
        self._preset_lbl.setStyleSheet(
            f"font-size: 12px; color: {c('dim')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._estimate_title.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {c('label')}; background: transparent;"
        )
        self._estimate_lbl.setStyleSheet(
            f"font-size: 12px; color: {c('dim')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._hint_lbl.setStyleSheet(
            f"font-size: 12px; color: {c('dim')}; background: transparent;"
        )
        self._set_start_kbd("label")
        for desc in (self._vad_desc, self._acc_desc):
            desc.setStyleSheet(
                f"font-size: 12px; color: {c('dim')}; background: transparent;"
            )
        for title in (self._vad_title,):
            title.setStyleSheet(
                f"font-size: 13px; font-weight: 500; color: {c('text')};"
                " background: transparent;"
            )
        self._apply_accuracy_palette()

    def _apply_accuracy_palette(self):
        """Titolo "Alta precisione" attenuato quando l'opzione non è disponibile."""
        tone = "text" if self.accuracy_toggle.isEnabled() else "dim"
        self._acc_title.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {theme.c(tone)};"
            " background: transparent;"
        )

    # ── Pannello impostazioni ─────────────────────────────────────────────────

    def _set_row(self) -> tuple:
        """Sezione del pannello: (cornice con linea inferiore, layout verticale)."""
        row = QFrame()
        row.setObjectName("setRow")
        # mai più bassa del necessario: se manca spazio scorre il pannello (non si schiaccia)
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 14, 0, 14)
        lay.setSpacing(0)
        return row, lay

    def _toggle_row(self, title: QLabel, desc: QLabel, toggle: ToggleSwitch) -> QFrame:
        row, lay = self._set_row()
        h = QHBoxLayout()
        h.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(title)
        desc.setWordWrap(True)
        col.addWidget(desc)
        h.addLayout(col, 1)
        toggle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        toggle.setFixedWidth(38 + 10 + 96)
        h.addWidget(toggle, 0, Qt.AlignVCenter)
        lay.addLayout(h)
        return row

    def _saved_settings_width(self) -> int:
        value = QSettings("VideoSRT", "v2").value(_SETTINGS_PANEL_W_KEY, _PANEL_W)
        try:
            return max(SETTINGS_MIN_W, min(SETTINGS_MAX_W, int(value)))
        except (TypeError, ValueError):
            return _PANEL_W

    def _on_split_moved(self, *_):
        QSettings("VideoSRT", "v2").setValue(_SETTINGS_PANEL_W_KEY, self._settings_card.width())

    def _build_settings_card(self) -> QFrame:
        from engine import MODELS, DEFAULT_MODEL
        self._models = MODELS
        self._model_keys = list(MODELS.keys())
        self._field_labels: list = []
        ss = _combo_ss()

        card = QFrame()
        card.setObjectName("settingsCard")
        card.setMinimumWidth(SETTINGS_MIN_W)
        card.setMaximumWidth(SETTINGS_MAX_W)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 28, 28, 24)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(12)
        self._head_lbl = QLabel("Impostazioni di trascrizione")
        head.addWidget(self._head_lbl)
        # Origine dei parametri: "Parametri predefiniti" o il nome del file importato
        self._config_lbl = ElidedLabel("", Qt.ElideMiddle)
        self._config_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self._config_lbl, 1)
        lay.addLayout(head)
        lay.addSpacing(4)

        # Righe delle impostazioni: mai a scorrimento; la finestra non scende sotto l'altezza
        # che serve (MainWindow), così non si schiacciano. Riepilogo, stima e Avvia in fondo.
        card_lay = lay
        rows = _SettingsRows()
        rows.min_height_changed.connect(self.min_height_changed)
        rows.setObjectName("settingsRows")
        rows.setStyleSheet("QWidget#settingsRows { background: transparent; }")
        lay = QVBoxLayout(rows)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Modello Whisper + RAM / qualità
        row_m, ml = self._set_row()
        ml.addWidget(self._field("Modello Whisper"))
        ml.addSpacing(6)
        self.model_combo = QComboBox()
        self.model_combo.setAccessibleName("Modello Whisper")
        # Le voci sono lunghe ("consigliato, da scaricare, 1,6 GB"): il menu non deve chiedere
        # più spazio del pannello (la riga si schiaccerebbe); l'elenco aperto le mostra intere.
        self.model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(12)
        self.model_combo.view().setTextElideMode(Qt.ElideNone)
        self.model_combo.setStyleSheet(ss)
        for k in self._model_keys:
            self.model_combo.addItem(self._models[k]["label"], k)
        self.model_combo.setCurrentIndex(self._model_keys.index(DEFAULT_MODEL))
        self._refresh_model_labels()
        self.model_combo.currentIndexChanged.connect(self._update_estimate)
        self.model_combo.currentIndexChanged.connect(self._update_preset_label)
        self.model_combo.currentIndexChanged.connect(self._update_model_hint)
        ml.addWidget(self.model_combo)
        ml.addSpacing(8)
        self._model_hint = ElidedLabel("", Qt.ElideRight)
        ml.addWidget(self._model_hint)
        lay.addWidget(row_m)

        # Lingua
        row_l, ll = self._set_row()
        ll.addWidget(self._field("Lingua"))
        ll.addSpacing(6)
        self.lang_combo = QComboBox()
        self.lang_combo.setAccessibleName("Lingua dell'audio")
        self.lang_combo.setStyleSheet(ss)
        for label, code in (("Italiano", "it"), ("Inglese", "en"), ("Spagnolo", "es"),
                            ("Francese", "fr"), ("Tedesco", "de"),
                            ("Rilevamento automatico", "auto")):
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentIndexChanged.connect(self._update_preset_label)
        ll.addWidget(self.lang_combo)
        lay.addWidget(row_l)

        # Formato dei sottotitoli: Film/TV (2 righe, punteggiatura completa) o Reel
        row_f, fl = self._set_row()
        fl.addWidget(self._field("Formato sottotitoli"))
        fl.addSpacing(6)
        self.format_combo = QComboBox()
        self.format_combo.setAccessibleName("Formato dei sottotitoli")
        self.format_combo.setStyleSheet(ss)
        for label, code in FORMAT_CHOICES:
            self.format_combo.addItem(label, code)
        self.format_combo.setToolTip(
            "Film e TV: fino a 2 righe da 42 caratteri, punteggiatura completa.\n"
            "Reel e social: 1 riga corta, sottotitoli brevi, senza punto né virgola "
            "in fondo."
        )
        self._set_format(self._config.readability.subtitle_format)
        self.format_combo.currentIndexChanged.connect(self._update_preset_label)
        fl.addWidget(self.format_combo)
        lay.addWidget(row_f)

        # Glossario: termini inglesi, marchi, nomi propri (hotwords di faster-whisper)
        row_g, gl = self._set_row()
        gl.addWidget(self._field("Glossario (termini separati da virgola)"))
        gl.addSpacing(6)
        self.glossary_edit = QLineEdit()
        self.glossary_edit.setAccessibleName("Glossario")
        self.glossary_edit.setPlaceholderText("es. machine learning, Kubernetes, Rossi")
        self.glossary_edit.setToolTip(
            "Termini inglesi, marchi e nomi propri da riconoscere, separati da virgola:\n"
            "Whisper li tiene presenti per tutta la trascrizione."
        )
        self.glossary_edit.setStyleSheet(_line_edit_ss())
        self.glossary_edit.setText(", ".join(self._config.decoding.glossary))
        gl.addWidget(self.glossary_edit)
        lay.addWidget(row_g)

        # Filtro VAD
        self._vad_title = QLabel("Filtro VAD")
        self._vad_desc = QLabel("Salta i tratti senza parlato (consigliato)")
        self.vad_toggle = _ToggleSwitch("Attivo", "Disattivo", name="Filtro VAD")
        self.vad_toggle.setToolTip("Salta i tratti senza parlato (consigliato)")
        self.vad_toggle.setChecked(True)
        self.vad_toggle.toggled.connect(self._update_preset_label)
        lay.addWidget(self._toggle_row(self._vad_title, self._vad_desc, self.vad_toggle))
        self._vad_desc.hide()   # spiegazione nel tooltip

        # Alta precisione
        self._acc_title = QLabel("Alta precisione")
        self._acc_desc = QLabel("Allineamento fonetico delle parole con WhisperX: più lento")
        self.accuracy_toggle = _ToggleSwitch("Attiva", "Standard", name="Alta precisione")
        self.accuracy_toggle.setChecked(False)
        self.accuracy_toggle.setToolTip(
            "Allineamento fonetico delle parole con WhisperX: tempi più precisi, più lento."
        )
        self.accuracy_toggle.toggled.connect(self._update_preset_label)
        self._apply_accuracy_availability()
        lay.addWidget(self._toggle_row(self._acc_title, self._acc_desc, self.accuracy_toggle))
        # descrizione visibile solo quando l'opzione non è disponibile (dice perché)
        self._acc_desc.setVisible(self._acc_desc.property("unavailable") is True)


        # beam_spin non visibile: valore di default letto da _get_settings()
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 15)
        self.beam_spin.setValue(5)
        self.beam_spin.hide()

        lay = card_lay
        lay.addWidget(rows)
        lay.addStretch(1)

        # Parte bassa: riepilogo, stima, avvio, suggerimento
        bottom = QFrame()
        bottom.setObjectName("setBottom")
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 12, 0, 0)
        bl.setSpacing(0)
        self._preset_lbl = ElidedLabel("", Qt.ElideRight)
        bl.addWidget(self._preset_lbl)
        bl.addSpacing(12)
        est = QHBoxLayout()
        self._estimate_title = QLabel("Stima")
        est.addWidget(self._estimate_title)
        est.addStretch(1)
        self._estimate_lbl = ElidedLabel("–", Qt.ElideRight)
        self._estimate_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        est.addWidget(self._estimate_lbl, 1)
        bl.addLayout(est)
        bl.addSpacing(12)

        self.start_btn = QPushButton("Avvia trascrizione")
        self.start_btn.setObjectName("primary")
        self._start_icon = icons.bind_icon(self.start_btn, "play", "acc_ink", 14)
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setToolTip("Avvia la trascrizione  (Invio)")
        self.start_btn.clicked.connect(self._on_start)
        # suggerimento ↵ dentro il pulsante, a destra
        bl_btn = QHBoxLayout(self.start_btn)
        bl_btn.setContentsMargins(0, 0, 14, 0)
        bl_btn.addStretch(1)
        self._start_kbd = QLabel()
        self._start_kbd.setFixedSize(14, 14)
        self._start_kbd.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        bl_btn.addWidget(self._start_kbd)
        bl.addWidget(self.start_btn)
        bl.addSpacing(8)
        # Solo per gli errori (formato non supportato, glossario non valido): niente
        # frasi di istruzione, il pulsante Avvia dice già cosa fare
        self._hint_lbl = QLabel("")
        self._hint_lbl.setAlignment(Qt.AlignCenter)
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.hide()
        bl.addWidget(self._hint_lbl)
        lay.addWidget(bottom)

        self._update_preset_label()
        self._update_model_hint()
        self._update_config_label()
        return card

    def _field(self, text: str) -> QLabel:
        lbl = QLabel(text)
        self._field_labels.append(lbl)
        return lbl

    def _apply_accuracy_availability(self):
        """Disattiva "Alta precisione" se WhisperX non è utilizzabile, spiegando perché."""
        try:
            from engine import high_accuracy_unavailable_reason
            reason = high_accuracy_unavailable_reason()
        except Exception as exc:  # noqa: BLE001 — engine non importabile: opzione non usabile
            reason = f"motore di trascrizione non disponibile ({exc})"
        if reason:
            self.accuracy_toggle.set_unavailable(
                "Non disponibile",
                f"Alta precisione non disponibile: {reason}.\n"
                "La trascrizione usa la modalità standard.",
            )
            self._acc_desc.setText(f"{reason[:1].upper()}{reason[1:]}: si usa la modalità standard")
            self._acc_desc.setProperty("unavailable", True)

    def _refresh_model_labels(self) -> None:
        """Etichette del menu: "consigliato" e "da scaricare, N GB" accanto ai modelli."""
        from engine import is_model_available, recommended_model
        rec = recommended_model()
        for i, key in enumerate(self._model_keys):
            info = self._models[key]
            tags = []
            if key == rec:
                tags.append("consigliato")
            if not is_model_available(key):
                tags.append(f"da scaricare, {_gb_text(info['download_gb'])}")
            text = info["label"] + (f"  ({', '.join(tags)})" if tags else "")
            self.model_combo.setItemText(i, text)

    def refresh_models(self) -> None:
        """Ricalcola cosa è scaricato (dopo un download o tornando alla Home)."""
        self._refresh_model_labels()
        self._update_model_hint()

    def showEvent(self, event):  # noqa: N802 (override Qt)
        super().showEvent(event)
        self.refresh_models()

    def _update_model_hint(self, *_):
        """Riga mono sotto il modello: RAM, qualità, consigliato, scaricato o da scaricare."""
        from engine import is_model_available, recommended_model
        key = self.model_combo.currentData()
        info = self._models.get(key, {})
        parts = []
        if info.get("ram"):
            parts.append(f"RAM {info['ram']}")
        if info.get("quality"):
            parts.append(_quality_text(info["quality"]))
        if key == recommended_model():
            parts.append("consigliato per questo computer")
        if key in self._models:
            parts.append("scaricato" if is_model_available(key)
                         else f"da scaricare · {_gb_text(info['download_gb'])}")
        self._model_hint.setText("      ".join(parts))

    def _update_preset_label(self):
        """Riepilogo delle impostazioni correnti (sopra la stima)."""
        parts = [self.lang_combo.currentText()]
        model_key = self.model_combo.currentData()
        if model_key:
            parts.append(str(model_key))
        parts.append(self.format_combo.currentText().split(" —")[0])
        parts.append("VAD attivo" if self.vad_toggle.isChecked() else "VAD disattivo")
        parts.append("alta precisione" if self.accuracy_toggle.isChecked() else "standard")
        self._preset_lbl.setText("  ·  ".join(parts))

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
        self._hint_lbl.setText("")
        self._hint_lbl.hide()
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
                "  min-height: 40px;"
                "}"
                f"QPushButton:hover {{ background-color: {c('acc_fill_h')}; }}"
                f"QPushButton:pressed {{ background-color: {c('acc_fill_d')}; }}"
                + theme.focus_rule("QPushButton", 4)
            )
            self._set_start_kbd("acc_ink")
        else:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("Avvia trascrizione")
            self._start_icon.set_icon("play", "dim")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: transparent;"
                f"  color: {c('dim')};"
                f"  border: 1px solid {c('line')};"
                "  border-radius: 4px;"
                "  font-size: 14px;"
                "  font-weight: 600;"
                "  padding: 0 22px;"
                "  min-height: 40px;"
                "}"
            )
            self._set_start_kbd("label")

    def _set_start_kbd(self, token: str):
        """Suggerimento Invio: icona disegnata (non un glifo di testo) nel colore del token."""
        self._start_kbd.setStyleSheet("background: transparent; border: none;")
        self._start_kbd.setPixmap(icons.pixmap("enter", theme.qcolor(token), 14))

    def _on_file_error(self, ext: str):
        self.drop.show_error(ext)
        self._source_path = None
        self._set_start_btn_state(False)
        self._hint_lbl.setText(
            f"Formato .{ext} non supportato" if ext else "Formato non supportato"
        )
        self._hint_lbl.show()

    def _on_start(self):
        if not self._source_path:
            return
        try:
            self.current_config()
        except ValueError as e:
            self._hint_lbl.setText(f"Glossario non valido. {e}")
            self._hint_lbl.show()
            return
        self.start_requested.emit(self._source_path, self._get_settings())

    def _get_settings(self) -> dict:
        return {
            "model_size":    self.model_combo.currentData(),
            "language":      self.lang_combo.currentData(),
            "vad_filter":    self.vad_toggle.isChecked(),
            "denoise":       self._config.denoise,
            "high_accuracy": self.accuracy_toggle.isEnabled() and self.accuracy_toggle.isChecked(),
            "beam_size":     self.beam_spin.value(),
        }

    # ── Configurazione ────────────────────────────────────────────────────────

    def check_config(self, config: TranscriptionConfig) -> None:
        """ValueError (in italiano) se la configurazione chiede un modello che l'app non ha."""
        if self.model_combo.findData(config.model_size) < 0:
            raise ValueError(
                f"Il modello Whisper \"{config.model_size}\" non è disponibile in questa "
                f"versione dell'app (disponibili: {', '.join(self._model_keys)})"
            )

    def apply_config(self, config: TranscriptionConfig, name: str = "") -> None:
        """Mostra la configurazione nei controlli e la usa per le prossime trascrizioni.

        ``name`` è l'origine mostrata nell'intestazione ("" = predefinita o ultima usata).
        Solleva ValueError, senza cambiare nulla, se il modello non è disponibile.
        """
        self.check_config(config)
        lang_idx = self.lang_combo.findData(config.language)
        if lang_idx < 0:
            # Lingua valida per Whisper ma non nell'elenco: la si aggiunge col suo codice
            self.lang_combo.addItem(f"Lingua \"{config.language}\"", config.language)
            lang_idx = self.lang_combo.count() - 1
        self._config = config
        self._config_name = name
        self.model_combo.setCurrentIndex(self.model_combo.findData(config.model_size))
        self.lang_combo.setCurrentIndex(lang_idx)
        self.vad_toggle.setChecked(config.vad_filter)
        if self.accuracy_toggle.isEnabled():
            self.accuracy_toggle.setChecked(config.high_accuracy)
        self.beam_spin.setValue(config.beam_size)
        self.glossary_edit.setText(", ".join(config.decoding.glossary))
        self._set_format(config.readability.subtitle_format)
        self._update_preset_label()
        self._update_config_label()

    def current_config(self) -> TranscriptionConfig:
        """Configurazione completa con le scelte attuali dei controlli.

        Se "Alta precisione" non è disponibile su questo computer si conserva il valore
        della configurazione (la trascrizione userà comunque la modalità standard).
        Il formato scelto applica i suoi valori (righe, caratteri, durata); se è lo
        stesso della configurazione restano i limiti di quella (anche se personalizzati).
        ValueError (in italiano) se il glossario non è valido.
        """
        acc = self.accuracy_toggle
        glossary = parse_glossary(self.glossary_edit.text())
        readability = self._config.readability
        fmt = self.format_combo.currentData() or "film"
        if fmt != readability.subtitle_format:
            readability = readability.with_format(fmt)
        return replace(
            self._config,
            model_size=self.model_combo.currentData(),
            language=self.lang_combo.currentData() or AUTO_LANGUAGE,
            vad_filter=self.vad_toggle.isChecked(),
            high_accuracy=acc.isChecked() if acc.isEnabled() else self._config.high_accuracy,
            beam_size=self.beam_spin.value(),
            decoding=replace(self._config.decoding, glossary=glossary),
            readability=readability,
        )

    def config_name(self) -> str:
        return self._config_name

    def _update_config_label(self):
        lbl = self._config_lbl
        if self._config_name:
            lbl.setText(f"Configurazione: {self._config_name}")
            origin = f"dalla configurazione \"{self._config_name}\""
        elif self._advanced_is_default():
            lbl.setText("Parametri predefiniti")
            origin = "predefiniti"
        else:
            lbl.setText("Parametri personalizzati")
            origin = "personalizzati"
        lbl.set_full_tooltip(
            f"Parametri avanzati (decodifica, VAD, leggibilità) {origin}.\n"
            "File → Importa configurazione… per caricarne altri, "
            "Esporta configurazione… per salvarli."
        )

    def _advanced_is_default(self) -> bool:
        """True se i parametri senza controlli sono i predefiniti (il formato dei
        sottotitoli ha il suo menu: conta solo se i limiti differiscono dal formato)."""
        base = TranscriptionConfig()
        cfg = self._config
        fmt = cfg.readability.subtitle_format
        return (cfg.decoding, cfg.vad, cfg.readability, cfg.denoise) == (
            base.decoding, base.vad, base.readability.with_format(fmt), base.denoise)

    def _set_format(self, subtitle_format: str) -> None:
        i = self.format_combo.findData(subtitle_format)
        self.format_combo.setCurrentIndex(max(0, i))

    def _update_estimate(self):
        if not self._source_path:
            self._estimate_lbl.setText("–")
            return
        try:
            size_mb = os.path.getsize(self._source_path) / (1024 * 1024)
            model_key = self.model_combo.currentData() or "large-v3"
            factor = {
                "tiny": 0.15, "base": 0.25, "small": 0.4,
                "medium": 0.65, "large-v3-turbo": 0.5, "large-v3": 1.0,
            }.get(model_key, 1.0)
            mins = max(1, int(size_mb * factor / 100 * 1.5))
            srt_kb = max(1, int(size_mb * 0.05))
            self._estimate_lbl.setText(
                f"~ {mins}–{mins * 2} min · ~ {srt_kb} KB"
            )
        except OSError:
            self._estimate_lbl.setText("–")

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
        self._deps_wrap.setVisible(self.deps_banner.isVisibleTo(self._deps_wrap))

    def preload_file(self, path: str):
        """Pre-carica un file (es. da File → Apri); estensioni non media → errore visibile."""
        self._on_file_selected(path)

    def reset(self):
        self._source_path = None
        self.drop.reset()
        self._set_start_btn_state(False)
        self._estimate_lbl.setText("–")
        self._refresh_recents()


# ── _DesignDropZone ───────────────────────────────────────────────────────────

class _DesignDropZone(QWidget):
    """
    Zona di rilascio con widget fissi (uno per stato, nessun rebuild): tratteggiata
    da 330 px a riposo, riga compatta "file caricato" (con Cambia) a file scelto.
    Accetta click, Invio/Spazio da tastiera e drag & drop; i formati non supportati
    vengono rifiutati con un messaggio visibile.
    """

    file_selected  = Signal(str)
    file_error     = Signal(str)   # estensione rifiutata (senza punto)
    open_requested = Signal(str)   # SRT / .v2srt: da aprire nell'editor

    _IDLE   = "idle"
    _HOVER  = "hover"
    _LOADED = "loaded"
    _ERROR  = "error"

    # Altezze minime di progetto; quella effettiva segue il contenuto (font grandi)
    _H_NORMAL = _DROP_H
    _H_LOADED = 72

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

        def _icon() -> QLabel:
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(32, 32)
            return lbl

        def _centered(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            return lbl

        # ── Idle ──────────────────────────────────────────────────────────────
        self._w_idle, lay_idle = _state_page()
        self._idle_icon = _icon()
        lay_idle.addWidget(self._idle_icon, 0, Qt.AlignCenter)
        self._idle_t1 = _centered("Trascina qui un video o un audio")
        lay_idle.addWidget(self._idle_t1)
        self._idle_t2 = _centered("")
        self._idle_t2.setTextFormat(Qt.RichText)
        self._idle_t2.hide()   # il riquadro è cliccabile e ⌘O è nel menu File
        lay_idle.addWidget(self._idle_t2)
        lay_idle.addSpacing(8)
        # Formati: un gruppo per tipo (video, audio, sottotitoli) su una riga; se la colonna
        # è stretta (bordo trascinato) i gruppi vanno uno sotto l'altro invece di essere tagliati
        self._chips: list = []
        self._chip_groups: list = []
        self._chips_box = QBoxLayout(QBoxLayout.LeftToRight)
        self._chips_box.setSpacing(10)
        for group in _FORMAT_GROUPS:
            gw = QWidget()
            gl = QHBoxLayout(gw)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(6)
            for name in group:
                chip = QLabel(name)
                chip.setAlignment(Qt.AlignCenter)
                self._chips.append(chip)
                gl.addWidget(chip)
            self._chip_groups.append(gw)
            self._chips_box.addWidget(gw, 0, Qt.AlignCenter)
        # La riga dei formati non impone la sua larghezza alla zona (altrimenti la colonna
        # non potrebbe stringersi e i gruppi non andrebbero mai a capo: vedi resizeEvent)
        chips_w = QWidget()
        chips_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        chips = QHBoxLayout(chips_w)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.addStretch(1)
        chips.addLayout(self._chips_box)
        chips.addStretch(1)
        lay_idle.addWidget(chips_w)

        # ── Hover ─────────────────────────────────────────────────────────────
        self._w_hover, lay_hover = _state_page()
        self._hover_icon = _icon()
        lay_hover.addWidget(self._hover_icon, 0, Qt.AlignCenter)
        self._hover_t1 = _centered("Rilascia per caricare")
        lay_hover.addWidget(self._hover_t1)

        # ── Error ─────────────────────────────────────────────────────────────
        self._w_error, lay_error = _state_page()
        self._err_icon = _icon()
        lay_error.addWidget(self._err_icon, 0, Qt.AlignCenter)
        self._err_t1 = _centered("Formato non supportato")
        lay_error.addWidget(self._err_t1)
        self._err_t2 = _centered(f"Usa un file video o audio: {_FORMATS_HINT}")
        lay_error.addWidget(self._err_t2)

        # ── Loaded: riga del file (icona, nome, dimensione · estensione, Cambia) ─
        self._w_loaded = QWidget()
        lay_loaded = QHBoxLayout(self._w_loaded)
        lay_loaded.setSpacing(14)
        lay_loaded.setContentsMargins(16, 14, 16, 14)
        lay_loaded.setAlignment(Qt.AlignVCenter)

        self._loaded_icon = QLabel()
        self._loaded_icon.setAlignment(Qt.AlignCenter)
        self._loaded_icon.setFixedSize(24, 24)
        lay_loaded.addWidget(self._loaded_icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(0)
        self._loaded_name = ElidedLabel("")
        self._loaded_detail = QLabel("")
        info_col.addWidget(self._loaded_name)
        info_col.addWidget(self._loaded_detail)
        lay_loaded.addLayout(info_col, 1)

        self._change_btn = QPushButton("Cambia")
        self._change_btn.setMinimumHeight(28)
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
        self._idle_icon.setStyleSheet("background: transparent; border: none;")
        self._idle_icon.setPixmap(icons.pixmap("import", theme.qcolor("dim"), 30))
        self._idle_t1.setStyleSheet(
            f"font-size: 20px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        kbd = platform_support.shortcut_label("Ctrl+O")
        self._idle_t2.setText(
            f"oppure clicca, o premi "
            f"<span style=\"font-family: {theme.FONT_MONO}; color: {c('text')};\">{kbd}</span>"
            ", per scegliere un file"
        )
        self._idle_t2.setStyleSheet(
            f"font-size: 13px; color: {c('dim')}; background: transparent;"
        )
        for chip in self._chips:
            chip.setStyleSheet(
                f"font-size: 11px; color: {c('dim')}; background: transparent;"
                f" border: 1px solid {c('line')}; padding: 2px 6px;"
                f" font-family: {theme.FONT_MONO};"
            )
        self._hover_icon.setStyleSheet("background: transparent; border: none;")
        self._hover_icon.setPixmap(icons.pixmap("import", theme.qcolor("acc"), 30))
        self._hover_t1.setStyleSheet(
            f"font-size: 20px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        self._err_icon.setStyleSheet("background: transparent; border: none;")
        self._err_icon.setPixmap(icons.pixmap("alert", theme.qcolor("err"), 30))
        self._err_t1.setStyleSheet(
            f"font-size: 20px; font-weight: 500; color: {c('err')}; background: transparent;"
        )
        self._err_t2.setStyleSheet(f"font-size: 13px; color: {c('dim')}; background: transparent;")
        self._loaded_icon.setStyleSheet("background: transparent; border: none;")
        self._loaded_icon.setPixmap(icons.pixmap(self._loaded_icon_name(), theme.qcolor("dim"), 24))
        self._loaded_name.setStyleSheet(
            f"font-size: 14px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        self._loaded_detail.setStyleSheet(
            f"font-size: 12px; color: {c('dim')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._change_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {c('line')};"
            f" border-radius: 4px; color: {c('text')}; font-size: 13px; padding: 0 9px; }}"
            f"QPushButton:hover {{ background: {c('raise')}; border-color: {c('line_2')}; }}"
            f"QPushButton:pressed {{ background: {c('raise')}; }}"
            + theme.focus_rule("QPushButton", 4)
        )
        self.update()

    def _loaded_icon_name(self) -> str:
        if not self._file_path:
            return "video"
        return "audio" if Path(self._file_path).suffix.lower() in SUPPORTED_AUDIO_EXTS else "video"

    def chips_stacked(self) -> bool:
        return self._chips_box.direction() == QBoxLayout.TopToBottom

    def resizeEvent(self, event):  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        groups = [g.sizeHint().width() for g in self._chip_groups]
        one_row = sum(groups) + self._chips_box.spacing() * (len(groups) - 1) + 48
        direction = (QBoxLayout.LeftToRight if self.width() >= one_row
                     else QBoxLayout.TopToBottom)
        if direction != self._chips_box.direction():
            self._chips_box.setDirection(direction)
            self._set_state(self._state)      # altezza adeguata alle righe dei formati

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
        r = self.rect().adjusted(0, 0, -1, -1)
        r = r.adjusted(0, 0, 0, 0)

        border = {self._IDLE: "label", self._HOVER: "acc", self._LOADED: "line",
                  self._ERROR: "err"}[self._state]
        p.setBrush(theme.qcolor("raise" if self._state == self._HOVER else "panel"))
        pen = QPen(theme.qcolor(border))
        if self._state != self._LOADED:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r.adjusted(0, 0, 0, 0), 6, 6)

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
        # separatori nativi: su Windows toLocalFile() restituisce C:/...
        return [QDir.toNativeSeparators(u.toLocalFile())
                for u in mime.urls() if u.isLocalFile()]

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
        self._loaded_detail.setText(f"{fmt_size(path).replace('.', ',')} · {ext}")
        self._loaded_icon.setPixmap(icons.pixmap(self._loaded_icon_name(), theme.qcolor("dim"), 24))
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

# ── Recenti: elenco a tabella (Nome | Cartella | Dimensione) ────────────────────

class _RecentCard(QFrame):
    """Riga di un file recente: cliccabile e attivabile da tastiera (Invio/Spazio)."""

    activated = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self.setObjectName("recentCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"Apri recente: {Path(path).name}")
        self.setToolTip(path)
        self.setMinimumHeight(max(_ROW_H, self.fontMetrics().height() + 18))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(0)

        name_box = QHBoxLayout()
        name_box.setSpacing(10)
        self._ic = QLabel()
        self._ic.setFixedSize(16, 16)
        name_box.addWidget(self._ic)
        self._name = ElidedLabel(Path(path).name)
        self._name.set_full_tooltip(path)
        name_box.addWidget(self._name, 1)
        lay.addLayout(name_box, _COL_NAME)
        lay.addSpacing(12)

        self._dir = ElidedLabel(_short_dir(path), Qt.ElideMiddle)
        self._dir.set_full_tooltip(path)
        lay.addWidget(self._dir, _COL_DIR)

        self._meta = QLabel(fmt_size(path).replace(".", ","))
        self._meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._meta.setFixedWidth(_COL_SIZE)
        lay.addWidget(self._meta)
        self.apply_palette()

    def _icon_name(self) -> str:
        ext = Path(self._path).suffix.lower()
        if ext in SUPPORTED_SUBTITLE_EXTS:
            return "document"
        return "audio" if ext in SUPPORTED_AUDIO_EXTS else "video"

    def apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"QFrame#recentCard {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {c('line')}; border-radius: 0; }}"
            f"QFrame#recentCard:hover {{ background: {c('panel')}; }}"
            f"QFrame#recentCard:focus {{ border: 1px solid {c('focus')}; }}"
        )
        self._ic.setStyleSheet("background: transparent; border: none;")
        self._ic.setPixmap(icons.pixmap(self._icon_name(), theme.qcolor("dim"), 16))
        self._name.setStyleSheet(
            f"font-size: 13px; color: {c('text')}; background: transparent; border: none;"
        )
        self._dir.setStyleSheet(
            f"font-size: 13px; color: {c('dim')}; background: transparent; border: none;"
        )
        self._meta.setStyleSheet(
            f"font-size: 13px; color: {c('dim')}; background: transparent; border: none;"
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
    """Elenco dei file recenti — visibile solo se ci sono file."""

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self.setVisible(False)
        self.setStyleSheet("background: transparent;")
        self._paths: list = []

        self._title = QLabel("Recenti")
        self._lay.addWidget(self._title)
        self._lay.addSpacing(6)

        # intestazione di colonna (stesse proporzioni delle righe)
        self._head = QFrame()
        self._head.setObjectName("recentHead")
        hl = QHBoxLayout(self._head)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(0)
        self._head_lbls = []
        for text, stretch, align in (("Nome", _COL_NAME, Qt.AlignLeft),
                                     ("Cartella", _COL_DIR, Qt.AlignLeft)):
            lbl = QLabel(text)
            lbl.setAlignment(align | Qt.AlignVCenter)
            self._head_lbls.append(lbl)
            hl.addWidget(lbl, stretch)
            if text == "Nome":
                hl.addSpacing(12)
        size_lbl = QLabel("Dimensione")
        size_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        size_lbl.setFixedWidth(_COL_SIZE)
        self._head_lbls.append(size_lbl)
        hl.addWidget(size_lbl)
        self._head.setFixedHeight(30)
        self._lay.addWidget(self._head)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(0)
        self._lay.addLayout(self._rows)
        self._cards: list = []
        self._apply_palette()

    def _apply_palette(self):
        c = theme.c
        self._title.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c('text')}; background: transparent;"
        )
        self._head.setStyleSheet(
            f"QFrame#recentHead {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
        )
        for lbl in self._head_lbls:
            lbl.setStyleSheet(
                f"font-size: 11px; font-weight: 500; color: {c('label')};"
                " background: transparent; border: none;"
            )
        for card in self._cards:
            card.apply_palette()

    def set_recents(self, paths: list):
        self._paths = list(paths)
        for card in self._cards:
            self._rows.removeWidget(card)
            card.deleteLater()
        self._cards = []
        for path in self._paths:
            card = _RecentCard(path)
            card.activated.connect(self.file_selected)
            self._rows.addWidget(card)
            self._cards.append(card)
        self.setVisible(bool(self._paths))
