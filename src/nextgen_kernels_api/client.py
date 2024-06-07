import asyncio
import typing as t
from jupyter_client.session import Session
from jupyter_client.asynchronous.client import AsyncKernelClient
from traitlets import Set
from traitlets import Instance
from .utils import LRUCache
from jupyter_server.utils import ensure_async

import anyio

import random 
import string

CHANNELS = ["shell", "control", "stdin", "iopub", "hb"]


class NextGenKernelClient(AsyncKernelClient):
    """
    """

    message_source_cache = Instance(
        default_value=LRUCache(maxsize=1000), klass=LRUCache
    )

    @property
    def channels(self): 
        return [
            self.shell_channel, 
            self.control_channel, 
            self.hb_channel, 
            self.stdin_channel, 
            self.iopub_channel
        ]

    # A set of callables that are called when a
    # ZMQ message comes back from the kernel.
    _listeners = Set(allow_none=True)

    @property
    def listeners(self) -> t.Optional[set]:
        """A set of callables that are called when a
        ZMQ message comes back from the kernel.
        """
        return self._listeners
    
    def start_channels(self, shell: bool = True, iopub: bool = True, stdin: bool = True, hb: bool = True, control: bool = True) -> None:
        out = super().start_channels(shell, iopub, stdin, hb, control)
        for channel_name in ["shell", "control", "stdin", "iopub"]:
            asyncio.create_task(
                self._listen_for_messages(channel_name)
            )
        return out

    def send_message(self, channel_name, msg):
        """Use the given session to send the message."""
        # Cache the message ID and its socket name so that
        # any response message can be mapped back to the
        # source channel.
        msg_id = msg["header"]["msg_id"]
        self.message_source_cache[msg_id] = channel_name
        channel = getattr(self, f"{channel_name}_channel")
        channel.send(msg)
        
    async def recv_message(self, channel_name, raw_msg):
        """This is the main method that consumes every
        message coming back from the kernel. It parses the header
        (not the content, which might be large) and updates
        the last_activity, execution_state, and lifecycle_state
        when appropriate. Then, it routes the message
        to all listeners.
        """
        # Broadcast messages
        async with anyio.create_task_group() as tg:
            # Broadcast the message to all listeners.
            for listener in self.listeners:

                async def _wrap_listener(listener, channel_name, raw_msg): 
                    """
                    Wrap the listener to ensure its async and 
                    logs (instead of raises) exceptions.
                    """
                    try:
                        listener(channel_name, raw_msg)
                    except Exception as err:
                        self.log.error(err)
                
                tg.start_soon(_wrap_listener, listener, channel_name, raw_msg)

        
    def broadcast_state(self):
        """Broadcast the current execution state to all listeners.

        This method is useful when a disconnect happens or if
        a client implements a polling mechanism for the execution state.
        """
        for listener in self.state_listeners:
            try:
                listener()
            except Exception as err:
                self.log.error(err)

    def add_listener(self, callback: t.Callable[[dict], None]):
        """Add a listener to the ZMQ Interface.

        A listener is a callable function/method that takes
        the deserialized (minus the content) ZMQ message.

        If the listener is already registered, it won't be registered again.
        """
        self._listeners.add(callback)

    def remove_listener(self, callback: t.Callable[[dict], None]):
        """Remove a listener to teh ZMQ interface. If the listener
        is not found, this method does nothing.
        """
        self._listeners.discard(callback)

    async def _listen_for_messages(self, channel_name):
        """The basic polling loop for listened to kernel messages
        on a ZMQ socket.
        """
        # Wire up the ZMQ sockets
        # Setup up ZMQSocket broadcasting.
        channel = getattr(self, f"{channel_name}_channel")
        while True:
            # Wait for a message
            await channel.socket.poll(timeout=float("inf"))
            raw_msg = await channel.socket.recv_multipart()
            try:
                await self.recv_message(channel_name, raw_msg)
            except Exception as err:
                self.log.error(err)