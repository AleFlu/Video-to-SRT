"""test_transcription_worker.py — Test per core/transcription_worker.py (senza Whisper)."""

from __future__ import annotations

import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.transcription_worker import TranscriptionParams, TranscriptionWorker


def test_params_defaults():
    p = TranscriptionParams(input_path="a.mp4")
    assert (p.model_size, p.beam_size, p.vad_filter, p.denoise,
            p.high_accuracy, p.language) == ("large-v3", 5, True, True, False, "it")


def test_params_frozen():
    p = TranscriptionParams(input_path="a.mp4")
    with pytest.raises(Exception):
        p.beam_size = 1  # type: ignore[misc]


def test_params_from_dict_ignores_unknown_keys():
    p = TranscriptionParams.from_dict({"input_path": "a.mp4", "beam_size": 3, "extra": 1})
    assert p.beam_size == 3 and p.input_path == "a.mp4"


def test_params_from_dict_missing_input_raises():
    with pytest.raises(ValueError):
        TranscriptionParams.from_dict({"beam_size": 3})


def test_worker_accepts_dict_and_dataclass():
    w1 = TranscriptionWorker({"input_path": "a.mp4", "denoise": False})
    w2 = TranscriptionWorker(TranscriptionParams(input_path="a.mp4"))
    assert isinstance(w1.params, TranscriptionParams) and w1.params.denoise is False
    assert w2.params.input_path == "a.mp4"


def test_worker_run_passes_params(monkeypatch):
    seen = {}

    class Cancelled(Exception):
        pass

    def fake_transcribe(**kw):
        seen.update(kw)
        return [{"start": 0.0, "end": 1.0, "text": "x"}]

    fake = types.SimpleNamespace(
        transcribe=fake_transcribe,
        post_process_timing=lambda segs: segs,
        TranscriptionCancelled=Cancelled,
    )
    monkeypatch.setitem(sys.modules, "engine", fake)
    w = TranscriptionWorker({"input_path": "a.mp4", "beam_size": 2, "language": "en"})
    done = []
    w.finished.connect(lambda segs: done.append(segs))
    w.run()
    assert done and done[0][0]["text"] == "x"
    assert seen["beam_size"] == 2 and seen["language"] == "en"
    assert seen["input_path"] == "a.mp4"


def test_worker_failure_emits_failed(monkeypatch):
    class Cancelled(Exception):
        pass

    def boom(**kw):
        raise RuntimeError("rotto")

    fake = types.SimpleNamespace(transcribe=boom, post_process_timing=lambda s: s,
                                 TranscriptionCancelled=Cancelled)
    monkeypatch.setitem(sys.modules, "engine", fake)
    w = TranscriptionWorker({"input_path": "a.mp4"})
    errs = []
    w.failed.connect(errs.append)
    w.run()
    assert errs == ["rotto"]
