"""Kernel manager state machine mixin."""

import enum
from typing import Callable
from traitlets import HasTraits, Unicode, observe
from functools import wraps


class LifecycleState(str, enum.Enum):
    """Kernel lifecycle states."""
    UNKNOWN = "unknown"
    STARTING = "starting"
    STARTED = "started"
    RESTARTING = "restarting"
    TERMINATING = "terminating"
    DEAD = "dead"


def state_transition(start_state: LifecycleState, end_state: LifecycleState):
    """Decorator to handle state transitions for kernel manager methods."""
    def decorator(method: Callable) -> Callable:
        @wraps(method)
        async def async_wrapper(self, *args, **kwargs):
            # Set the starting state
            self.lifecycle_state = start_state
            try:
                # Call the original method
                result = await method(self, *args, **kwargs)
                # Set the end state on success
                self.lifecycle_state = end_state
                return result
            except Exception as e:
                # Set to unknown state on failure
                self.lifecycle_state = LifecycleState.UNKNOWN
                raise

        @wraps(method)
        def sync_wrapper(self, *args, **kwargs):
            # Set the starting state
            self.lifecycle_state = start_state
            try:
                # Call the original method
                result = method(self, *args, **kwargs)
                # Set the end state on success
                self.lifecycle_state = end_state
                return result
            except Exception as e:
                # Set to unknown state on failure
                self.lifecycle_state = LifecycleState.UNKNOWN
                raise

        # Return the appropriate wrapper based on whether the method is async
        import asyncio
        if asyncio.iscoroutinefunction(method):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class KernelManagerStateMixin(HasTraits):
    """Mixin class that adds lifecycle state tracking to kernel managers.

    This mixin works with any kernel manager that follows the KernelManagerABC
    interface. It automatically tracks and updates the lifecycle_state of kernels
    as they go through various operations.

    The state machine handles these transitions:
    - start_kernel: unknown -> starting -> started (or unknown on failure)
    - restart_kernel: * -> restarting -> restarted (or unknown on failure)
    - shutdown_kernel: * -> terminating -> dead (or unknown on failure)

    Usage:
        class MyKernelManager(KernelManagerStateMixin, SomeBaseKernelManager):
            pass
    """

    lifecycle_state = Unicode(
        default_value=LifecycleState.UNKNOWN,
        help="The current lifecycle state of the kernel"
    ).tag(config=True)

    @observe('lifecycle_state')
    def _lifecycle_state_changed(self, change):
        """Log lifecycle state changes."""
        old_state = change['old']
        new_state = change['new']
        kernel_id = getattr(self, 'kernel_id', 'unknown')
        if hasattr(self, 'log'):
            self.log.debug(f"Kernel {kernel_id} state changed: {old_state} -> {new_state}")

    def __init_subclass__(cls, **kwargs):
        """Automatically wrap kernel management methods when the class is subclassed."""
        super().__init_subclass__(**kwargs)

        # Wrap start_kernel method
        if hasattr(cls, 'start_kernel'):
            original_start = cls.start_kernel
            cls.start_kernel = state_transition(
                LifecycleState.STARTING,
                LifecycleState.STARTED
            )(original_start)

        # Wrap restart_kernel method
        if hasattr(cls, 'restart_kernel'):
            original_restart = cls.restart_kernel
            cls.restart_kernel = state_transition(
                LifecycleState.RESTARTING,
                LifecycleState.STARTED
            )(original_restart)

        # Wrap shutdown_kernel method
        if hasattr(cls, 'shutdown_kernel'):
            original_shutdown = cls.shutdown_kernel
            cls.shutdown_kernel = state_transition(
                LifecycleState.TERMINATING,
                LifecycleState.DEAD
            )(original_shutdown)

    @property
    def is_starting(self) -> bool:
        """Check if kernel is in starting state."""
        return self.lifecycle_state == LifecycleState.STARTING

    @property
    def is_started(self) -> bool:
        """Check if kernel is in started state."""
        return self.lifecycle_state == LifecycleState.STARTED

    @property
    def is_restarting(self) -> bool:
        """Check if kernel is in restarting state."""
        return self.lifecycle_state == LifecycleState.RESTARTING

    @property
    def is_restarted(self) -> bool:
        """Check if kernel is in restarted state."""
        return self.lifecycle_state == LifecycleState.STARTED

    @property
    def is_terminating(self) -> bool:
        """Check if kernel is in terminating state."""
        return self.lifecycle_state == LifecycleState.TERMINATING

    @property
    def is_dead(self) -> bool:
        """Check if kernel is in dead state."""
        return self.lifecycle_state == LifecycleState.DEAD

    @property
    def is_unknown(self) -> bool:
        """Check if kernel is in unknown state."""
        return self.lifecycle_state == LifecycleState.UNKNOWN

    def set_lifecycle_state(self, state: LifecycleState) -> None:
        """Manually set the lifecycle state."""
        self.lifecycle_state = state