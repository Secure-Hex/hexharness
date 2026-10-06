"""Push-to-talk dictation toggle flow, with injected fake mic + transcriber (no real
audio/model). Confirms audio is transcribed locally and only text comes back."""
from __future__ import annotations

from hexharness.voice.dictation import Dictation


class _FakeRecorder:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def snapshot(self):
        return [0.0, 0.1]       # audio-so-far while still recording

    def stop(self):
        self.stopped = True
        return [0.0, 0.1, 0.2]  # stand-in for captured audio frames


class _FakeTranscriber:
    def __init__(self, text="scan the target"):
        self.text = text
        self.seen = None

    def transcribe(self, audio, sample_rate):
        self.seen = (audio, sample_rate)
        return self.text


async def test_toggle_records_then_transcribes():
    rec, tx = _FakeRecorder(), _FakeTranscriber("resolve www.acme.example")
    d = Dictation(recorder=rec, transcriber=tx)

    assert d.is_recording is False
    d.start()
    assert d.is_recording is True and rec.started

    text = await d.stop_and_transcribe()
    assert d.is_recording is False and rec.stopped
    assert text == "resolve www.acme.example"
    assert tx.seen == ([0.0, 0.1, 0.2], d.sample_rate)  # local transcription got the audio


async def test_live_partials_fire_while_recording():
    import asyncio

    rec, tx = _FakeRecorder(), _FakeTranscriber("live words")
    d = Dictation(recorder=rec, transcriber=tx, partial_interval=0.01)
    partials: list[str] = []

    d.start(on_partial=partials.append)
    await asyncio.sleep(0.05)          # let a few partial ticks run
    assert partials and partials[-1] == "live words"   # prompt filled live, mid-speech

    final = await d.stop_and_transcribe()
    assert final == "live words" and d.is_recording is False


def test_available_is_false_without_optional_deps():
    # sounddevice/faster-whisper are not installed in the test env => unavailable.
    import importlib.util

    expected = all(importlib.util.find_spec(m) for m in ("sounddevice", "faster_whisper"))
    assert Dictation.available() is expected
