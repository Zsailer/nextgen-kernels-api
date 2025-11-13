"""
Minimal Jupyter Server configuration for nextgen-kernels-api.

This is the simplest configuration to get started with the enhanced kernel architecture.

Usage:
    jupyter server --config=jupyter_config.minimal.py
"""

c = get_config()  # noqa

# Use the enhanced kernel manager with shared kernel clients
c.ServerApp.kernel_manager_class = "nextgen_kernels_api.services.kernels.kernelmanager.MultiKernelManager"

# Configure which KernelManager class each kernel uses
c.MultiKernelManager.kernel_manager_class = "nextgen_kernels_api.services.kernels.kernelmanager.KernelManager"

# Configure which client class the KernelManager uses
c.KernelManager.client_class = "nextgen_kernels_api.services.kernels.client.JupyterServerKernelClient"

# Configure the WebSocket connection class
c.ServerApp.kernel_websocket_connection_class = "nextgen_kernels_api.services.kernels.connection.kernel_client_connection.KernelClientWebsocketConnection"

# Optional: Enable debug logging to see message routing
# c.Application.log_level = "DEBUG"

# Optional: Disable token for local development (NOT for production\!)
# c.ServerApp.token = ""
