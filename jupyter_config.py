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

# ============================================================================
# Kernel Client Registry Configuration
# ============================================================================
# The KernelClientRegistry automatically discovers provisioner-to-client mappings
# from entry points in the 'jupyter_kernel_client_registry' group.
#
# Entry points should be defined in external packages like:
#
# In pyproject.toml:
# [project.entry-points.jupyter_kernel_client_registry]
# "jupyter_server.saturn.provisioners.spark_provisioner:SparkProvisioner" =
#     "jupyter_server_documents.kernel_client:DocumentAwareSparkProvisionerAwareKernelClient"

# Configure the fallback kernel client (used when no provisioner-specific mapping exists)
# Defaults to jupyter_client.client.KernelClient if not set
# c.KernelClientRegistry.fallback_client_class = "nextgen_kernels_api.services.kernels.client.JupyterServerKernelClient"

# Optional: Enable debug logging to see message routing and entry point discovery
# c.Application.log_level = "DEBUG"

# Optional: Disable token for local development (NOT for production\!)
# c.ServerApp.token = ""
