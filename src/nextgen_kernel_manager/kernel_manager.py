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





class NextGenKernelManager(AsyncKernelManager):
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
    
    def set_state(self, lifecycle_state: types.LIFECYCLE_STATES, execution_state: types.EXECUTION_STATES):
        self._lifecycle_state = lifecycle_state
        self._execution_state = execution_state
        
    
    _client: typing.Optional[AsyncKernelClient] = Instance(klass="nextgen_kernel_manager.client.NextGenKernelClient", allow_none=True)
    
    client_class: DottedObjectName = DottedObjectName(
        "nextgen_kernel_manager.client.NextGenKernelClient"
    )

    @default("client_factory")
    def _client_factory_default(self) -> Type:
        return import_item(self.client_class)
    
    def _get_client(self, **kwargs: typing.Any):
        """Create a client configured to connect to our kernel"""
        kw: dict = {}
        kw.update(self.get_connection_info(session=True))
        kw.update(
            {
                "connection_file": self.connection_file,
                "parent": self,
            }
        )

        # add kwargs last, for manual overrides
        kw.update(kwargs)
        return self.client_factory(**kw)        
    
    # Replace the API where we can create multiple clients
    # per kernel manager. We don't want this anymore. We
    # *always* want only one client. This client can be
    # used in multiple places, but ideally, we only have a 
    # single set of ZMQ sockets open per kernel.
    @property
    def client(self):
        return self._client

    async def start_kernel(self, *args, **kwargs):
        self.set_state("starting", "starting")
        out = await super().start_kernel(*args, **kwargs)
        self.set_state("started", "busy")
        await self._connect_to_kernel()
        return out
        
    async def shutdown_kernel(self, *args, **kwargs):
        self.set_state("terminating", "busy")
        out = await super().shutdown_kernel(*args, **kwargs)
        self.set_state("terminated", "dead")
     
    async def restart_kernel(self, *args, **kwargs):
        self.set_state("restarting", "busy")
        out = await super().shutdown_kernel(*args, **kwargs)
        self.set_state("restarted", "busy")
        
    def execution_state_listener(self, channel_name, raw_msg):
        """Set the execution state by watching messages returned by the shell channel."""
        # Only continue if we're on the IOPub where the status is published.
        if channel_name != "iopub":
            return
        # Deserialize the message
        _, smsg = self.session.feed_identities(raw_msg)
        # Only deserialize the headers to determine is this is a status message
        deserialized_msg = self.session.deserialize(smsg, content=False)
        if deserialized_msg["msg_type"] == "status":
            content = self.session.unpack(deserialized_msg["content"])
            status = content["execution_state"]
            if status == "starting":
                self.set_state("starting", status)
            else:
                parent = deserialized_msg.get("parent_header", {})
                msg_id = parent.get("msg_id", "")
                parent_channel = self.client.message_source_cache.get(msg_id, None)
                if parent_channel and parent_channel == "shell":
                    self.set_state("connected", status)
        
    async def _connect_to_kernel(self):
        """Open a single client interface to the kernel.
        
        Ideally this method doesn't care if the kernel
        is actually started. It will just try a ZMQ 
        connection anyways and wait. This is helpful for
        handling 'pending' kernels, which might still 
        be in a starting phase. We can keep a connection
        open regardless if the kernel is ready. 
        """
        self.set_state("connecting", "busy")
        # Use the new API for getting a client.
        self._client = self._get_client()        
        # Track execution state by watching all messages that come through
        # the kernel client.
        self.client.add_listener(self.execution_state_listener)
        self.client.start_channels()
        # The Heartbeat channel is paused by default; unpause it here
        self.client.hb_channel.unpause()
        # Wait for a living heartbeat.
        attempt = 0
        while not self.client.hb_channel.is_alive():
            attempt += 1
            if attempt > self.time_to_connect:
                # Set the state to unknown.
                self.set_state("unknown", "unknown")
                raise Exception("The kernel took too long to connect to the ZMQ sockets.")
            # Wait a second until the next time we try again.
            await asyncio.sleep(1)
        self.set_state("connected", "busy")