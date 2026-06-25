import json
from unittest.mock import patch

import pytest

from nanobot.utils.calibration import ModelCalibrationManager, _load_model_map


@pytest.fixture
def mock_workspace_path(tmp_path):
    """Mocks nanobot.utils.calibration.get_workspace_path to return a temp directory."""
    with patch("nanobot.utils.calibration.get_workspace_path", return_value=tmp_path):
        yield tmp_path


def test_load_model_map_success(mock_workspace_path):
    # Setup valid model_map.json
    model_map_data = {
        "gpt-4": ["gpt-4", "gpt-4-turbo", "gpt-4o"],
        "claude-3": ["claude-3-opus", "claude-3-sonnet"],
    }
    model_map_file = mock_workspace_path / "model_map.json"
    model_map_file.write_text(json.dumps(model_map_data), encoding="utf-8")

    result = _load_model_map()

    assert result == {
        "gpt-4": ("gpt-4", "gpt-4-turbo", "gpt-4o"),
        "claude-3": ("claude-3-opus", "claude-3-sonnet"),
    }


def test_load_model_map_missing_file(mock_workspace_path):
    # Ensure file doesn't exist
    model_map_file = mock_workspace_path / "model_map.json"
    if model_map_file.exists():
        model_map_file.unlink()

    result = _load_model_map()
    assert result == {}


def test_load_model_map_malformed_json(mock_workspace_path):
    # Setup malformed JSON
    model_map_file = mock_workspace_path / "model_map.json"
    model_map_file.write_text("invalid json", encoding="utf-8")

    result = _load_model_map()
    assert result == {}


def test_get_ratio_resolution_order():
    # We patch the module-level constants to isolate the test
    with (
        patch("nanobot.utils.calibration._MODEL_TO_SERIES", {"gpt-4o": "gpt-series"}),
        patch("nanobot.utils.calibration._DEFAULT_RATIO", 1.0),
    ):
        manager = ModelCalibrationManager()

        # 1. Built-in series: gpt-4o -> gpt-series. Ratio is in self.ratios.
        manager.ratios["gpt-series"] = 1.2
        assert manager.get_ratio("gpt-4o") == 1.2

        # 2. User-defined series: 'custom-model' in 'custom-series'.
        manager.series["custom-series"] = ["custom-model"]
        manager.ratios["custom-series"] = 1.5
        assert manager.get_ratio("custom-model") == 1.5

        # 3. Direct model ID ratio.
        manager.ratios["direct-model"] = 0.8
        assert manager.get_ratio("direct-model") == 0.8

        # 4. Default
        assert manager.get_ratio("unknown-model") == 1.0


def test_update_ratio_ema(tmp_path):
    # Mock calibration file to avoid side effects on real workspace
    cal_file = tmp_path / "model_calibration.json"
    with patch("nanobot.utils.calibration._CALIBRATION_FILE", cal_file):
        manager = ModelCalibrationManager()

        # Initial ratio for 'model-a' should be the raw ratio on first update
        # raw = 120 / 100 = 1.2
        # current = 1.2 (since it doesn't exist in self.ratios)
        # new = 0.1 * 1.2 + 0.9 * 1.2 = 1.2
        ratio = manager.update_ratio("model-a", 120, 100)
        assert ratio == pytest.approx(1.2)
        assert manager.ratios["model-a"] == pytest.approx(1.2)

        # Second update
        # raw = 140 / 100 = 1.4
        # current = 1.2
        # new = 0.1 * 1.4 + 0.9 * 1.2 = 0.14 + 1.08 = 1.22
        ratio = manager.update_ratio("model-a", 140, 100)
        assert ratio == pytest.approx(1.22)
        assert manager.ratios["model-a"] == pytest.approx(1.22)


def test_update_ratio_invalid_estimate(tmp_path):
    cal_file = tmp_path / "model_calibration.json"
    with patch("nanobot.utils.calibration._CALIBRATION_FILE", cal_file):
        manager = ModelCalibrationManager()

        # estimated = 0
        assert manager.update_ratio("model-a", 100, 0) == 1.0
        # estimated < 0
        assert manager.update_ratio("model-a", 100, -10) == 1.0


def test_update_ratio_persistence(tmp_path):
    cal_file = tmp_path / "model_calibration.json"
    with patch("nanobot.utils.calibration._CALIBRATION_FILE", cal_file):
        manager = ModelCalibrationManager()

        manager.update_ratio("model-persist", 110, 100)

        # Check if file was written
        assert cal_file.exists()
        data = json.loads(cal_file.read_text())
        assert "ratios" in data
        assert data["ratios"]["model-persist"] == pytest.approx(1.1)


def test_model_calibration_manager_init_with_data(tmp_path):
    # Setup existing calibration data
    cal_file = tmp_path / "model_calibration.json"
    cal_data = {
        "series": {"gpt-series": ["gpt-4", "gpt-4o"]},
        "ratios": {"gpt-series": 1.1, "claude-direct": 0.9},
    }
    cal_file.write_text(json.dumps(cal_data))

    with patch("nanobot.utils.calibration._CALIBRATION_FILE", cal_file):
        manager = ModelCalibrationManager()
        assert manager.series["gpt-series"] == ["gpt-4", "gpt-4o"]
        assert manager.ratios["gpt-series"] == 1.1
        assert manager.ratios["claude-direct"] == 0.9


def test_model_calibration_manager_init_malformed_data(tmp_path):
    cal_file = tmp_path / "model_calibration.json"
    cal_file.write_text("invalid json")

    with patch("nanobot.utils.calibration._CALIBRATION_FILE", cal_file):
        manager = ModelCalibrationManager()
        assert manager.series == {}
        assert manager.ratios == {}
