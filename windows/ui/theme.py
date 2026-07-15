"""
theme.py — Dark palette + stylesheet globale (versione Windows).

Differenze rispetto a macOS:
- Font stack: "Segoe UI" (Windows) prima di "Helvetica Neue" / "-apple-system"
- Monospace: "Consolas" (Windows) prima di "SF Mono"
- Resto identico al macOS
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG_BASE      = "#0e0e14"
BG_WINDOW    = "#12121a"
BG_PANEL     = "#1a1a24"
BG_CARD      = "#1e1e2a"
BG_TIMELINE  = "#16161e"
BG_WIDGET    = "#16161e"
BG_INPUT     = "#1c1c28"
BG_ALT       = "#1a1a26"
BG_HOVER     = "#22222e"
BG_SELECTED  = "#2a2a3e"

ACCENT       = "#4f8cff"
ACCENT_HOVER = "#6aa3ff"
ACCENT_DIM   = "#2a4a8a"

ERROR        = "#e05555"
WARNING      = "#d4924a"
SUCCESS      = "#4caf50"
MUTED        = "#5a5a7a"
TEXT_MAIN    = "#e4e4ef"
TEXT_DIM     = "#8888aa"
BORDER       = "#2a2a3a"
BORDER_FOCUS = "#4f8cff"

SEP_COLOR    = "#111114"


class AuroraMixin:
    """
    Mixin che aggiunge un blob luminoso animato in alto a sinistra.
    Usare come primo parent: class MyWidget(AuroraMixin, QWidget).
    Il widget deve chiamare super().__init__() normalmente.
    """

    def _aurora_init(self):
        self._aurora_t = 0.0
        from PySide6.QtCore import QTimer
        self._aurora_timer = QTimer(self)
        self._aurora_timer.setInterval(32)
        self._aurora_timer.timeout.connect(self._aurora_tick)
        self._aurora_timer.start()

    def _aurora_tick(self):
        self._aurora_t += 0.012
        self.update()

    def _aurora_paint(self, painter):
        import math
        from PySide6.QtGui import QRadialGradient, QColor
        from PySide6.QtCore import QPointF
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#0e0e14"))
        cx = w * (0.5 + 0.18 * math.sin(self._aurora_t))
        cy = h * (0.5 + 0.18 * math.cos(self._aurora_t * 0.7))
        rg = QRadialGradient(QPointF(cx, cy), min(w, h) * 0.55)
        rg.setColorAt(0.0, QColor(79, 140, 255, 35))
        rg.setColorAt(1.0, QColor(79, 140, 255, 0))
        painter.fillRect(self.rect(), rg)


def apply_dark_palette(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(BG_WINDOW))
    palette.setColor(QPalette.WindowText,      QColor(TEXT_MAIN))
    palette.setColor(QPalette.Base,            QColor(BG_INPUT))
    palette.setColor(QPalette.AlternateBase,   QColor(BG_ALT))
    palette.setColor(QPalette.ToolTipBase,     QColor(BG_CARD))
    palette.setColor(QPalette.ToolTipText,     QColor(TEXT_MAIN))
    palette.setColor(QPalette.Text,            QColor(TEXT_MAIN))
    palette.setColor(QPalette.Button,          QColor(BG_WIDGET))
    palette.setColor(QPalette.ButtonText,      QColor(TEXT_MAIN))
    palette.setColor(QPalette.BrightText,      QColor("#ffffff"))
    palette.setColor(QPalette.Link,            QColor(ACCENT))
    palette.setColor(QPalette.Highlight,       QColor(ACCENT_DIM))
    palette.setColor(QPalette.HighlightedText, QColor(TEXT_MAIN))
    palette.setColor(QPalette.Disabled, QPalette.Text,       QColor(MUTED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    app.setPalette(palette)


def build_stylesheet() -> str:
    return f"""
/* ── Base ── */
QWidget {{
    background-color: {BG_BASE};
    color: {TEXT_MAIN};
    font-family: "Segoe UI", "Helvetica Neue", -apple-system, Arial, sans-serif;
    font-size: 13px;
    outline: none;
}}

QMainWindow, QDialog {{
    background-color: {BG_WINDOW};
}}

/* ── Panel & Card ── */
QWidget#contentPanel {{
    background-color: {BG_PANEL};
}}

QFrame#card {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

/* ── Labels ── */
QLabel#title {{
    font-size: 18px;
    font-weight: 600;
    color: {TEXT_MAIN};
    background: transparent;
}}

QLabel#subtitle {{
    font-size: 13px;
    color: {TEXT_DIM};
    background: transparent;
}}

QLabel#muted {{
    color: {MUTED};
    background: transparent;
}}

QLabel#sectionTitle {{
    font-size: 11px;
    font-weight: 600;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: transparent;
}}

QLabel#success {{
    color: {SUCCESS};
    background: transparent;
}}

QLabel#errorLabel {{
    color: {ERROR};
    background: transparent;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {BG_WIDGET};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 13px;
    min-height: 28px;
}}

QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: #3a3a4a;
}}

QPushButton:pressed {{
    background-color: {BG_SELECTED};
}}

QPushButton:disabled {{
    color: {MUTED};
    background-color: {BG_BASE};
    border-color: {BG_BASE};
}}

QPushButton#primary {{
    background-color: {ACCENT};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}

QPushButton#primary:hover {{
    background-color: {ACCENT_HOVER};
}}

QPushButton#primary:pressed {{
    background-color: #3a72e0;
}}

QPushButton#primary:disabled {{
    background-color: {ACCENT_DIM};
    color: #7a9adf;
}}

QPushButton#danger {{
    background-color: transparent;
    color: {ERROR};
    border: 1px solid {ERROR};
}}

QPushButton#danger:hover {{
    background-color: rgba(224, 85, 85, 0.12);
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: {ACCENT_DIM};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {BORDER_FOCUS};
}}

QLineEdit:disabled {{
    color: {MUTED};
    background-color: {BG_BASE};
}}

/* ── ComboBox ── */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 28px;
}}

QComboBox:hover {{
    border-color: #3a3a4a;
}}

QComboBox:focus {{
    border-color: {BORDER_FOCUS};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {MUTED};
    width: 0;
    height: 0;
    margin-right: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    selection-background-color: {BG_SELECTED};
    selection-color: {TEXT_MAIN};
    outline: none;
}}

/* ── SpinBox / DoubleSpinBox ── */
QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {BORDER_FOCUS};
}}

/* ── CheckBox / RadioButton ── */
QCheckBox, QRadioButton {{
    color: {TEXT_MAIN};
    spacing: 6px;
    background: transparent;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER};
    background-color: {BG_INPUT};
    border-radius: 3px;
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ── Slider ── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BG_WIDGET};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: {ACCENT};
    border-radius: 7px;
    border: none;
}}

QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
}}

QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ── ProgressBar ── */
QProgressBar {{
    background-color: {BG_WIDGET};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

/* ── Table ── */
QTableView {{
    background-color: {BG_BASE};
    color: {TEXT_MAIN};
    border: none;
    gridline-color: {SEP_COLOR};
    selection-background-color: {BG_SELECTED};
    selection-color: {TEXT_MAIN};
    alternate-background-color: {BG_ALT};
}}

QTableView::item {{
    padding: 2px 6px;
    border: none;
}}

QTableView::item:selected {{
    background-color: {BG_SELECTED};
}}

QHeaderView::section {{
    background-color: {BG_PANEL};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {SEP_COLOR};
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}

/* ── ScrollBar ── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.12);
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(255,255,255,0.20);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,0.12);
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: rgba(255,255,255,0.20);
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Toolbar ── */
QToolBar {{
    background-color: {BG_PANEL};
    border: none;
    border-bottom: 1px solid {SEP_COLOR};
    spacing: 2px;
    padding: 2px 4px;
}}

QToolBar QToolButton {{
    background: transparent;
    color: {TEXT_MAIN};
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}

QToolBar QToolButton:hover {{
    background-color: {BG_HOVER};
}}

QToolBar QToolButton:pressed {{
    background-color: {BG_SELECTED};
}}

QToolBar QToolButton:checked {{
    background-color: {BG_SELECTED};
    color: {ACCENT};
}}

QToolBar QToolButton:disabled {{
    color: {MUTED};
}}

/* ── Separators ── */
QToolBar::separator {{
    background-color: {BORDER};
    width: 1px;
    margin: 4px 3px;
}}

QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    background-color: {SEP_COLOR};
    border: none;
    max-height: 1px;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background-color: {SEP_COLOR};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* ── TabBar ── */
QTabBar::tab {{
    background-color: {BG_PANEL};
    color: {MUTED};
    border: none;
    padding: 6px 16px;
    font-size: 12px;
    margin-right: 1px;
}}

QTabBar::tab:selected {{
    color: {TEXT_MAIN};
    background-color: {BG_WIDGET};
    border-bottom: 2px solid {ACCENT};
}}

QTabBar::tab:hover:!selected {{
    background-color: {BG_HOVER};
    color: {TEXT_DIM};
}}

/* ── Dock ── */
QDockWidget {{
    color: {TEXT_MAIN};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}

QDockWidget::title {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {SEP_COLOR};
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.4px;
}}

QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    border-radius: 3px;
    padding: 1px;
}}

QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {BG_HOVER};
}}

/* ── Menu ── */
QMenuBar {{
    background-color: {BG_WINDOW};
    color: {TEXT_MAIN};
    border-bottom: 1px solid {SEP_COLOR};
    padding: 2px 4px;
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background-color: {BG_HOVER};
}}

QMenu {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 0;
}}

QMenu::item {{
    padding: 5px 28px 5px 16px;
    border-radius: 3px;
    margin: 1px 4px;
}}

QMenu::item:selected {{
    background-color: {BG_SELECTED};
}}

QMenu::item:disabled {{
    color: {MUTED};
}}

QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 3px 8px;
}}

/* ── StatusBar ── */
QStatusBar {{
    background-color: {BG_WINDOW};
    color: {MUTED};
    border-top: 1px solid {SEP_COLOR};
    font-size: 11px;
}}

/* ── ToolTip ── */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 12px;
}}

/* ── ScrollArea ── */
QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
"""
