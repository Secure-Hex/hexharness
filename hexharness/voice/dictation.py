"""Push-to-talk dictation. Records the mic, transcribes LOCALLY with Whisper so the
audio never leaves the machine (opsec: no egress mid-engagement).

Toggle, not hold: terminals don't reliably report key-release, so the TUI starts
recording on one keypress and stops on the next. Audio capture and the Whisper model
are optional deps ([voice]) and are lazy-imported, so the package works without them.

The recorder and transcriber are injectable so the toggle flow is testable without a
real microphone or model.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

SAMPLE_RATE = 16_000  # Whisper expects 16 kHz mono


class Recorder(Protocol):
    def start(self) -> None: ...
    def stop(self):  # returns captured audio (numpy float32 mono) ...
        ...


class Transcriber(Protocol):
    def transcribe(self, audio, sample_rate: int) -> str: ...


def available() -> bool:
    """True only if the local capture + STT stack is importable."""
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


class _SoundDeviceRecorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._stream = None
        self._frames: list = []

    def start(self) -> None:
        import sounddevice as sd

        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            callback=lambda indata, frames, t, status: self._frames.append(indata.copy()),
        )
        self._stream.start()

    def stop(self):
        import numpy as np

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(self._frames, axis=0).reshape(-1)


class _WhisperTranscriber:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model = None

    def transcribe(self, audio, sample_rate: int) -> str:
        from faster_whisper import WhisperModel

        if self._model is None:  # first use downloads the model
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        if audio is None or len(audio) == 0:
            return ""
        segments, _ = self._model.transcribe(audio, language=None)
        return " ".join(s.text.strip() for s in segments).strip()


class Dictation:
    def __init__(self, *, model_size: str = "base", recorder: Recorder | None = None,
                 transcriber: Transcriber | None = None, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._recorder = recorder or _SoundDeviceRecorder(sample_rate)
        self._transcriber = transcriber or _WhisperTranscriber(model_size)
        self.is_recording = False

    @staticmethod
    def available() -> bool:
        return available()

    def start(self) -> None:
        self._recorder.start()
        self.is_recording = True

    async def stop_and_transcribe(self) -> str:
        audio = self._recorder.stop()
        self.is_recording = False
        # Whisper is CPU-bound — run off the event loop so the UI never freezes.
        return await asyncio.to_thread(self._transcriber.transcribe, audio, self.sample_rate)
