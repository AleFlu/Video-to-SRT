"""
test_self_test.py — Autotest dell'app compilata (``--self-test``) e controllo delle
librerie del bundle macOS (``packaging/macos/check_bundle.py``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "packaging" / "macos"))

import check_bundle  # noqa: E402
import self_test  # noqa: E402


def _ok():
    return "tutto bene"


def _boom():
    raise RuntimeError("ffmpeg non trovato")


def test_failed_required_check_fails_the_self_test(tmp_path):
    checks = [("uno", _ok, True), ("due", _boom, True), ("info", _boom, False)]
    results = self_test.run_checks(checks)
    assert results[0] == ("OK", "uno", "tutto bene")
    assert results[1][0] == "ERRORE" and "ffmpeg non trovato" in results[1][2]
    assert results[2][0] == "INFO"            # facoltativo: mai un errore
    text = self_test.report_text(results)
    assert "NON superato" in text and "ERRORE due" in text.replace("  ", " ")


def test_report_file_and_exit_code(tmp_path, monkeypatch):
    report = tmp_path / "autotest.txt"
    monkeypatch.setattr(self_test, "CHECKS", [("uno", _ok, True), ("info", _boom, False)])
    assert self_test.main(["app", "--self-test", "--self-test-report", str(report)]) == 0
    assert "Autotest superato" in report.read_text(encoding="utf-8")
    monkeypatch.setattr(self_test, "CHECKS", [("due", _boom, True)])
    assert self_test.main(["app", "--self-test"]) == 1


def test_main_runs_self_test_before_any_window(monkeypatch):
    """``main.py --self-test`` esce con l'esito dell'autotest senza aprire finestre."""
    import main as app_main
    called = []
    monkeypatch.setattr(sys, "argv", ["main.py", "--self-test"])
    monkeypatch.setattr(self_test, "main", lambda argv: called.append(argv) or 3)
    try:
        app_main.main()
    except SystemExit as e:
        assert e.code == 3
    assert called == [["main.py", "--self-test"]]


# ── Librerie fuori dal bundle (macOS) ────────────────────────────────────────

_OTOOL = """/x/Video-to-SRT.app/Contents/Frameworks/ffmpeg:
\t@rpath/libavdevice.62.dylib (compatibility version 62.0.0, current version 62.3.100)
\t/opt/homebrew/opt/x264/lib/libx264.165.dylib (compatibility version 0.0.0, current version 0.0.0)
\t/usr/local/lib/libfoo.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
\t/System/Library/Frameworks/VideoToolbox.framework/Versions/A/VideoToolbox (compatibility version 1.0.0, current version 1.0.0)
"""


def test_libraries_outside_the_bundle_are_reported():
    assert check_bundle.external_deps(_OTOOL) == [
        "/opt/homebrew/opt/x264/lib/libx264.165.dylib", "/usr/local/lib/libfoo.dylib"]


def test_macho_detection(tmp_path):
    lib = tmp_path / "lib.dylib"
    lib.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 32)
    txt = tmp_path / "file.txt"
    txt.write_text("ciao", encoding="utf-8")
    assert check_bundle.is_macho(lib) and not check_bundle.is_macho(txt)
