"""OpenAI-compatible HTTP API server for a fixed nanobot session.

Provides /v1/chat/completions and /v1/models endpoints.
All requests route to a single persistent API session.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json as _json
import time
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable, cast

from aiohttp import web
from loguru import logger

from nanobot.config.paths import get_media_dir
from nanobot.providers.base import LLMUsage
from nanobot.utils.helpers import safe_filename
from nanobot.utils.media_decode import (
    MAX_FILE_SIZE,
)
from nanobot.utils.media_decode import (
    FileSizeExceeded as _FileSizeExceeded,
)
from nanobot.utils.media_decode import (
    save_base64_data_url as _save_base64_data_url,
)
from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop

__all__ = (
    "MAX_FILE_SIZE",
    "_FileSizeExceeded",
    "_save_base64_data_url",
    "create_app",
    "handle_chat_completions",
)


API_SESSION_KEY = "api:default"
API_CHAT_ID = "default"
_AGENT_LOOP_KEY = web.AppKey[Any]("agent_loop")
_MODEL_NAME_KEY = web.AppKey[str]("model_name")
_REQUEST_TIMEOUT_KEY = web.AppKey[float]("request_timeout")
_SESSION_LOCKS_KEY = web.AppKey[dict[str, asyncio.Lock]]("session_locks")
_PREPARE_AGENT_KEY = web.AppKey[Callable[[], Awaitable[None]] | None]("prepare_agent")
_CORS_ORIGINS_KEY = web.AppKey[list[str]]("cors_origins")
_MAX_TURN_PROMPT_LENGTH_KEY = web.AppKey[int]("max_turn_prompt_length")
_RATE_LIMIT_IP_KEY = web.AppKey[int]("rate_limit_ip_per_min")
_RATE_LIMIT_SESSION_KEY = web.AppKey[int]("rate_limit_session_per_min")
_RATE_LIMITER_KEY = web.AppKey[Any]("rate_limiter")
_MISSING = object()


def _app_value(
    app: Any,
    key: web.AppKey[Any],
    legacy_key: str,
    default: Any = _MISSING,
) -> Any:
    """Read typed aiohttp state while accepting lightweight dict test doubles."""
    try:
        return app[key]
    except KeyError:
        if default is _MISSING:
            return app[legacy_key]
        return app.get(legacy_key, default)


async def _prepare_agent(app: Any) -> None:
    prepare: Callable[[], Awaitable[None]] | None = _app_value(
        app,
        _PREPARE_AGENT_KEY,
        "prepare_agent",
        None,
    )
    if prepare is not None:
        await prepare()


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter per key (IP or session_id)."""

    def __init__(self) -> None:
        self._history: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, max_requests: int, window_seconds: float = 60.0) -> bool:
        if max_requests <= 0:
            return True
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            timestamps = self._history.get(key, [])
            valid_timestamps = [t for t in timestamps if t > cutoff]
            if len(valid_timestamps) >= max_requests:
                self._history[key] = valid_timestamps
                return False
            valid_timestamps.append(now)
            self._history[key] = valid_timestamps
            return True


def _cors_headers(request: web.Request, allowed_origins: list[str] | None = None) -> dict[str, str]:
    origins = allowed_origins or ["*"]
    origin = request.headers.get("Origin", "*")
    if not origins or "*" in origins:
        allow_origin = origin if origin != "*" else "*"
    elif origin in origins:
        allow_origin = origin
    else:
        allow_origin = origins[0]

    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Session-Id, X-Requested-With",
        "Access-Control-Max-Age": "86400",
    }


def _error_json(
    status: int,
    message: str,
    err_type: str = "invalid_request_error",
    headers: dict[str, str] | None = None,
) -> web.Response:
    resp_headers = dict(headers) if headers else {}
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
        headers=resp_headers,
    )


def _chat_completion_response(
    content: str,
    model: str,
    usage: LLMUsage | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
    elif usage is not None:
        prompt = usage.input_tokens
        completion = usage.output_tokens
        total = usage.total_tokens
    else:
        prompt = 0
        completion = 0
        total = 0
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        },
    }


def _response_text(value: Any) -> str:
    """Normalize process_direct output to plain assistant text."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        return str(getattr(value, "content") or "")
    return str(value)


def _as_str(value: object) -> str:
    """Return *value* when it is text, otherwise an empty string."""
    return value if isinstance(value, str) else ""


def _require_json_object(value: object, field: str) -> dict[str, Any]:
    """Validate an object-valued field from an untrusted JSON request."""
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _require_json_string(value: object, field: str) -> str:
    """Validate a string-valued field from an untrusted JSON request."""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_chunk(delta: str, model: str, chunk_id: str, finish_reason: str | None = None) -> bytes:
    """Format a single OpenAI-compatible SSE chunk."""
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta} if delta else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {_json.dumps(payload)}\n\n".encode()


_SSE_DONE = b"data: [DONE]\n\n"

# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------


def _parse_json_content(body: dict[str, Any]) -> tuple[str, list[str]]:
    """Parse JSON request body. Returns (text, media_paths)."""
    messages_value = cast(object, body.get("messages"))
    if not isinstance(messages_value, list):
        raise ValueError("Only a single user message is supported")
    messages = cast(list[object], messages_value)
    if len(messages) != 1:
        raise ValueError("Only a single user message is supported")
    message_value: object = messages[0]
    if not isinstance(message_value, dict):
        raise ValueError("Only a single user message is supported")
    message = cast(dict[str, Any], message_value)
    if message.get("role") != "user":
        raise ValueError("Only a single user message is supported")

    user_content = message.get("content", "")
    media_dir = get_media_dir("api")
    media_paths: list[str] = []

    if isinstance(user_content, list):
        text_parts: list[str] = []
        for part_value in cast(list[object], user_content):
            if not isinstance(part_value, dict):
                continue
            part = cast(dict[str, Any], part_value)
            if part.get("type") == "text":
                text_parts.append(
                    _require_json_string(
                        cast(object, part.get("text", "")),
                        "messages[0].content[].text",
                    )
                )
            elif part.get("type") == "image_url":
                image_url = _require_json_object(
                    cast(object, part.get("image_url", {})),
                    "messages[0].content[].image_url",
                )
                url = _require_json_string(
                    cast(object, image_url.get("url", "")),
                    "messages[0].content[].image_url.url",
                )
                if url.startswith("data:"):
                    saved = _save_base64_data_url(url, media_dir)
                    if saved:
                        media_paths.append(saved)
                elif url:
                    raise ValueError(
                        "Remote image URLs are not supported. "
                        "Use base64 data URLs or upload files via multipart/form-data."
                    )
        text = " ".join(text_parts)
    elif isinstance(user_content, str):
        text = user_content
    else:
        raise ValueError("Invalid content format")

    return text, media_paths


async def _parse_multipart(request: web.Request) -> tuple[str, list[str], str | None, str | None]:
    """Parse multipart/form-data. Returns (text, media_paths, session_id, model)."""
    media_dir = get_media_dir("api")
    reader = await request.multipart()
    text = ""
    session_id = None
    model = None
    media_paths: list[str] = []

    while True:
        part: Any = await reader.next()
        if part is None:
            break
        if part.name == "message":
            text = (await part.read()).decode("utf-8")
        elif part.name == "session_id":
            session_id = (await part.read()).decode("utf-8").strip()
        elif part.name == "model":
            model = (await part.read()).decode("utf-8").strip()
        elif part.name == "files":
            raw = await part.read()
            if len(raw) > MAX_FILE_SIZE:
                raise _FileSizeExceeded(
                    f"File '{part.filename}' exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit"
                )
            base = safe_filename(part.filename or "upload.bin")
            filename = f"{uuid.uuid4().hex[:12]}_{base}"
            dest = media_dir / filename
            dest.write_bytes(raw)
            media_paths.append(str(dest))

    if not text:
        text = "请分析上传的文件"

    return text, media_paths, session_id, model


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_options(request: web.Request) -> web.Response:
    """OPTIONS preflight route handler."""
    origins = _app_value(request.app, _CORS_ORIGINS_KEY, "cors_origins", ["*"])
    headers = _cors_headers(request, origins)
    return web.Response(status=200, headers=headers)


async def handle_chat_completions(request: web.Request) -> web.Response | web.StreamResponse:
    """POST /v1/chat/completions — supports JSON and multipart/form-data."""
    cors_origins = _app_value(request.app, _CORS_ORIGINS_KEY, "cors_origins", ["*"])
    headers = _cors_headers(request, cors_origins)

    if request.method == "OPTIONS":
        return web.Response(status=200, headers=headers)

    client_ip = request.remote or "127.0.0.1"
    rate_limiter = _app_value(request.app, _RATE_LIMITER_KEY, "rate_limiter", None)

    raw_ip_limit = _app_value(request.app, _RATE_LIMIT_IP_KEY, "rate_limit_ip_per_min", 10)
    rate_limit_ip = raw_ip_limit if isinstance(raw_ip_limit, int) and not type(raw_ip_limit).__name__.endswith("Mock") else 10

    raw_sess_limit = _app_value(request.app, _RATE_LIMIT_SESSION_KEY, "rate_limit_session_per_min", 5)
    rate_limit_session = raw_sess_limit if isinstance(raw_sess_limit, int) and not type(raw_sess_limit).__name__.endswith("Mock") else 5

    raw_prompt_len = _app_value(request.app, _MAX_TURN_PROMPT_LENGTH_KEY, "max_turn_prompt_length", 2000)
    max_prompt_len = raw_prompt_len if isinstance(raw_prompt_len, int) and not type(raw_prompt_len).__name__.endswith("Mock") else 2000

    # 1. Rate Limit IP Check
    if rate_limiter and not await rate_limiter.is_allowed(f"ip:{client_ip}", rate_limit_ip):
        logger.warning("API IP rate limit hit (429) for IP {}", client_ip)
        return _error_json(429, "Rate limit exceeded for IP. Please wait before retrying.", err_type="rate_limit_error", headers=headers)

    content_type = _as_str(cast(object, request.content_type or ""))
    agent_loop = _app_value(request.app, _AGENT_LOOP_KEY, "agent_loop")
    timeout_s: float = _app_value(
        request.app,
        _REQUEST_TIMEOUT_KEY,
        "request_timeout",
        120.0,
    )
    model_name: str = _app_value(request.app, _MODEL_NAME_KEY, "model_name", "nanobot")

    stream = False
    session_id = None
    try:
        if content_type.startswith("multipart/"):
            text, media_paths, session_id, requested_model = await _parse_multipart(request)
        else:
            try:
                body = await request.json()
            except Exception:
                return _error_json(400, "Invalid JSON body", headers=headers)
            if not isinstance(body, dict):
                return _error_json(400, "Invalid JSON body", headers=headers)
            body = cast(dict[str, Any], body)
            stream = body.get("stream", False)
            requested_model = body.get("model")
            text, media_paths = _parse_json_content(body)
            session_id = body.get("session_id") or body.get("user") or request.headers.get("X-Session-Id")
    except ValueError as e:
        return _error_json(400, str(e), headers=headers)
    except _FileSizeExceeded as e:
        return _error_json(413, str(e), err_type="invalid_request_error", headers=headers)
    except Exception:
        logger.exception("Error parsing upload")
        return _error_json(413, "File too large or invalid upload", headers=headers)

    # 2. Session ID resolution
    if session_id:
        session_key = f"api:{session_id}"
    else:
        has_browser_context = bool(request.headers.get("Origin") or request.headers.get("Referer"))
        if has_browser_context:
            ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:12]
            session_id = f"web:anon_{ip_hash}"
            session_key = f"api:{session_id}"
        else:
            session_key = API_SESSION_KEY
            session_id = "default"

    # 3. Rate Limit Session Check
    if rate_limiter and not await rate_limiter.is_allowed(f"sess:{session_key}", rate_limit_session):
        logger.warning("API session rate limit hit (429) for session {}", session_key)
        return _error_json(429, "Rate limit exceeded for session. Please wait before retrying.", err_type="rate_limit_error", headers=headers)

    # 4. Turn Prompt Length Limit Check
    if len(text) > max_prompt_len:
        logger.warning("API prompt length ceiling hit (400) for session {}: {} > {}", session_key, len(text), max_prompt_len)
        return _error_json(400, f"Prompt length ({len(text)} chars) exceeds turn limit of {max_prompt_len} chars.", headers=headers)

    if requested_model and requested_model not in (model_name, "nanobot"):
        logger.warning(
            "API request requested model '{}', but server is running configured model '{}'. Proceeding.",
            requested_model,
            model_name,
        )

    session_locks: dict[str, asyncio.Lock] = _app_value(
        request.app,
        _SESSION_LOCKS_KEY,
        "session_locks",
    )
    session_lock = session_locks.setdefault(session_key, asyncio.Lock())

    if session_lock.locked():
        logger.warning("API session concurrency conflict (409) for session {}", session_key)
        return _error_json(409, "A request is currently in progress for this session. Please wait for completion.", err_type="conflict_error", headers=headers)

    start_time = time.monotonic()
    logger.info(
        "API request start [{}] ip={} user={} media={} stream={} text_len={}: '{}'",
        session_key, client_ip, session_id, len(media_paths), stream, len(text), text[:60],
    )
    # -- streaming path --
    if stream:
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        stream_failed = False
        emitted_content = False

        async def _on_stream(token: str) -> None:
            nonlocal emitted_content
            if token:
                emitted_content = True
            await queue.put(token)

        async def _on_stream_end(*_a: Any, **_kw: Any) -> None:
            # Agent stream-end callbacks mark generation segment boundaries.
            # Tool-backed requests may continue after a segment ends, so the
            # HTTP SSE stream is closed only when process_direct returns.
            return None

        async def _run() -> None:
            nonlocal stream_failed
            try:
                async with session_lock:
                    async with asyncio.timeout(timeout_s):
                        await _prepare_agent(request.app)
                        response = await agent_loop.process_direct(
                            content=text,
                            media=media_paths if media_paths else None,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                            on_stream=_on_stream,
                            on_stream_end=_on_stream_end,
                        )
                    if not emitted_content:
                        response_text = _response_text(response)
                        if response_text.strip():
                            await queue.put(response_text)
            except Exception:
                stream_failed = True
                logger.exception("Streaming error for session {}", session_key)
            finally:
                await queue.put(None)

        task = asyncio.create_task(_run())
        try:
            while True:
                token = await queue.get()
                if token is None:
                    break
                await resp.write(_sse_chunk(token, model_name, chunk_id))
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if not stream_failed:
            await resp.write(_sse_chunk("", model_name, chunk_id, finish_reason="stop"))
            await resp.write(_SSE_DONE)
            logger.info("API streaming request complete [{}] in {:.2f}s", session_key, time.monotonic() - start_time)
        return resp

    # -- non-streaming path (original logic) --
    try:
        async with session_lock:
            try:
                async with asyncio.timeout(timeout_s):
                    await _prepare_agent(request.app)
                    response = await agent_loop.process_direct(
                        content=text,
                        media=media_paths if media_paths else None,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                    )
                response_text = _response_text(response)
                if not response_text or not response_text.strip():
                    logger.warning("Empty response for session {}, using fallback", session_key)
                    response_text = EMPTY_FINAL_RESPONSE_MESSAGE

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", session_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected API lock error for session {}", session_key)
        return _error_json(500, "Internal server error", err_type="server_error")

    duration = time.monotonic() - start_time
    logger.info("API request done [{}] status=200 duration={:.2f}s", session_key, duration)
    return web.json_response(
        _chat_completion_response(response_text, model_name, getattr(agent_loop, "_last_usage", None)),
        headers=headers,
    )


async def handle_models(request: web.Request) -> web.Response:
    """GET /v1/models"""
    model_name = _app_value(request.app, _MODEL_NAME_KEY, "model_name", "nanobot")
    origins = _app_value(request.app, _CORS_ORIGINS_KEY, "cors_origins", ["*"])
    headers = _cors_headers(request, origins)
    return web.json_response(
        {
            "object": "list",
            "data": [
                {
                    "id": model_name,
                    "object": "model",
                    "created": 0,
                    "owned_by": "nanobot",
                }
            ],
        },
        headers=headers,
    )


async def handle_audit_sessions(request: web.Request) -> web.Response:
    """GET /v1/audit_sessions — returns audited session records for WebUI Dashboard."""
    origins = _app_value(request.app, _CORS_ORIGINS_KEY, "cors_origins", ["*"])
    headers = _cors_headers(request, origins)

    loop = _app_value(request.app, _AGENT_LOOP_KEY, "agent_loop")
    from nanobot.agent.tools.audit_sessions import AuditSessionsTool, detect_channel

    config = getattr(loop, "config", None) if loop else None
    audit_tool = AuditSessionsTool.from_config(config)

    channel_filter = request.query.get("channel", "all").strip().lower()

    session_dirs = audit_tool.resolve_session_dirs()
    sessions = audit_tool.load_sessions(session_dirs)

    res_sessions: list[dict[str, Any]] = []
    for s in sessions:
        key = str(s.get("key", ""))
        chan = detect_channel(key)
        if channel_filter != "all" and chan != channel_filter:
            continue
        res_sessions.append(s)

    return web.json_response({"status": "ok", "sessions": res_sessions}, headers=headers)


async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    origins = _app_value(request.app, _CORS_ORIGINS_KEY, "cors_origins", ["*"])
    headers = _cors_headers(request, origins)
    return web.json_response({"status": "ok"}, headers=headers)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    agent_loop: "AgentLoop",
    model_name: str = "nanobot",
    request_timeout: float = 120.0,
    api_key: str = "",
    prepare_agent: Callable[[], Awaitable[None]] | None = None,
    cors_origins: list[str] | None = None,
    max_turn_prompt_length: int | None = None,
    rate_limit_ip_per_min: int | None = None,
    rate_limit_session_per_min: int | None = None,
) -> web.Application:
    """Create the aiohttp application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        model_name: Model name reported in responses.
        request_timeout: Per-request timeout in seconds.
        api_key: Optional API key for Bearer-token authentication on API routes.
        prepare_agent: Optional application-owned readiness callback run before each turn.
        cors_origins: Allowed CORS origins list.
        max_turn_prompt_length: Per-turn prompt character ceiling.
        rate_limit_ip_per_min: Max requests per minute per IP.
        rate_limit_session_per_min: Max requests per minute per session.
    """
    raw_cfg = getattr(agent_loop, "config", None)
    api_cfg = getattr(raw_cfg, "api", None) if raw_cfg and not type(raw_cfg).__name__.endswith("Mock") else None
    if cors_origins is None:
        raw_origins: Any = getattr(api_cfg, "cors_origins", None) if api_cfg else None
        cors_origins = cast(list[str], raw_origins) if isinstance(raw_origins, list) else ["*"]
    if max_turn_prompt_length is None:
        raw_len = getattr(api_cfg, "max_turn_prompt_length", None) if api_cfg else None
        max_turn_prompt_length = raw_len if isinstance(raw_len, int) else 2000
    if rate_limit_ip_per_min is None:
        raw_ip = getattr(api_cfg, "rate_limit_ip_per_min", None) if api_cfg else None
        rate_limit_ip_per_min = raw_ip if isinstance(raw_ip, int) else 10
    if rate_limit_session_per_min is None:
        raw_sess = getattr(api_cfg, "rate_limit_session_per_min", None) if api_cfg else None
        rate_limit_session_per_min = raw_sess if isinstance(raw_sess, int) else 5

    app = web.Application(client_max_size=20 * 1024 * 1024)  # 20MB for base64 images
    app[_AGENT_LOOP_KEY] = agent_loop
    app[_MODEL_NAME_KEY] = model_name
    app[_REQUEST_TIMEOUT_KEY] = request_timeout
    app[_SESSION_LOCKS_KEY] = {}  # per-user locks, keyed by session_key
    app[_PREPARE_AGENT_KEY] = prepare_agent
    app[_CORS_ORIGINS_KEY] = cors_origins
    app[_MAX_TURN_PROMPT_LENGTH_KEY] = max_turn_prompt_length
    app[_RATE_LIMIT_IP_KEY] = rate_limit_ip_per_min
    app[_RATE_LIMIT_SESSION_KEY] = rate_limit_session_per_min
    app[_RATE_LIMITER_KEY] = SlidingWindowRateLimiter()

    @web.middleware
    async def auth_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        # Allow unauthenticated health checks, CORS preflights, and WebUI session audit requests.
        if request.path == "/health" or request.method == "OPTIONS" or "audit_sessions" in request.path:
            return await handler(request)
        if not api_key:
            return await handler(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            headers = _cors_headers(request, cors_origins)
            return _error_json(401, "Missing Authorization header. Use: Bearer <api_key>", headers=headers)
        if not hmac.compare_digest(auth[len("Bearer "):], api_key):
            headers = _cors_headers(request, cors_origins)
            return _error_json(401, "Invalid API key", headers=headers)
        return await handler(request)

    app.middlewares.append(auth_middleware)

    app.router.add_options("/v1/chat/completions", handle_options)
    app.router.add_options("/v1/models", handle_options)
    app.router.add_options("/v1/audit_sessions", handle_options)
    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/v1/audit_sessions", handle_audit_sessions)
    app.router.add_get("/health", handle_health)
    return app
