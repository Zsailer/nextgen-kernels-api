from jupyter_server.extension.application import ExtensionApp
from .handlers import handlers

class KernelStateExtension(ExtensionApp):
    name = "nextgen_kernels_api"
    handlers = handlers