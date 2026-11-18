"""
test_settings_isolation.py — I test non toccano mai le preferenze reali dell'utente.

L'app salva le preferenze con ``QSettings("VideoSRT", "v2")`` (su macOS il plist
``~/Library/Preferences/com.videosrt.v2.plist``, su Windows il registro). ``conftest.py`` le
reindirizza su file INI in una cartella temporanea nuova per ogni test. Se l'isolamento si
rompe, questi test falliscono PRIMA di scrivere qualsiasi valore.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import PySide6.QtCore as QtCore
from PySide6.QtCore import QSettings

ORG, APP = "VideoSRT", "v2"
APP_DIR = Path(__file__).resolve().parent.parent

# Moduli che importano QSettings a livello di modulo; gli altri (theme, main) lo importano
# dentro le funzioni da PySide6.QtCore, coperto da `test_settings_constructors_use_temp_dir`.
_APP_MODULES = ("ui.main_window", "ui.home_widget", "ui.project_widget", "ui.workspace",
                "ui.subtitle_timeline")


def _inside(path: str, root: Path) -> bool:
    """True se `path` sta dentro `root` (link simbolici risolti, es. /var → /private/var)."""
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@pytest.fixture
def base(tmp_path_factory) -> Path:
    """Cartella temporanea di pytest per questa sessione: le preferenze devono stare qui."""
    return tmp_path_factory.getbasetemp()


def _assert_isolated(settings, base: Path) -> None:
    assert _inside(settings.fileName(), base), (
        f"QSettings scrive fuori dalla cartella dei test: {settings.fileName()}")


def test_settings_constructors_use_temp_dir(base):
    _assert_isolated(QSettings(ORG, APP), base)
    _assert_isolated(QtCore.QSettings(ORG, APP), base)    # import locale (theme, main)
    _assert_isolated(QSettings(QSettings.Scope.UserScope, ORG, APP), base)
    _assert_isolated(
        QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, ORG, APP), base)
    _assert_isolated(QSettings(), base)


def test_app_modules_use_isolated_settings(base):
    for name in _APP_MODULES:
        importlib.import_module(name)
    checked = []
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if not path or not hasattr(mod, "QSettings"):
            continue
        if not _inside(path, APP_DIR) or _inside(path, APP_DIR / "tests"):
            continue
        _assert_isolated(mod.QSettings(ORG, APP), base)
        checked.append(name)
    assert set(_APP_MODULES) <= set(checked)


def test_home_recent_file_stays_in_temp_dir(app, tmp_path, base):
    """Regressione: `HomeWidget._on_file_selected` aggiungeva il file dei test ai Recenti
    reali dell'utente."""
    from ui.home_widget import HomeWidget
    from ui.prefs import read_list
    _assert_isolated(QSettings(ORG, APP), base)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 10)
    HomeWidget()._on_file_selected(str(clip))
    settings = QSettings(ORG, APP)
    assert str(clip) in read_list(settings, "recent_files")
    assert Path(settings.fileName()).is_file()


def test_each_test_starts_with_empty_settings(base):
    """Ogni test ha preferenze nuove: niente Recenti, tema o geometria lasciati da altri test."""
    settings = QSettings(ORG, APP)
    _assert_isolated(settings, base)
    assert settings.allKeys() == []
