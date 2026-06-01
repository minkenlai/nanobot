from unittest.mock import MagicMock

from nanobot.providers.base import GenerationSettings
from nanobot.providers.fallback import FallbackClient


def test_fallback_provider_max_context():
    """FallbackClient should compute the max context_max across all its slots."""
    p1 = MagicMock()
    p1.generation = GenerationSettings(context_max=100000)
    p1.debug = False
    p1.dump_dir = None

    p2 = MagicMock()
    p2.generation = GenerationSettings(context_max=2000000)

    p3 = MagicMock()
    p3.generation = GenerationSettings(context_max=128000)

    fp = FallbackClient(
        [
            (p1, "m1", "id1", "UTC"),
            (p2, "m2", "id2", "UTC"),
            (p3, "m3", "id3", "UTC"),
        ]
    )

    assert fp.generation.context_max == 2000000


def test_fallback_provider_max_context_none():
    """If all context_max are None, FallbackClient's context_max should be None (or primary's None)."""
    p1 = MagicMock()
    p1.generation = GenerationSettings(context_max=None)
    p1.debug = False
    p1.dump_dir = None

    p2 = MagicMock()
    p2.generation = GenerationSettings(context_max=None)

    fp = FallbackClient(
        [
            (p1, "m1", "id1", "UTC"),
            (p2, "m2", "id2", "UTC"),
        ]
    )

    assert fp.generation.context_max is None
