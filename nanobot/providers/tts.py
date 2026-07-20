"""Text-to-Speech (TTS) provider interface and implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI


class TTSClient(ABC):
    """Base interface for Text-to-Speech providers."""

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base

    @abstractmethod
    async def synthesize(self, text: str, output_path: Path, voice: str = "alloy") -> bool:
        """
        Synthesize text to an audio file.
        Returns True if successful, False otherwise.
        """
        pass


class OpenAITTProvider(TTSClient):
    """OpenAI TTS implementation using the /v1/audio/speech endpoint."""

    def __init__(
        self, api_key: str | None = None, api_base: str | None = None, default_voice: str = "alloy"
    ):
        super().__init__(api_key, api_base)
        self.default_voice = default_voice
        self._client = AsyncOpenAI(api_key=api_key or "no-key", base_url=api_base)

    async def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> bool:
        """Synthesize text to audio using OpenAI TTS."""
        if not text:
            return False

        target_voice = voice or self.default_voice
        try:
            response = await self._client.audio.speech.create(
                model="tts-1",
                voice=target_voice,
                input=text,
            )

            # Save the binary content to disk
            content = await response.content
            output_path.write_bytes(content)
            return True
        except Exception as e:
            logger.error("OpenAI TTS synthesis failed for {}: {}", text[:50], e)
            return False
