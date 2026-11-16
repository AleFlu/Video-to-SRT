"""Test di platform_support e della sua adozione nel codice dell'app."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

import platform_support as ps

APP_DIR = Path(__file__).resolve().parent.parent


def test_shortcut_label_mac(monkeypatch):
    monkeypatch.setattr(ps, "IS_MAC", True)
    assert ps.shortcut_label("Ctrl+Shift+T") == "⌘⇧T"
    assert ps.shortcut_label("Ctrl+Alt+F") == "⌘⌥F"
    assert ps.shortcut_label("Ctrl+Return") == "⌘↵"


def test_shortcut_label_non_mac(monkeypatch):
    monkeypatch.setattr(ps, "IS_MAC", False)
    assert ps.shortcut_label("Ctrl+Shift+T") == "Ctrl+Shift+T"


def test_fullscreen_shortcut(monkeypatch):
    monkeypatch.setattr(ps, "IS_MAC", True)
    assert ps.fullscreen_shortcut() == "Meta+Ctrl+F"
    monkeypatch.setattr(ps, "IS_MAC", False)
    assert ps.fullscreen_shortcut() == "F11"


def test_app_cache_dir_creates_dir():
    d = ps.app_cache_dir()
    assert d.is_dir()


def test_app_cache_dir_fallback(monkeypatch, tmp_path):
    """Se la cartella preferita non è creabile si ripiega su tempdir."""
    real_mkdir = Path.mkdir
    calls = {"n": 0}

    def fake_mkdir(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("negato")
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    monkeypatch.setattr(ps.tempfile, "gettempdir", lambda: str(tmp_path))
    d = ps.app_cache_dir()
    assert d == tmp_path / "VideoSRT_cache"
    assert d.is_dir()


def test_cpu_threads_at_least_one():
    assert ps.cpu_threads() >= 1


def test_native_media_exts(monkeypatch):
    common = {".mp4", ".mov", ".m4a", ".m4v", ".mp3", ".wav", ".aac"}
    monkeypatch.setattr(ps, "IS_MAC", True)
    monkeypatch.setattr(ps, "IS_WIN", False)
    assert common | {".aiff"} == ps.native_media_exts()
    monkeypatch.setattr(ps, "IS_MAC", False)
    monkeypatch.setattr(ps, "IS_WIN", True)
    assert common | {".wma"} == ps.native_media_exts()
    monkeypatch.setattr(ps, "IS_WIN", False)
    assert common == ps.native_media_exts()


def test_legacy_cache_dirs(monkeypatch):
    monkeypatch.setattr(ps, "IS_MAC", True)
    assert ps.legacy_cache_dirs() == [Path.home() / ".cache" / "VideoSRT"]
    monkeypatch.setattr(ps, "IS_MAC", False)
    assert ps.legacy_cache_dirs() == []


def test_ffmpeg_name_and_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr(ps, "IS_WIN", False)
    assert ps.ffmpeg_executable_name() == "ffmpeg"
    assert ps.subprocess_kwargs() == {}
    monkeypatch.setattr(ps, "IS_WIN", True)
    assert ps.ffmpeg_executable_name() == "ffmpeg.exe"
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert ps.subprocess_kwargs() == {"creationflags": 0x08000000}


def test_reveal_windows_single_select_argument(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "IS_WIN", True)
    monkeypatch.setattr(ps, "IS_MAC", False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert ps.reveal_in_file_manager(r"C:\x\a b.srt") is True
    assert calls == [["explorer", r"/select,C:\x\a b.srt"]]


def test_reveal_windows_normalises_forward_slashes(monkeypatch):
    import ntpath
    calls = []
    monkeypatch.setattr(ps, "IS_WIN", True)
    monkeypatch.setattr(ps, "IS_MAC", False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(ps.os.path, "normpath", ntpath.normpath)   # come su Windows
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert ps.reveal_in_file_manager("C:/x/a b.srt") is True
    assert calls == [["explorer", r"/select,C:\x\a b.srt"]]


def test_reveal_mac_and_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "IS_WIN", False)
    monkeypatch.setattr(ps, "IS_MAC", True)
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert ps.reveal_in_file_manager("/a/b.srt") is True
    assert calls == [["open", "-R", "/a/b.srt"]]

    def boom(cmd, **kw):
        raise FileNotFoundError("nessun comando")

    monkeypatch.setattr(ps.subprocess, "run", boom)
    assert ps.reveal_in_file_manager("/a/b.srt") is False


def test_font_helpers_non_empty():
    assert ps.font_stack_ui() and ps.font_stack_mono()
    assert ps.ui_font_family() and ps.mono_font_family()


def test_mac_fonts_use_installed_families(monkeypatch):
    monkeypatch.setattr(ps, "IS_MAC", True)
    monkeypatch.setattr(ps, "IS_WIN", False)
    ui = ps.font_stack_ui()
    assert ui.startswith('"IBM Plex Sans", ".AppleSystemUIFont"')
    assert "SF Pro" not in ui
    assert ps.ui_font_family() == "IBM Plex Sans"
    assert ps.font_stack_mono().startswith('"IBM Plex Mono", "Menlo"')
    assert "SF Mono" not in ps.font_stack_mono()
    assert ps.mono_font_family() == "IBM Plex Mono"


@pytest.mark.parametrize("mac,win", [(True, False), (False, True), (False, False)])
def test_plex_first_in_every_stack(monkeypatch, mac, win):
    monkeypatch.setattr(ps, "IS_MAC", mac)
    monkeypatch.setattr(ps, "IS_WIN", win)
    assert ps.font_stack_ui().startswith('"IBM Plex Sans", "')
    assert ps.font_stack_mono().startswith('"IBM Plex Mono", "')
    assert ps.ui_font_family() == "IBM Plex Sans"
    assert ps.mono_font_family() == "IBM Plex Mono"


def test_app_icon_path(tmp_path):
    assert ps.app_icon_path(tmp_path) is None
    (tmp_path / "app_512.png").write_bytes(b"x")
    assert ps.app_icon_path(tmp_path) == tmp_path / "app_512.png"


def test_no_platform_checks_outside_platform_support():
    """Nessun sys.platform / platform.system() fuori da platform_support.py."""
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR)
        if rel.name == "platform_support.py" or rel.parts[0] == "tests":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                full = ast.unparse(node)
                if full in ("sys.platform", "platform.system"):
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


@pytest.mark.parametrize("mac,win", [(True, False), (False, True), (False, False)])
def test_font_stacks_have_no_generic_css_families(monkeypatch, mac, win):
    """Qt tratta 'sans-serif'/'monospace' come nomi letterali: "missing font family"."""
    monkeypatch.setattr(ps, "IS_MAC", mac)
    monkeypatch.setattr(ps, "IS_WIN", win)
    for stack in (ps.font_stack_ui(), ps.font_stack_mono()):
        for fam in stack.split(","):
            assert fam.strip().strip('"').lower() not in (
                "sans-serif", "serif", "monospace", "cursive", "fantasy")
            assert fam.strip().startswith('"')


def test_mac_font_stacks_exact(monkeypatch):
    monkeypatch.setattr(ps, "IS_MAC", True)
    monkeypatch.setattr(ps, "IS_WIN", False)
    assert ps.font_stack_ui() == '"IBM Plex Sans", ".AppleSystemUIFont", "Helvetica Neue"'
    assert ps.font_stack_mono() == '"IBM Plex Mono", "Menlo", "Monaco"'
