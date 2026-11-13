"""test_undo_commands.py — Test per core/undo_commands.py"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from core.subtitle_model import Subtitle
from core.subtitle_table_model import SubtitleTableModel, COL_START, COL_END, COL_TEXT
from core.undo_commands import (
    EditFieldCommand, DeleteSubtitleCommand, SplitSubtitleCommand,
    MergeWithNextCommand, ReplaceAllCommand,
)


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def model():
    return SubtitleTableModel([
        Subtitle(0, 2, "uno due tre quattro"),
        Subtitle(2, 4, "cinque"),
        Subtitle(4, 6, "sei"),
    ])


def _texts(m):
    return [s.text for s in m.subtitles()]


# ── EditFieldCommand ──────────────────────────────────────────────────────────

def test_text_edits_merge_into_single_undo(model):
    stack = QUndoStack()
    stack.push(EditFieldCommand(model, 0, COL_TEXT, "uno due tre quattro", "a", "Modifica"))
    stack.push(EditFieldCommand(model, 0, COL_TEXT, "a", "ab", "Modifica"))
    assert stack.count() == 1
    assert model.subtitle_at(0).text == "ab"
    stack.undo()
    assert model.subtitle_at(0).text == "uno due tre quattro"


def test_text_edits_on_different_rows_do_not_merge(model):
    stack = QUndoStack()
    stack.push(EditFieldCommand(model, 0, COL_TEXT, "uno due tre quattro", "x", "m"))
    stack.push(EditFieldCommand(model, 1, COL_TEXT, "cinque", "y", "m"))
    assert stack.count() == 2


@pytest.mark.parametrize("col,attr,old,new1,new2,val1", [
    (COL_START, "start", 0.0, "00:00.500", "00:01.000", 0.5),
    (COL_END, "end", 2.0, "00:03.000", "00:04.000", 3.0),
])
def test_time_edits_do_not_merge(model, col, attr, old, new1, new2, val1):
    stack = QUndoStack()
    stack.push(EditFieldCommand(model, 0, col, old, new1, "t"))
    stack.push(EditFieldCommand(model, 0, col, new1, new2, "t"))
    assert stack.count() == 2
    stack.undo()
    # Un solo passo indietro: resta applicato il primo valore
    assert getattr(model.subtitle_at(0), attr) == pytest.approx(val1)


def test_merge_with_rejects_non_text_directly(model):
    a = EditFieldCommand(model, 0, COL_START, 0.0, "1", "t")
    b = EditFieldCommand(model, 0, COL_START, "1", "2", "t")
    assert a.mergeWith(b) is False
    assert a.new_value == "1"


# ── Delete / Split / Merge / ReplaceAll ───────────────────────────────────────

def test_delete_undo_redo(model):
    stack = QUndoStack()
    stack.push(DeleteSubtitleCommand(model, [0, 2]))
    assert _texts(model) == ["cinque"]
    stack.undo()
    assert _texts(model) == ["uno due tre quattro", "cinque", "sei"]
    stack.redo()
    assert _texts(model) == ["cinque"]


def test_split_undo_redo(model):
    stack = QUndoStack()
    stack.push(SplitSubtitleCommand(model, 0, 7))
    assert model.rowCount() == 4
    left, right = model.subtitle_at(0), model.subtitle_at(1)
    assert left.end == pytest.approx(right.start)
    assert (left.text + " " + right.text) == "uno due tre quattro"
    stack.undo()
    assert model.rowCount() == 3 and model.subtitle_at(0).text == "uno due tre quattro"


def test_split_without_space_is_noop(model):
    stack = QUndoStack()
    stack.push(SplitSubtitleCommand(model, 1, 3))   # "cinque": nessuno spazio
    assert model.rowCount() == 3


def test_merge_with_next_undo_redo(model):
    stack = QUndoStack()
    stack.push(MergeWithNextCommand(model, 1))
    assert _texts(model)[1] == "cinque sei"
    assert model.subtitle_at(1).end == 6
    stack.undo()
    assert _texts(model) == ["uno due tre quattro", "cinque", "sei"]


def test_replace_all_single_undo(model):
    stack = QUndoStack()
    stack.push(ReplaceAllCommand(model, [(0, "uno due tre quattro", "A"), (2, "sei", "B")]))
    assert _texts(model) == ["A", "cinque", "B"]
    assert stack.count() == 1
    stack.undo()
    assert _texts(model) == ["uno due tre quattro", "cinque", "sei"]
