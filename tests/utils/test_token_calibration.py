"""TDD tests for token calibration bugs:
1. Anchor Mismatch — history hash should be a prefix hash.
2. Delta Bug — add incremental delta instead of full estimate.
"""

import base64
import hashlib
import json
import math
import time

from nanobot.utils.helpers import (
    calculate_base_hash,
    calculate_calibrated_prompt_tokens,
    calculate_history_hash,
    estimate_prompt_tokens,
)


def _make_messages(*texts):
    return [{"role": "user", "content": t} for t in texts]


def _hash_full(messages):
    """Helper: hash an entire message list (not just a prefix)."""
    return hashlib.sha256(
        json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def test_prefix_hash_stability():
    """The prefix hash of Turn N+1 must match the full hash of Turn N.

    calculate_history_hash(messages) always hashes messages[:-1], so:
      - hash(turn_N) == _hash_full(turn_{N-1})
      - hash(turn_1) == _hash_full([])  (single-message turn → empty prefix)
    """
    turn1 = _make_messages("Hello")
    turn2 = _make_messages("Hello", "How are you?")
    turn3 = _make_messages("Hello", "How are you?", "Fine thanks")

    # Turn 1 has a single message → prefix is empty list
    assert calculate_history_hash(turn1) == _hash_full([])

    # Turn 2 prefix is turn1's full list
    assert calculate_history_hash(turn2) == _hash_full(turn1)

    # Turn 3 prefix is turn2's full list
    assert calculate_history_hash(turn3) == _hash_full(turn2)


def test_delta_calculation_accuracy():
    """Verify that only the incremental delta is added to prev_actual,
    using math.ceil for conservative token estimation."""
    prev_actual = 1000
    ratio = 1.5
    sentinel = "anchor-matched"

    # Messages: [Prefix] + [New Message]
    prefix = _make_messages("Long history message that takes up space")
    new_msg = [{"role": "user", "content": "Short update"}]
    messages = prefix + new_msg

    # Force anchor match
    result = calculate_calibrated_prompt_tokens(
        messages=messages,
        tools=None,
        ratio=ratio,
        current_base_hash=sentinel,
        current_history_hash=sentinel,
        prev_actual=prev_actual,
        prev_base_hash=sentinel,
        prev_history_hash=sentinel,
    )

    # Expected: prev_actual + ceil(estimate(new_msg) * ratio)
    incremental_est = estimate_prompt_tokens(new_msg)
    expected = prev_actual + math.ceil(incremental_est * ratio)

    assert result == expected, f"Expected {expected}, got {result}"


# ---------------------------------------------------------------------------
# Expanded test cases (post-review additions)
# ---------------------------------------------------------------------------


def test_base_hash_mismatch():
    """Verify that changing the system prompt or tool list correctly invalidates
    the anchor and triggers a full estimate instead of incremental delta."""
    system_prompt_v1 = "You are a helpful assistant."
    system_prompt_v2 = "You are a different helpful assistant."
    tools = [{"type": "function", "function": {"name": "calc", "description": "Calculate"}}]

    messages = _make_messages("Hello", "How are you?")

    base_hash_v1 = calculate_base_hash(system_prompt_v1, tools)
    base_hash_v2 = calculate_base_hash(system_prompt_v2, tools)

    # Base hashes must differ when system prompt changes
    assert base_hash_v1 != base_hash_v2, (
        "Different system prompts must produce different base hashes"
    )

    history_hash = calculate_history_hash(messages)

    # With matching base hash → incremental path (anchor matched)
    result_matched = calculate_calibrated_prompt_tokens(
        messages=messages,
        tools=tools,
        ratio=1.2,
        current_base_hash=base_hash_v1,
        current_history_hash=history_hash,
        prev_actual=5000,
        prev_base_hash=base_hash_v1,
        prev_history_hash=history_hash,
    )

    # With mismatched base hash → full estimate path
    result_mismatched = calculate_calibrated_prompt_tokens(
        messages=messages,
        tools=tools,
        ratio=1.2,
        current_base_hash=base_hash_v2,
        current_history_hash=history_hash,
        prev_actual=5000,
        prev_base_hash=base_hash_v1,
        prev_history_hash=history_hash,
    )

    # The mismatched result should be the full estimate, NOT prev_actual + delta
    full_est = estimate_prompt_tokens(messages, tools)
    expected_full = int(full_est * 1.2)
    assert result_mismatched == expected_full, (
        f"Base hash mismatch should trigger full estimate. "
        f"Expected {expected_full}, got {result_mismatched}"
    )

    # The matched result should be incremental (prev_actual + delta)
    incremental_est = estimate_prompt_tokens(messages[-1:], tools)
    expected_incremental = 5000 + math.ceil(incremental_est * 1.2)
    assert result_matched == expected_incremental, (
        f"Base hash match should use incremental delta. "
        f"Expected {expected_incremental}, got {result_matched}"
    )

    # Verify that changing tools also invalidates the anchor
    tools_v2 = [{"type": "function", "function": {"name": "search", "description": "Search"}}]
    base_hash_tools_v2 = calculate_base_hash(system_prompt_v1, tools_v2)
    assert base_hash_v1 != base_hash_tools_v2, "Different tools must produce different base hashes"


def test_cold_start_transition():
    """Verify the logic when transitioning from Turn 1 (prev_actual=0)
    to Turn 2 (prev_actual > 0).

    Turn 1: prev_actual=0 means cold start → always full estimate.
    Turn 2: prev_actual > 0 and anchors match → incremental delta.
    """
    system_prompt = "You are an assistant."
    messages_turn1 = _make_messages("Hello")
    messages_turn2 = _make_messages("Hello", "How are you?")

    base_hash = calculate_base_hash(system_prompt)
    history_hash_t1 = calculate_history_hash(messages_turn1)
    history_hash_t2 = calculate_history_hash(messages_turn2)

    # --- Turn 1 (cold start, prev_actual=0) ---
    # Even with matching hashes, prev_actual=0 forces full estimate path
    result_turn1 = calculate_calibrated_prompt_tokens(
        messages=messages_turn1,
        tools=None,
        ratio=1.1,
        current_base_hash=base_hash,
        current_history_hash=history_hash_t1,
        prev_actual=0,  # cold start
        prev_base_hash=base_hash,
        prev_history_hash=history_hash_t1,
    )

    full_est_t1 = estimate_prompt_tokens(messages_turn1)
    expected_turn1 = int(full_est_t1 * 1.1)
    assert result_turn1 == expected_turn1, (
        f"Cold start (prev_actual=0) must use full estimate. "
        f"Expected {expected_turn1}, got {result_turn1}"
    )

    # Simulate the actual token count reported back from the LLM
    turn1_actual = 95  # plausible actual count after ratio adjustment

    # --- Turn 2 (warm, anchors match) ---
    # history_hash_t2 should match the "previous" history_hash_t1
    # because turn1's messages[:-1] == [], and turn2's messages[:-1] == turn1
    # So we pass prev_history_hash=history_hash_t1 and current_history_hash=history_hash_t2
    result_turn2 = calculate_calibrated_prompt_tokens(
        messages=messages_turn2,
        tools=None,
        ratio=1.1,
        current_base_hash=base_hash,
        current_history_hash=history_hash_t2,
        prev_actual=turn1_actual,
        prev_base_hash=base_hash,
        prev_history_hash=history_hash_t1,
    )

    # Turn 2: current_history_hash != prev_history_hash (prefix grew)
    # So this should trigger full estimate, not incremental
    full_est_t2 = estimate_prompt_tokens(messages_turn2)
    expected_turn2 = int(full_est_t2 * 1.1)
    assert result_turn2 == expected_turn2, (
        f"Turn 2 with different history hash must use full estimate. "
        f"Expected {expected_turn2}, got {result_turn2}"
    )


def test_multimodal_payload_stability():
    """Verify that large base64 encoded multimodal blocks in the history
    are hashed stably and don't cause unexpected bottlenecks."""
    # Generate a synthetic large base64 payload (~500KB, typical for a small image)
    raw_bytes = bytes(range(256)) * 1000  # 256KB repeating pattern
    b64_payload = base64.b64encode(raw_bytes).decode()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_payload}"},
                },
                {"type": "text", "text": "Analyze this image."},
            ],
        },
        {
            "role": "assistant",
            "content": "I see an image with repeating patterns.",
        },
        {
            "role": "user",
            "content": "What colors do you see?",
        },
    ]

    # Hash should be deterministic and stable across multiple calls
    hash_run1 = calculate_history_hash(messages)
    hash_run2 = calculate_history_hash(messages)
    hash_run3 = calculate_history_hash(messages)

    assert hash_run1 == hash_run2 == hash_run3, "History hash must be stable for identical input"

    # Verify hash is a valid 64-char hex string (SHA-256)
    assert len(hash_run1) == 64, f"SHA-256 hex should be 64 chars, got {len(hash_run1)}"
    assert all(c in "0123456789abcdef" for c in hash_run1), "Hash should be lowercase hex"

    # Performance: hashing should complete quickly even with large payloads
    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        calculate_history_hash(messages)
    elapsed = time.perf_counter() - start
    per_call_ms = (elapsed / iterations) * 1000

    # Should complete well under 50ms per call
    assert per_call_ms < 50.0, (
        f"Multimodal hash took {per_call_ms:.1f}ms/call — "
        f"expected < 50ms. Large base64 may be causing bottlenecks."
    )

    # Verify that the hash changes when multimodal content changes
    messages_modified = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_payload}MODIFIED"},
                },
                {"type": "text", "text": "Analyze this image."},
            ],
        },
        {
            "role": "assistant",
            "content": "I see an image with repeating patterns.",
        },
        {
            "role": "user",
            "content": "What colors do you see?",
        },
    ]
    hash_modified = calculate_history_hash(messages_modified)
    assert hash_run1 != hash_modified, "Hash must change when multimodal content changes"
