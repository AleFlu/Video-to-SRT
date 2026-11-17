"""
theme.py — Sistema tema "Bianco e nero" — design system Video→SRT v2.

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

import logging

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen

import platform_support

logger = logging.getLogger(__name__)


# ── Palette: token "Bianco e nero" ──────────────────────────────────────────
# Stesse chiavi per dark e light. Il colore compare SOLO per errori e avvisi:
# accento, selezione e azione principale usano il contrasto (bianco su scuro,
# quasi nero su chiaro). I soft sono pre-calcolati: Qt QSS non ha color-mix().
#
# Nomi "nuovi" (dal mockup): panel, raise, label, sel, wave.
# Nomi storici mantenuti: surface/card = panel, card_2 = raise, inset = bg,
# muted = label, acc_fill* = acc*, wave_fill = wave.

PALETTE_DARK = {
    # superfici
    "bg":        "#141414",   # fondo: area di lavoro, campi
    "panel":     "#1b1b1b",   # barre, ispettore, log
    "raise":     "#262626",   # controllo premuto, blocchi
    "surface":   "#1b1b1b",   # = panel
    "card":      "#1b1b1b",   # = panel (niente card sollevate)
    "card_2":    "#262626",   # = raise
    "inset":     "#141414",   # = bg (campi incassati)
    # linee
    "line":      "#303030",
    "line_2":    "#3d3d3d",   # bordo in hover
    "card_border": "#303030",
    # testo
    "text":      "#f2f2f2",
    "dim":       "#a6a6a6",   # secondario
    "label":     "#8c8c8c",   # etichette (11-12 px)
    "muted":     "#8c8c8c",   # = label
    "faint":     "#5c5c5c",   # solo decorazioni / testo disabilitato
    # accento monocromatico
    "acc":       "#ffffff",
    "acc_h":     "#e6e6e6",
    "acc_d":     "#cccccc",
    "acc_ink":   "#141414",   # testo su accento
    "acc_fill":   "#ffffff",
    "acc_fill_h": "#e6e6e6",
    "acc_fill_d": "#cccccc",
    "focus":     "#ffffff",
    "acc_soft":  "rgba(255,255,255,0.08)",
    "acc_soft_2":"rgba(255,255,255,0.14)",
    "sel":       "#2e2e2e",   # riga selezionata
    # severity: unico colore dell'interfaccia (sempre con icona o parola)
    "ok":        "#f2f2f2",   # neutro: niente verde
    "warn":      "#f0a63c",
    "err":       "#f2706b",
    "ok_soft":   "rgba(255,255,255,0.08)",
    "warn_soft": "rgba(240,166,60,0.12)",
    "err_soft":  "rgba(242,112,107,0.14)",
    # effetti / extra
    "lift":      "rgba(255,255,255,0.03)",
    "wave":      "#5c5c5c",   # forma d'onda
    "wave_bg":   "#141414",
    "wave_fill": "#5c5c5c",
    "playhead":  "#ffffff",
    "wave_outline": "rgba(255,255,255,0.24)",
    # tabella sottotitoli (provider colori di SubtitleTableModel)
    "row_error_bg":   "rgba(242,112,107,0.10)",
    "row_warning_bg": "rgba(240,166,60,0.08)",
    # anteprima video (invarianti: il video resta su nero)
    "video_bg":   "#0b0b0c",
    "overlay_bg": "rgba(0,0,0,0.72)",
    "overlay_fg": "#ffffff",
    "knob":      "#141414",   # pallino dell'interruttore acceso (su acc)
}

PALETTE_LIGHT = {
    "bg":        "#f4f4f4",
    "panel":     "#ffffff",
    "raise":     "#e8e8e8",
    "surface":   "#ffffff",
    "card":      "#ffffff",
    "card_2":    "#e8e8e8",
    "inset":     "#f4f4f4",
    "line":      "#d4d4d4",
    "line_2":    "#bdbdbd",
    "card_border": "#d4d4d4",
    "text":      "#141414",
    "dim":       "#595959",
    "label":     "#6b6b6b",
    "muted":     "#6b6b6b",
    "faint":     "#a3a3a3",   # solo decorazioni / testo disabilitato
    "acc":       "#141414",
    "acc_h":     "#2e2e2e",
    "acc_d":     "#444444",
    "acc_ink":   "#ffffff",
    "acc_fill":   "#141414",
    "acc_fill_h": "#2e2e2e",
    "acc_fill_d": "#444444",
    "focus":     "#141414",
    "acc_soft":  "rgba(20,20,20,0.06)",
    "acc_soft_2":"rgba(20,20,20,0.12)",
    "sel":       "#e4e4e4",
    "ok":        "#141414",
    "warn":      "#8f5400",
    "err":       "#b92f2a",
    "ok_soft":   "rgba(20,20,20,0.06)",
    "warn_soft": "rgba(143,84,0,0.10)",
    "err_soft":  "rgba(185,47,42,0.10)",
    "lift":      "rgba(20,20,20,0.03)",
    "wave":      "#b3b3b3",
    "wave_bg":   "#f4f4f4",
    "wave_fill": "#b3b3b3",
    "playhead":  "#141414",
    "wave_outline": "rgba(20,20,20,0.28)",
    "row_error_bg":   "rgba(185,47,42,0.08)",
    "row_warning_bg": "rgba(143,84,0,0.07)",
    "video_bg":   "#0b0b0c",
    "overlay_bg": "rgba(0,0,0,0.72)",
    "overlay_fg": "#ffffff",
    "knob":      "#ffffff",
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


def qcolor(name: str, theme: str | None = None):
    """
    Token → QColor. Gestisce anche i valori "rgba(r,g,b,a)" (alpha 0..1), che il
    costruttore di QColor non interpreta.
    """
    from PySide6.QtGui import QColor
    value = c(name, theme).strip()
    if value == "transparent":
        return QColor(0, 0, 0, 0)
    if value.startswith("rgba(") and value.endswith(")"):
        parts = [p.strip() for p in value[5:-1].split(",")]
        r, g, b = (int(float(x)) for x in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return QColor(r, g, b, max(0, min(255, round(a * 255))))
    return QColor(value)


def build_palette(theme: str | None = None):
    """QPalette derivata dai token: copre i widget/dialog nativi non raggiunti dal QSS."""
    from PySide6.QtGui import QPalette
    pal = QPalette()
    q = lambda n: qcolor(n, theme)  # noqa: E731
    roles = {
        QPalette.Window: "bg",
        QPalette.WindowText: "text",
        QPalette.Base: "bg",
        QPalette.AlternateBase: "panel",
        QPalette.Text: "text",
        QPalette.Button: "raise",
        QPalette.ButtonText: "text",
        QPalette.ToolTipBase: "raise",
        QPalette.ToolTipText: "text",
        QPalette.PlaceholderText: "muted",
        QPalette.Highlight: "acc_fill",
        QPalette.HighlightedText: "acc_ink",
        QPalette.Link: "text",
        QPalette.BrightText: "err",
    }
    for role, token in roles.items():
        pal.setColor(role, q(token))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, q("faint"))
    return pal


def apply_theme(app, name: str):
    """
    Imposta il tema, applica QPalette + QSS globale a `app` e notifica i widget
    con stile inline (theme_changed).
    """
    set_theme(name)
    app.setPalette(build_palette(name))
    app.setStyleSheet(build_stylesheet(name))
    MANAGER.theme_changed.emit(name)


def toggle_theme(app=None) -> str:
    """Passa all'altro tema, lo applica e lo salva nelle preferenze. Ritorna il nuovo nome."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    new = "light" if _current == "dark" else "dark"
    apply_theme(app or QApplication.instance(), new)
    QSettings("VideoSRT", "v2").setValue("theme", new)
    return new


def focus_rule(selector: str, radius: int | None = None) -> str:
    """
    Regola QSS per l'anello di focus da tastiera. Da aggiungere agli stylesheet
    inline (che prevalgono sul QSS globale e ne nasconderebbero il focus).
    """
    rad = f" border-radius: {radius}px;" if radius is not None else ""
    return f"{selector}:focus {{ border: 1px solid {c('focus')};{rad} }}"


# ── Font ─────────────────────────────────────────────────────────────────────
FONT_UI   = platform_support.font_stack_ui()
FONT_MONO = platform_support.font_stack_mono()


# ── Chevron dei menu a tendina ────────────────────────────────────────────────
# Il trucco CSS del triangolo con i bordi non è renderizzato da Qt (appare un
# quadratino): la freccia è un piccolo PNG (1x + @2x per HiDPI) disegnato con
# QPainter nel colore "muted" del tema e salvato nella cache dell'app.

_CHEVRON_SIZE = 10
_CHEVRON_CACHE: dict = {}


def _draw_chevron(path, color, scale: int) -> bool:
    size = _CHEVRON_SIZE * scale
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(color)
        pen.setWidthF(1.6 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        k = scale
        p.drawPolyline([QPointF(1.8 * k, 3.4 * k), QPointF(5.0 * k, 6.6 * k),
                        QPointF(8.2 * k, 3.4 * k)])
    finally:
        p.end()
    return img.save(str(path), "PNG")


def chevron_url(theme: str | None = None) -> str | None:
    """
    Percorso (barre normali, pronto per ``url(...)`` del QSS) del chevron per il tema,
    generato al volo. None se il file non si può scrivere: il QSS toglie la freccia.
    """
    name = theme or _current
    color = qcolor("muted", name)
    try:
        folder = platform_support.app_cache_dir() / "icons"
        key = (str(folder), name, color.rgba())
        cached = _CHEVRON_CACHE.get(key)
        if cached is not None and folder.joinpath(cached).exists():
            return (folder / cached).as_posix()
        folder.mkdir(parents=True, exist_ok=True)
        fname = f"chevron-{name}-{color.rgba():08x}.png"
        ok1 = _draw_chevron(folder / fname, color, 1)
        ok2 = _draw_chevron(folder / fname.replace(".png", "@2x.png"), color, 2)
        if not (ok1 and ok2):
            return None
        _CHEVRON_CACHE[key] = fname
        return (folder / fname).as_posix()
    except OSError:
        logger.warning("Chevron dei menu non scrivibile: freccia omessa", exc_info=True)
        return None


def combo_arrow_rule(theme: str | None = None) -> str:
    """Regola QSS ``QComboBox::down-arrow`` (chevron PNG, o nessuna immagine se non disponibile)."""
    url = chevron_url(theme)
    image = f"url({url})" if url else "none"
    return f"QComboBox::down-arrow {{ image: {image}; width: 10px; height: 10px; margin-right: 8px; }}"


def check_url(theme: str | None = None) -> str | None:
    """
    Percorso del segno di spunta (PNG, colore ``acc_ink``) per l'indicatore delle
    checkbox selezionate, generato nella cache come il chevron. None se non scrivibile.
    """
    from ui import icons
    name = theme or _current
    color = qcolor("acc_ink", name)
    try:
        folder = platform_support.app_cache_dir() / "icons"
        folder.mkdir(parents=True, exist_ok=True)
        fname = f"check-{name}-{color.rgba():08x}.png"
        ok1 = icons.pixmap("check", color, 12, 1.0).save(str(folder / fname), "PNG")
        ok2 = icons.pixmap("check", color, 12, 2.0).save(
            str(folder / fname.replace(".png", "@2x.png")), "PNG")
        return (folder / fname).as_posix() if ok1 and ok2 else None
    except OSError:
        logger.warning("Segno di spunta non scrivibile: omesso", exc_info=True)
        return None


# ── Stylesheet globale ────────────────────────────────────────────────────────

def build_stylesheet(theme: str | None = None) -> str:
    """
    QSS Qt globale per il tema indicato (o corrente).

    Forma: raggio 4 px sui controlli, 0 su pannelli e righe, linee da 1 px,
    nessuna sfumatura, nessuna ombra, nessuna etichetta in maiuscolo.
    """
    t = tokens(theme)

    BG      = t["bg"]
    PANEL   = t["panel"]
    RAISE   = t["raise"]
    LINE    = t["line"]
    LINE_2  = t["line_2"]
    SEL     = t["sel"]
    TEXT    = t["text"]
    DIM     = t["dim"]
    LABEL   = t["label"]
    FAINT   = t["faint"]
    ACC     = t["acc"]
    ACC_H   = t["acc_h"]
    ACC_D   = t["acc_d"]
    INK     = t["acc_ink"]
    ERR     = t["err"]
    ERR_SOFT = t["err_soft"]
    FOCUS   = t["focus"]
    FONT_SANS = FONT_UI
    FONT_MONO_ = FONT_MONO
    check = check_url(theme)
    check_img = f"image: url({check});" if check else ""

    return f"""
    /* ============ GLOBAL ============ */
    QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: {FONT_SANS};
        font-size: 13px;
    }}

    QMainWindow {{
        background-color: {BG};
    }}

    /* ============ PANNELLI (linee, mai card con ombra) ============ */
    QWidget#contentPanel {{
        background-color: {BG};
    }}

    QFrame#card {{
        background-color: {PANEL};
        border: 1px solid {LINE};
        border-radius: 0;
    }}

    QDialog {{
        background-color: {BG};
    }}

    /* ============ LABEL ============ */
    QLabel#homeEyebrow {{
        font-size: 11px;
        font-weight: 500;
        color: {LABEL};
    }}
    QLabel#homeTitle {{
        font-size: 22px;
        font-weight: 500;
        color: {TEXT};
    }}
    QLabel#homeSub {{
        font-size: 13px;
        color: {DIM};
    }}
    QLabel#title {{
        font-size: 22px;
        font-weight: 500;
        color: {TEXT};
    }}
    QLabel#sectionTitle {{
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#settingsLabel {{
        font-size: 11px;
        font-weight: 500;
        color: {LABEL};
    }}
    QLabel#subtitle {{
        font-size: 11px;
        color: {LABEL};
    }}
    QLabel#muted {{
        color: {LABEL};
    }}
    QLabel#success {{
        color: {TEXT};
        font-weight: 600;
    }}
    QLabel#error {{
        color: {ERR};
    }}

    /* ============ BOTTONI ============ */
    QPushButton {{
        background-color: transparent;
        color: {TEXT};
        border: 1px solid {LINE};
        border-radius: 4px;
        padding: 0 12px;
        min-height: 28px;
        font-size: 13px;
        font-weight: 400;
    }}
    QPushButton:hover {{
        background-color: {RAISE};
        border-color: {LINE_2};
    }}
    QPushButton:pressed {{
        background-color: {RAISE};
        color: {DIM};
    }}
    QPushButton:disabled {{
        background-color: transparent;
        color: {FAINT};
        border-color: {LINE};
    }}

    QPushButton#primary {{
        background-color: {ACC};
        color: {INK};
        border: 1px solid {ACC};
        font-weight: 600;
        padding: 0 16px;
        font-size: 13px;
        min-height: 32px;
    }}
    QPushButton#primary:hover {{
        background-color: {ACC_H};
        border-color: {ACC_H};
        color: {INK};
    }}
    QPushButton#primary:pressed {{
        background-color: {ACC_D};
        border-color: {ACC_D};
        color: {INK};
    }}
    QPushButton#primary:disabled {{
        background-color: transparent;
        color: {FAINT};
        border: 1px solid {LINE};
    }}

    QPushButton#secondary {{
        background-color: transparent;
        color: {TEXT};
        border: 1px solid {LINE};
        font-weight: 400;
        min-height: 32px;
        padding: 0 14px;
    }}
    QPushButton#secondary:hover {{
        background-color: {RAISE};
        border-color: {LINE_2};
        color: {TEXT};
    }}
    QPushButton#secondary:pressed {{
        background-color: {RAISE};
    }}

    QPushButton#danger {{
        background-color: transparent;
        color: {ERR};
        border: 1px solid {ERR};
        font-weight: 400;
        min-height: 32px;
        padding: 0 14px;
    }}
    QPushButton#danger:hover {{
        background-color: {ERR_SOFT};
        color: {ERR};
    }}
    QPushButton#danger:pressed {{
        background-color: {ERR_SOFT};
    }}

    /* Interrompi / Torna alla Home (36 px): icona + testo a sinistra, l'indicazione Esc a destra */
    QPushButton#danger[stopButton="true"], QPushButton#primary[stopButton="true"] {{
        text-align: left;
        padding: 0 14px;
        min-height: 34px;
    }}
    /* Pulsante secondario compatto da 28 px (es. "Copia log") */
    QPushButton#secondary[compact="true"] {{
        min-height: 26px;
        padding: 0 10px;
    }}

    /* Toolbar / ghost: nessun bordo, hover = rialzo */
    QPushButton#ghost, QPushButton#toolbar {{
        background-color: transparent;
        color: {DIM};
        border: 1px solid transparent;
        padding: 0 9px;
    }}
    QPushButton#ghost:hover, QPushButton#toolbar:hover {{
        background-color: {RAISE};
        color: {TEXT};
        border-color: transparent;
    }}

    /* Anello di focus da tastiera (gli stili inline aggiungono theme.focus_rule) */
    QPushButton:focus, QToolButton:focus {{
        border: 1px solid {FOCUS};
    }}
    QCheckBox:focus {{
        color: {TEXT};
    }}
    QCheckBox::indicator:focus {{
        border: 1px solid {FOCUS};
    }}
    QSlider:focus, QTableView:focus {{
        border: 1px solid {FOCUS};
    }}

    /* ============ TOOLBAR BUTTONS ============ */
    QToolButton {{
        background-color: transparent;
        color: {DIM};
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px 9px;
        font-size: 13px;
    }}
    QToolButton:hover {{
        background-color: {RAISE};
        color: {TEXT};
    }}
    QToolButton:pressed {{
        background-color: {RAISE};
        color: {DIM};
    }}
    QToolButton:checked {{
        background-color: {RAISE};
        color: {TEXT};
    }}
    QToolButton:checked:hover {{
        background-color: {RAISE};
        color: {TEXT};
    }}
    QToolButton:disabled {{
        color: {FAINT};
    }}

    /* ============ CAMPI ============ */
    QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        background-color: {BG};
        color: {TEXT};
        border: 1px solid {LINE};
        border-radius: 4px;
        padding: 4px 8px;
        selection-background-color: {ACC};
        selection-color: {INK};
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        min-height: 20px;
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {LINE_2};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {FOCUS};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
    QTextEdit:disabled, QPlainTextEdit:disabled {{
        color: {FAINT};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0;
        border: none;
    }}

    QComboBox {{
        background-color: {BG};
        color: {TEXT};
        border: 1px solid {LINE};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 13px;
        min-height: 20px;
        selection-background-color: {SEL};
    }}
    QComboBox:hover {{
        border-color: {LINE_2};
        color: {TEXT};
    }}
    QComboBox:focus {{
        border: 1px solid {FOCUS};
    }}
    QComboBox:disabled {{
        color: {FAINT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    {combo_arrow_rule(theme)}
    QComboBox QAbstractItemView {{
        background-color: {PANEL};
        color: {TEXT};
        border: 1px solid {LINE_2};
        border-radius: 4px;
        selection-background-color: {SEL};
        selection-color: {TEXT};
        outline: none;
        padding: 2px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {RAISE};
        color: {TEXT};
    }}

    /* ============ CHECKBOX ============ */
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
        font-size: 13px;
    }}
    QCheckBox:hover {{
        color: {TEXT};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {LINE_2};
        border-radius: 3px;
        background-color: {BG};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACC};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACC};
        border-color: {ACC};
        {check_img}
    }}
    QCheckBox::indicator:checked:hover {{
        background-color: {ACC_H};
        border-color: {ACC_H};
    }}

    /* ============ PROGRESS BAR (4 px piatta) ============ */
    QProgressBar {{
        background-color: {RAISE};
        border: none;
        border-radius: 0;
        min-height: 4px;
        max-height: 4px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background-color: {ACC};
        border-radius: 0;
    }}

    /* ============ DOCK / SPLITTER ============ */
    QDockWidget {{
        color: {TEXT};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{
        background-color: {PANEL};
        padding: 6px 12px;
        border-bottom: 1px solid {LINE};
        font-weight: 600;
        font-size: 12px;
        color: {LABEL};
    }}

    QSplitter::handle {{
        background-color: {LINE};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* ============ SLIDER ============ */
    QSlider::groove:horizontal {{
        height: 4px;
        background: {LINE_2};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACC};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {ACC};
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal:disabled {{
        background: {FAINT};
    }}
    QSlider::sub-page:horizontal:disabled {{
        background: {LINE_2};
    }}

    /* ============ SCROLLBAR (sottile, neutra) ============ */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {LINE_2};
        border-radius: 2px;
        min-height: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {LABEL};
    }}
    QScrollBar::handle:vertical:pressed {{
        background: {DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {LINE_2};
        border-radius: 2px;
        min-width: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {LABEL};
    }}
    QScrollBar::handle:horizontal:pressed {{
        background: {DIM};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ============ MENU BAR / MENU ============ */
    QMenuBar {{
        background-color: {PANEL};
        color: {DIM};
        border-bottom: 1px solid {LINE};
        padding: 2px;
        font-size: 13px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 10px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background: {RAISE};
        color: {TEXT};
    }}
    QMenuBar::item:pressed {{
        background: {RAISE};
    }}
    QMenu {{
        background-color: {PANEL};
        color: {TEXT};
        border: 1px solid {LINE_2};
        border-radius: 4px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px;
        border-radius: 3px;
        font-size: 13px;
    }}
    QMenu::item:selected {{
        background-color: {RAISE};
        color: {TEXT};
    }}
    QMenu::item:disabled {{
        color: {FAINT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {LINE};
        margin: 4px 8px;
    }}

    /* ============ STATUS BAR ============ */
    QStatusBar {{
        background-color: {PANEL};
        color: {DIM};
        border-top: 1px solid {LINE};
        font-size: 11px;
        font-family: {FONT_MONO_};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QStatusBar QLabel {{
        background: transparent;
    }}

    /* ============ TABELLE (righe 34 px, intestazione 30 px) ============ */
    QTableView {{
        background-color: {BG};
        alternate-background-color: {BG};
        color: {TEXT};
        gridline-color: transparent;
        border: none;
        selection-background-color: {SEL};
        selection-color: {TEXT};
        outline: none;
    }}
    QTableView::item {{
        padding: 0 10px;
        border: none;
        border-bottom: 1px solid {LINE};
    }}
    QTableView::item:hover {{
        background-color: {t["lift"]};
    }}
    QTableView::item:selected {{
        background-color: {SEL};
        color: {TEXT};
    }}
    QTableView::item:selected:hover {{
        background-color: {SEL};
    }}
    QHeaderView {{
        background-color: {BG};
    }}
    QHeaderView::section {{
        background-color: {BG};
        color: {LABEL};
        padding: 0 10px;
        min-height: 30px;
        max-height: 30px;
        border: none;
        border-bottom: 1px solid {LINE};
        font-weight: 500;
        font-size: 11px;
    }}
    QHeaderView::section:hover {{
        background-color: {PANEL};
        color: {TEXT};
    }}

    /* ============ TOOLTIP ============ */
    QToolTip {{
        background-color: {RAISE};
        color: {TEXT};
        border: 1px solid {LINE_2};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    """


# ── Alias modulo-livello (retro-compatibilità — puntano al tema scuro) ─────────
# Deprecati: preferire theme.c("token"). Mantenuti per non rompere import esistenti.

BG_DARK       = PALETTE_DARK["bg"]
BG_MEDIUM     = PALETTE_DARK["panel"]
BG_LIGHT      = PALETTE_DARK["card"]
BG_HOVER      = PALETTE_DARK["raise"]
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
SIDEBAR_BG    = PALETTE_DARK["bg"]
SIDEBAR_ACTIVE= PALETTE_DARK["card"]
BG_PANEL      = PALETTE_DARK["panel"]
BG_TIMELINE   = PALETTE_DARK["bg"]
SEPARATOR     = PALETTE_DARK["line"]
