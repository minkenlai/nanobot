"""Model calibration manager for prompt token ratio tracking.

Maintains per-family calibration ratios (actual / estimated) so that
tiktoken-based prompt token estimates can be corrected toward the
real usage reported by LLM providers.

Ratios are persisted to `model_calibration.json` in the workspace root.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Final

# ---------------------------------------------------------------------------
# Model series (family) → concrete model IDs
# Loaded from workspace/model_map.json
# ---------------------------------------------------------------------------
from nanobot.config.paths import get_workspace_path


def _load_model_map() -> Dict[str, tuple[str, ...]]:
    """Load model series mapping from workspace/model_map.json."""
    try:
        model_map_file = get_workspace_path() / "model_map.json"
        text = model_map_file.read_text(encoding="utf-8")
        data = json.loads(text)
        return {k: tuple(v) for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


# We initialize MODEL_SERIES and _MODEL_TO_SERIES lazily or at module level.
# Note: get_workspace_path() is safe to call at module level as it uses defaults.
MODEL_SERIES: Dict[str, tuple[str, ...]] = _load_model_map()
_MODEL_TO_SERIES: Dict[str, str] = {}
for _series, _ids in MODEL_SERIES.items():
    for _mid in _ids:
        _MODEL_TO_SERIES[_mid] = _series

del _series, _ids, _mid  # cleanup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_RATIO: Final[float] = 1.0
_ALPHA: Final[float] = 0.1  # moving-average smoothing factor

# Resolve workspace root:
_CALIBRATION_FILE: Final[Path] = get_workspace_path() / "model_calibration.json"


def _load_calibration_data() -> dict:
    """Load persisted calibration data, returning empty structure on error."""
    try:
        text = _CALIBRATION_FILE.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_calibration_data(data: dict) -> None:
    """Atomically persist calibration data via a temp file + rename."""
    parent = _CALIBRATION_FILE.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp = _CALIBRATION_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CALIBRATION_FILE)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# ModelCalibrationManager
# ---------------------------------------------------------------------------


class ModelCalibrationManager:
    """Thread-safe manager for model token-estimation calibration ratios.

    Each model family (series) gets a single ratio that converges toward
    the true `actual / estimated` via exponential moving average (alpha=0.1).

    Resolution order for :meth:`get_ratio`:
        1. Look up model ID in :data:`MODEL_SERIES` → return series ratio.
        2. Look up model ID directly in persisted ratios → return it.
        3. Default to ``1.0`` (no calibration).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        raw = _load_calibration_data()

        # `series` persisted data (may add user-defined families later)
        self.series: Dict[str, list[str]] = {}
        if "series" in raw and isinstance(raw["series"], dict):
            for _k, _v in raw["series"].items():
                if isinstance(_v, list):
                    self.series[_k] = _v

        # `ratios` persisted data
        self.ratios: Dict[str, float] = {}
        if "ratios" in raw and isinstance(raw["ratios"], dict):
            for _k, _v in raw["ratios"].items():
                if isinstance(_v, (int, float)):
                    self.ratios[_k] = float(_v)

    # -- public API ----------------------------------------------------------

    def get_ratio(self, model_id: str) -> float:
        """Return the calibration ratio for *model_id*.

        Resolution order:
            1. Series membership (``MODEL_SERIES`` or persisted ``self.series``).
            2. Direct persisted ratio for the model ID.
            3. Default ``1.0``.
        """
        with self._lock:
            # 1. Built-in series
            series_key = _MODEL_TO_SERIES.get(model_id)
            if series_key is not None:
                return self.ratios.get(series_key, _DEFAULT_RATIO)

            # 1b. Persisted (user-defined) series
            for _sk, _sids in self.series.items():
                if model_id in _sids:
                    return self.ratios.get(_sk, _DEFAULT_RATIO)

            # 2. Direct model-id ratio
            if model_id in self.ratios:
                return self.ratios[model_id]

            # 3. Default
            return _DEFAULT_RATIO

    def update_ratio(self, model_id: str, actual: int, estimated: int) -> float:
        """Update the calibration ratio for *model_id* using EMA.

        Args:
            model_id: The model ID (or any identifier used by :meth:`get_ratio`).
            actual: Actual prompt tokens reported by the provider.
            estimated: Estimated prompt tokens from tiktoken.

        Returns:
            The new ratio after smoothing.
        """
        if estimated <= 0:
            return _DEFAULT_RATIO

        raw_ratio = actual / estimated

        with self._lock:
            # Resolve target key
            target_key = self._resolve_key(model_id)

            current = self.ratios.get(target_key, raw_ratio)
            new_ratio = _ALPHA * raw_ratio + (1.0 - _ALPHA) * current
            self.ratios[target_key] = new_ratio

            _save_calibration_data(self._to_persist_dict())
            return new_ratio

    # -- internals -----------------------------------------------------------

    def _resolve_key(self, model_id: str) -> str:
        """Map a model ID to its persist-key (series or direct)."""
        series_key = _MODEL_TO_SERIES.get(model_id)
        if series_key is not None:
            return series_key
        for _sk, _sids in self.series.items():
            if model_id in _sids:
                return _sk
        return model_id  # fall back to direct key

    def _to_persist_dict(self) -> dict:
        return {
            "series": self.series,
            "ratios": dict(self.ratios),
        }
