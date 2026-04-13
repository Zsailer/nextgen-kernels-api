"""Kernel manager for the Apple JupyterLab Kernel Monitor Extension."""

import asyncio

from jupyter_server.services.kernels.kernelmanager import ServerKernelManager
from jupyter_server.services.kernels.kernelmanager import (
    AsyncMappingKernelManager,
)
from traitlets import Type, observe, Instance
from .client import JupyterServerKernelClient
from .kernel_client_registry import KernelClientRegistry


class KernelManager(ServerKernelManager):
    """Kernel manager with enhanced client.

    This kernel manager inherits from ServerKernelManager and adds:
    - Enhanced kernel client (JupyterServerKernelClient) with message ID encoding
    - Pre-created kernel client instance stored as a property
    - Automatic client connection/disconnection on kernel start/shutdown

    The client encodes channel information in message IDs using simple string operations.
    """

    client_class = Type(
        default_value=JupyterServerKernelClient,
        klass='jupyter_client.client.KernelClient',
        config=True,
        help="""The kernel client class to use for creating kernel clients."""
    )

    client_factory = Type(
        default_value=JupyterServerKernelClient,
        klass='jupyter_client.client.KernelClient',
        config=True,
        help="""The kernel client factory class to use."""
    )

    kernel_client = Instance(
        'jupyter_client.client.KernelClient',
        allow_none=True,
        help="""Pre-created kernel client instance. Created on initialization."""
    )

    def __init__(self, **kwargs):
        """Initialize the kernel manager and create a kernel client instance."""
        super().__init__(**kwargs)

    @observe('client_class')
    def _client_class_changed(self, change):
        """Override parent's _client_class_changed to handle Type trait instead of DottedObjectName."""
        # Set client_factory to the same class
        self.client_factory = change['new']

    async def _async_post_start_kernel(self, **kwargs):
        """After kernel starts, connect the kernel client.

        This method is called after the kernel has been successfully started.
        It loads the latest connection info (with ports set by provisioner)
        and connects the kernel client to the kernel.

        Note: If you override this method, make sure to call super().post_start_kernel(**kwargs)
        to ensure the kernel client connects properly.
        """
        await super()._async_post_start_kernel(**kwargs)

        self.select_client()

        self.kernel_client = self.client(session=self.session)

        try:
            # Load latest connection info from kernel manager
            # The provisioner has now set the real ports
            self.kernel_client.load_connection_info(self.get_connection_info(session=True))

            # Connect the kernel client
            success = await self.kernel_client.connect()

            if not success:
                raise RuntimeError(f"Failed to connect kernel client for kernel {self.kernel_id}")

            self.log.info(f"Successfully connected kernel client for kernel {self.kernel_id}")

        except Exception as e:
            self.log.error(f"Failed to connect kernel client: {e}")
            # Re-raise to fail the kernel start
            raise

    def select_client(self):
        # abstract method for subclass to override.
        # Select appropriate client class based on provisioner type
        pass

    async def cleanup_resources(self, restart=False):
        """Cleanup resources, disconnecting the kernel client if not restarting.

        Parameters
        ----------
        restart : bool
            If True, the kernel is being restarted and we should keep the client
            connected but clear its state. If False, fully disconnect.
        """
        if self.kernel_client:
            if restart:
                # On restart, clear client state but keep connection
                # The connection will be refreshed in post_start_kernel after restart
                self.log.debug(f"Clearing kernel client state for restart of kernel {self.kernel_id}")
                self.kernel_client.last_shell_status_time = None
                self.kernel_client.last_control_status_time = None
                # Disconnect before restart - will reconnect after
                await self.kernel_client.stop_listening()
                self.kernel_client.stop_channels()
            else:
                # On shutdown, fully disconnect the client
                self.log.debug(f"Disconnecting kernel client for kernel {self.kernel_id}")
                await self.kernel_client.stop_listening()
                self.kernel_client.stop_channels()

        await super().cleanup_resources(restart=restart)
    

class MultiKernelManager(AsyncMappingKernelManager):
    """Custom kernel manager that uses Apple's enhanced monitoring kernel manager."""

    def start_watching_activity(self, kernel_id):
        pass
    
    def stop_buffering(self, kernel_id):
        pass

    def _handle_kernel_died(self, kernel_id):
        """Handle a kernel that has died by performing full shutdown cleanup.

        Unlike the default implementation which only calls remove_kernel()
        (a bare dict pop), this performs proper cleanup:
        - Stops the kernel restarter
        - Disconnects the kernel client
        - Cleans up connection files
        - Removes from kernel map
        """
        self.log.warning("Kernel %s died, shutting down and removing.", kernel_id)
        try:
            km = self.get_kernel(kernel_id)
            km.stop_restarter()
        except KeyError:
            pass
        # shutdown_kernel handles cleanup_resources + remove_kernel
        # Use now=True since the kernel is already dead
        asyncio.ensure_future(self.shutdown_kernel(kernel_id, now=True))

import typing as t

class ProvisionerAwareKernelManager(KernelManager):
    """Generic kernel manager that selects client class based on provisioner type.

    This kernel manager uses KernelClientRegistry to map provisioner types to their
    appropriate kernel client classes. This enables:
    - LocalProvisioner → JupyterServerKernelClient (ZMQ ports)
    - SparkProvisioner → GatewayKernelClient (WebSocket URL)
    - Future provisioners → Their custom clients

    The provisioner is responsible for providing connection_info with the fields
    its paired client expects.
    """

    def get_connection_info(self, session: bool = False) -> dict:
        """Get connection info by delegating to provisioner.

        The provisioner is the source of truth for connection details.
        This enables extensible connection info (ZMQ ports, WebSocket URLs, etc.)
        without KernelManager needing provisioner-specific attributes.

        Parameters
        ----------
        session : bool
            If True, include the session key in the connection info

        Returns
        -------
        dict
            Connection info dictionary with provisioner-specific fields:
            - LocalProvisioner: shell_port, iopub_port, stdin_port, control_port, hb_port, ip, transport
            - SparkProvisioner: ws_url, key
            - Future provisioners: any custom fields they need
        """
        if self.provisioner and hasattr(self.provisioner, 'connection_info') and self.provisioner.connection_info :
            # Delegate to provisioner (new extensible pattern)
            info = self.provisioner.connection_info.copy()
            self.log.debug(f"Got connection info from provisioner: {list(info.keys())}")
        else:
            # Fallback: Build from KM attributes (backward compatibility)
            info = {
                "shell_port": self.shell_port,
                "iopub_port": self.iopub_port,
                "stdin_port": self.stdin_port,
                "control_port": self.control_port,
                "hb_port": self.hb_port,
                "ip": self.ip,
                "transport": self.transport,
                "signature_scheme": self.session.signature_scheme,
            }

        # Add session key if requested
        if session:
            info["key"] = self.session.key

        return info

    def select_client(self):
        # Select appropriate client class based on provisioner type
        if self.provisioner:
            # Get singleton registry instance
            registry = KernelClientRegistry.instance(config=self.config)
            client_class = registry.get_client_for_provisioner(self.provisioner)

            if client_class:
                self.client_class = client_class
                self.client_factory = client_class
                self.log.debug(
                    f"Selected client class {client_class.__name__} for provisioner "
                    f"{type(self.provisioner).__name__}"
                )
            else:
                self.log.warning(
                    f"No client class registered for provisioner {type(self.provisioner).__name__}, "
                    f"using default {self.client_class.__name__}"
                )
