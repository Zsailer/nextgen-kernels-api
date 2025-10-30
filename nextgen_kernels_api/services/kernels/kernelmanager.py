"""Kernel manager for the Apple JupyterLab Kernel Monitor Extension."""

from jupyter_server.services.kernels.kernelmanager import ServerKernelManager
from jupyter_server.services.kernels.kernelmanager import (
    AsyncMappingKernelManager,
)
from traitlets import Type, observe, Instance
from .client import JupyterServerKernelClient
from .state_mixin import KernelManagerStateMixin


class KernelManager(KernelManagerStateMixin, ServerKernelManager):
    """Kernel manager with state tracking and enhanced client.

    This kernel manager inherits from ServerKernelManager and adds:
    - Automatic lifecycle state tracking via KernelManagerStateMixin
    - Enhanced kernel client (JupyterServerKernelClient)
    - Pre-created kernel client instance stored as a property
    - Automatic client connection/disconnection on kernel start/shutdown
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
        # Create a kernel client instance immediately
        self.kernel_client = self.client(session=self.session)

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
                self.kernel_client.message_cache.clear()
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
