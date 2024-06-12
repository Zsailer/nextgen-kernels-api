import json
from tornado import web

from jupyter_server.auth.decorator import authorized
from jupyter_server.extension.handler import ExtensionHandlerMixin
from jupyter_server.base.handlers import APIHandler
from jupyter_server.services.kernels.handlers import _kernel_id_regex


class KernelStateHandler(ExtensionHandlerMixin, APIHandler):

    auth_resource = "kernels"
    
    @web.authenticated
    @authorized
    def get(self, kernel_id): 
        kernel = self.kernel_manager.get_kernel(kernel_id)
        state = {
            "kernel_id": kernel_id,
            "lifecycle_state": kernel.lifecycle_state,
            "execution_state": kernel.execution_state
        }
        self.write(json.dumps(state))
        self.finish()
        
        
handlers = [
    (r"/api/kernels/%s/state" % _kernel_id_regex, KernelStateHandler),
]