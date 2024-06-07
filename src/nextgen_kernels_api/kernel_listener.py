import asyncio
import typing as t
from traitlets import Set
from traitlets import Instance
from traitlets import Any
from traitlets import HasTraits
from .utils import LRUCache
from jupyter_client.asynchronous.client import AsyncKernelClient

import anyio


class KernelListenerMixin(HasTraits): 
    """"""
    _client: t.Optional[AsyncKernelClient] = Instance(AsyncKernelClient, allow_none=True)
    
    # Having this message cache is not ideal. 
    # Unfortunately, we don't include the parent channel
    # in the messages that generate IOPub status messages, thus,
    # we can't differential between the control channel vs.
    # shell channel status. This message cache gives us 
    # the ability to map status message back to their source.
    message_source_cache = Instance(
        default_value=LRUCache(maxsize=1000), klass=LRUCache
    )

    # A set of callables that are called when a
    # ZMQ message comes back from the kernel.
    _listeners = Set(allow_none=True)

    async def start_listening(self):
        """Start listening to messages coming from the kernel.
        
        Use anyio to setup a task group for listening.
        """
        if not self._client:
            raise Exception("It doesn't look like a kernel client has been defined. Try calling `connect`.")
        
        # Wrap a taskgroup so that it can be backgrounded.
        async def _listening():
            async with anyio.create_task_group() as tg:
                for channel_name in ["shell", "control", "stdin", "iopub"]:
                    tg.start_soon(
                        self._listen_for_messages, channel_name
                    )
    
        # Background this task.
        self._listening_task = asyncio.create_task(_listening())

    async def stop_listening(self):
        # If the listening task isn't defined yet
        # do nothing.
        if not self._listening_task:
            return
        
        # Attempt to cancel the task.
        self._listening_task.cancel()
        try:
            # Await cancellation.
            await self._listening_task
        except asyncio.CancelledError:
            self.log.info("Disconnected from client from the kernel.")
        # Log any exceptions that were raised.
        except Exception as err:
            self.log.error(err)
                        
    _listening_task: t.Optional[t.Awaitable] = Any(allow_none=True)

    def send_message(self, channel_name, msg):
        """Use the given session to send the message."""
        # Cache the message ID and its socket name so that
        # any response message can be mapped back to the
        # source channel.
        msg_id = msg["header"]["msg_id"]
        self.message_source_cache[msg_id] = channel_name
        channel = getattr(self._client, f"{channel_name}_channel")
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
            for listener in self._listeners:

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
        channel = getattr(self._client, f"{channel_name}_channel")
        while True:
            # Wait for a message
            await channel.socket.poll(timeout=float("inf"))
            raw_msg = await channel.socket.recv_multipart()
            try:
                await self.recv_message(channel_name, raw_msg)
            except Exception as err:
                self.log.error(err)
        
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
                # Don't broadcast, since this message is already going out.
                self.set_state("starting", status, broadcast=False)
            else:
                parent = deserialized_msg.get("parent_header", {})
                msg_id = parent.get("msg_id", "")
                parent_channel = self.message_source_cache.get(msg_id, None)
                if parent_channel and parent_channel == "shell":
                    # Don't broadcast, since this message is already going out.
                    self.set_state("connected", status, broadcast=False)

    def broadcast_state(self):
        """Broadcast state to all listeners"""
        # Emit this state to all listeners
        for listener in self._listeners:
            # Manufacture a message
            msg = self.session.msg("status", {"execution_state": self.execution_state})
            raw_msg = self.session.serialize(msg)
            listener("iopub", raw_msg)    

    async def connect(self):
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
        self._client = self.client()
        # Track execution state by watching all messages that come through
        # the kernel client.
        self.add_listener(self.execution_state_listener)
        self._client.start_channels()
        await self.start_listening()
        # The Heartbeat channel is paused by default; unpause it here
        self._client.hb_channel.unpause()
        # Wait for a living heartbeat.
        attempt = 0
        while not self._client.hb_channel.is_alive():
            attempt += 1
            if attempt > self.time_to_connect:
                # Set the state to unknown.
                self.set_state("unknown", "unknown")
                raise Exception("The kernel took too long to connect to the ZMQ sockets.")
            # Wait a second until the next time we try again.
            await asyncio.sleep(1)
        self.set_state("connected")
        
    async def disconnect(self):
        await self.stop_listening()
        self._client.stop_channels()