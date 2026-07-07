from __future__ import annotations

import audioop
import io
import logging
import subprocess
import threading
import wave
from collections import deque

import discord

LOGGER = logging.getLogger(__name__)
DISCORD_SAMPLE_RATE = 48_000
DISCORD_CHANNELS = 2
DISCORD_SAMPLE_WIDTH = 2
DISCORD_FRAME_DURATION_MS = 20
DISCORD_FRAME_SIZE = (
    DISCORD_SAMPLE_RATE
    * DISCORD_FRAME_DURATION_MS
    // 1000
    * DISCORD_CHANNELS
    * DISCORD_SAMPLE_WIDTH
)
ANNOUNCEMENT_VOLUME = 0.9
DUCKED_BGM_VOLUME = 0.35
MAX_ANNOUNCEMENT_QUEUE_SIZE = 4


class UnsupportedAnnouncementAudioError(ValueError):
    pass


def audio_to_discord_pcm(audio_data: bytes) -> bytes:
    try:
        return wav_to_discord_pcm(audio_data)
    except UnsupportedAnnouncementAudioError:
        return _ffmpeg_to_discord_pcm(audio_data)


def wav_to_discord_pcm(audio_data: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(audio_data), "rb") as wav:
            if wav.getnchannels() != DISCORD_CHANNELS:
                raise UnsupportedAnnouncementAudioError("announcement WAV must be stereo")
            if wav.getsampwidth() != DISCORD_SAMPLE_WIDTH:
                raise UnsupportedAnnouncementAudioError("announcement WAV must be 16-bit PCM")
            if wav.getframerate() != DISCORD_SAMPLE_RATE:
                raise UnsupportedAnnouncementAudioError("announcement WAV must be 48kHz")
            pcm = wav.readframes(wav.getnframes())
    except wave.Error as exc:
        raise UnsupportedAnnouncementAudioError("announcement audio must be WAV") from exc

    remainder = len(pcm) % DISCORD_FRAME_SIZE
    if remainder:
        pcm += b"\x00" * (DISCORD_FRAME_SIZE - remainder)
    return pcm


def _ffmpeg_to_discord_pcm(audio_data: bytes) -> bytes:
    try:
        process = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                str(DISCORD_CHANNELS),
                "-ar",
                str(DISCORD_SAMPLE_RATE),
                "pipe:1",
            ],
            input=audio_data,
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise UnsupportedAnnouncementAudioError("announcement audio conversion failed") from exc

    pcm = process.stdout
    remainder = len(pcm) % DISCORD_FRAME_SIZE
    if remainder:
        pcm += b"\x00" * (DISCORD_FRAME_SIZE - remainder)
    return pcm


class AnnouncementMixerAudioSource(discord.AudioSource):
    def __init__(
        self,
        base_source: discord.AudioSource,
        *,
        announcement_volume: float = ANNOUNCEMENT_VOLUME,
        ducked_bgm_volume: float = DUCKED_BGM_VOLUME,
    ) -> None:
        self._base_source = base_source
        self._announcement_volume = announcement_volume
        self._ducked_bgm_volume = ducked_bgm_volume
        self._lock = threading.Lock()
        self._queue: deque[bytes] = deque(maxlen=MAX_ANNOUNCEMENT_QUEUE_SIZE)
        self._current: bytes = b""
        self._current_offset = 0

    def is_opus(self) -> bool:
        return False

    def read(self) -> bytes:
        base_frame = self._base_source.read()
        announcement_frame = self._read_announcement_frame()
        if announcement_frame is None:
            return base_frame
        if not base_frame:
            base_frame = b"\x00" * DISCORD_FRAME_SIZE
        elif len(base_frame) < DISCORD_FRAME_SIZE:
            base_frame += b"\x00" * (DISCORD_FRAME_SIZE - len(base_frame))

        try:
            ducked_base = audioop.mul(base_frame, DISCORD_SAMPLE_WIDTH, self._ducked_bgm_volume)
            announcement = audioop.mul(
                announcement_frame,
                DISCORD_SAMPLE_WIDTH,
                self._announcement_volume,
            )
            return audioop.add(ducked_base, announcement, DISCORD_SAMPLE_WIDTH)
        except audioop.error:
            LOGGER.exception("Failed to mix announcement audio")
            return base_frame

    def cleanup(self) -> None:
        self._base_source.cleanup()

    def can_accept(self) -> bool:
        with self._lock:
            return len(self._queue) < MAX_ANNOUNCEMENT_QUEUE_SIZE

    def enqueue_audio(self, audio_data: bytes) -> bool:
        return self.enqueue_pcm(audio_to_discord_pcm(audio_data))

    def enqueue_wav(self, audio_data: bytes) -> bool:
        return self.enqueue_pcm(wav_to_discord_pcm(audio_data))

    def enqueue_pcm(self, pcm: bytes) -> bool:
        if not pcm:
            return False
        with self._lock:
            if len(self._queue) >= MAX_ANNOUNCEMENT_QUEUE_SIZE:
                return False
            self._queue.append(pcm)
            return True

    def set_base_volume(self, volume: float) -> None:
        if isinstance(self._base_source, discord.PCMVolumeTransformer):
            self._base_source.volume = volume

    def _read_announcement_frame(self) -> bytes | None:
        with self._lock:
            if self._current_offset >= len(self._current):
                self._current = self._queue.popleft() if self._queue else b""
                self._current_offset = 0
            if not self._current:
                return None

            start = self._current_offset
            end = start + DISCORD_FRAME_SIZE
            frame = self._current[start:end]
            self._current_offset = end
            if len(frame) < DISCORD_FRAME_SIZE:
                frame += b"\x00" * (DISCORD_FRAME_SIZE - len(frame))
            return frame
