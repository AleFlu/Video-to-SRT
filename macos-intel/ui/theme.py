"""
theme.py — Palette colori e stylesheet globali.
Palette A "Pro Conservative" — design system Video→SRT v2.
"""

# ── Palette A ────────────────────────────────────────────────────────────────
BG_DARK       = "#0e1014"   # --bg: sfondo principale
BG_MEDIUM     = "#15171d"   # --surf: pannelli, tab bar
BG_LIGHT      = "#1a1d24"   # --card: card, input
BG_HOVER      = "#1f232c"   # --card2: hover, input focus bg

BORDER        = "#262a33"   # --line: bordi principali
BORDER_LIGHT  = "#2f343e"   # --line2: bordi secondari

TEXT          = "#e8eaf0"   # --text
TEXT_DIM      = "#a8aebb"   # --dim
TEXT_MUTED    = "#6c727f"   # --muted
TEXT_FAINT    = "#4a4f5a"   # --faint

ACCENT        = "#5b8cff"   # --acc
ACCENT_HOVER  = "#7aa2ff"   # --acc-h
ACCENT_DIM    = "#3f6fd8"   # --acc-p
ACCENT_SOFT   = "rgba(91,140,255,0.12)"   # --acc-soft
ACCENT_SOFT2  = "rgba(91,140,255,0.22)"   # --acc-soft-2

SUCCESS       = "#3ecf8e"   # --ok
SUCCESS_SOFT  = "rgba(62,207,142,0.14)"
WARNING       = "#f5b461"   # --warn
WARNING_SOFT  = "rgba(245,180,97,0.14)"
ERROR         = "#ef5e6c"   # --err
ERROR_SOFT    = "rgba(239,94,108,0.14)"
PURPLE        = "#a78bfa"   # --purple

# Alias per compatibilità con codice esistente
SIDEBAR_BG    = "#0e1014"
SIDEBAR_ACTIVE= "#1a1d24"

# ── Layout ───────────────────────────────────────────────────────────────────
BG_PANEL      = "#15171d"   # pannelli top
BG_TIMELINE   = "#0e1014"   # timeline inferiore
SEPARATOR     = "#000000"   # handle splitter


class AuroraMixin:
    """
    Mixin che aggiunge un blob luminoso animato in alto a sinistra.
    Usare come primo parent: class MyWidget(AuroraMixin, QWidget).
    Il widget deve chiamare super().__init__() normalmente.
    """

    def _aurora_init(self):
        import math as _m
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
        painter.fillRect(self.rect(), QColor("#0e1014"))
        cx = w * (0.5 + 0.18 * math.sin(self._aurora_t))
        cy = h * (0.5 + 0.18 * math.cos(self._aurora_t * 0.7))
        rg = QRadialGradient(QPointF(cx, cy), min(w, h) * 0.55)
        rg.setColorAt(0.0, QColor(91, 140, 255, 35))
        rg.setColorAt(1.0, QColor(91, 140, 255, 0))
        painter.fillRect(self.rect(), rg)


def build_stylesheet() -> str:
    """Stylesheet Qt globale. Applicato a QApplication."""
    return f"""
    /* ============ GLOBAL ============ */
    QWidget {{
        background-color: {BG_DARK};
        color: {TEXT};
        font-family: "SF Pro Display", "SF Pro Text", -apple-system, "Helvetica Neue", sans-serif;
        font-size: 13px;
    }}

    QMainWindow {{
        background-color: {BG_DARK};
    }}

    /* ============ SIDEBAR ============ */
    QWidget#sidebar {{
        background-color: {SIDEBAR_BG};
        border-right: 1px solid {BORDER};
    }}

    QPushButton#sidebarButton {{
        background-color: transparent;
        color: {TEXT_MUTED};
        border: none;
        border-left: 3px solid transparent;
        padding: 10px 16px;
        text-align: left;
        font-size: 13px;
    }}
    QPushButton#sidebarButton:hover {{
        background-color: {BG_LIGHT};
        color: {TEXT};
    }}
    QPushButton#sidebarButton:checked {{
        background-color: {SIDEBAR_ACTIVE};
        color: {TEXT};
        border-left: 3px solid {ACCENT};
        font-weight: 600;
    }}

    /* ============ PANNELLI ============ */
    QWidget#contentPanel {{
        background-color: {BG_DARK};
    }}

    QFrame#card {{
        background-color: {BG_LIGHT};
        border: 1px solid {BORDER};
        border-radius: 11px;
    }}

    QFrame#dropZone {{
        background-color: {BG_LIGHT};
        border: 1.5px dashed {BORDER_LIGHT};
        border-radius: 12px;
    }}
    QFrame#dropZone[active="true"] {{
        border: 1.5px dashed {ACCENT};
        background-color: {BG_HOVER};
    }}
    QFrame#dropZone[loaded="true"] {{
        border: 1.5px solid {BORDER_LIGHT};
        background-color: {BG_LIGHT};
    }}
    QFrame#dropZone[error="true"] {{
        border: 1.5px dashed {ERROR};
        background-color: {BG_LIGHT};
    }}

    /* ============ BANNER DIPENDENZE ============ */
    QFrame#depsBanner {{
        background-color: rgba(180, 120, 0, 30);
        border: 1px solid #9a6a00;
        border-radius: 8px;
        padding: 4px;
    }}
    QFrame#depsBanner[severity="error"] {{
        background-color: rgba(180, 40, 40, 30);
        border: 1px solid #a03030;
    }}

    /* ============ LABEL ============ */
    QLabel#homeEyebrow {{
        font-size: 11px;
        font-weight: 600;
        color: {TEXT_MUTED};
        letter-spacing: 1.5px;
    }}
    QLabel#homeTitle {{
        font-size: 28px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.5px;
    }}
    QLabel#homeSub {{
        font-size: 14px;
        color: {TEXT_DIM};
        line-height: 1.5;
    }}
    QLabel#title {{
        font-size: 22px;
        font-weight: bold;
        color: {TEXT};
    }}
    QLabel#sectionTitle {{
        font-size: 15px;
        font-weight: bold;
        color: {TEXT};
    }}
    QLabel#settingsLabel {{
        font-size: 10px;
        font-weight: 600;
        color: {TEXT_MUTED};
        letter-spacing: 1px;
    }}
    QLabel#subtitle {{
        font-size: 11px;
        color: {TEXT_MUTED};
    }}
    QLabel#muted {{
        color: {TEXT_MUTED};
    }}
    QLabel#success {{
        color: {SUCCESS};
        font-weight: bold;
    }}
    QLabel#error {{
        color: {ERROR};
    }}

    /* ============ BOTTONI ============ */
    QPushButton {{
        background-color: {BG_HOVER};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: 7px;
        padding: 6px 14px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: #2a3040;
        border-color: #4a5168;
        color: #ffffff;
    }}
    QPushButton:pressed {{
        background-color: {BG_LIGHT};
        border-color: {BORDER_LIGHT};
        color: {TEXT_DIM};
    }}
    QPushButton:disabled {{
        color: {TEXT_FAINT};
        background-color: {BG_HOVER};
        border-color: {BORDER};
    }}

    QPushButton#primary {{
        background-color: {ACCENT};
        color: white;
        border: none;
        font-weight: 600;
        padding: 0 22px;
        font-size: 14px;
        border-radius: 9px;
        min-height: 44px;
    }}
    QPushButton#primary:hover {{
        background-color: {ACCENT_HOVER};
        color: white;
    }}
    QPushButton#primary:pressed {{
        background-color: {ACCENT_DIM};
    }}
    QPushButton#primary:disabled {{
        background-color: {BG_LIGHT};
        color: {TEXT_MUTED};
        border: 1px solid {BORDER_LIGHT};
    }}

    QPushButton#secondary {{
        background-color: transparent;
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        font-weight: 500;
        font-size: 13px;
        border-radius: 9px;
        min-height: 44px;
        padding: 0 18px;
    }}
    QPushButton#secondary:hover {{
        background-color: {BG_HOVER};
        border-color: #4a5168;
        color: #ffffff;
    }}
    QPushButton#secondary:pressed {{
        background-color: {BG_LIGHT};
    }}

    QPushButton#danger {{
        background-color: transparent;
        color: #ffb6bd;
        border: 1px solid rgba(239,94,108,0.36);
        font-weight: 500;
        border-radius: 9px;
        min-height: 44px;
        padding: 0 18px;
    }}
    QPushButton#danger:hover {{
        background-color: rgba(239,94,108,0.15);
        border-color: rgba(239,94,108,0.6);
        color: #ffffff;
    }}
    QPushButton#danger:pressed {{
        background-color: rgba(239,94,108,0.08);
    }}

    /* ============ TOOLBAR BUTTONS ============ */
    QToolButton {{
        background-color: transparent;
        color: {TEXT_MUTED};
        border: none;
        border-radius: 5px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    QToolButton:hover {{
        background-color: {BG_HOVER};
        color: {TEXT};
    }}
    QToolButton:pressed {{
        background-color: {BG_LIGHT};
        color: {TEXT_DIM};
    }}
    QToolButton:checked {{
        background-color: {ACCENT_SOFT};
        color: {ACCENT};
    }}
    QToolButton:checked:hover {{
        background-color: {ACCENT_SOFT2};
        color: {ACCENT_HOVER};
    }}

    /* ============ INPUT ============ */
    QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        background-color: {BG_HOVER};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: 7px;
        padding: 6px 10px;
        selection-background-color: {ACCENT_DIM};
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: #3a404e;
        background-color: #232832;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {ACCENT};
        background-color: #23283a;
    }}

    QComboBox {{
        background-color: {BG_HOVER};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: 7px;
        padding: 5px 10px;
        font-size: 13px;
        font-weight: 500;
        min-height: 32px;
        selection-background-color: {ACCENT_DIM};
    }}
    QComboBox:hover {{
        background-color: #23283a;
        border-color: #4a5168;
        color: #ffffff;
    }}
    QComboBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_MUTED};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_LIGHT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 7px;
        selection-background-color: {ACCENT_DIM};
        padding: 4px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {BG_HOVER};
        color: #ffffff;
    }}

    /* ============ CHECKBOX ============ */
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
        font-size: 13px;
        font-weight: 500;
    }}
    QCheckBox:hover {{
        color: #ffffff;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {BORDER_LIGHT};
        border-radius: 4px;
        background-color: {BG_HOVER};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
        background-color: {ACCENT_SOFT};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    /* ============ PROGRESS BAR ============ */
    QProgressBar {{
        background-color: {BG_HOVER};
        border: none;
        border-radius: 3px;
        min-height: 5px;
        max-height: 5px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_DIM}, stop:1 {ACCENT_HOVER});
        border-radius: 3px;
    }}

    /* ============ DOCK / SPLITTER ============ */
    QDockWidget {{
        color: {TEXT};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{
        background-color: {BG_MEDIUM};
        padding: 6px 12px;
        border-bottom: 1px solid {BORDER};
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: {TEXT_MUTED};
    }}

    QSplitter::handle {{
        background-color: {SEPARATOR};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* ============ SCROLLBAR ============ */
    QScrollBar:vertical {{
        background: {BG_DARK};
        width: 8px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 4px;
        min-height: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {TEXT_MUTED};
    }}
    QScrollBar::handle:vertical:pressed {{
        background: {TEXT_DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {BG_DARK};
        height: 8px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER};
        border-radius: 4px;
        min-width: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {TEXT_MUTED};
    }}
    QScrollBar::handle:horizontal:pressed {{
        background: {TEXT_DIM};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ============ MENU BAR ============ */
    QMenuBar {{
        background-color: {BG_MEDIUM};
        color: {TEXT};
        border-bottom: 1px solid {SEPARATOR};
        padding: 2px;
        font-size: 13px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 10px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background: {BG_HOVER};
        color: #ffffff;
    }}
    QMenuBar::item:pressed {{
        background: {BG_LIGHT};
    }}
    QMenu {{
        background-color: {BG_LIGHT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px;
        border-radius: 5px;
        font-size: 13px;
    }}
    QMenu::item:selected {{
        background-color: {ACCENT_DIM};
        color: white;
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 0;
    }}

    /* ============ STATUS BAR ============ */
    QStatusBar {{
        background-color: {BG_MEDIUM};
        color: {TEXT_MUTED};
        border-top: 1px solid {SEPARATOR};
        font-size: 11px;
        font-family: "SF Mono", "Menlo", monospace;
    }}
    QStatusBar::item {{
        border: none;
    }}

    /* ============ TABLE VIEW ============ */
    QTableView {{
        background-color: {BG_DARK};
        alternate-background-color: {BG_MEDIUM};
        color: {TEXT};
        gridline-color: {BORDER};
        border: none;
        selection-background-color: rgba(91,140,255,0.18);
        selection-color: {TEXT};
    }}
    QTableView::item {{
        padding: 8px 6px;
        border: none;
        border-bottom: 1px solid {BORDER};
    }}
    QTableView::item:hover {{
        background-color: rgba(255,255,255,0.04);
    }}
    QTableView::item:selected {{
        background-color: rgba(91,140,255,0.18);
        border-left: 2px solid {ACCENT};
    }}
    QTableView::item:selected:hover {{
        background-color: rgba(91,140,255,0.26);
    }}
    QHeaderView::section:hover {{
        background-color: {BG_HOVER};
        color: {TEXT};
    }}
    QHeaderView::section {{
        background-color: {BG_MEDIUM};
        color: {TEXT_MUTED};
        padding: 6px 8px;
        border: none;
        border-right: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        font-weight: 600;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-family: "SF Mono", "Menlo", monospace;
    }}

    /* ============ TOOLTIP ============ */
    QToolTip {{
        background-color: {BG_LIGHT};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: 6px;
        padding: 5px 9px;
        font-size: 12px;
    }}
    """
