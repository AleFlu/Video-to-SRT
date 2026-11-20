"""
review_marks.py — Segni di revisione nel testo dei sottotitoli: parole incerte di Whisper
(evidenziate) ed errori di ortografia (sottolineatura ondulata). Logica in
``core.spelling``; qui solo il disegno, condiviso da tabella e Inspector.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QSyntaxHighlighter, QTextCharFormat

from core.spelling import SPELLER, Span, uncertain_spans
from core.subtitle_model import Subtitle
from ui import theme

# Parola a destra della cella Testo quando la riga non ha problemi più gravi
HINT_SPELLING = ("ortografia", "warn")
HINT_UNCERTAIN = ("incerto", "dim")


def marks_for(text: str, sub: Optional[Subtitle]) -> Tuple[List[Span], Tuple[Span, ...]]:
    """(parole incerte, parole sconosciute) del testo, per il sottotitolo ``sub``."""
    if sub is None:
        return [], ()
    return (uncertain_spans(text, sub.uncertain, sub.asr_text),
            SPELLER.misspelled_spans(text, sub.asr_text))


def hint_word(sub: Optional[Subtitle]) -> Optional[tuple]:
    """("ortografia"|"incerto", token colore) per la riga, None se non c'è nulla."""
    if sub is None:
        return None
    uncertain, wrong = marks_for(sub.text, sub)
    if wrong:
        return HINT_SPELLING
    if uncertain:
        return HINT_UNCERTAIN
    return None


def uncertain_fill() -> QColor:
    col = theme.qcolor("warn")
    col.setAlpha(70)
    return col


def paint_wavy(painter: QPainter, x0: float, x1: float, y: float, color: QColor) -> None:
    """Sottolineatura ondulata (come i correttori) da ``x0`` a ``x1`` all'altezza ``y``."""
    if x1 - x0 < 2:
        return
    path = QPainterPath(QPointF(x0, y))
    x, up, step = x0, True, 2.0
    while x < x1:
        x = min(x1, x + step)
        path.lineTo(QPointF(x, y - 1.5 if up else y + 0.5))
        up = not up
    pen = QPen(color, 1.0)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def visible_spans(spans: Sequence[Span], shown: str, full: str) -> List[Span]:
    """Le posizioni che restano intere nel testo mostrato (eventualmente troncato con …)."""
    limit = len(shown) if shown == full else max(0, len(shown) - 1)
    return [(s, e) for s, e in spans if e <= limit]


class ReviewHighlighter(QSyntaxHighlighter):
    """Evidenzia parole incerte ed errori di ortografia nel campo di testo dell'Inspector.

    Le posizioni si calcolano sul testo intero del documento (inizio frase, parole
    della trascrizione) e si riportano sul singolo blocco (riga).
    """

    def __init__(self, document):
        super().__init__(document)
        self._sub: Optional[Subtitle] = None
        self._text = ""
        self._spans: Tuple[List[Span], Tuple[Span, ...]] = ([], ())
        SPELLER.notifier.changed.connect(self._on_dictionary_changed)

    def _on_dictionary_changed(self) -> None:
        self._text = None        # le posizioni in cache sono quelle col vecchio dizionario
        self.rehighlight()

    def set_subtitle(self, sub: Optional[Subtitle]) -> None:
        self._sub = sub
        self._text = None        # ricalcolo al prossimo blocco
        self.rehighlight()

    def current_spans(self) -> Tuple[List[Span], Tuple[Span, ...]]:
        text = self.document().toPlainText()
        if text != self._text:
            self._text = text
            self._spans = marks_for(text, self._sub)
        return self._spans

    def highlightBlock(self, text: str):  # noqa: N802 (override Qt)
        if self._sub is None:
            return
        uncertain, wrong = self.current_spans()
        base = self.currentBlock().position()
        end = base + len(text)
        fill = QTextCharFormat()
        fill.setBackground(uncertain_fill())
        for s, e in uncertain:
            if s >= base and e <= end:
                self.setFormat(s - base, e - s, fill)
        for s, e in wrong:
            if s >= base and e <= end:
                fmt = self.format(s - base)
                fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
                fmt.setUnderlineColor(theme.qcolor("err"))
                self.setFormat(s - base, e - s, fmt)
