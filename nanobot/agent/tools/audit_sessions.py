"""Tool for reviewing, auditing, and generating reports for public and agent sessions."""

from __future__ import annotations

import base64
import html as html_lib
import json
import re
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.config.paths import (
    get_legacy_sessions_dir,
    get_runtime_subdir,
    get_sessions_dir,
    get_workspace_path,
)

_FLAG_KEYWORDS_RE = re.compile(
    r"\b(?:error|exception|failed|confused|unhelpful|wrong|invalid|issue|problem|broken|help)\b",
    re.IGNORECASE,
)


def _parse_timestamp(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        cleaned_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned_ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        try:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})", ts_str)
            if m:
                return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
        except Exception:
            pass
        return None


def _matches_timeframe(dt: datetime | None, timeframe: str) -> bool:
    if not dt or timeframe == "all":
        return True
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    now = datetime.now()
    if timeframe == "today":
        return dt.date() == now.date()
    if timeframe == "yesterday":
        yesterday = (now - timedelta(days=1)).date()
        return dt.date() == yesterday
    if timeframe == "7d":
        return dt >= now - timedelta(days=7)
    if timeframe == "30d":
        return dt >= now - timedelta(days=30)
    return True


def _filter_messages_for_timeframe(
    messages: list[dict[str, Any]],
    timeframe: str,
    cursor_ts: str | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for m in messages:
        ts_str = str(m.get("timestamp") or "").strip()
        if cursor_ts and ts_str and ts_str <= cursor_ts:
            continue
        dt = _parse_timestamp(ts_str)
        if _matches_timeframe(dt, timeframe):
            filtered.append(m)
    return filtered


def _load_checkpoint(reports_dir: Path) -> dict[str, Any]:
    checkpoint_file = reports_dir / ".audit_checkpoint.json"
    if checkpoint_file.exists():
        try:
            raw = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return cast(dict[str, Any], raw)
        except Exception:
            pass
    return {"last_run_at": None, "sessions": {}}


def _save_checkpoint(reports_dir: Path, checkpoint: dict[str, Any]) -> None:
    try:
        checkpoint_file = reports_dir / ".audit_checkpoint.json"
        reports_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    except Exception:
        pass


def _decode_session_key(stem: str) -> str:
    if ":" in stem or "@" in stem:
        return stem

    for cand_str in (stem, stem + "=", stem + "=="):
        try:
            decoded = base64.urlsafe_b64decode(cand_str.encode("ascii")).decode("utf-8")
            if ":" in decoded or "@" in decoded:
                return decoded
        except Exception:
            pass
    return stem


def _parse_session_key_from_filename(stem: str) -> str:
    if ":" in stem:
        return stem

    decoded = _decode_session_key(stem)
    if decoded != stem and (":" in decoded or "@" in decoded):
        return decoded

    # Handle lossy filenames (e.g. api_whatsapp_123 -> api:whatsapp:123, whatsapp_123@g.us -> whatsapp:123@g.us)
    if stem.startswith("api_whatsapp_"):
        return "api:whatsapp:" + stem[13:]
    if stem.startswith("api_web_"):
        return "api:web:" + stem[8:]
    if stem.startswith("api_telegram_"):
        return "api:telegram:" + stem[13:]
    if stem.startswith("whatsapp_"):
        return "whatsapp:" + stem[9:]
    if stem.startswith("telegram_"):
        return "telegram:" + stem[9:]
    if stem.startswith("web_"):
        return "web:" + stem[4:]

    return stem


def _detect_node_info(file_path: Path, session_key: str) -> tuple[str, str]:
    path_parts = [p.lower() for p in file_path.parts]
    marker = file_path.parent / ".workspace"
    if marker.exists():
        with suppress(Exception):
            ws_path = marker.read_text(encoding="utf-8").lower()
            if "guide" in ws_path:
                return ("guide", "Guide Node")
    if (
        "guide-workspace" in path_parts
        or "guide" in path_parts
        or session_key.startswith("api:")
        or ":guide:" in session_key.lower()
        or "guide" in session_key.lower()
    ):
        return ("guide", "Guide Node")
    return ("primary", "Primary Node")


def _load_single_session_file(file_path: Path, index_map: dict[str, str] | None = None) -> dict[str, Any] | None:
    override_key = index_map.get(file_path.name) or index_map.get(file_path.stem) if index_map else None

    if file_path.suffix == ".json":
        try:
            raw_data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(raw_data, dict):
                dict_data: dict[str, Any] = cast(dict[str, Any], raw_data)
                dict_data["_file_path"] = str(file_path)
                raw_key = dict_data.get("key") or override_key
                session_key = str(raw_key) if isinstance(raw_key, str) and raw_key else _parse_session_key_from_filename(file_path.stem)
                dict_data["key"] = session_key
                node_type, node_label = _detect_node_info(file_path, session_key)
                dict_data["node_type"] = node_type
                dict_data["node_label"] = node_label
                return dict_data
        except Exception:
            return None

    if file_path.suffix == ".jsonl":
        try:
            lines = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                return None

            header: dict[str, Any] = {}
            messages: list[dict[str, Any]] = []

            for i, line in enumerate(lines):
                try:
                    obj: Any = json.loads(line)
                    if isinstance(obj, dict):
                        data = cast(dict[str, Any], obj)
                        if i == 0 and data.get("_type") == "metadata":
                            header = data
                            continue
                        if data.get("_type") != "provider_state":
                            if "role" in data or "content" in data or "timestamp" in data:
                                messages.append(data)
                except Exception:
                    continue

            raw_session_key = header.get("key") or override_key
            session_key = str(raw_session_key) if isinstance(raw_session_key, str) and raw_session_key else _parse_session_key_from_filename(file_path.stem)
            created_at = str(header.get("created_at") or "")
            updated_at = str(header.get("updated_at") or "")

            first_msg = messages[0] if messages else {}
            first_ts_val: Any = first_msg.get("timestamp") if "timestamp" in first_msg else None
            first_ts = str(first_ts_val) if first_ts_val is not None else ""

            last_msg = messages[-1] if messages else {}
            last_ts_val: Any = last_msg.get("timestamp") if "timestamp" in last_msg else None
            latest_ts = str(last_ts_val) if last_ts_val is not None else ""

            raw_metadata = header.get("metadata")
            metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}

            effective_created = created_at or first_ts
            effective_updated = updated_at or latest_ts or effective_created

            node_type, node_label = _detect_node_info(file_path, session_key)

            return {
                "_file_path": str(file_path),
                "key": session_key,
                "node_type": node_type,
                "node_label": node_label,
                "created_at": effective_created,
                "updated_at": effective_updated,
                "messages": messages,
                "metadata": metadata,
            }
        except Exception:
            return None

    return None


def _detect_channel(session_key: str) -> str:
    key_lower = session_key.lower()
    if "whatsapp" in key_lower:
        return "whatsapp"
    if "telegram" in key_lower:
        return "telegram"
    if "web" in key_lower:
        return "web"
    if "api" in key_lower:
        return "api"
    if "cli" in key_lower:
        return "cli"
    if "dream" in key_lower:
        return "system"
    return "other"


detect_channel = _detect_channel


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Action to perform: 'list' (list recent sessions), 'inspect' (view session transcript), "
            "'summary' (aggregate volume and topics), or 'flagged' (sessions with errors or unresolved issues)."
        ),
        channel=StringSchema(
            "Filter by channel name ('whatsapp', 'web', 'api', or 'all'). Default is 'all'."
        ),
        session_id=StringSchema(
            "Specific session ID or key to inspect (e.g. 'web:anon_9f8e7d' or 'whatsapp:13105551234@s.whatsapp.net'). Required for 'inspect'."
        ),
        timeframe=StringSchema(
            "Timeframe for summary or list ('today', 'yesterday', '7d', '30d', 'all'). Default is '7d'."
        ),
        limit=IntegerSchema(
            description="Maximum number of records to return. Default is 20."
        ),
        required=["action"],
    )
)
class AuditSessionsTool(Tool):
    """Tool for querying and auditing session logs across all channels."""

    @property
    def name(self) -> str:
        return "audit_sessions"

    @property
    def description(self) -> str:
        return (
            "Query, inspect, summarize, and audit session logs across Telegram, WhatsApp, Web, and API channels. "
            "Use to review user interactions, check for errors or unresolved questions, "
            "and compute usage statistics."
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        audit_cfg = getattr(ctx.config, "audit_sessions", None)
        return bool(getattr(audit_cfg, "enabled", True))

    def __init__(self, sessions_dirs: list[Path | str] | None = None) -> None:
        self._raw_sessions_dirs = (
            [Path(d) for d in sessions_dirs] if sessions_dirs else None
        )

    @classmethod
    def from_config(cls, config: Any, tool_config: Any = None) -> AuditSessionsTool:
        return cls()

    def _resolve_single_path(self, raw_path: Path | str, ws: Path) -> Path:
        p = Path(raw_path).expanduser()
        if p.is_absolute():
            return p
        ws_candidate = (ws / p).resolve()
        if ws_candidate.exists():
            return ws_candidate
        cwd_candidate = (Path.cwd() / p).resolve()
        if cwd_candidate.exists():
            return cwd_candidate
        return ws_candidate

    def resolve_session_dirs(self, ctx: ToolContext | None = None) -> list[Path]:
        return self._resolve_session_dirs(ctx)

    def _resolve_session_dirs(self, ctx: ToolContext | None = None) -> list[Path]:
        ws = get_workspace_path()
        if ctx and hasattr(ctx, "workspace") and getattr(ctx, "workspace", None):
            ws = Path(getattr(ctx, "workspace")).expanduser()

        if self._raw_sessions_dirs:
            return [self._resolve_single_path(d, ws) for d in self._raw_sessions_dirs]

        candidates: list[Path] = [
            get_runtime_subdir("sessions"),
            get_legacy_sessions_dir(),
            get_sessions_dir(),
            ws / "sessions",
            ws / "guide-workspace" / "sessions",
            Path.home() / ".nanobot" / "workspace" / "sessions",
            Path.home() / ".nanobot" / "workspace" / "guide-workspace" / "sessions",
            Path.cwd() / "sessions",
        ]
        existing: list[Path] = []
        for cand in candidates:
            cand_resolved = cand.resolve()
            if cand_resolved.exists() and cand_resolved.is_dir():
                if cand_resolved not in existing:
                    existing.append(cand_resolved)
                # Expand out-of-workspace workspace session subdirectories (e.g. ~/.nanobot/sessions/<workspace_id>/)
                with suppress(Exception):
                    for sub in cand_resolved.iterdir():
                        if sub.is_dir() and sub not in existing and not sub.name.startswith("."):
                            if (sub / ".workspace").exists() or (sub / "archives").exists() or list(sub.glob("*.json*")):
                                existing.append(sub)

        if existing:
            return existing
        return [get_runtime_subdir("sessions").resolve()]

    def load_sessions(self, dirs: list[Path]) -> list[dict[str, Any]]:
        return self._load_sessions(dirs)

    def _load_sessions(self, dirs: list[Path]) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for d in dirs:
            if not d.is_dir():
                continue

            # Load index mapping if present (.webui_session_index.json or .session_index.json)
            index_map: dict[str, str] = {}
            for index_filename in (".webui_session_index.json", ".session_index.json"):
                index_file = d / index_filename
                if index_file.exists():
                    try:
                        raw_idx = json.loads(index_file.read_text(encoding="utf-8"))
                        if isinstance(raw_idx, dict):
                            raw_dict = cast(dict[Any, Any], raw_idx)
                            for k, v in raw_dict.items():
                                if isinstance(k, str) and isinstance(v, str):
                                    index_map[v] = k
                                    index_map[Path(v).stem] = k
                    except Exception:
                        pass

            # Scan both .jsonl and .json files in main session dir and archives/ subfolder
            target_dirs = [d]
            archives_sub = d / "archives"
            if archives_sub.exists() and archives_sub.is_dir():
                target_dirs.append(archives_sub)

            file_paths: list[Path] = []
            for target_d in target_dirs:
                file_paths.extend([
                    f for f in list(target_d.glob("*.jsonl")) + list(target_d.glob("*.json"))
                    if not f.name.startswith(".")
                ])

            for file_path in file_paths:
                session_data = _load_single_session_file(file_path, index_map=index_map)
                if session_data:
                    key = str(session_data.get("key", ""))
                    # Use unique file-path key for archive snapshots to prevent dropping pre-reset turns
                    dedup_key = f"{key}:{file_path.name}" if "archives" in file_path.parts else key
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        sessions.append(session_data)
        return sessions

    def prune_expired_archives(self, dirs: list[Path], retention_days: int = 30) -> int:
        """Prune archived session snapshot files older than retention_days."""
        if retention_days < 0:
            return 0
        now = datetime.now()
        pruned_count = 0
        for d in dirs:
            archives_dir = d / "archives" if d.name != "archives" else d
            if not archives_dir.exists() or not archives_dir.is_dir():
                continue
            for f in list(archives_dir.glob("*.json")) + list(archives_dir.glob("*.jsonl")):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if now - mtime >= timedelta(days=retention_days):
                        f.unlink()
                        pruned_count += 1
                except Exception:
                    pass
        return pruned_count

    async def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()
        channel_filter = str(kwargs.get("channel", "all")).strip().lower()
        timeframe = str(kwargs.get("timeframe", "7d")).strip().lower()
        session_id_query = str(kwargs.get("session_id", "")).strip()
        limit = int(kwargs.get("limit", 20))

        ctx = args[0] if args else getattr(self, "context", None)
        session_dirs = self._resolve_session_dirs(ctx)
        if not session_dirs:
            return ToolResult.error(
                "No valid session directories found to audit. Please check session store configuration."
            )

        sessions = self._load_sessions(session_dirs)

        if action == "list":
            return ToolResult(self._action_list(sessions, channel_filter, timeframe, limit))
        if action == "inspect":
            if not session_id_query:
                return ToolResult.error("session_id parameter is required for action='inspect'.")
            res_str = self._action_inspect(sessions, session_id_query)
            if res_str.startswith("Error:"):
                return ToolResult.error(res_str)
            return ToolResult(res_str)
        if action == "summary":
            return ToolResult(self._action_summary(sessions, channel_filter, timeframe))
        if action == "flagged":
            return ToolResult(self._action_flagged(sessions, channel_filter, timeframe, limit))
        if action == "generate_report":
            return ToolResult(await self._action_generate_report(ctx, sessions, channel_filter, timeframe))

        return ToolResult.error(
            f"Unknown action '{action}'. Supported actions: 'list', 'inspect', 'summary', 'flagged', 'generate_report'."
        )

    def _action_list(
        self,
        sessions: list[dict[str, Any]],
        channel_filter: str,
        timeframe: str,
        limit: int,
    ) -> str:
        filtered: list[tuple[datetime, dict[str, Any]]] = []
        for s in sessions:
            key = s.get("key", "")
            chan = _detect_channel(key)
            if channel_filter != "all" and chan != channel_filter:
                continue
            dt = _parse_timestamp(s.get("updated_at") or s.get("created_at"))
            if _matches_timeframe(dt, timeframe):
                filtered.append((dt or datetime.min, s))

        filtered.sort(key=lambda x: x[0], reverse=True)
        results = filtered[:limit]

        lines = [f"### Session Audit List ({len(results)} of {len(filtered)} matching sessions)\n"]
        lines.append("| Session Key | Channel | Node Workspace | Messages | Created At | Last Updated |")
        lines.append("|---|---|---|---|---|---|")

        for dt, s in results:
            key = s.get("key", "unknown")
            chan = _detect_channel(key)
            node_lbl = str(s.get("node_label", "Primary Node"))
            msg_count = len(s.get("messages", []))
            created = (s.get("created_at") or "")[:19]
            updated = (s.get("updated_at") or "")[:19]
            lines.append(f"| `{key}` | {chan} | {node_lbl} | {msg_count} | {created} | {updated} |")

        return "\n".join(lines)

    def _action_inspect(
        self,
        sessions: list[dict[str, Any]],
        session_id_query: str,
    ) -> str:
        target: dict[str, Any] | None = None
        for s in sessions:
            key = s.get("key", "")
            if session_id_query in (key, key.replace("api:", ""), s.get("_file_path", "")):
                target = s
                break

        if not target:
            # Substring search fallback
            for s in sessions:
                if session_id_query in s.get("key", ""):
                    target = s
                    break

        if not target:
            return f"Error: Session matching '{session_id_query}' not found."

        key = target.get("key", "unknown")
        created = target.get("created_at", "")[:19]
        updated = target.get("updated_at", "")[:19]
        messages = target.get("messages", [])
        node_lbl = str(target.get("node_label", "Primary Node"))
        file_path = str(target.get("_file_path", ""))

        lines = [f"### Session Transcript: `{key}`"]
        lines.append(f"- **Node Workspace**: **{node_lbl}** (`{file_path}`)")
        lines.append(f"- **Created**: {created}")
        lines.append(f"- **Last Updated**: {updated}")
        lines.append(f"- **Total Turns**: {len(messages)}\n")
        lines.append("---")

        for msg in messages:
            role = msg.get("role", "unknown").upper()
            ts = (msg.get("timestamp") or "")[:19]
            content = str(msg.get("content", "")).strip()
            lines.append(f"\n**[{ts}] {role}:**\n{content}")

        return "\n".join(lines)

    def _action_summary(
        self,
        sessions: list[dict[str, Any]],
        channel_filter: str,
        timeframe: str,
    ) -> str:
        channel_counts: dict[str, int] = {}
        node_counts: dict[str, int] = {}
        total_messages = 0
        matching_sessions = 0
        initial_questions: list[str] = []

        for s in sessions:
            key = s.get("key", "")
            chan = _detect_channel(key)
            node_lbl = str(s.get("node_label", "Primary Node"))
            if channel_filter != "all" and chan != channel_filter:
                continue

            msgs = s.get("messages", [])
            new_msgs = _filter_messages_for_timeframe(msgs, timeframe)
            if not new_msgs:
                continue

            matching_sessions += 1
            channel_counts[chan] = channel_counts.get(chan, 0) + 1
            node_counts[node_lbl] = node_counts.get(node_lbl, 0) + 1
            total_messages += len(new_msgs)

            # Extract first user message in timeframe as initial question
            for m in new_msgs:
                if m.get("role") == "user":
                    text = str(m.get("content", "")).strip()
                    if text:
                        initial_questions.append(text[:80])
                    break

        avg_msgs = round(total_messages / matching_sessions, 1) if matching_sessions > 0 else 0.0

        lines = [f"### Session Summary Report (Timeframe: `{timeframe}`)\n"]
        lines.append(f"- **Total Matching Sessions**: {matching_sessions}")
        lines.append(f"- **Total New Conversation Messages**: {total_messages}")
        lines.append(f"- **Average New Messages / Session**: {avg_msgs}\n")

        lines.append("#### Workspace Breakdown")
        for node, cnt in node_counts.items():
            lines.append(f"- **{node}**: {cnt} sessions")

        lines.append("\n#### Channel Breakdown")
        for chan, cnt in channel_counts.items():
            lines.append(f"- **{chan}**: {cnt} sessions")

        if initial_questions:
            lines.append("\n#### Recent User Queries (Sample)")
            for q in initial_questions[:10]:
                lines.append(f"- \"{q}\"")

        return "\n".join(lines)

    def _action_flagged(
        self,
        sessions: list[dict[str, Any]],
        channel_filter: str,
        timeframe: str,
        limit: int,
    ) -> str:
        flagged: list[tuple[str, str, dict[str, Any]]] = []

        for s in sessions:
            key = s.get("key", "")
            chan = _detect_channel(key)
            if channel_filter != "all" and chan != channel_filter:
                continue

            msgs = s.get("messages", [])
            new_msgs = _filter_messages_for_timeframe(msgs, timeframe)
            if not new_msgs:
                continue

            has_flag = False
            flag_reason = ""

            for m in new_msgs:
                role = m.get("role")
                content = str(m.get("content", "")).strip()

                if role == "assistant" and not content:
                    has_flag = True
                    flag_reason = "Empty assistant response"
                    break

                if _FLAG_KEYWORDS_RE.search(content):
                    has_flag = True
                    flag_reason = f"Keyword match in message ('{content[:40]}...')"
                    break

            if has_flag:
                flagged.append((flag_reason, key, s))

        results = flagged[:limit]

        lines = [f"### Flagged Sessions ({len(results)} of {len(flagged)} matching flagged sessions)\n"]
        if not results:
            lines.append("No sessions flagged for errors or issues in this timeframe.")
            return "\n".join(lines)

        lines.append("| Session Key | Channel | Node Workspace | Reason | Messages | Last Updated |")
        lines.append("|---|---|---|---|---|---|")

        for reason, key, s in results:
            chan = _detect_channel(key)
            node_lbl = str(s.get("node_label", "Primary Node"))
            msg_count = len(s.get("messages", []))
            updated = (s.get("updated_at") or "")[:19]
            lines.append(f"| `{key}` | {chan} | {node_lbl} | {reason} | {msg_count} | {updated} |")

        return "\n".join(lines)

    async def _action_generate_report(
        self,
        ctx: ToolContext | None,
        sessions: list[dict[str, Any]],
        channel_filter: str,
        timeframe: str,
    ) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Resolve reports directory
        ws = get_workspace_path()
        if ctx and hasattr(ctx, "workspace") and getattr(ctx, "workspace", None):
            ws = Path(getattr(ctx, "workspace")).expanduser()

        reports_dir = self._resolve_single_path("./audit_reports", ws)
        audit_cfg = getattr(ctx.config, "audit_sessions", None) if ctx and hasattr(ctx, "config") else None
        if audit_cfg is not None:
            custom_reports = getattr(audit_cfg, "reports_dir", None)
            if custom_reports and not type(custom_reports).__name__.endswith("Mock"):
                reports_dir = self._resolve_single_path(str(custom_reports), ws)

        reports_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = _load_checkpoint(reports_dir)

        html_content = self._build_html_content(sessions, channel_filter, timeframe, date_str, checkpoint)

        report_file = reports_dir / f"{date_str}.html"
        report_file.write_text(html_content, encoding="utf-8")

        # Update checkpoint cursor
        checkpoint["last_run_at"] = datetime.now().isoformat()
        session_cursors: dict[str, str] = checkpoint.get("sessions", {})
        for s in sessions:
            key = str(s.get("key", ""))
            if not key:
                continue
            msgs = s.get("messages", [])
            max_ts = max([str(m.get("timestamp") or "") for m in msgs if m.get("timestamp")], default="")
            if max_ts:
                session_cursors[key] = max_ts
        checkpoint["sessions"] = session_cursors
        _save_checkpoint(reports_dir, checkpoint)

        # Multi-Channel Dispatch
        dispatched_channels: list[str] = []
        bus: Any = getattr(ctx, "bus", None) if ctx else None
        if bus is not None:
            audit_cfg = getattr(ctx.config, "audit_sessions", None) if ctx and hasattr(ctx, "config") else None
            raw_wa = getattr(audit_cfg, "dispatch_whatsapp_jid", "") if audit_cfg else ""
            wa_jid = str(raw_wa) if raw_wa and not type(raw_wa).__name__.endswith("Mock") else ""

            raw_tg = getattr(audit_cfg, "dispatch_telegram_chat_id", "") if audit_cfg else ""
            tg_id = str(raw_tg) if raw_tg and not type(raw_tg).__name__.endswith("Mock") else ""

            summary_msg = (
                f"📊 *Daily Guide Audit Summary ({date_str})*\n"
                f"• Report File: `{report_file}`\n"
                f"• Timeframe: `{timeframe}`\n"
                f"• Channel Filter: `{channel_filter}`\n"
                f"• Evaluated Sessions: {len(sessions)}"
            )

            from nanobot.bus.events import OutboundMessage

            if wa_jid.strip():
                try:
                    await bus.publish_outbound(OutboundMessage(channel="whatsapp", chat_id=wa_jid, content=summary_msg))
                    dispatched_channels.append(f"WhatsApp (`{wa_jid}`)")
                except Exception:
                    pass

            if tg_id.strip():
                try:
                    await bus.publish_outbound(OutboundMessage(channel="telegram", chat_id=tg_id, content=summary_msg))
                    dispatched_channels.append(f"Telegram (`{tg_id}`)")
                except Exception:
                    pass

        dirs = self._resolve_session_dirs(ctx)
        retention_days = int(getattr(audit_cfg, "retention_days", 30))
        pruned = self.prune_expired_archives(dirs, retention_days=retention_days)

        dispatch_str = ", ".join(dispatched_channels) if dispatched_channels else "None (No staff channels configured or active)"

        res_lines = [
            "### Daily Audit Report Generated Successfully\n",
            f"- **Saved Report File**: `{report_file.resolve()}`",
            f"- **Checkpoint File**: `{reports_dir.resolve()}/.audit_checkpoint.json`",
            f"- **Report Date**: `{date_str}`",
            f"- **Dispatched Staff Channels**: {dispatch_str}",
            f"- **Sessions Processed**: {len(sessions)}",
        ]
        if pruned > 0:
            res_lines.append(f"- **Pruned Expired Archives**: {pruned} snapshot file(s) (> {retention_days} days old)")
        return "\n".join(res_lines)

    def _build_html_content(
        self,
        sessions: list[dict[str, Any]],
        channel_filter: str,
        timeframe: str,
        date_str: str,
        checkpoint: dict[str, Any] | None = None,
    ) -> str:
        matching_sessions: list[dict[str, Any]] = []
        channel_counts: dict[str, int] = {}
        node_counts: dict[str, int] = {}
        total_new_turns = 0
        flagged_count = 0
        cursor_map: dict[str, str] = checkpoint.get("sessions", {}) if checkpoint else {}

        for s in sessions:
            key = s.get("key", "")
            chan = _detect_channel(key)
            node_lbl = str(s.get("node_label", "Primary Node"))
            if channel_filter != "all" and chan != channel_filter:
                continue

            msgs = s.get("messages", [])
            cursor_ts = cursor_map.get(key)
            new_msgs = _filter_messages_for_timeframe(msgs, timeframe, cursor_ts=cursor_ts)
            dt = _parse_timestamp(s.get("updated_at") or s.get("created_at"))

            # Include session if session updated in timeframe or contains new messages
            if not _matches_timeframe(dt, timeframe) and not new_msgs:
                continue

            matching_sessions.append(s)
            channel_counts[chan] = channel_counts.get(chan, 0) + 1
            node_counts[node_lbl] = node_counts.get(node_lbl, 0) + 1
            total_new_turns += len(new_msgs) if new_msgs else len(msgs)

            for m in (new_msgs or msgs):
                if (m.get("role") == "assistant" and not str(m.get("content", "")).strip()) or _FLAG_KEYWORDS_RE.search(str(m.get("content", ""))):
                    flagged_count += 1
                    break

        avg_msgs = round(total_new_turns / len(matching_sessions), 1) if matching_sessions else 0.0

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Guide Audit Report - {date_str}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ color: #38bdf8; font-size: 24px; border-bottom: 2px solid #334155; padding-bottom: 10px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .card {{ background: #1e293b; padding: 15px; border-radius: 8px; border: 1px solid #334155; }}
        .card .metric {{ font-size: 28px; font-weight: bold; color: #38bdf8; }}
        .card .label {{ font-size: 14px; color: #94a3b8; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; background: #1e293b; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; text-transform: uppercase; font-size: 12px; }}
        .badge {{ background: #0284c7; color: white; padding: 3px 8px; border-radius: 12px; font-size: 12px; }}
        .badge-guide {{ background: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); padding: 3px 8px; border-radius: 12px; font-size: 11px; margin-left: 6px; }}
        .badge-primary {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); padding: 3px 8px; border-radius: 12px; font-size: 11px; margin-left: 6px; }}
        .badge-new {{ background: #22c55e; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 6px; }}
        details {{ margin-top: 10px; background: #1e293b; padding: 10px 15px; border-radius: 6px; border: 1px solid #334155; }}
        summary {{ font-weight: bold; cursor: pointer; color: #38bdf8; display: flex; align-items: center; justify-content: space-between; }}
        .msg {{ margin: 8px 0; padding: 8px; border-radius: 4px; background: #0f172a; }}
        .msg.user {{ border-left: 3px solid #38bdf8; }}
        .msg.assistant {{ border-left: 3px solid #22c55e; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Daily Guide Audit Report ({date_str})</h1>
        <div class="grid">
            <div class="card"><div class="metric">{len(matching_sessions)}</div><div class="label">Active Sessions</div></div>
            <div class="card"><div class="metric">{total_new_turns}</div><div class="label">New Turns</div></div>
            <div class="card"><div class="metric">{avg_msgs}</div><div class="label">Avg New Turns / Session</div></div>
            <div class="card"><div class="metric" style="color: #ef4444;">{flagged_count}</div><div class="label">Flagged Sessions</div></div>
        </div>

        <h2>Workspace & Channel Distribution</h2>
        <div style="margin-bottom: 20px;">
"""
        for node, cnt in node_counts.items():
            safe_node = html_lib.escape(node)
            b_cls = "badge-guide" if "guide" in node.lower() else "badge-primary"
            html += f'            <span class="{b_cls}">{safe_node}: {cnt}</span>\n'

        for chan, cnt in channel_counts.items():
            safe_chan = html_lib.escape(chan)
            html += f'            <span class="badge">{safe_chan}: {cnt}</span>\n'

        html += """        </div>

        <h2>Session Transcripts</h2>
"""
        for s in matching_sessions[:50]:
            key_str = str(s.get("key", "unknown"))
            key = html_lib.escape(key_str)
            node_lbl = str(s.get("node_label", "Primary Node"))
            b_cls = "badge-guide" if "guide" in node_lbl.lower() else "badge-primary"
            node_badge = f'<span class="{b_cls}">{html_lib.escape(node_lbl)}</span>'
            msgs = s.get("messages", [])
            cursor_ts = cursor_map.get(key_str)
            updated = html_lib.escape((s.get("updated_at") or "")[:19])
            html += f"""        <details>
            <summary><span><code>{key}</code> {node_badge}</span> <span>({len(msgs)} total msgs, updated {updated})</span></summary>
"""
            for m in msgs:
                role = html_lib.escape(str(m.get("role", "unknown")).lower())
                content = html_lib.escape(str(m.get("content", "")).strip())
                ts_raw = str(m.get("timestamp") or "")
                ts = html_lib.escape(ts_raw[:19])
                is_new = not cursor_ts or (ts_raw > cursor_ts)
                new_tag = '<span class="badge-new">NEW</span>' if is_new else ''
                html += f'            <div class="msg {role}"><strong>[{ts}] {role.upper()}:</strong> {content} {new_tag}</div>\n'
            html += "        </details>\n"

        html += """    </div>
</body>
</html>"""
        return html

