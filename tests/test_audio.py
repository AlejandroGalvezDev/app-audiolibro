from __future__ import annotations

import io
import wave

import pytest

from app import audio


def _wav_bytes(frames: int, rate: int = 22050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def test_concat_mp3_is_lossless_binary_join():
    assert audio.concat_audio([b"abc", b"def"], "mp3") == b"abcdef"


def test_concat_mp3_strips_previous_id3_tags():
    payload = b"TIT2"
    tag = b"ID3\x03\x00\x00" + bytes([0, 0, 0, len(payload)]) + payload
    combined = audio.concat_audio([tag + b"AUDIO-A", tag + b"AUDIO-B"], "mp3")
    assert combined == b"AUDIO-AAUDIO-B"


def test_concat_wav():
    combined = audio.concat_audio([_wav_bytes(10), _wav_bytes(5)], "wav")
    with wave.open(io.BytesIO(combined), "rb") as wav:
        assert wav.getnframes() == 15
        assert wav.getframerate() == 22050


def test_concat_wav_rejects_mismatched_formats():
    with pytest.raises(audio.AudioError, match="parámetros distintos"):
        audio.concat_audio([_wav_bytes(10), _wav_bytes(10, rate=44100)], "wav")


def test_concat_empty_raises():
    with pytest.raises(audio.AudioError):
        audio.concat_audio([], "mp3")


def test_convert_without_ffmpeg_raises(monkeypatch):
    monkeypatch.setattr(audio, "ffmpeg_path", lambda: None)
    with pytest.raises(audio.AudioError, match="ffmpeg"):
        audio.convert_audio(b"audio", "wav", "mp3")


def test_write_audio_creates_file(tmp_path):
    destination = tmp_path / "capitulo.mp3"
    audio.write_audio(
        destination,
        b"ID3fake-audio-data",
        "mp3",
        title="Prueba",
        artist="Test",
        album="Álbum",
        track=1,
    )
    assert destination.is_file()
    assert destination.read_bytes()
