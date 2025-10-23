"""Kernel manager for the Apple JupyterLab Kernel Monitor Extension."""

from jupyter_server.services.kernels.kernelmanager import ServerKernelManager
from jupyter_server.services.kernels.kernelmanager import (
    AsyncMappingKernelManager,
)
from traitlets import Type, observe
from .client import JupyterServerKernelClient
from .state_mixin import KernelManagerStateMixin


class KernelManager(KernelManagerStateMixin, ServerKernelManager):
    """Kernel manager with state tracking and enhanced client.

    This kernel manager inherits from ServerKernelManager and adds:
    - Automatic lifecycle state tracking via KernelManagerStateMixin
    - Enhanced kernel client (JupyterServerKernelClient)
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

    @observe('client_class')
    def _client_class_changed(self, change):
        """Override parent's _client_class_changed to handle Type trait instead of DottedObjectName."""
        # Set client_factory to the same class
        self.client_factory = change['new']
    

class MultiKernelManager(AsyncMappingKernelManager):
    """Custom kernel manager that uses Apple's enhanced monitoring kernel manager."""

    def start_watching_activity(self, kernel_id):
        pass
    
    def stop_buffering(self, kernel_id):
        pass
