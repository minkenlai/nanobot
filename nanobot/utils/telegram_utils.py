"""
Utility functions for persisting Telegram topic profile mappings.
"""

import json
from pathlib import Path
from typing import Dict, Optional

PINS_FILE = Path("sessions/tg_pins.json")


def load_topic_pins() -> Dict[str, Dict[int, Optional[str]]]:
    """Load the topic profile mappings from the JSON file."""
    if not PINS_FILE.exists():
        return {}

    try:
        with open(PINS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert keys to correct types
        result = {}
        for chat_id_str, topics in data.items():
            chat_id = str(chat_id_str)
            result[chat_id] = {}
            for topic_id_str, profile in topics.items():
                topic_id = int(topic_id_str)
                result[chat_id][topic_id] = profile if profile is not None else None

        return result
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Failed to load topic pins: {e}")
        return {}


def save_topic_pins(pins: Dict[str, Dict[int, Optional[str]]]) -> None:
    """Save the topic profile mappings to the JSON file."""
    # Convert to serializable format
    serializable = {}
    for chat_id, topics in pins.items():
        serializable[chat_id] = {}
        for topic_id, profile in topics.items():
            serializable[chat_id][str(topic_id)] = profile

    PINS_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(PINS_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Failed to save topic pins: {e}")


def get_cached_profile(
    pins: Dict[str, Dict[int, Optional[str]]], chat_id: str, topic_id: int
) -> Optional[str]:
    """Get the cached profile for a chat/topic from the in-memory pins dict."""
    return pins.get(chat_id, {}).get(topic_id)


def set_cached_profile(
    pins: Dict[str, Dict[int, Optional[str]]], chat_id: str, topic_id: int, profile: Optional[str]
) -> None:
    """Set the cached profile for a chat/topic in the in-memory pins dict."""
    if chat_id not in pins:
        pins[chat_id] = {}
    pins[chat_id][topic_id] = profile


def remove_cached_profile(
    pins: Dict[str, Dict[int, Optional[str]]], chat_id: str, topic_id: int
) -> None:
    """Remove the cached profile for a chat/topic from the in-memory pins dict."""
    if chat_id in pins and topic_id in pins[chat_id]:
        del pins[chat_id][topic_id]
        # Clean up empty chat_id entries
        if not pins[chat_id]:
            del pins[chat_id]


def add_lazy_topic_entry(
    pins: Dict[str, Dict[int, Optional[str]]], chat_id: str, topic_id: int
) -> None:
    """Add a lazy topic entry to the pins dict if it doesn't exist yet."""
    if chat_id not in pins:
        pins[chat_id] = {}
    if topic_id not in pins[chat_id]:
        pins[chat_id][topic_id] = None
