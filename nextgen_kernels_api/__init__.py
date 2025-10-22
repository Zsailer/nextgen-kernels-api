from jupyter_server.serverapp import ServerApp
from traitlets.config import Config
from .services.kernels.client_registry import KernelClientRegistry


_PACKAGE_NAME = "nextgen_kernels_api"


def _jupyter_server_extension_points():
    print("Hello")
    return [{"module": _PACKAGE_NAME}]


def _is_gateway_configured(server_app: ServerApp):
    """
    Check if the server app is configured to use a kernel gateway.
    
    Returns True if any gateway configuration is detected:
    - gateway_url is set
    - kernel_manager_class is set to a gateway manager
    
    Args:
        server_app: The JupyterServer application instance
        
    Returns:
        bool: True if gateway is configured, False otherwise
    """
    # Check if gateway_url is configured (most common way to enable gateway)
    if hasattr(server_app, 'gateway_url') and server_app.gateway_url:
        return True
    
    # Check if kernel_manager_class is already set to a gateway manager
    kernel_manager_class = getattr(server_app, 'kernel_manager_class', None)
    if kernel_manager_class:
        # Handle both string and class references
        if isinstance(kernel_manager_class, str):
            return 'gateway' in kernel_manager_class.lower()
        else:
            # Check class name and module
            class_name = getattr(kernel_manager_class, '__name__', '').lower()
            module_name = getattr(kernel_manager_class, '__module__', '').lower()
            return 'gateway' in class_name or 'gateway' in module_name
    
    # Check config for gateway settings
    config = getattr(server_app, 'config', {})
    if config:
        # Check ServerApp config for gateway_url
        server_app_config = config.get('ServerApp', {})
        if server_app_config.get('gateway_url'):
            return True
        
        # Check GatewayClient config (indicates gateway is being used)
        if 'GatewayClient' in config:
            return True
    
    return False


def _link_jupyter_server_extension(serverapp: ServerApp):
    serverapp.log.info("Overriding Kernel APIs with Next Generation Kernels API")
    
    # Check if the server is configured to use a gateway
    is_gateway_configured = _is_gateway_configured(serverapp)
    
    c = Config()
    c.ServerApp.kernel_websocket_connection_class = f'{_PACKAGE_NAME}.services.kernels.connection.kernel_client_connection.KernelClientWebsocketConnection'
    
    # Use gateway kernel manager if gateway is configured, otherwise use local manager
    if is_gateway_configured:
        c.ServerApp.kernel_manager_class = f'{_PACKAGE_NAME}.gateway.managers.GatewayMultiKernelManager'
        serverapp.log.info("Gateway detected - using enhanced GatewayKernelManager")
    else:
        c.ServerApp.kernel_manager_class = f'{_PACKAGE_NAME}.services.kernels.kernelmanager.MultiKernelManager'
        c.AsyncMappingKernelManager.kernel_manager_class = f'{_PACKAGE_NAME}.services.kernels.kernelmanager.KernelManager'
        serverapp.log.info("Local kernels - using enhanced KernelManager")
    
    serverapp.update_config(c)


def _load_jupyter_server_extension(serverapp: ServerApp):
        client_registry = KernelClientRegistry.instance(parent=serverapp, multi_kernel_manager=serverapp.kernel_manager)
        # Get the event logger from the server app
        event_logger = serverapp.event_logger

        # Register event listeners in each registry
        client_registry.register_event_listener(event_logger)
        serverapp.web_app.settings["client_registry"] = client_registry
