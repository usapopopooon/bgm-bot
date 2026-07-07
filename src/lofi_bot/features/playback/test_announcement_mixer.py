from __future__ import annotations

import io
import wave

from lofi_bot.features.playback.announcement_mixer import (
    DISCORD_CHANNELS,
    DISCORD_FRAME_SIZE,
    DISCORD_SAMPLE_RATE,
    DISCORD_SAMPLE_WIDTH,
    AnnouncementMixerAudioSource,
    UnsupportedAnnouncementAudioError,
    wav_to_discord_pcm,
)


class SilentSource:
    def read(self) -> bytes:
        return b"\x00" * DISCORD_FRAME_SIZE

    def cleanup(self) -> None:
        pass


def _make_wav(*, channels: int = DISCORD_CHANNELS, sample_rate: int = DISCORD_SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(DISCORD_SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x10" * channels * 960)
    return buffer.getvalue()


def test_wav_to_discord_pcm_pads_to_frame_size() -> None:
    pcm = wav_to_discord_pcm(_make_wav())

    assert len(pcm) == DISCORD_FRAME_SIZE


def test_wav_to_discord_pcm_rejects_mono_wav() -> None:
    try:
        wav_to_discord_pcm(_make_wav(channels=1))
    except UnsupportedAnnouncementAudioError:
        pass
    else:
        raise AssertionError("mono WAV should be rejected")


def test_mixer_overlays_queued_announcement() -> None:
    mixer = AnnouncementMixerAudioSource(SilentSource())
    mixer.enqueue_wav(_make_wav())

    frame = mixer.read()

    assert len(frame) == DISCORD_FRAME_SIZE
    assert frame != b"\x00" * DISCORD_FRAME_SIZE
