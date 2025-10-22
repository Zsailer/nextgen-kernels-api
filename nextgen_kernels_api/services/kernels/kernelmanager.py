"""Kernel manager for the Apple JupyterLab Kernel Monitor Extension."""

from jupyter_server.services.kernels.kernelmanager import ServerKernelManager
from jupyter_server.services.kernels.kernelmanager import (
    AsyncMappingKernelManager,
)
from .client import JupyterServerKernelClient
from .state_mixin import KernelManagerStateMixin


class KernelManager(KernelManagerStateMixin, ServerKernelManager):
    """Kernel manager with state tracking and enhanced client.

    This kernel manager inherits from ServerKernelManager and adds:
    - Automatic lifecycle state tracking via KernelManagerStateMixin
    - Enhanced kernel client (JupyterServerKernelClient)
    """
    # Since these are not configurable traits, we have to override them.
    client_class = JupyterServerKernelClient
    client_factory = JupyterServerKernelClient
    

class MultiKernelManager(AsyncMappingKernelManager):
    """Custom kernel manager that uses Apple's enhanced monitoring kernel manager."""

    def start_watching_activity(self, kernel_id):
        pass
    
    def stop_buffering(self, kernel_id):
        pass
