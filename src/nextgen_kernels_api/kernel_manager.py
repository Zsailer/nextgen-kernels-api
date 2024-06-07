import typing
import asyncio
from traitlets import default
from traitlets import Instance
from traitlets import Int
from traitlets import Type
from traitlets import Unicode
from traitlets import validate
from traitlets import TraitError
from traitlets import DottedObjectName
from traitlets.utils.importstring import import_item

from jupyter_client.asynchronous.client import AsyncKernelClient
from jupyter_client.manager import AsyncKernelManager

from . import types
from . import states
from .kernel_listener import KernelListenerMixin

class NextGenKernelManager(KernelListenerMixin, AsyncKernelManager):
    """
    """
    # Configurable settings in a kernel manager that I want.
    time_to_connect: int = Int(
        default_value=10,
        help="The timeout for connecting to a kernel."
    ).tag(config=True)
    
    _execution_state: types.EXECUTION_STATES = Unicode()
    
    @validate("_execution_state")
    def _validate_execution_state(self, proposal: dict):
        if not proposal["value"] in states.EXECUTION_STATES:
            raise TraitError(f"execution_state must be one of {states.EXECUTION_STATES}")
        return proposal["value"]
    
    @property
    def execution_state(self) -> types.EXECUTION_STATES:
        return self._execution_state
    
    @execution_state.setter
    def execution_state(self, val):
        self._execution_state = val

    _lifecycle_state: types.EXECUTION_STATES = Unicode()
    
    @validate("_lifecycle_state")
    def _validate_lifecycle_state(self, proposal: dict):
        if not proposal["value"] in states.LIFECYCLE_STATES:
            raise TraitError(f"lifecycle_state must be one of {states.LIFECYCLE_STATES}")
        return proposal["value"]

    @property
    def lifecycle_state(self) -> types.LIFECYCLE_STATES:
        return self._lifecycle_state
    
    def set_state(
        self, 
        lifecycle_state: typing.Optional[types.LIFECYCLE_STATES] = None, 
        execution_state: typing.Optional[types.EXECUTION_STATES] = None,
        broadcast=True
    ):
        if lifecycle_state:
            self._lifecycle_state = lifecycle_state
        if execution_state:
            self._execution_state = execution_state
            
        if broadcast:
            # Broadcast this state change to all listeners
            self.broadcast_state()

    async def start_kernel(self, *args, **kwargs):
        self.set_state("starting", "starting")
        out = await super().start_kernel(*args, **kwargs)
        self.set_state("started", "busy")
        await self.connect()
        return out
        
    async def shutdown_kernel(self, *args, **kwargs):
        self.set_state("terminating", "busy")
        await self.disconnect()
        out = await super().shutdown_kernel(*args, **kwargs)
        self.set_state("terminated", "dead")
     
    async def restart_kernel(self, *args, **kwargs):
        self.set_state("restarting", "busy")
        return await super().restart_kernel(*args, **kwargs)
