"""
Kernel Client Registry - Manages kernel clients independently from kernel managers
"""
import asyncio
import time
from typing import Dict, Optional
from traitlets import Instance
from traitlets.config import SingletonConfigurable

from .client import JupyterServerKernelClient
from .states import LifecycleStates


class KernelClientRegistry(SingletonConfigurable):
    """Registry to manage kernel clients independently from kernel managers."""

    multi_kernel_manager = Instance(
        "jupyter_client.multikernelmanager.MultiKernelManager",
        allow_none=True,
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.clients: Dict[str, JupyterServerKernelClient] = {}
        self._event_listener_registered = False
    
    def register_event_listener(self, event_logger):
        """Register kernel action event listener for client management."""
        if self._event_listener_registered:
            return
            
        event_logger.add_listener(
            schema_id="https://events.jupyter.org/jupyter_server/kernel_actions/v1",
            listener=self._handle_kernel_action_event
        )
        self._event_listener_registered = True
        if self.log:
            self.log.info("Registered kernel action event listener for client management")
    
    async def _handle_kernel_action_event(self, logger, schema_id, data):
        """Handle kernel action events for client management."""
        action = data.get("action")
        kernel_id = data.get("kernel_id")

        if not kernel_id:
            return

        if action == "start":
            # Create and connect client when kernel starts
            client = self.create_client(kernel_id)
            if client:
                await self.connect_client(kernel_id)

        elif action == "restart":
            # Reset client state when kernel restarts
            if self.has_client(kernel_id):
                client = self.get_client(kernel_id)
                self.log.debug(f"Handling restart for kernel {kernel_id}, cache size: {len(client.message_cache)}")

                # Clear message cache - old message IDs are no longer valid
                client.message_cache.clear()
                client.last_shell_status_time = None
                client.last_control_status_time = None

                # Don't reset execution_state to "starting" - let the kernel's actual
                # status messages update it. This prevents showing stale "starting" state
                # when websockets reconnect after the kernel is already idle.

                self.log.info(f"Reset client state for restarted kernel {kernel_id}")

        elif action in ("shutdown", "interrupt"):
            # Remove client when kernel shuts down
            if self.has_client(kernel_id):
                await self.remove_client(kernel_id)
    
    def create_client(self, kernel_id: str) -> Optional[JupyterServerKernelClient]:
        """Create and register a kernel client for the given kernel."""
        if kernel_id in self.clients:
            return self.clients[kernel_id]

        try:
            # Get kernel manager from multi_kernel_manager trait
            if self.multi_kernel_manager is None:
                self.log.error("No multi_kernel_manager configured")
                return None

            kernel_manager = self.multi_kernel_manager.get_kernel(kernel_id)

            if not kernel_manager:
                self.log.error(f"No kernel manager found for kernel {kernel_id}")
                return None

            # Create client using kernel manager's client factory
            # This automatically uses the kernel manager's configurable client_class trait
            client = kernel_manager.client(session=kernel_manager.session)

            # Register the client
            self.clients[kernel_id] = client

            if self.log:
                self.log.info(f"Created client for kernel {kernel_id}")

            return client

        except Exception as e:
            self.log.error(f"Failed to create client for kernel {kernel_id}: {e}")
            return None
    
    async def connect_client(self, kernel_id: str) -> bool:
        """Connect a kernel client to its Kernel Sockets.

        This method ensures the kernel is fully started and connection info is set,
        then delegates to the client's connect method.
        """
        client = self.get_client(kernel_id)
        if not client:
            self.log.error(f"No client found for kernel {kernel_id}")
            return False

        # Don't try to connect if already connecting or connected
        if client.is_connecting() or client.is_connected():
            self.log.info(f"Client for kernel {kernel_id} is already connecting or connected")
            return client.is_connected() or await client.wait_for_connection_ready()

        try:
            # Get kernel manager from multi_kernel_manager trait
            if self.multi_kernel_manager is None:
                self.log.error("No multi_kernel_manager configured")
                return False

            kernel_manager = self.multi_kernel_manager.get_kernel(kernel_id)
            if not kernel_manager:
                self.log.error(f"No kernel manager found for kernel {kernel_id}")
                return False

            # Check if kernel is already in a terminal state before waiting
            try:
                current_state = kernel_manager.lifecycle_state
                if current_state == LifecycleStates.DEAD:
                    self.log.warning(f"Kernel {kernel_id} is in terminal state {current_state}, cannot connect")
                    return False
            except AttributeError:
                # Kernel manager might not have lifecycle_state attribute
                self.log.debug(f"Kernel manager for {kernel_id} does not have lifecycle_state attribute")

            # Wait for kernel to be in "started" state before connecting channels
            if not await self._wait_for_kernel_started(kernel_manager, kernel_id):
                self.log.error(f"Kernel {kernel_id} failed to reach started state")
                return False

            # Set connection info before attempting to connect
            client.load_connection_info(kernel_manager.get_connection_info(session=True))

            # Delegate to the client's connect method
            success = await client.connect()

            if success:
                self.log.info(f"Successfully connected client for kernel {kernel_id}")

            return success

        except Exception as e:
            self.log.error(f"Failed to connect client for kernel {kernel_id}: {e}")
            import traceback
            self.log.debug(f"Traceback: {traceback.format_exc()}")
            return False

    async def _wait_for_kernel_started(self, kernel_manager, kernel_id: str, timeout: float = 30.0) -> bool:
        """Wait for the kernel to reach 'started' state before connecting channels."""
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            try:
                current_state = kernel_manager.lifecycle_state
                self.log.debug(f"Waiting for kernel {kernel_id} to start, current state: {current_state}")

                # Check if kernel reached started state
                if current_state == LifecycleStates.STARTED:
                    self.log.info(f"Kernel {kernel_id} reached started state")
                    return True

                # Check if kernel is in a terminal failure state
                if current_state == LifecycleStates.DEAD:
                    self.log.error(f"Kernel {kernel_id} is in terminal state {current_state}, cannot connect")
                    return False

                # Wait before next check
                await asyncio.sleep(0.5)
            except Exception as e:
                self.log.debug(f"Error checking kernel {kernel_id} state: {e}")
                await asyncio.sleep(0.5)

        self.log.error(f"Timeout waiting for kernel {kernel_id} to reach started state (last state: {kernel_manager.lifecycle_state if hasattr(kernel_manager, 'lifecycle_state') else 'unknown'})")
        return False
    
    async def disconnect_client(self, kernel_id: str):
        """Disconnect a kernel client from its Kernel Sockets."""
        client = self.get_client(kernel_id)
        if client:
            try:
                await client.stop_listening()
                client.stop_channels()
                self.log.info(f"Disconnected client for kernel {kernel_id}")
            except Exception as e:
                self.log.error(f"Failed to disconnect client for kernel {kernel_id}: {e}")
    
    async def remove_client(self, kernel_id: str):
        """Remove a kernel client from the registry."""
        if kernel_id in self.clients:
            # Disconnect first
            await self.disconnect_client(kernel_id)
            
            # Remove from registry
            client = self.clients.pop(kernel_id, None)
            if client:
                self.log.info(f"Removed client for kernel {kernel_id}")
    
    def get_client(self, kernel_id: str) -> Optional[JupyterServerKernelClient]:
        """Get the client for a specific kernel."""
        return self.clients.get(kernel_id)
    
    def has_client(self, kernel_id: str) -> bool:
        """Check if a client exists for a kernel."""
        return kernel_id in self.clients
    
    async def remove_all_clients(self):
        """Remove all clients from the registry."""
        kernel_ids = list(self.clients.keys())
        for kernel_id in kernel_ids:
            await self.remove_client(kernel_id)

