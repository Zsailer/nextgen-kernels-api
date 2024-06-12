from .extension.app import KernelStateExtension


def _jupyter_server_extension_points():
    return [
        {
            "module": "nextgen_kernels_api.extension.app", 
            "app": KernelStateExtension
        }
    ]