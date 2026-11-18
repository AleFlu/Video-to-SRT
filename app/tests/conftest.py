"""conftest.py — fixture condivise: QApplication unica, preferenze isolate e pulizia dei
top-level widget."""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import PySide6.QtCore as QtCore
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


# ── Preferenze isolate ────────────────────────────────────────────────────────
# L'app usa `QSettings("VideoSRT", "v2")`. Con organizzazione e applicazione Qt usa sempre il
# formato nativo (plist su macOS, registro su Windows) e ignora `setDefaultFormat` e
# `setPath`: senza intervento i test scriverebbero nelle preferenze reali dell'utente
# (Recenti, geometria della finestra, tema...). La classe viene quindi sostituita in
# `PySide6.QtCore` già qui, PRIMA che i test importino i moduli dell'app, che fanno
# `from PySide6.QtCore import QSettings` a livello di modulo: da quel momento ogni QSettings
# con organizzazione/applicazione è un file INI nella cartella impostata con `setPath`, che
# la fixture `isolated_settings_dir` rende nuova a ogni test.
# `test_settings_isolation.py` fallisce se l'isolamento si rompe.

_RealQSettings = QtCore.QSettings
_INI = _RealQSettings.Format.IniFormat
_NATIVE = _RealQSettings.Format.NativeFormat


class IsolatedSettings(_RealQSettings):
    """QSettings che, invece delle preferenze native, usa un file INI nella cartella dei test.

    I costruttori con organizzazione/applicazione passano al formato INI; quello con un
    percorso esplicito (`QSettings(file, formato)`) resta invariato; quelli senza nome usano
    il formato predefinito, impostato a INI da `_point_settings_to`.
    """

    def __init__(self, *args, **kwargs) -> None:
        args = list(args)
        if args and isinstance(args[0], _RealQSettings.Format):
            # (formato, ambito, organizzazione, ...): il formato nativo diventa INI
            if args[0] == _NATIVE:
                args[0] = _INI
        elif (args and isinstance(args[0], _RealQSettings.Scope)
              and len(args) > 1 and isinstance(args[1], str)):
            args.insert(0, _INI)                                  # (ambito, org, ...)
        elif args and isinstance(args[0], str) and not (
                len(args) > 1 and isinstance(args[1], _RealQSettings.Format)):
            args[0:0] = [_INI, _RealQSettings.Scope.UserScope]   # (org, app, ...)
        super().__init__(*args, **kwargs)


def _point_settings_to(folder: Path | str) -> None:
    """Fa salvare tutte le QSettings INI (e le predefinite) dentro `folder`."""
    _RealQSettings.setDefaultFormat(_INI)
    _RealQSettings.setPath(_INI, _RealQSettings.Scope.UserScope, str(folder))
    _RealQSettings.setPath(_INI, _RealQSettings.Scope.SystemScope,
                           os.path.join(str(folder), "system"))


QtCore.QSettings = IsolatedSettings
# Cartella di riserva per eventuali QSettings create durante la raccolta dei test, prima
# della prima fixture: mai nelle preferenze reali né in ~/.config.
_COLLECTION_SETTINGS_DIR = tempfile.mkdtemp(prefix="videosrt-test-settings-")
atexit.register(shutil.rmtree, _COLLECTION_SETTINGS_DIR, ignore_errors=True)
_point_settings_to(_COLLECTION_SETTINGS_DIR)


@pytest.fixture(autouse=True)
def isolated_settings_dir(tmp_path_factory) -> Path:
    """Ogni test parte da preferenze vuote, in una cartella temporanea tutta sua."""
    folder = tmp_path_factory.mktemp("qsettings")
    _point_settings_to(folder)
    return folder


@pytest.fixture(scope="session")
def app():
    """QApplication condivisa da tutti i test."""
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _cleanup_top_level_widgets():
    """Dopo ogni test chiude e distrugge i widget top-level rimasti (dialog senza parent
    inclusi), così non sopravvivono fino alla chiusura dell'interprete."""
    yield
    qapp = QApplication.instance()
    if qapp is None:
        return
    for w in QApplication.topLevelWidgets():
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:
            pass
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
