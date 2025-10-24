"""Unit tests for KernelManagerStateMixin.

Tests the state tracking functionality including:
- Lifecycle state transitions
- State transition decorators
- Property checks for different states
"""

import asyncio

import pytest
from traitlets import HasTraits

from nextgen_kernels_api.services.kernels.state_mixin import (
    KernelManagerStateMixin,
    LifecycleState,
    state_transition,
)


class MockKernelManager(KernelManagerStateMixin, HasTraits):
    """Mock kernel manager for testing state transitions."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.kernel_id = "test-kernel-123"
        self.start_called = False
        self.restart_called = False
        self.shutdown_called = False

    async def start_kernel(self):
        """Mock async start_kernel method."""
        self.start_called = True
        await asyncio.sleep(0.01)  # Simulate some work
        return "started"

    async def restart_kernel(self):
        """Mock async restart_kernel method."""
        self.restart_called = True
        await asyncio.sleep(0.01)  # Simulate some work
        return "restarted"

    async def shutdown_kernel(self):
        """Mock async shutdown_kernel method."""
        self.shutdown_called = True
        await asyncio.sleep(0.01)  # Simulate some work
        return "shutdown"


class SyncMockKernelManager(KernelManagerStateMixin, HasTraits):
    """Mock kernel manager with synchronous methods for testing."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.kernel_id = "test-kernel-456"

    def start_kernel(self):
        """Mock sync start_kernel method."""
        return "started"

    def restart_kernel(self):
        """Mock sync restart_kernel method."""
        return "restarted"

    def shutdown_kernel(self):
        """Mock sync shutdown_kernel method."""
        return "shutdown"


@pytest.fixture
def kernel_manager():
    """Create a MockKernelManager instance."""
    return MockKernelManager()


@pytest.fixture
def sync_kernel_manager():
    """Create a SyncMockKernelManager instance."""
    return SyncMockKernelManager()


def test_initial_state(kernel_manager):
    """Test that kernel manager initializes with UNKNOWN state."""
    assert kernel_manager.lifecycle_state == LifecycleState.UNKNOWN


def test_is_unknown_property(kernel_manager):
    """Test the is_unknown property."""
    assert kernel_manager.is_unknown is True
    kernel_manager.lifecycle_state = LifecycleState.STARTING
    assert kernel_manager.is_unknown is False


def test_is_starting_property(kernel_manager):
    """Test the is_starting property."""
    kernel_manager.lifecycle_state = LifecycleState.STARTING
    assert kernel_manager.is_starting is True
    kernel_manager.lifecycle_state = LifecycleState.STARTED
    assert kernel_manager.is_starting is False


def test_is_started_property(kernel_manager):
    """Test the is_started property."""
    kernel_manager.lifecycle_state = LifecycleState.STARTED
    assert kernel_manager.is_started is True
    kernel_manager.lifecycle_state = LifecycleState.STARTING
    assert kernel_manager.is_started is False


def test_is_restarting_property(kernel_manager):
    """Test the is_restarting property."""
    kernel_manager.lifecycle_state = LifecycleState.RESTARTING
    assert kernel_manager.is_restarting is True
    kernel_manager.lifecycle_state = LifecycleState.STARTED
    assert kernel_manager.is_restarting is False


def test_is_terminating_property(kernel_manager):
    """Test the is_terminating property."""
    kernel_manager.lifecycle_state = LifecycleState.TERMINATING
    assert kernel_manager.is_terminating is True
    kernel_manager.lifecycle_state = LifecycleState.DEAD
    assert kernel_manager.is_terminating is False


def test_is_dead_property(kernel_manager):
    """Test the is_dead property."""
    kernel_manager.lifecycle_state = LifecycleState.DEAD
    assert kernel_manager.is_dead is True
    kernel_manager.lifecycle_state = LifecycleState.UNKNOWN
    assert kernel_manager.is_dead is False


def test_set_lifecycle_state(kernel_manager):
    """Test manually setting the lifecycle state."""
    kernel_manager.set_lifecycle_state(LifecycleState.STARTED)
    assert kernel_manager.lifecycle_state == LifecycleState.STARTED

    kernel_manager.set_lifecycle_state(LifecycleState.TERMINATING)
    assert kernel_manager.lifecycle_state == LifecycleState.TERMINATING


@pytest.mark.asyncio
async def test_start_kernel_state_transition(kernel_manager):
    """Test that start_kernel transitions from STARTING to STARTED."""
    assert kernel_manager.lifecycle_state == LifecycleState.UNKNOWN

    result = await kernel_manager.start_kernel()

    assert kernel_manager.start_called is True
    assert result == "started"
    assert kernel_manager.lifecycle_state == LifecycleState.STARTED


@pytest.mark.asyncio
async def test_restart_kernel_state_transition(kernel_manager):
    """Test that restart_kernel transitions from RESTARTING to STARTED."""
    kernel_manager.lifecycle_state = LifecycleState.STARTED

    result = await kernel_manager.restart_kernel()

    assert kernel_manager.restart_called is True
    assert result == "restarted"
    assert kernel_manager.lifecycle_state == LifecycleState.STARTED


@pytest.mark.asyncio
async def test_shutdown_kernel_state_transition(kernel_manager):
    """Test that shutdown_kernel transitions from TERMINATING to DEAD."""
    kernel_manager.lifecycle_state = LifecycleState.STARTED

    result = await kernel_manager.shutdown_kernel()

    assert kernel_manager.shutdown_called is True
    assert result == "shutdown"
    assert kernel_manager.lifecycle_state == LifecycleState.DEAD


class FailingMockKernelManager(KernelManagerStateMixin, HasTraits):
    """Mock kernel manager that fails on start for testing error handling."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.kernel_id = "test-kernel-fail"

    async def start_kernel(self):
        """Mock async start_kernel method that fails."""
        raise RuntimeError("Start failed")

    async def restart_kernel(self):
        """Mock async restart_kernel method."""
        return "restarted"

    async def shutdown_kernel(self):
        """Mock async shutdown_kernel method."""
        return "shutdown"


@pytest.fixture
def failing_kernel_manager():
    """Create a FailingMockKernelManager instance."""
    return FailingMockKernelManager()


@pytest.mark.asyncio
async def test_start_kernel_failure_sets_unknown(failing_kernel_manager):
    """Test that start_kernel failure sets state to UNKNOWN."""
    with pytest.raises(RuntimeError, match="Start failed"):
        await failing_kernel_manager.start_kernel()

    assert failing_kernel_manager.lifecycle_state == LifecycleState.UNKNOWN


def test_sync_start_kernel_state_transition(sync_kernel_manager):
    """Test that synchronous start_kernel transitions states correctly."""
    assert sync_kernel_manager.lifecycle_state == LifecycleState.UNKNOWN

    result = sync_kernel_manager.start_kernel()

    assert result == "started"
    assert sync_kernel_manager.lifecycle_state == LifecycleState.STARTED


def test_sync_restart_kernel_state_transition(sync_kernel_manager):
    """Test that synchronous restart_kernel transitions states correctly."""
    sync_kernel_manager.lifecycle_state = LifecycleState.STARTED

    result = sync_kernel_manager.restart_kernel()

    assert result == "restarted"
    assert sync_kernel_manager.lifecycle_state == LifecycleState.STARTED


def test_sync_shutdown_kernel_state_transition(sync_kernel_manager):
    """Test that synchronous shutdown_kernel transitions states correctly."""
    sync_kernel_manager.lifecycle_state = LifecycleState.STARTED

    result = sync_kernel_manager.shutdown_kernel()

    assert result == "shutdown"
    assert sync_kernel_manager.lifecycle_state == LifecycleState.DEAD


def test_sync_kernel_failure_sets_unknown(sync_kernel_manager):
    """Test that synchronous kernel method failure sets state to UNKNOWN."""

    def failing_start(self):
        raise RuntimeError("Start failed")

    sync_kernel_manager.start_kernel = failing_start

    with pytest.raises(RuntimeError, match="Start failed"):
        wrapped = state_transition(LifecycleState.STARTING, LifecycleState.STARTED)(
            sync_kernel_manager.start_kernel
        )
        wrapped(sync_kernel_manager)

    assert sync_kernel_manager.lifecycle_state == LifecycleState.UNKNOWN


def test_state_transition_decorator_async():
    """Test the state_transition decorator with async functions."""

    class TestClass:
        def __init__(self):
            self.lifecycle_state = LifecycleState.UNKNOWN

        @state_transition(LifecycleState.STARTING, LifecycleState.STARTED)
        async def test_method(self):
            return "success"

    obj = TestClass()
    result = asyncio.run(obj.test_method())

    assert result == "success"
    assert obj.lifecycle_state == LifecycleState.STARTED


def test_state_transition_decorator_sync():
    """Test the state_transition decorator with synchronous functions."""

    class TestClass:
        def __init__(self):
            self.lifecycle_state = LifecycleState.UNKNOWN

        @state_transition(LifecycleState.STARTING, LifecycleState.STARTED)
        def test_method(self):
            return "success"

    obj = TestClass()
    result = obj.test_method()

    assert result == "success"
    assert obj.lifecycle_state == LifecycleState.STARTED
