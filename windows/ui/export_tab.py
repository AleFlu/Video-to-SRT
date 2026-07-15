"""
export_tab.py — ExportTab: pannello esportazione (terza tab di ProjectWidget).

Layout:
  ┌── Header: N sub · fonte · badge ──────────────────────────────────────────┐
  ├── Sezione "Salva file" (2 colonne: SRT★ VTT / TXT ASS / V2SRT) ──────────┤
  ├── Sezione "Pubblica direttamente" (YouTube captions, Vimeo, ecc.) ─────────┤
  └────────────────────────────────────────────────────────────────────────────┘

API pubblica:
  refresh(segments_raw, editor_subs, source_path, is_modified)
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QScrollArea, QStackedWidget, QPlainTextEdit,
)

from core.subtitle_model import Subtitle
from ui.theme import AuroraMixin


# ── Stili bottone export ───────────────────────────────────────────────────────

_SS_BTN = (
    "QPushButton {"
    "  background: #1a1d24; border: 1px solid #262a33; border-radius: 10px;"
    "  color: #e8eaf0; text-align: left; padding: 0 16px;"
    "}"
    "QPushButton:hover { background: #1f232c; border-color: #3a404e; }"
    "QPushButton:pressed { background: #15171d; }"
)

_SS_BTN_ACCENT = (
    "QPushButton {"
    "  background: rgba(91,140,255,0.12); border: 1px solid rgba(91,140,255,0.35);"
    "  border-radius: 10px; color: #e8eaf0; text-align: left; padding: 0 16px;"
    "}"
    "QPushButton:hover { background: rgba(91,140,255,0.2); border-color: rgba(91,140,255,0.6); }"
    "QPushButton:pressed { background: rgba(91,140,255,0.08); }"
)

_SS_BTN_PUBLISH = (
    "QPushButton {"
    "  background: #1a1d24; border: 1px solid #262a33; border-radius: 10px;"
    "  color: #a8aebb; text-align: left; padding: 0 16px;"
    "}"
    "QPushButton:hover { background: #1f232c; border-color: #3a404e; color: #e8eaf0; }"
    "QPushButton:pressed { background: #15171d; }"
)


def _export_btn(title: str, subtitle: str, style: str, height: int = 56) -> QPushButton:
    """Bottone export con titolo bold + descrizione dim sulla seconda riga."""
    b = QPushButton()
    b.setFixedHeight(height)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    b.setStyleSheet(style)
    b.setCursor(Qt.PointingHandCursor)

    inner = QWidget(b)
    inner.setAttribute(Qt.WA_TransparentForMouseEvents)
    inner_lay = QVBoxLayout(inner)
    inner_lay.setContentsMargins(0, 0, 0, 0)
    inner_lay.setSpacing(2)

    t = QLabel(title)
    t.setAttribute(Qt.WA_TransparentForMouseEvents)
    t.setStyleSheet("color: #e8eaf0; font-size: 13px; font-weight: 600;"
                    " background: transparent; border: none;")
    inner_lay.addWidget(t)

    s = QLabel(subtitle)
    s.setAttribute(Qt.WA_TransparentForMouseEvents)
    s.setStyleSheet("color: #6c727f; font-size: 11px;"
                    " background: transparent; border: none;")
    inner_lay.addWidget(s)

    # posiziona l'inner widget quando il bottone viene ridimensionato
    def _reposition(event=None):
        inner.setGeometry(16, 0, b.width() - 32, b.height())
    b.resizeEvent = lambda e: (_reposition(), QPushButton.resizeEvent(b, e))
    _reposition()

    return b


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color: #4a4f5a; font-size: 10px; font-weight: 700;"
        " letter-spacing: 1.5px; font-family: 'SF Mono',monospace;"
    )
    return lbl


# ── ExportTab ─────────────────────────────────────────────────────────────────

class ExportTab(AuroraMixin, QWidget):

    export_srt_requested  = Signal()
    export_vtt_requested  = Signal()
    export_txt_requested  = Signal()
    export_ass_requested  = Signal()
    save_v2srt_requested  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._aurora_init()
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

        self._stack.setCurrentIndex(0)

    def paintEvent(self, event):
        p = QPainter(self)
        self._aurora_paint(p)
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
        lay.setSpacing(12)

        icon = QLabel("↑")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(60, 60)
        icon.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #6c727f;"
            " background: #1a1d24; border: 1px solid #262a33; border-radius: 14px;"
        )
        lay.addWidget(icon, alignment=Qt.AlignCenter)

        msg = QLabel("Nessun sottotitolo da esportare")
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("color: #6c727f; font-size: 15px; font-weight: 600;")
        lay.addWidget(msg)

        sub = QLabel("Completa una trascrizione o importa un file SRT nell'editor.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color: #4a4f5a; font-size: 12px;")
        lay.addWidget(sub)


# ── Export panel ──────────────────────────────────────────────────────────────

class _ExportPanel(QWidget):
    _PREVIEW_BLOCKS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Scroll esterno per tutta la pagina
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; border: none; }"
            "QScrollBar::handle:vertical { background: #2f343e; border-radius: 3px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(40, 36, 40, 40)
        root.setSpacing(0)

        # ── Header info ────────────────────────────────────────────────────────
        info_card = QFrame()
        info_card.setObjectName("exportInfo")
        info_card.setStyleSheet(
            "QFrame#exportInfo { background: #1a1d24; border: 1px solid #262a33;"
            " border-radius: 11px; }"
        )
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(20, 14, 20, 14)
        info_lay.setSpacing(6)

        top_row = QHBoxLayout()
        self._lbl_count = QLabel("—")
        self._lbl_count.setStyleSheet(
            "color: #e8eaf0; font-size: 14px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        top_row.addWidget(self._lbl_count)

        self._badge_mod = QLabel("● modificato nell'editor")
        self._badge_mod.setStyleSheet(
            "color: #f5b461; font-size: 11px; background: transparent; border: none;"
        )
        self._badge_mod.setVisible(False)
        top_row.addWidget(self._badge_mod)
        top_row.addStretch()
        info_lay.addLayout(top_row)

        self._lbl_source = QLabel("")
        self._lbl_source.setStyleSheet(
            "color: #6c727f; font-size: 11px; background: transparent; border: none;"
        )
        info_lay.addWidget(self._lbl_source)

        self._lbl_origin = QLabel("")
        self._lbl_origin.setStyleSheet(
            "color: #5b8cff; font-size: 11px; background: transparent; border: none;"
        )
        info_lay.addWidget(self._lbl_origin)

        root.addWidget(info_card)
        root.addSpacing(28)

        # ── Sezione: Salva file ────────────────────────────────────────────────
        root.addWidget(_section_label("Salva file"))
        root.addSpacing(10)

        # Prima riga: SRT (accent) + VTT
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self.btn_srt = _export_btn(
            "SRT",
            "SubRip Subtitle — standard universale",
            _SS_BTN_ACCENT,
        )
        self.btn_vtt = _export_btn(
            "VTT",
            "WebVTT — per video HTML5 e web player",
            _SS_BTN,
        )
        row1.addWidget(self.btn_srt)
        row1.addWidget(self.btn_vtt)
        root.addLayout(row1)
        root.addSpacing(8)

        # Seconda riga: TXT + ASS
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.btn_txt = _export_btn(
            "TXT",
            "Testo semplice — solo dialoghi, senza timing",
            _SS_BTN,
        )
        self.btn_ass = _export_btn(
            "ASS",
            "Advanced SubStation Alpha — stili avanzati",
            _SS_BTN,
        )
        row2.addWidget(self.btn_txt)
        row2.addWidget(self.btn_ass)
        root.addLayout(row2)
        root.addSpacing(8)

        # Terza riga: V2SRT (progetto) — full width
        self.btn_v2srt = _export_btn(
            "Progetto .v2srt",
            "Salva tutto il progetto — riapribile e modificabile",
            _SS_BTN,
        )
        root.addWidget(self.btn_v2srt)
        root.addSpacing(32)

        # ── Sezione: Pubblica direttamente ────────────────────────────────────
        root.addWidget(_section_label("Pubblica direttamente"))
        root.addSpacing(10)

        pub_row1 = QHBoxLayout()
        pub_row1.setSpacing(10)

        self._btn_youtube = _export_btn(
            "YouTube Studio",
            "Copia il testo formattato — incollalo nelle caption manuale",
            _SS_BTN_PUBLISH,
        )
        self._btn_youtube.clicked.connect(self._publish_youtube)

        self._btn_vimeo = _export_btn(
            "Vimeo",
            "Esporta SRT compatibile con Vimeo subtitle uploader",
            _SS_BTN_PUBLISH,
        )
        self._btn_vimeo.clicked.connect(self._publish_vimeo)

        pub_row1.addWidget(self._btn_youtube)
        pub_row1.addWidget(self._btn_vimeo)
        root.addLayout(pub_row1)
        root.addSpacing(8)

        pub_row2 = QHBoxLayout()
        pub_row2.setSpacing(10)

        self._btn_premiere = _export_btn(
            "Premiere Pro / DaVinci",
            "Esporta SRT — importa con File → Import nel progetto",
            _SS_BTN_PUBLISH,
        )
        self._btn_premiere.clicked.connect(self._publish_premiere)

        self._btn_clipboard = _export_btn(
            "Copia negli appunti",
            "Copia tutto il testo SRT — incolla dove vuoi",
            _SS_BTN_PUBLISH,
        )
        self._btn_clipboard.clicked.connect(self._publish_clipboard)

        pub_row2.addWidget(self._btn_premiere)
        pub_row2.addWidget(self._btn_clipboard)
        root.addLayout(pub_row2)

        root.addSpacing(28)

        # ── Anteprima SRT ──────────────────────────────────────────────────────
        root.addWidget(_section_label("Anteprima SRT"))
        root.addSpacing(10)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFixedHeight(180)
        self._preview.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #1a1d24; color: #a8aebb;"
            "  border: 1px solid #262a33; border-radius: 9px;"
            "  font-family: 'SF Mono','Menlo',monospace; font-size: 11px;"
            "  padding: 10px;"
            "}"
        )
        root.addWidget(self._preview)
        root.addStretch(1)

        # Riferimento ai sottotitoli per le azioni di pubblicazione
        self._current_subs: list = []

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

    def _publish_vimeo(self):
        """Esporta SRT rinominato per Vimeo."""
        from PySide6.QtWidgets import QFileDialog
        from core.srt_io import subtitles_to_srt
        if not self._current_subs:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta per Vimeo", "sottotitoli_vimeo.srt", "SRT (*.srt)"
        )
        if path:
            Path(path).write_text(subtitles_to_srt(self._current_subs), encoding="utf-8")

    def _publish_premiere(self):
        """Esporta SRT ottimizzato per NLE (Premiere/DaVinci)."""
        from PySide6.QtWidgets import QFileDialog
        from core.srt_io import subtitles_to_srt
        if not self._current_subs:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta per NLE", "sottotitoli_nle.srt", "SRT (*.srt)"
        )
        if path:
            Path(path).write_text(subtitles_to_srt(self._current_subs), encoding="utf-8")

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
        self._lbl_source.setVisible(bool(source_path))
        self._lbl_origin.setText(
            "Versione dell'editor" if has_editor_subs
            else "Trascrizione originale"
        )
        self._badge_mod.setVisible(has_editor_subs and is_modified)

        preview_subs = subtitles[:self._PREVIEW_BLOCKS]
        preview_text = subtitles_to_srt(preview_subs)
        if n > self._PREVIEW_BLOCKS:
            preview_text += f"\n… e altri {n - self._PREVIEW_BLOCKS} sottotitoli"
        self._preview.setPlainText(preview_text)
