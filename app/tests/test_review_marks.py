"""
test_review_marks.py — Parole incerte di Whisper e controllo ortografico nell'editor.

Nessun modello: le parole incerte arrivano da probabilità scritte a mano (caso reale del
reel di Cappato: "E'" a 0,44 diventa "È" con la tipografia).
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtGui import QImage, QPainter, QTextCharFormat
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from core import spelling
from core import subtitle_layout as sl
from core.spelling import Speller, uncertain_spans
from core.subtitle_model import Subtitle
from core.subtitle_table_model import SubtitleTableModel, COL_TEXT
from core.undo_commands import EditFieldCommand, MergeWithNextCommand, SplitSubtitleCommand

pytest.importorskip("spellchecker")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def speller():
    return Speller(user_words=[])


@pytest.fixture
def no_user_words(monkeypatch):
    """Il correttore condiviso senza parole dell'utente (e senza cache di altri test)."""
    monkeypatch.setattr(spelling.SPELLER, "_user", set())
    spelling.SPELLER._cache.clear()
    yield spelling.SPELLER
    spelling.SPELLER._cache.clear()


def _bad(sp: Speller, text: str, asr: str = ""):
    return [text[s:e] for s, e in sp.misspelled_spans(text, asr)]


# ── Ortografia ───────────────────────────────────────────────────────────────

def test_typos_are_found_and_italian_words_are_not(speller):
    assert _bad(speller, "il cittadinno vuole partecipre alla democrazia") == [
        "cittadinno", "partecipre"]
    assert _bad(speller, "Perché la necessità di investire su questi sistemi?") == []


def test_names_acronyms_elisions_and_truncations_are_ignored(speller):
    text = "Cos'è l'intelligenza artificiale? Ne parla Cappato con gli LLM, un po' ovunque."
    assert _bad(speller, text) == []


def test_capitalized_word_is_checked_at_sentence_start(speller):
    assert _bad(speller, "Va bene. Perchè no?") == ["Perchè"]
    assert _bad(speller, "Perchè no?") == ["Perchè"]


def test_words_written_by_whisper_are_trusted(speller):
    asr = "per potenziare i propri diritti con la ricarica"
    assert _bad(speller, asr, asr) == []
    # un refuso scritto a mano nello stesso sottotitolo resta segnalato
    assert _bad(speller, "per potenziare i proprii diritti", asr) == ["proprii"]


def test_suggestions_keep_capitalization(speller):
    assert speller.suggestions("cittadinno")[0] == "cittadino"
    assert speller.suggestions("Perchè")[0] == "Perché"


def test_user_dictionary_is_remembered(app):
    first = Speller()
    assert first.misspelled_spans("parla lo scrumble") != ()
    changed = []
    first.notifier.changed.connect(lambda: changed.append(1))
    first.add_user_word("Scrumble")
    assert first.misspelled_spans("parla lo scrumble") == () and changed == [1]
    assert Speller().is_known("scrumble")          # salvato nelle preferenze


def test_missing_library_turns_spelling_off(speller, monkeypatch):
    monkeypatch.setitem(sys.modules, "spellchecker", None)
    off = Speller(user_words=[])
    assert not off.available and off.misspelled_spans("cittadinno") == ()


# ── Parole incerte ───────────────────────────────────────────────────────────

def _cappato_words():
    spec = [(" che", 0.0, 0.2, 0.9), (" viene", 0.2, 0.5, 0.95), (" superata.", 0.5, 1.0, 0.9),
            (" E'", 1.2, 1.3, 0.44), (" un'illusione.", 1.3, 2.0, 0.92)]
    return [sl.Word(t, s, e, p) for t, s, e, p in spec]


def test_layout_records_uncertain_words():
    subs = sl.segment(_cappato_words(), set())
    assert [s.get("uncertain") for s in subs] == [("e",)]


def test_engine_keeps_whisper_text():
    import engine
    words = [{"word": w.text, "start": w.start, "end": w.end, "probability": w.probability}
             for w in _cappato_words()]
    seg = {"start": 0.0, "end": 2.0, "text": "", "words": words}
    subs = engine._build_subtitles([seg], sl.LayoutRules(), 2.5, True)
    assert subs[0]["asr_text"] == subs[0]["text"]
    sub = Subtitle.from_dict(subs[0])
    # "E'" diventa "È" con la tipografia: l'evidenziazione ignora gli accenti
    assert [sub.text[s:e] for s, e in uncertain_spans(sub.text, sub.uncertain,
                                                       sub.asr_text)] == ["È"]


def test_uncertain_words_disappear_once_the_text_is_edited():
    sub = Subtitle(0, 2, "facendo così colorato", asr_text="facendo così colorato",
                   uncertain=("colorato",))
    assert uncertain_spans(sub.text, sub.uncertain, sub.asr_text) == [(13, 21)]
    assert uncertain_spans("facendo così con l'orecchio", sub.uncertain, sub.asr_text) == []
    assert uncertain_spans("facendo  così\ncolorato", sub.uncertain, sub.asr_text) != []
    # sottotitolo importato: nessuna trascrizione, nessuna parola incerta
    assert uncertain_spans("colorato", ("colorato",), "") == []


def test_project_file_keeps_review_data(tmp_path):
    from core.subtitle_model import SubtitleProject
    from core.v2srt_io import load_project, save_project
    project = SubtitleProject(subtitles=[
        Subtitle(0, 1, "uno", asr_text="uno", uncertain=("uno",)), Subtitle(1, 2, "due")])
    path = tmp_path / "p.v2srt"
    save_project(project, str(path))
    loaded, _ = load_project(str(path))
    assert loaded.subtitles[0].asr_text == "uno" and loaded.subtitles[0].uncertain == ("uno",)
    assert "asr_text" not in loaded.subtitles[1].to_dict()


def test_undo_of_a_text_edit_brings_the_highlight_back(app):
    from PySide6.QtGui import QUndoStack
    model = SubtitleTableModel([Subtitle(0, 2, "così colorato", asr_text="così colorato",
                                         uncertain=("colorato",))])
    stack = QUndoStack()
    stack.push(EditFieldCommand(model, 0, COL_TEXT, "così colorato", "così colorito", "t"))
    assert not model.subtitle_at(0).unedited
    stack.undo()
    assert model.subtitle_at(0).unedited


def test_split_and_merge_keep_whisper_text(app):
    text = "facendo così colorato se tu devi"
    model = SubtitleTableModel([Subtitle(0, 4, text, asr_text=text, uncertain=("colorato",)),
                                Subtitle(4, 5, "cittadinno", asr_text="")])
    SplitSubtitleCommand(model, 0, 21).redo()
    left, right = model.subtitle_at(0), model.subtitle_at(1)
    assert left.unedited and right.unedited and left.uncertain == ("colorato",)
    MergeWithNextCommand(model, 0).redo()
    assert model.subtitle_at(0).unedited and model.subtitle_at(0).asr_text == text


# ── Interfaccia ──────────────────────────────────────────────────────────────

def _inspector(app, subs):
    from ui.inspector_widget import InspectorWidget
    model = SubtitleTableModel(subs)
    insp = InspectorWidget()
    insp.bind_model(model)
    insp.show_row(0)
    return insp, model


def test_inspector_highlights_and_lists_review_words(app, no_user_words):
    text = "il cittadinno è colorato"
    insp, _ = _inspector(app, [Subtitle(0, 2, text, asr_text="il cittadino è colorato",
                                        uncertain=("colorato",))])
    labels = [r.findChildren(type(insp.issues_label))[-1].text() for r in insp._issue_rows]
    assert labels == ["Ortografia da controllare: «cittadinno»"]   # testo modificato
    insp, _ = _inspector(app, [Subtitle(0, 2, "il cittadinno è colorato",
                                        asr_text="il cittadinno è colorato",
                                        uncertain=("colorato",))])
    labels = [r.findChildren(type(insp.issues_label))[-1].text() for r in insp._issue_rows]
    assert labels == ["Parole incerte, da riascoltare: «colorato»"]
    ranges = insp.text_edit.document().firstBlock().layout().formats()
    assert [(r.start, r.length) for r in ranges
            if r.format.background().color().alpha() > 0] == [(16, 8)]


def test_inspector_underlines_typos_while_typing(app, no_user_words):
    insp, _ = _inspector(app, [Subtitle(0, 2, "ciao", asr_text="ciao")])
    insp.text_edit.setPlainText("ciao cittadinno")
    ranges = insp.text_edit.document().firstBlock().layout().formats()
    assert [(r.start, r.length) for r in ranges
            if r.format.underlineStyle() == QTextCharFormat.SpellCheckUnderline] == [(5, 10)]


def test_choosing_a_suggestion_replaces_and_commits(app, no_user_words):
    insp, model = _inspector(app, [Subtitle(0, 2, "il cittadinno vota")])
    edits = []
    insp.text_committed.connect(lambda row, text: edits.append((row, text)))
    span = insp._misspelled_at(5)
    assert span == (3, 13)
    insp._replace_word(span, "cittadino")
    assert edits == [(0, "il cittadino vota")]


def test_adding_a_word_clears_the_marks(app, no_user_words):
    insp, _ = _inspector(app, [Subtitle(0, 2, "parla lo scrumble")])
    assert insp._misspelled_at(10) is not None
    no_user_words.add_user_word("scrumble")
    assert insp._misspelled_at(10) is None
    assert not insp._issue_rows


def test_table_shows_review_hint_and_paints(app, no_user_words):
    from ui.review_marks import hint_word
    from ui.subtitle_timeline import SubtitleTimeline
    assert hint_word(Subtitle(0, 2, "il cittadinno")) == ("ortografia", "warn")
    assert hint_word(Subtitle(0, 2, "così colorato", asr_text="così colorato",
                              uncertain=("colorato",))) == ("incerto", "dim")
    assert hint_word(Subtitle(0, 2, "tutto bene", asr_text="tutto bene")) is None
    tl = SubtitleTimeline()
    tl.load_subtitles([Subtitle(0, 2, "così colorato", asr_text="così colorato",
                                uncertain=("colorato",)), Subtitle(2, 4, "il cittadinno")])
    image = QImage(600, 40, QImage.Format_ARGB32)
    painter = QPainter(image)
    for row in (0, 1):
        opt = QStyleOptionViewItem()
        opt.rect = image.rect()
        tl.view.itemDelegate().paint(painter, opt, tl.model.index(row, COL_TEXT))
    painter.end()
