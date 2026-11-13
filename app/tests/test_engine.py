"""
test_engine.py — Test del motore di trascrizione senza caricare modelli Whisper.

Usa oggetti finti (SimpleNamespace) per parole e segmenti, e moduli finti
``faster_whisper`` / ``ctranslate2`` iniettati in ``sys.modules``.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

import engine


# ── Helper ────────────────────────────────────────────────────────────────────

def _w(word: str, start: float, end: float, prob: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(word=word, start=start, end=end, probability=prob)


def _seg(words, text: str = "", start: float = None, end: float = None) -> SimpleNamespace:
    if start is None:
        start = words[0].start if words else 0.0
    if end is None:
        end = words[-1].end if words else 0.0
    if not text:
        text = " ".join(w.word.strip() for w in words)
    return SimpleNamespace(
        words=words, text=text, start=start, end=end,
        no_speech_prob=0.0, avg_logprob=-0.2,
    )


def _all_text(subs) -> str:
    return " ".join(s["text"] for s in subs)


# ── Bug parole perse ──────────────────────────────────────────────────────────

def test_synthetic_segment_followed_by_real_words_keeps_all_words():
    """Segmento senza parole affidabili seguito da parlato: nessuna parola sparisce."""
    low = [_w(" ok", 0.0, 0.3, 0.1), _w(" va", 0.3, 0.6, 0.1), _w(" bene", 0.6, 1.0, 0.1)]
    seg1 = _seg(low, text=" ok va bene", start=0.0, end=1.0)
    real_words = ["allora", "oggi", "parliamo", "di", "sottotitoli"]
    seg2 = _seg([_w(" " + t, 1.05 + i * 0.3, 1.3 + i * 0.3) for i, t in enumerate(real_words)])

    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    text = _all_text(subs)
    for token in ["ok", "va", "bene"] + real_words:
        assert token in text.split(), f"parola persa: {token!r} in {text!r}"


def test_collect_all_words_returns_module_level_fake_word():
    seg = _seg([_w(" ehm", 0.0, 0.5, 0.05)], text=" ehm", start=0.0, end=0.5)
    words, boundaries = engine.collect_all_words([seg])
    assert len(words) == 1
    assert isinstance(words[0], engine._FakeWord)
    assert words[0].word == "ehm"
    assert boundaries == set()


def test_synthetic_word_is_isolated_in_its_own_block():
    """Un word sintetico forza uno split prima e dopo di sé (prima del merge)."""
    seg0 = _seg([_w(" Buongiorno", 0.0, 0.4), _w(" a", 0.42, 0.5), _w(" tutti", 0.52, 0.8)])
    seg1 = _seg([_w(" xx", 0.85, 1.0, 0.1)], text=" mh mh", start=0.85, end=1.0)
    seg2 = _seg([_w(" e", 1.05, 1.1), _w(" benvenuti", 1.12, 1.6)])
    words, boundaries = engine.collect_all_words([seg0, seg1, seg2])
    # Disattiva il merge per osservare i blocchi grezzi
    old = engine.MERGE_MIN_CHARS
    engine.MERGE_MIN_CHARS = 0
    try:
        subs = engine.segment_words_semantic(words, boundaries)
    finally:
        engine.MERGE_MIN_CHARS = old
    assert [s["text"] for s in subs] == ["Buongiorno a tutti", "mh mh", "e benvenuti"]


# ── Merge frammenti corti ─────────────────────────────────────────────────────

def test_merge_respects_max_duration():
    seg1 = _seg([_w(" Ciao.", 0.0, 0.5)])
    tokens = ["uno", "due", "tre", "quattro"]
    # Il secondo blocco dura 6.75 s: unito al primo supererebbe MAX_SUBTITLE_DURATION
    seg2 = _seg([_w(" " + t, 0.6 + i * 1.7, 0.6 + i * 1.7 + 1.65) for i, t in enumerate(tokens)])
    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    assert subs[0]["text"] == "Ciao."
    for s in subs:
        assert s["end"] - s["start"] <= engine.MAX_SUBTITLE_DURATION
    assert _all_text(subs).split() == ["Ciao."] + tokens


def test_merge_respects_hard_limit():
    seg1 = _seg([_w(" Ciao.", 0.0, 0.5)])
    tokens = ["parola%02d" % i for i in range(9)]  # 9 * 8 + 8 spazi = 80 caratteri
    seg2 = _seg([_w(" " + t, 0.6 + i * 0.3, 0.6 + i * 0.3 + 0.25) for i, t in enumerate(tokens)])
    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    for s in subs:
        assert len(s["text"]) <= engine.HARD_LIMIT
    assert _all_text(subs).split() == ["Ciao."] + tokens


def test_merge_still_joins_short_fragments():
    seg1 = _seg([_w(" Ciao.", 0.0, 0.5)])
    seg2 = _seg([_w(" Come", 0.6, 0.9), _w(" stai?", 0.92, 1.3)])
    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    assert [s["text"] for s in subs] == ["Ciao. Come stai?"]


# ── post_process_timing ───────────────────────────────────────────────────────

def test_post_process_timing_overlapping_segments():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "uno"},
        {"start": 1.5, "end": 3.0, "text": "due"},
        {"start": 2.9, "end": 4.0, "text": "tre"},
        {"start": 1.0001, "end": 1.0002, "text": "quattro"},
        {"start": 1.0802, "end": 1.5, "text": "cinque"},
    ]
    out = engine.post_process_timing(segs)
    assert len(out) == 5
    for s in out:
        assert s["end"] > s["start"], s
    for cur, nxt in zip(out, out[1:]):
        limit = nxt["start"] - engine.MIN_GAP_BETWEEN_SUBS
        if limit > cur["start"]:
            assert cur["end"] <= limit + 1e-9, (cur, nxt)


def test_post_process_timing_rounding_never_collapses():
    segs = [
        {"start": 1.0001, "end": 1.0002, "text": "a"},
        {"start": 1.0803, "end": 2.0, "text": "b"},
    ]
    out = engine.post_process_timing(segs)
    assert all(s["end"] > s["start"] for s in out), out


# ── Cache modello thread-safe ─────────────────────────────────────────────────

@pytest.fixture
def fake_backends(monkeypatch):
    """Inietta moduli finti faster_whisper e ctranslate2."""
    calls = []
    lock = threading.Lock()

    class FakeWhisperModel:
        def __init__(self, path, **kwargs):
            time.sleep(0.05)
            with lock:
                calls.append((path, kwargs))
            self.path = path

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeWhisperModel
    ct2 = types.ModuleType("ctranslate2")
    ct2.cuda_count = 0
    ct2.get_cuda_device_count = lambda: ct2.cuda_count
    ct2.get_supported_compute_types = lambda device: {"int8", "float32"}
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    monkeypatch.setitem(engine._model_cache, "model", None)
    monkeypatch.setitem(engine._model_cache, "model_key", None)
    return SimpleNamespace(calls=calls, ct2=ct2)


def test_model_cache_concurrent_loads_once(fake_backends):
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(engine._get_or_load_model("tiny"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(fake_backends.calls) == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert results[0].path == "tiny"
    assert fake_backends.calls[0][1].get("num_workers") == 1


def test_model_cache_reload_on_different_key(fake_backends):
    m1 = engine._get_or_load_model("tiny")
    m2 = engine._get_or_load_model("tiny")
    m3 = engine._get_or_load_model("base")
    assert m1 is m2
    assert m3 is not m1
    assert len(fake_backends.calls) == 2


def test_get_optimal_device_uses_ctranslate2(fake_backends):
    assert engine.get_optimal_device() == ("cpu", "int8")
    fake_backends.ct2.cuda_count = 1
    assert engine.get_optimal_device() == ("cuda", "float16")


# ── Varie ─────────────────────────────────────────────────────────────────────

def test_check_cancel():
    engine._check_cancel(None)
    ev = threading.Event()
    engine._check_cancel(ev)
    ev.set()
    with pytest.raises(engine.TranscriptionCancelled, match="annullata dall'utente"):
        engine._check_cancel(ev)


def test_renamed_postprocessors():
    assert engine._postprocess_codeswitching("il macchina lerning") == "il machine learning"
    assert engine._postprocess_typography("ciao , un po bene") == "ciao, un po' bene"
    assert not hasattr(engine, "_postprocess_italian")
    assert not hasattr(engine, "_postprocess_italian_subs")


def test_dead_code_removed():
    for name in ("format_timestamp_srt", "wrap_subtitle_text", "generate_srt",
                 "write_srt", "_unique_output_path", "split_segment_by_words",
                 "SILENCE_THRESHOLD", "END_PAD_SPEECH", "END_PAD_SILENCE",
                 "READING_SPEED_CPS"):
        assert not hasattr(engine, name), name


def test_vad_params_constant():
    assert engine.VAD_PARAMS == dict(min_silence_duration_ms=150, speech_pad_ms=100,
                                     threshold=0.50)


def test_vad_error_classification():
    assert engine._is_vad_unavailable_error(ImportError("No module named 'onnxruntime'"))
    assert engine._is_vad_unavailable_error(
        RuntimeError("[ONNXRuntimeError] : 3 : NO_SUCHFILE silero_vad.onnx"))
    assert not engine._is_vad_unavailable_error(RuntimeError("out of memory"))
    assert not engine._is_vad_unavailable_error(FileNotFoundError("video.mp4"))


def test_preprocess_audio_failure_reports_status(monkeypatch, tmp_path):
    import subprocess

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    msgs = []
    assert engine.preprocess_audio(str(tmp_path / "x.mp4"), on_status=msgs.append) is None
    assert any("Pre-elaborazione audio non riuscita" in m for m in msgs)


def test_preprocess_audio_uses_absolute_path(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=1, stderr="errore", stdout="")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    engine.preprocess_audio("-strano.mp4")
    i = seen["cmd"].index("-i")
    assert seen["cmd"][i + 1].startswith(("/", "\\")) or ":" in seen["cmd"][i + 1]


def test_transcribe_is_keyword_only():
    import inspect
    params = inspect.signature(engine.transcribe).parameters
    names = list(params)
    assert names[0] == "input_path"
    for name in names[1:]:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert "language" in params


def test_check_ffmpeg_uses_which(monkeypatch):
    monkeypatch.setattr(engine, "get_bundled_ffmpeg", lambda: None)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    assert engine.check_ffmpeg() is False
    monkeypatch.setattr(engine.shutil, "which", lambda name: "/usr/bin/" + name)
    assert engine.check_ffmpeg() is True
