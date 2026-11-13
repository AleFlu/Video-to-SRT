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
from ui import theme


# ── Stili bottone export (theme-aware) ──────────────────────────────────────────

def _ss_btn() -> str:
    c = theme.c
    return (
        "QPushButton {"
        f"  background: {c('card')}; border: 1px solid {c('card_border')}; border-radius: 10px;"
        f"  color: {c('text')}; text-align: left; padding: 0 16px;"
        "}"
        f"QPushButton:hover {{ background: {c('card_2')}; border-color: {c('acc')}; }}"
        f"QPushButton:pressed {{ background: {c('surface')}; }}"
    )


def _ss_btn_accent() -> str:
    c = theme.c
    return (
        "QPushButton {"
        f"  background: {c('acc_soft')}; border: 1px solid {c('acc')};"
        f"  border-radius: 10px; color: {c('text')}; text-align: left; padding: 0 16px;"
        "}"
        f"QPushButton:hover {{ background: {c('acc_soft_2')}; border-color: {c('acc')}; }}"
        f"QPushButton:pressed {{ background: {c('acc_soft')}; }}"
    )


# kind: "normal" | "accent" | "publish"  → ricolorabili su theme_changed
def _export_btn(title: str, subtitle: str, kind: str, store: list, height: int = 56) -> QPushButton:
    """Bottone export con titolo bold + descrizione dim sulla seconda riga.
    `store` raccoglie (button, kind, title_lbl, sub_lbl) per la re-tematizzazione."""
    b = QPushButton()
    b.setFixedHeight(height)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    b.setCursor(Qt.PointingHandCursor)

    inner = QWidget(b)
    inner.setAttribute(Qt.WA_TransparentForMouseEvents)
    inner_lay = QVBoxLayout(inner)
    inner_lay.setContentsMargins(0, 0, 0, 0)
    inner_lay.setSpacing(2)

    t = QLabel(title)
    t.setAttribute(Qt.WA_TransparentForMouseEvents)
    inner_lay.addWidget(t)

    s = QLabel(subtitle)
    s.setAttribute(Qt.WA_TransparentForMouseEvents)
    inner_lay.addWidget(s)

    # posiziona l'inner widget quando il bottone viene ridimensionato
    def _reposition(event=None):
        inner.setGeometry(16, 0, b.width() - 32, b.height())
    b.resizeEvent = lambda e: (_reposition(), QPushButton.resizeEvent(b, e))
    _reposition()

    store.append((b, kind, t, s))
    return b


def _style_export_btn(b: QPushButton, kind: str, t: QLabel, s: QLabel):
    c = theme.c
    b.setStyleSheet({"accent": _ss_btn_accent()}.get(kind, _ss_btn()))
    t.setStyleSheet(
        f"color: {c('text')}; font-size: 13px; font-weight: 600;"
        " background: transparent; border: none;"
    )
    s.setStyleSheet(
        f"color: {c('muted')}; font-size: 11px;"
        " background: transparent; border: none;"
    )


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {theme.c('muted')}; font-size: 10px; font-weight: 700;"
        f" letter-spacing: 1.5px; font-family: {theme.FONT_MONO};"
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

        self._icon = QLabel("↑")
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setFixedSize(60, 60)
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
        self._icon.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {c('muted')};"
            f" background: {c('card_2')}; border: none; border-radius: 14px;"
        )
        self._msg.setStyleSheet(
            f"color: {c('muted')}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        self._sub.setStyleSheet(
            f"color: {c('faint')}; font-size: 12px; background: transparent;"
        )


# ── Export panel ──────────────────────────────────────────────────────────────

class _ExportPanel(QWidget):
    _PREVIEW_BLOCKS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._btn_store: list = []   # (button, kind, title_lbl, sub_lbl)

        # Scroll esterno per tutta la pagina
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(40, 36, 40, 40)
        root.setSpacing(0)

        # ── Header info ────────────────────────────────────────────────────────
        self._info_card = QFrame()
        self._info_card.setObjectName("exportInfo")
        info_lay = QVBoxLayout(self._info_card)
        info_lay.setContentsMargins(20, 14, 20, 14)
        info_lay.setSpacing(6)

        top_row = QHBoxLayout()
        self._lbl_count = QLabel("—")
        top_row.addWidget(self._lbl_count)

        self._badge_mod = QLabel("● modificato nell'editor")
        self._badge_mod.setVisible(False)
        top_row.addWidget(self._badge_mod)
        top_row.addStretch()
        info_lay.addLayout(top_row)

        self._lbl_source = QLabel("")
        info_lay.addWidget(self._lbl_source)

        self._lbl_origin = QLabel("")
        info_lay.addWidget(self._lbl_origin)

        root.addWidget(self._info_card)
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
            "accent", self._btn_store,
        )
        self.btn_vtt = _export_btn(
            "VTT",
            "WebVTT — per video HTML5 e web player",
            "normal", self._btn_store,
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
            "normal", self._btn_store,
        )
        self.btn_ass = _export_btn(
            "ASS",
            "Advanced SubStation Alpha — stili avanzati",
            "normal", self._btn_store,
        )
        row2.addWidget(self.btn_txt)
        row2.addWidget(self.btn_ass)
        root.addLayout(row2)
        root.addSpacing(8)

        # Terza riga: V2SRT (progetto) — full width
        self.btn_v2srt = _export_btn(
            "Progetto .v2srt",
            "Salva tutto il progetto — riapribile e modificabile",
            "normal", self._btn_store,
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
            "publish", self._btn_store,
        )
        self._btn_youtube.clicked.connect(self._publish_youtube)

        self._btn_vimeo = _export_btn(
            "Vimeo",
            "Esporta SRT compatibile con Vimeo subtitle uploader",
            "publish", self._btn_store,
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
            "publish", self._btn_store,
        )
        self._btn_premiere.clicked.connect(self._publish_premiere)

        self._btn_clipboard = _export_btn(
            "Copia negli appunti",
            "Copia tutto il testo SRT — incolla dove vuoi",
            "publish", self._btn_store,
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
        root.addWidget(self._preview)
        root.addStretch(1)

        # Riferimento ai sottotitoli per le azioni di pubblicazione
        self._current_subs: list = []

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    # ── Tema ────────────────────────────────────────────────────────────────

    def _apply_palette(self):
        c = theme.c
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._info_card.setStyleSheet(
            f"QFrame#exportInfo {{ background: {c('card')}; border: 1px solid {c('card_border')};"
            " border-radius: 11px; }"
        )
        self._lbl_count.setStyleSheet(
            f"color: {c('text')}; font-size: 14px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        self._badge_mod.setStyleSheet(
            f"color: {c('warn')}; font-size: 11px; background: transparent; border: none;"
        )
        self._lbl_source.setStyleSheet(
            f"color: {c('muted')}; font-size: 11px; background: transparent; border: none;"
        )
        self._lbl_origin.setStyleSheet(
            f"color: {c('acc')}; font-size: 11px; background: transparent; border: none;"
        )
        self._preview.setStyleSheet(
            "QPlainTextEdit {"
            f"  background: {c('inset')}; color: {c('dim')};"
            f"  border: 1px solid {c('line')}; border-radius: 9px;"
            f"  font-family: {theme.FONT_MONO}; font-size: 12px;"
            "  padding: 10px;"
            "}"
        )
        for b, kind, t, s in self._btn_store:
            _style_export_btn(b, kind, t, s)

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
