"""Variable path resolution, template interpolation, and choice rule evaluation."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from nanobot.workflow.schema import ChoiceRule

_TEMPLATE_VAR_RE = re.compile(r"(?:\{\{|\$\{)\s*(\$?\.?[a-zA-Z0-9_.\-\[\]]+)\s*(?:\}\}|\})")
_INDEX_SPLIT_RE = re.compile(r"\[(\d+)\]")


def _clean_path(path: str) -> list[str | int]:
    """Parse a dot/index notation path into list of keys/indices.

    Examples:
        "$.inbox.latest" -> ["inbox", "latest"]
        "items[0].name"  -> ["items", 0, "name"]
        "result"         -> ["result"]
    """
    clean = path.strip()
    if clean.startswith("$"):
        clean = clean[1:]
    if clean.startswith("."):
        clean = clean[1:]

    parts: list[str | int] = []
    for chunk in clean.split("."):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Check for array indices like items[0]
        if "[" in chunk and chunk.endswith("]"):
            base = chunk[:chunk.find("[")]
            if base:
                parts.append(base)
            for match in _INDEX_SPLIT_RE.finditer(chunk):
                parts.append(int(match.group(1)))
        else:
            parts.append(chunk)
    return parts


def resolve_path(data: Any, path: str, default: Any = None) -> Any:
    """Resolve a nested path from a dictionary or list."""
    if not path or not path.strip():
        return data
    parts = _clean_path(path)
    current: Any = data
    for part in parts:
        if current is None:
            return default
        if isinstance(part, int):
            if isinstance(current, (list, tuple)) and 0 <= part < len(cast(list[Any], current)):
                current = cast(list[Any], current)[part]
            else:
                return default
        elif isinstance(current, dict):
            dict_cur = cast(dict[str, Any], current)
            if part in dict_cur:
                current = dict_cur[part]
            else:
                return default
        else:
            return default
    return current


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    """Set a value at a nested path, creating intermediate dicts as necessary."""
    parts = _clean_path(path)
    if not parts:
        return
    current: dict[str, Any] = data
    for part in parts[:-1]:
        if isinstance(part, int):
            continue
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]

    last_part = parts[-1]
    if isinstance(last_part, str):
        current[last_part] = value


def interpolate_template(template: str, context: dict[str, Any]) -> str:
    """Interpolate {{$.path}} or ${$.path} placeholders in a string template."""
    if not template or ("{{" not in template and "${" not in template):
        return template

    def _replace_braced(match: re.Match[str]) -> str:
        var_path = match.group(1)
        val = resolve_path(context, var_path)
        if val is None:
            return ""
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)

    return _TEMPLATE_VAR_RE.sub(_replace_braced, template)


def interpolate_obj(obj: Any, context: dict[str, Any]) -> Any:
    """Recursively interpolate string templates in dicts, lists, and primitives."""
    if isinstance(obj, str):
        return interpolate_template(obj, context)
    if isinstance(obj, dict):
        d_obj = cast(dict[Any, Any], obj)
        return {k: interpolate_obj(v, context) for k, v in d_obj.items()}
    if isinstance(obj, list):
        l_obj = cast(list[Any], obj)
        return [interpolate_obj(item, context) for item in l_obj]
    return obj


def evaluate_choice(rule: ChoiceRule, context: dict[str, Any]) -> bool:
    """Evaluate whether a ChoiceRule matches against the current execution context."""
    val = resolve_path(context, rule.variable)

    if rule.is_null is not None:
        return (val is None) == rule.is_null

    if rule.equals is not None:
        return val == rule.equals

    if rule.not_equals is not None:
        return val != rule.not_equals

    if rule.boolean_equals is not None:
        return bool(val) == rule.boolean_equals

    if rule.numeric_gt is not None:
        return isinstance(val, (int, float)) and val > rule.numeric_gt

    if rule.numeric_gte is not None:
        return isinstance(val, (int, float)) and val >= rule.numeric_gte

    if rule.numeric_lt is not None:
        return isinstance(val, (int, float)) and val < rule.numeric_lt

    if rule.numeric_lte is not None:
        return isinstance(val, (int, float)) and val <= rule.numeric_lte

    if rule.contains is not None:
        if isinstance(val, str):
            return rule.contains in val
        if isinstance(val, (list, tuple, set)):
            return rule.contains in val
        return False

    if rule.starts_with is not None:
        return isinstance(val, str) and val.startswith(rule.starts_with)

    if rule.ends_with is not None:
        return isinstance(val, str) and val.endswith(rule.ends_with)

    return False
