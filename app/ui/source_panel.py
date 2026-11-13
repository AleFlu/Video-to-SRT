"""
source_panel.py — Pannello di caricamento file sorgente.

Supporta click-per-sfogliare e drag & drop nativo di Qt.
Mostra un banner di avviso prominente se FFmpeg o il modello Whisper
non sono disponibili (logica ripresa da Try1).
"""

from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QPainter, QPen, QColor, QPainterPath
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QFileDialog, QSizePolicy
)


SUPPORTED_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma",
}

FILE_FILTERS = (
    "File multimediali (*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg);;"
    "Video (*.mp4 *.mkv *.avi *.mov *.webm);;"
    "Audio (*.mp3 *.wav *.m4a *.flac *.ogg);;"
    "Tutti i file (*.*)"
)


def fmt_size(path: str) -> str:
    try:
        s = os.path.getsize(path)
        if s < 1024:      return f"{s} B"
        if s < 1024**2:   return f"{s/1024:.1f} KB"
        if s < 1024**3:   return f"{s/1024**2:.1f} MB"
        return f"{s/1024**3:.2f} GB"
    except OSError:
        return ""


class DepsBanner(QFrame):
    """
    Banner di avviso in cima al SourcePanel quando FFmpeg o il modello
    Whisper non sono disponibili. Si nasconde automaticamente se tutto è ok.

    Usa colori inline (non delegati al tema) per garantire visibilità
    indipendentemente dall'ordine di applicazione degli stylesheet.
    """

    _STYLE_WARN = (
        "QFrame {"
        "  background-color: #3a2800;"
        "  border: 1px solid #c87d00;"
        "  border-radius: 8px;"
        "}"
    )
    _STYLE_ERROR = (
        "QFrame {"
        "  background-color: #3a0a0a;"
        "  border: 1px solid #c83030;"
        "  border-radius: 8px;"
        "}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("depsBanner")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        self._title = QLabel("")
        self._title.setStyleSheet(
            "color: #ffcc55; font-weight: bold; font-size: 14px;"
            "background: transparent;"
        )
        layout.addWidget(self._title)

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setOpenExternalLinks(True)
        self._body.setTextFormat(Qt.RichText)
        self._body.setStyleSheet(
            "color: #ddaa77; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self._body)

    def set_status(self, ffmpeg_ok: bool, model_ok: bool):
        """Mostra o nasconde il banner in base alle dipendenze mancanti."""
        issues: list[str] = []
        hints:  list[str] = []

        if not ffmpeg_ok:
            issues.append("FFmpeg non trovato")
            hints.append(
                "• <b>FFmpeg</b>: installa con <code>brew install ffmpeg</code>"
            )

        if not model_ok:
            issues.append("Modello Whisper non disponibile")
            hints.append(
                "• <b>Modello Whisper large-v3</b>: esegui <code>./setup_mac.sh</code> "
                "per scaricarlo (≈ 3 GB)"
            )

        if not issues:
            self.setVisible(False)
            return

        both_missing = not ffmpeg_ok and not model_ok
        self._title.setText("⚠️   " + "  ·  ".join(issues))
        self._title.setStyleSheet(
            f"color: {'#ff8888' if both_missing else '#ffcc55'};"
            "font-weight: bold; font-size: 14px; background: transparent;"
        )
        self._body.setText("<br>".join(hints))
        self.setStyleSheet(self._STYLE_ERROR if both_missing else self._STYLE_WARN)
        self.setVisible(True)


class _DropIcon(QWidget):
    """Icona vettoriale disegnata con QPainter: documento con freccia verso il basso."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded = False
        self.setFixedSize(64, 64)

    def set_loaded(self, loaded: bool):
        self._loaded = loaded
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        color = QColor("#4f8cff") if self._loaded else QColor("#5a5a6a")
        pen = QPen(color, 2.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if self._loaded:
            # Check circle
            p.drawEllipse(QRectF(8, 8, 48, 48))
            p.drawLine(QPointF(22, 32), QPointF(30, 40))
            p.drawLine(QPointF(30, 40), QPointF(44, 24))
        else:
            # Documento con freccia upload
            doc = QPainterPath()
            doc.moveTo(14, 4)
            doc.lineTo(42, 4)
            doc.lineTo(50, 14)
            doc.lineTo(50, 60)
            doc.lineTo(14, 60)
            doc.closeSubpath()
            # Corner fold
            fold = QPainterPath()
            fold.moveTo(42, 4)
            fold.lineTo(42, 14)
            fold.lineTo(50, 14)
            p.drawPath(doc)
            p.drawPath(fold)
            # Freccia verso il basso al centro
            p.drawLine(QPointF(32, 22), QPointF(32, 44))
            p.drawLine(QPointF(32, 44), QPointF(24, 36))
            p.drawLine(QPointF(32, 44), QPointF(40, 36))

        p.end()


class DropZone(QFrame):
    """Area drag & drop che emette 'file_selected' quando un file è valido."""
    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setMinimumHeight(240)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 32, 24, 32)

        self._icon_widget = _DropIcon()
        icon_row = QHBoxLayout()
        icon_row.addStretch(1)
        icon_row.addWidget(self._icon_widget)
        icon_row.addStretch(1)
        layout.addLayout(icon_row)

        self.label = QLabel("Trascina un file qui o clicca per sfogliare")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 14px; font-weight: 500;")
        layout.addWidget(self.label)

        self.detail = QLabel("MP4 · MOV · MKV · MP3 · WAV · FLAC · ...")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setObjectName("subtitle")
        layout.addWidget(self.detail)

    # ---- Drag & drop ----
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls and Path(urls[0].toLocalFile()).suffix.lower() in SUPPORTED_EXTS:
                e.acceptProposedAction()
                self.setProperty("active", True)
                self.style().unpolish(self); self.style().polish(self)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setProperty("active", False)
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        self.setProperty("active", False)
        self.style().unpolish(self); self.style().polish(self)
        urls = e.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if Path(path).suffix.lower() in SUPPORTED_EXTS and os.path.isfile(path):
            self.file_selected.emit(path)
            e.acceptProposedAction()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "Seleziona un file video o audio", "", FILE_FILTERS
            )
            if path:
                self.file_selected.emit(path)

    def show_loaded(self, path: str):
        self.setProperty("loaded", True)
        self.style().unpolish(self); self.style().polish(self)
        name = Path(path).name
        if len(name) > 50:
            name = name[:47] + "..."
        self._icon_widget.set_loaded(True)
        self.label.setText(name)
        self.label.setStyleSheet("font-size: 14px; font-weight: 600; color: #4f8cff;")
        self.detail.setText(f"{fmt_size(path)}  ·  {Path(path).suffix.upper()}")

    def reset(self):
        self.setProperty("loaded", False)
        self.style().unpolish(self); self.style().polish(self)
        self._icon_widget.set_loaded(False)
        self.label.setText("Trascina un file qui o clicca per sfogliare")
        self.label.setStyleSheet("font-size: 14px; font-weight: 500;")
        self.detail.setText("MP4 · MOV · MKV · MP3 · WAV · FLAC · ...")


class SourcePanel(QWidget):
    file_loaded = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(16)

        title = QLabel("Sorgente")
        title.setObjectName("title")
        outer.addWidget(title)

        sub = QLabel("Carica il file video o audio da trascrivere.")
        sub.setObjectName("subtitle")
        outer.addWidget(sub)

        # ---- Banner avviso dipendenze (visibile solo se ci sono problemi) ----
        self.deps_banner = DepsBanner()
        outer.addWidget(self.deps_banner)

        outer.addSpacing(6)

        self.drop = DropZone()
        self.drop.file_selected.connect(self._on_file)
        outer.addWidget(self.drop)

        # Azioni
        row = QHBoxLayout()
        self.next_btn = QPushButton("Continua alle impostazioni  →")
        self.next_btn.setObjectName("primary")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next)
        row.addStretch(1)
        row.addWidget(self.next_btn)
        outer.addLayout(row)

        outer.addStretch(1)

    def set_deps_status(self, ffmpeg_ok: bool, model_ok: bool):
        """Aggiorna il banner di avviso dipendenze. Chiamato da MainWindow dopo la splash."""
        self.deps_banner.set_status(ffmpeg_ok, model_ok)

    def _on_file(self, path: str):
        self.drop.show_loaded(path)
        self.next_btn.setEnabled(True)
        self._current_path = path
        self.file_loaded.emit(path)

    def _on_next(self):
        # Il MainWindow ascolta file_loaded e abilita la sezione successiva.
        # Qui emettiamo un segnale supplementare tramite la sidebar dal MainWindow.
        pass

    def next_clicked_signal(self):
        return self.next_btn.clicked
