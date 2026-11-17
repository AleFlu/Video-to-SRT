"""test_subtitle_table_model.py — Test per core/subtitle_table_model.py"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from core.subtitle_model import Subtitle
from core.subtitle_table_model import (
    SubtitleTableModel, parse_timestamp, format_timestamp,
    COL_INDEX, COL_START, COL_END, COL_CPS, COL_TEXT,
)


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication(sys.argv)


def _model(*subs):
    return SubtitleTableModel(list(subs))


# ── parse_timestamp ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("01:02:03.500", 3723.5),
    ("1:02,5", 62.5),
    ("00:10", 10.0),
    ("12.345", 12.345),
    ("12,345", 12.345),
])
def test_parse_timestamp_valid(text, expected):
    assert parse_timestamp(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["-1", "-0.5", "nan", "inf", "-inf", "abc", "", "1e999"])
def test_parse_timestamp_rejects_invalid(text):
    assert parse_timestamp(text) is None


def test_parse_timestamp_none():
    assert parse_timestamp(None) is None


def test_format_timestamp_roundtrip():
    assert parse_timestamp(format_timestamp(3723.5)) == pytest.approx(3723.5)


def test_unused_ts_regex_removed():
    import core.subtitle_table_model as m
    assert not hasattr(m, "_TS_RE")


# ── Costanti condivise ────────────────────────────────────────────────────────

def test_thresholds_come_from_constants():
    import core.constants as c
    import core.subtitle_table_model as m
    assert c.WARN_CPS == 17.0
    assert m.MAX_CPS is c.MAX_CPS
    assert m.WARN_CPS is c.WARN_CPS


# ── Codici di problema ────────────────────────────────────────────────────────

def test_issue_codes_all_kinds():
    m = _model(
        Subtitle(0, 0.2, "x" * 100),       # too_short + too_fast
        Subtitle(0.1, 3.0, "ok ok"),       # overlap con il precedente? no: sul 1°
        Subtitle(5, 4, ""),                # end_before_start + empty
    )
    assert m.row_issue_codes(0) == ["too_short", "too_fast", "overlap"]
    assert m.row_issue_codes(1) == []
    assert m.row_issue_codes(2) == ["end_before_start", "empty"]
    assert m.row_issue_codes(99) == []


def test_severity_from_codes():
    m = _model(
        Subtitle(0, 0.3, "ciao"),                 # solo too_short -> warning
        Subtitle(1, 3, "x" * 80),                 # too_fast -> warning
        Subtitle(4, 6, "ok"),                     # ok
        Subtitle(7, 9, "a"), Subtitle(8, 10, "b"),  # overlap -> error
        Subtitle(11, 12, ""),                     # empty -> error
    )
    assert m.row_severity(0) == "warning"
    assert m.row_severity(1) == "warning"
    assert m.row_severity(2) == "ok"
    assert m.row_severity(3) == "error"
    assert m.row_severity(5) == "error"


def test_row_issues_messages_unchanged():
    m = _model(Subtitle(5, 4, ""))
    assert m.row_issues(0) == ["La fine precede o coincide con l'inizio", "Testo vuoto"]
    m = _model(Subtitle(0, 0.3, "ciao"))
    assert m.row_issues(0) == ["Durata troppo breve (0.30s < 0.833s)"]
    m = _model(Subtitle(0, 1, "x" * 30))
    assert m.row_issues(0) == ["Troppo veloce (30.0 CPS, max 20)"]
    m = _model(Subtitle(0, 2, "a"), Subtitle(1, 3, "b"))
    assert m.row_issues(0) == ["Overlap con il sottotitolo successivo"]


def test_severity_does_not_depend_on_message_text(monkeypatch):
    # Un messaggio con "vuoto"/"Overlap" nel testo non deve cambiare la severità
    m = _model(Subtitle(0, 0.3, "Overlap precede vuoto"))
    assert m.row_severity(0) == "warning"


# ── Colori ────────────────────────────────────────────────────────────────────

def _bg(m, row):
    return m.data(m.index(row, COL_TEXT), Qt.BackgroundRole)


def _fg(m, row, col):
    return m.data(m.index(row, col), Qt.ForegroundRole)


def test_default_colors_unchanged():
    m = _model(Subtitle(5, 4, "x"), Subtitle(10, 10.4, "ciao"), Subtitle(20, 21, "x" * 25),
               Subtitle(30, 31, "x" * 18), Subtitle(40, 42, "ok"))
    assert _bg(m, 0).color() == QColor(231, 76, 60, 40)
    assert _bg(m, 1).color() == QColor(243, 156, 18, 30)
    assert _bg(m, 4) is None
    assert _fg(m, 0, COL_INDEX).color() == QColor("#6a6a7a")
    assert _fg(m, 2, COL_CPS).color() == QColor("#ff6b6b")
    assert _fg(m, 3, COL_CPS).color() == QColor("#f39c12")
    assert _fg(m, 4, COL_CPS) is None


def test_color_provider_is_used_and_names():
    m = _model(Subtitle(5, 4, "x"))
    asked = []

    def provider(name):
        asked.append(name)
        return QColor("#112233")

    m.set_color_provider(provider)
    assert _bg(m, 0).color() == QColor("#112233")
    assert _fg(m, 0, COL_INDEX).color() == QColor("#112233")
    assert "row_error_bg" in asked and "index_fg" in asked


def test_color_provider_none_result_gives_no_brush():
    m = _model(Subtitle(5, 4, "x"))
    m.set_color_provider(lambda name: None)
    assert _bg(m, 0) is None


def test_color_provider_reset_to_default():
    m = _model(Subtitle(5, 4, "x"))
    m.set_color_provider(lambda name: QColor("#000000"))
    m.set_color_provider(None)
    assert _bg(m, 0).color() == QColor(231, 76, 60, 40)


def test_set_color_provider_emits_data_changed():
    m = _model(Subtitle(0, 1, "a"), Subtitle(1, 2, "b"))
    hits = []
    m.dataChanged.connect(lambda *a: hits.append(a))
    m.set_color_provider(lambda n: None)
    assert hits


# ── Editing ───────────────────────────────────────────────────────────────────

def test_edit_text_preserves_internal_newlines():
    m = _model(Subtitle(0, 2, "a"))
    assert m.apply_edit_raw(0, COL_TEXT, "  riga uno\nriga due  ")
    assert m.subtitle_at(0).text == "riga uno\nriga due"


def test_edit_time_parse_and_clamp():
    m = _model(Subtitle(1, 2, "a"))
    assert m.apply_edit_raw(0, COL_START, "00:00.500")
    assert m.subtitle_at(0).start == pytest.approx(0.5)
    assert not m.apply_edit_raw(0, COL_START, "-3")
    assert not m.apply_edit_raw(0, COL_END, "nan")
    assert m.subtitle_at(0).start == pytest.approx(0.5)
    assert m.subtitle_at(0).end == 2


def test_setdata_uses_edit_handler():
    m = _model(Subtitle(0, 2, "a"))
    calls = []
    m.set_edit_handler(lambda r, c, v: calls.append((r, c, v)) or True)
    assert m.setData(m.index(0, COL_TEXT), "z")
    assert calls == [(0, COL_TEXT, "z")]
    assert m.subtitle_at(0).text == "a"


def test_insert_remove_and_modified_signal():
    m = _model(Subtitle(0, 1, "a"))
    n = []
    m.dataModified.connect(lambda: n.append(1))
    m.insert_subtitle(1, Subtitle(1, 2, "b"))
    m.remove_subtitle(0)
    assert m.rowCount() == 1 and m.subtitle_at(0).text == "b"
    assert len(n) == 2
