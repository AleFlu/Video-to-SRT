"""
theme.py — Sistema tema "Studio" — design system Video→SRT v2.

Supporta due temi (scuro/chiaro) commutabili a runtime.

Uso:
    from ui import theme
    theme.set_theme("dark")                       # imposta tema corrente
    app.setStyleSheet(theme.build_stylesheet())   # QSS globale del tema corrente
    theme.c("acc")                                # token colore corrente (hex/rgba)

I widget con stylesheet INLINE (non coperti dal QSS globale) devono:
    1. leggere i colori via theme.c("token") nei loro _apply_palette()
    2. connettersi a theme.MANAGER.theme_changed per ri-applicare lo stile

I nomi modulo-livello (ACCENT, BG_DARK, ...) restano come ALIAS del tema scuro
per retro-compatibilità: usarli solo dove il valore non deve cambiare col tema.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


# ── Palette: token "Studio" ─────────────────────────────────────────────────
# Stesse chiavi per dark e light. I soft (acc_soft, ecc.) sono pre-calcolati
# perché Qt QSS non supporta color-mix().

PALETTE_DARK = {
    # superfici
    "bg":        "#0d0e12",
    "surface":   "#14161c",
    "card":      "#1b1e27",
    "card_2":    "#252a35",
    "inset":     "#0a0b0e",
    # linee
    "line":      "rgba(255,255,255,0.075)",
    "line_2":    "rgba(255,255,255,0.12)",
    "card_border": "transparent",   # in dark le card non hanno bordo: staccano per sfondo
    # testo
    "text":      "#eef0f5",
    "dim":       "#aab0bd",
    "muted":     "#727885",
    "faint":     "#4c515d",
    # accento
    "acc":       "#5b8cff",
    "acc_h":     "#82a6ff",
    "acc_d":     "#3f6fd8",
    "acc_ink":   "#ffffff",
    "acc_soft":  "rgba(91,140,255,0.16)",
    "acc_soft_2":"rgba(91,140,255,0.26)",
    # severity (invarianti tra i temi)
    "ok":        "#38c990",
    "warn":      "#f0b15a",
    "err":       "#f0606f",
    "ok_soft":   "rgba(56,201,144,0.14)",
    "warn_soft": "rgba(240,177,90,0.15)",
    "err_soft":  "rgba(240,96,111,0.15)",
    # accento secondario (aurora blob 2)
    "purple":    "#a78bfa",
    # effetti / extra
    "lift":      "rgba(255,255,255,0.04)",
    "wave_bg":   "#101218",
    "wave_fill": "#436ac0",   # ≈ acc 60% + #2a3142
    "playhead":  "#ff5a5a",
    # sfondo "desktop" (gradiente radiale) — stop per QRadialGradient
    "desk_0":    "#1b2030",
    "desk_1":    "#0c0d11",
    "desk_2":    "#07080a",
}

PALETTE_LIGHT = {
    "bg":        "#eef0f4",
    "surface":   "#ffffff",
    "card":      "#ffffff",
    "card_2":    "#f3f5f9",
    "inset":     "#f6f8fb",
    "line":      "rgba(18,22,31,0.10)",
    "line_2":    "rgba(18,22,31,0.16)",
    "card_border": "rgba(18,22,31,0.08)",   # in light un bordo tenue dà definizione alle card bianche
    "text":      "#1a1d25",
    "dim":       "#545b69",
    "muted":     "#868d9b",
    "faint":     "#aeb4c0",
    "acc":       "#5b8cff",
    "acc_h":     "#82a6ff",
    "acc_d":     "#3f6fd8",
    "acc_ink":   "#ffffff",
    "acc_soft":  "rgba(91,140,255,0.12)",
    "acc_soft_2":"rgba(91,140,255,0.20)",
    "ok":        "#38c990",
    "warn":      "#f0b15a",
    "err":       "#f0606f",
    "ok_soft":   "rgba(56,201,144,0.14)",
    "warn_soft": "rgba(240,177,90,0.15)",
    "err_soft":  "rgba(240,96,111,0.15)",
    "purple":    "#a78bfa",
    "lift":      "rgba(18,22,31,0.03)",
    "wave_bg":   "#eef1f6",
    "wave_fill": "#9fb6e6",   # ≈ acc 45% + #c4cddd
    "playhead":  "#e23b3b",
    "desk_0":    "#dfe5f2",
    "desk_1":    "#e9ecf3",
    "desk_2":    "#e3e6ee",
}

PALETTES = {"dark": PALETTE_DARK, "light": PALETTE_LIGHT}


# ── Stato corrente + ThemeManager ───────────────────────────────────────────

_current = "dark"


class _ThemeManager(QObject):
    """Singleton: emette theme_changed(nome) quando il tema cambia.
    I widget con stile inline si connettono a questo segnale."""
    theme_changed = Signal(str)


MANAGER = _ThemeManager()


def get_theme() -> str:
    return _current


def set_theme(name: str):
    """Imposta il tema corrente (non applica lo stylesheet — vedi apply_theme)."""
    global _current
    if name not in PALETTES:
        name = "dark"
    _current = name


def tokens(theme: str | None = None) -> dict:
    return PALETTES.get(theme or _current, PALETTE_DARK)


def c(name: str, theme: str | None = None) -> str:
    """Ritorna il valore del token colore per il tema (corrente di default)."""
    return tokens(theme).get(name, "#ff00ff")


def apply_theme(app, name: str):
    """Imposta il tema, applica il QSS globale a `app` e notifica i widget inline."""
    set_theme(name)
    app.setStyleSheet(build_stylesheet(name))
    MANAGER.theme_changed.emit(name)


# ── Font ─────────────────────────────────────────────────────────────────────
FONT_UI   = '"SF Pro Display", "SF Pro Text", -apple-system, "Helvetica Neue", sans-serif'
FONT_MONO = '"SF Mono", "Menlo", "Roboto Mono", monospace'


# ── Stylesheet globale ────────────────────────────────────────────────────────

def build_stylesheet(theme: str | None = None) -> str:
    """QSS Qt globale per il tema indicato (o corrente)."""
    t = tokens(theme)

    BG_DARK      = t["bg"]
    BG_MEDIUM    = t["surface"]
    BG_LIGHT     = t["card"]
    BG_HOVER     = t["card_2"]
    INSET        = t["inset"]
    BORDER       = t["line"]
    BORDER_LIGHT = t["line_2"]
    TEXT         = t["text"]
    TEXT_DIM     = t["dim"]
    TEXT_MUTED   = t["muted"]
    TEXT_FAINT   = t["faint"]
    ACCENT       = t["acc"]
    ACCENT_HOVER = t["acc_h"]
    ACCENT_DIM   = t["acc_d"]
    ACCENT_INK   = t["acc_ink"]
    ACCENT_SOFT  = t["acc_soft"]
    ACCENT_SOFT2 = t["acc_soft_2"]
    SUCCESS      = t["ok"]
    WARNING      = t["warn"]
    ERROR        = t["err"]
    SEP          = t["line"]

    return f"""
    /* ============ GLOBAL ============ */
    QWidget {{
        background-color: {BG_DARK};
        color: {TEXT};
        font-family: {FONT_UI};
        font-size: 13px;
    }}

    QMainWindow {{
        background-color: {BG_DARK};
    }}

    /* ============ PANNELLI ============ */
    QWidget#contentPanel {{
        background-color: {BG_DARK};
    }}

    QFrame#card {{
        background-color: {BG_LIGHT};
        border: 1px solid {t["card_border"]};
        border-radius: 11px;
    }}

    /* ============ LABEL ============ */
    QLabel#homeEyebrow {{
        font-size: 11px;
        font-weight: 600;
        color: {TEXT_MUTED};
        letter-spacing: 1.6px;
    }}
    QLabel#homeTitle {{
        font-size: 30px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.6px;
    }}
    QLabel#homeSub {{
        font-size: 14px;
        color: {TEXT_DIM};
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
        border-radius: 8px;
        padding: 6px 14px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {BG_LIGHT};
        border-color: {BORDER_LIGHT};
        color: {TEXT};
    }}
    QPushButton:pressed {{
        background-color: {BG_HOVER};
        color: {TEXT_DIM};
    }}
    QPushButton:disabled {{
        color: {TEXT_FAINT};
        background-color: {BG_LIGHT};
        border-color: {BORDER};
    }}

    QPushButton#primary {{
        background-color: {ACCENT};
        color: {ACCENT_INK};
        border: none;
        font-weight: 600;
        padding: 0 22px;
        font-size: 14px;
        border-radius: 8px;
        min-height: 44px;
    }}
    QPushButton#primary:hover {{
        background-color: {ACCENT_HOVER};
        color: {ACCENT_INK};
    }}
    QPushButton#primary:pressed {{
        background-color: {ACCENT_DIM};
    }}
    QPushButton#primary:disabled {{
        background-color: {BG_LIGHT};
        color: {TEXT_MUTED};
        border: 1px solid {BORDER};
    }}

    QPushButton#secondary {{
        background-color: transparent;
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        font-weight: 500;
        font-size: 13px;
        border-radius: 8px;
        min-height: 44px;
        padding: 0 18px;
    }}
    QPushButton#secondary:hover {{
        background-color: {BG_HOVER};
        border-color: {BORDER_LIGHT};
        color: {TEXT};
    }}
    QPushButton#secondary:pressed {{
        background-color: {BG_LIGHT};
    }}

    QPushButton#danger {{
        background-color: transparent;
        color: {ERROR};
        border: 1px solid {t["err_soft"]};
        font-weight: 500;
        border-radius: 8px;
        min-height: 44px;
        padding: 0 18px;
    }}
    QPushButton#danger:hover {{
        background-color: {t["err_soft"]};
        color: {ERROR};
    }}

    /* ============ TOOLBAR BUTTONS ============ */
    QToolButton {{
        background-color: transparent;
        color: {TEXT_MUTED};
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 4px 9px;
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
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 10px;
        selection-background-color: {ACCENT_DIM};
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {BORDER_LIGHT};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {ACCENT};
    }}

    QComboBox {{
        background-color: {BG_HOVER};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 5px 10px;
        font-size: 13px;
        font-weight: 500;
        min-height: 32px;
        selection-background-color: {ACCENT_DIM};
    }}
    QComboBox:hover {{
        border-color: {BORDER_LIGHT};
        color: {TEXT};
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
        border: 1px solid {BORDER_LIGHT};
        border-radius: 8px;
        selection-background-color: {ACCENT_DIM};
        padding: 4px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {BG_HOVER};
        color: {TEXT};
    }}

    /* ============ CHECKBOX ============ */
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
        font-size: 13px;
        font-weight: 500;
    }}
    QCheckBox:hover {{
        color: {TEXT};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {BORDER_LIGHT};
        border-radius: 5px;
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
        min-height: 6px;
        max-height: 6px;
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
        background-color: {SEP};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* ============ SCROLLBAR ============ */
    QScrollBar:vertical {{
        background: transparent;
        width: 9px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_LIGHT};
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
        background: transparent;
        height: 9px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER_LIGHT};
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
        color: {TEXT_DIM};
        border-bottom: 1px solid {SEP};
        padding: 2px;
        font-size: 12.5px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 5px 11px;
        border-radius: 7px;
    }}
    QMenuBar::item:selected {{
        background: {BG_HOVER};
        color: {TEXT};
    }}
    QMenuBar::item:pressed {{
        background: {BG_LIGHT};
    }}
    QMenu {{
        background-color: {BG_LIGHT};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 24px;
        border-radius: 7px;
        font-size: 12.5px;
    }}
    QMenu::item:selected {{
        background-color: {ACCENT};
        color: {ACCENT_INK};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 5px 8px;
    }}

    /* ============ STATUS BAR ============ */
    QStatusBar {{
        background-color: {BG_MEDIUM};
        color: {TEXT_MUTED};
        border-top: 1px solid {SEP};
        font-size: 11px;
        font-family: {FONT_MONO};
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
        selection-background-color: {ACCENT_SOFT};
        selection-color: {TEXT};
    }}
    QTableView::item {{
        padding: 8px 6px;
        border: none;
        border-bottom: 1px solid {BORDER};
    }}
    QTableView::item:hover {{
        background-color: {t["lift"]};
    }}
    QTableView::item:selected {{
        background-color: {ACCENT_SOFT};
        border-left: 2px solid {ACCENT};
    }}
    QTableView::item:selected:hover {{
        background-color: {ACCENT_SOFT2};
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
        font-family: {FONT_MONO};
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


# ── AuroraMixin ────────────────────────────────────────────────────────────────

class AuroraMixin:
    """
    Mixin che dipinge lo sfondo "desktop" a gradiente radiale + due blob aurora
    animati (accento blu + viola), come il design Studio.
    Usare come primo parent: class MyWidget(AuroraMixin, QWidget).
    Chiamare self._aurora_init() in __init__ e self._aurora_paint(painter) in paintEvent.
    """

    AURORA_OPACITY = 1.0   # 0..1.4

    def _aurora_init(self):
        from PySide6.QtCore import QTimer
        self._aurora_t = 0.0
        self._aurora_timer = QTimer(self)
        self._aurora_timer.setInterval(32)
        self._aurora_timer.timeout.connect(self._aurora_tick)
        # Avviato/fermato da show/hideEvent: niente tick a 32ms su widget nascosti

    def showEvent(self, event):
        if hasattr(self, "_aurora_timer"):
            self._aurora_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        if hasattr(self, "_aurora_timer"):
            self._aurora_timer.stop()
        super().hideEvent(event)

    def _aurora_tick(self):
        self._aurora_t += 0.012
        self.update()

    def _aurora_paint(self, painter):
        import math
        from PySide6.QtGui import QRadialGradient, QColor
        from PySide6.QtCore import QPointF

        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        # sfondo "desktop": gradiente radiale dall'alto-destra
        desk = QRadialGradient(QPointF(w * 0.70, h * -0.10), max(w, h) * 1.3)
        desk.setColorAt(0.0,  QColor(c("desk_0")))
        desk.setColorAt(0.55, QColor(c("desk_1")))
        desk.setColorAt(1.0,  QColor(c("desk_2")))
        painter.fillRect(self.rect(), desk)

        op = self.AURORA_OPACITY
        acc = QColor(c("acc"))
        pur = QColor(c("purple"))

        # blob 1 — accento, in alto
        cx1 = w * (0.48 + 0.07 * math.sin(self._aurora_t))
        cy1 = h * (0.20 + 0.05 * math.cos(self._aurora_t * 0.7))
        g1 = QRadialGradient(QPointF(cx1, cy1), min(w, h) * 0.65)
        a1 = QColor(acc); a1.setAlpha(int(90 * op))
        g1.setColorAt(0.0, a1)
        a1b = QColor(acc); a1b.setAlpha(0)
        g1.setColorAt(1.0, a1b)
        painter.fillRect(self.rect(), g1)

        # blob 2 — viola/accento, in basso-destra
        cx2 = w * (0.80 - 0.06 * math.sin(self._aurora_t * 0.8))
        cy2 = h * (0.92 - 0.04 * math.cos(self._aurora_t))
        g2 = QRadialGradient(QPointF(cx2, cy2), min(w, h) * 0.55)
        a2 = QColor(pur); a2.setAlpha(int(64 * op))
        g2.setColorAt(0.0, a2)
        a2b = QColor(pur); a2b.setAlpha(0)
        g2.setColorAt(1.0, a2b)
        painter.fillRect(self.rect(), g2)


# ── Alias modulo-livello (retro-compatibilità — puntano al tema scuro) ─────────
# Deprecati: preferire theme.c("token"). Mantenuti per non rompere import esistenti.

BG_DARK       = PALETTE_DARK["bg"]
BG_MEDIUM     = PALETTE_DARK["surface"]
BG_LIGHT      = PALETTE_DARK["card"]
BG_HOVER      = PALETTE_DARK["card_2"]
BORDER        = PALETTE_DARK["line"]
BORDER_LIGHT  = PALETTE_DARK["line_2"]
TEXT          = PALETTE_DARK["text"]
TEXT_DIM      = PALETTE_DARK["dim"]
TEXT_MUTED    = PALETTE_DARK["muted"]
TEXT_FAINT    = PALETTE_DARK["faint"]
ACCENT        = PALETTE_DARK["acc"]
ACCENT_HOVER  = PALETTE_DARK["acc_h"]
ACCENT_DIM    = PALETTE_DARK["acc_d"]
ACCENT_SOFT   = PALETTE_DARK["acc_soft"]
ACCENT_SOFT2  = PALETTE_DARK["acc_soft_2"]
SUCCESS       = PALETTE_DARK["ok"]
SUCCESS_SOFT  = PALETTE_DARK["ok_soft"]
WARNING       = PALETTE_DARK["warn"]
WARNING_SOFT  = PALETTE_DARK["warn_soft"]
ERROR         = PALETTE_DARK["err"]
ERROR_SOFT    = PALETTE_DARK["err_soft"]
PURPLE        = PALETTE_DARK["purple"]
SIDEBAR_BG    = PALETTE_DARK["bg"]
SIDEBAR_ACTIVE= PALETTE_DARK["card"]
BG_PANEL      = PALETTE_DARK["surface"]
BG_TIMELINE   = PALETTE_DARK["bg"]
SEPARATOR     = PALETTE_DARK["line"]
