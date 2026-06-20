"""Tests for SubagentManager spawn gate lifecycle."""

import asyncio
from unittest.mock import MagicMock

import pytest


class FakeSubagentManager:
    """Minimal implementation exposing only spawn gate methods for unit testing."""

    def __init__(self):
        self._pending_gates: dict[str, asyncio.Event] = {}
        self._queued_gates: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def release_pending_gates(self) -> None:
        to_release = self._queued_gates.copy()
        self._queued_gates = self._pending_gates
        self._pending_gates = {}
        for gate in to_release.values():
            gate.set()

    def release_all_gates(self) -> None:
        for gate in self._pending_gates.values():
            gate.set()
        for gate in self._queued_gates.values():
            gate.set()
        self._pending_gates.clear()
        self._queued_gates.clear()

    async def _wait_for_gate(self, gate: asyncio.Event, timeout: float = 30.0) -> bool:
        try:
            await asyncio.wait_for(gate.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _cleanup(self, task: asyncio.Task) -> None:
        name = task.name
        self._pending_gates.pop(name, None)
        self._queued_gates.pop(name, None)
        self._tasks.pop(name, None)

    def stop(self) -> None:
        self.release_all_gates()


@pytest.fixture
def manager():
    return FakeSubagentManager()


class TestSpawnGateLifecycle:
    """Test the two-stage spawn gate release mechanism."""

    def test_pending_gates_starts_empty(self, manager):
        assert manager._pending_gates == {}
        assert manager._queued_gates == {}

    def test_release_pending_moves_to_queued_and_releases_old_queued(self, manager):
        gate1 = asyncio.Event()
        gate2 = asyncio.Event()
        gate2.set()  # Previously queued gate ready for release

        manager._pending_gates["task_1"] = gate1
        manager._queued_gates["task_2"] = gate2

        manager.release_pending_gates()

        assert "task_1" not in manager._pending_gates
        assert "task_1" in manager._queued_gates
        assert "task_2" not in manager._queued_gates
        assert manager._pending_gates == {}

    def test_release_pending_empty_no_error(self, manager):
        manager.release_pending_gates()
        assert manager._pending_gates == {}
        assert manager._queued_gates == {}

    def test_release_all_gates_clears_both_dicts(self, manager):
        gate1 = asyncio.Event()
        gate2 = asyncio.Event()

        manager._pending_gates["task_1"] = gate1
        manager._queued_gates["task_2"] = gate2

        manager.release_all_gates()

        assert manager._pending_gates == {}
        assert manager._queued_gates == {}
        assert gate1.is_set()
        assert gate2.is_set()

    def test_two_stage_release_sequence(self, manager):
        """First call queues pending, second call releases them."""
        gate = asyncio.Event()
        manager._pending_gates["task_1"] = gate

        # First call: pending → queued, no release yet
        manager.release_pending_gates()
        assert "task_1" in manager._queued_gates
        assert not gate.is_set()

        # Second call: queued gate is released
        manager.release_pending_gates()
        assert "task_1" not in manager._queued_gates
        assert gate.is_set()


class TestWaitForGate:
    """Test the _wait_for_gate async method."""

    @pytest.mark.asyncio
    async def test_wait_returns_true_when_set(self, manager):
        gate = asyncio.Event()
        gate.set()
        assert await manager._wait_for_gate(gate) is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self, manager):
        gate = asyncio.Event()
        assert await manager._wait_for_gate(gate, timeout=0.1) is False

    @pytest.mark.asyncio
    async def test_wait_returns_true_when_set_during_wait(self, manager):
        gate = asyncio.Event()

        async def set_later():
            await asyncio.sleep(0.05)
            gate.set()

        asyncio.create_task(set_later())
        assert await manager._wait_for_gate(gate, timeout=5) is True


class TestCleanupCallback:
    """Test _cleanup removes gates from both dicts on task completion."""

    def test_cleanup_removes_from_pending(self, manager):
        gate = asyncio.Event()
        task_mock = MagicMock()
        task_mock.name = "task_1"

        manager._pending_gates["task_1"] = gate
        manager._tasks["task_1"] = task_mock

        manager._cleanup(task_mock)

        assert "task_1" not in manager._pending_gates
        assert "task_1" not in manager._tasks

    def test_cleanup_removes_from_queued(self, manager):
        gate = asyncio.Event()
        task_mock = MagicMock()
        task_mock.name = "task_1"

        manager._queued_gates["task_1"] = gate
        manager._tasks["task_1"] = task_mock

        manager._cleanup(task_mock)

        assert "task_1" not in manager._queued_gates
        assert "task_1" not in manager._tasks

    def test_cleanup_no_error_if_task_not_tracked(self, manager):
        task_mock = MagicMock(name="unknown_task")
        manager._cleanup(task_mock)  # Should not raise


class TestStopReleasesGates:
    """Test that stop() releases all gates."""

    def test_stop_releases_all_gates(self, manager):
        gate1 = asyncio.Event()
        gate2 = asyncio.Event()

        manager._pending_gates["task_1"] = gate1
        manager._queued_gates["task_2"] = gate2

        manager.stop()

        assert manager._pending_gates == {}
        assert manager._queued_gates == {}
        assert gate1.is_set()
        assert gate2.is_set()
