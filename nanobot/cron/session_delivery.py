"""Helpers for routing bound cron turns back through their origin session."""

from __future__ import annotations

from typing import Any

from nanobot.cron.types import CronJob


def origin_delivery_context(job: CronJob) -> tuple[str, str, dict[str, Any]]:
    """Return ``(channel, chat_id, metadata)`` for a session-bound cron job's origin."""
    payload = job.payload
    if not payload.origin_channel or not payload.origin_chat_id:
        raise ValueError(f"cron job {job.id} is missing origin delivery context")
    return payload.origin_channel, payload.origin_chat_id, dict(payload.origin_metadata or {})


def target_delivery_context(job: CronJob) -> tuple[str, str, dict[str, Any]]:
    """Return ``(channel, chat_id, metadata)`` for a cron job's target destination."""
    payload = job.payload
    if payload.target_channel and payload.target_chat_id:
        meta = dict(payload.target_metadata or {})
        if payload.target_thread_id:
            meta["thread_id"] = payload.target_thread_id
            if payload.target_channel == "telegram":
                meta["message_thread_id"] = payload.target_thread_id
            elif payload.target_channel == "slack":
                meta["thread_ts"] = payload.target_thread_id
            elif payload.target_channel == "feishu":
                meta["root_id"] = payload.target_thread_id
        return payload.target_channel, payload.target_chat_id, meta
    return origin_delivery_context(job)


def has_custom_target(job: CronJob) -> bool:
    """Return True if job has an explicit target destination different from origin."""
    payload = job.payload
    if not (payload.target_channel and payload.target_chat_id):
        return False
    return (
        payload.target_channel != payload.origin_channel
        or payload.target_chat_id != payload.origin_chat_id
        or bool(payload.target_thread_id)
    )
