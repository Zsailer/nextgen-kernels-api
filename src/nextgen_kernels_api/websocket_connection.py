import asyncio
import json

from traitlets import Bool
from traitlets import default
from traitlets import Instance

try:
    from jupyter_client.jsonutil import json_default
except ImportError:
    from jupyter_client.jsonutil import date_default as json_default

from jupyter_client.session import Session
from tornado.websocket import WebSocketClosedError
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
)
from .states import LIFECYCLE_DEAD_STATES


class NextGenKernelWebsocketConnection(BaseKernelWebsocketConnection):
    """A websocket client that connects to a kernel manager."""

    # We explicitly set this to an empty string in JupyterLab 4.x,
    # since JLab 4 supports the newest websocket protocol, but
    # this custom kernel manager does not support this protocol.
    # This was leading to broken kernel communication. We need to
    # support the new subprotocol in the future.
    # Note that if this value is `None`, it will default to the
    # new (problematic) subprotocol.
    kernel_ws_protocol = ""

    _session: Session = Instance(Session, allow_none=True)

    @property
    def session(self) -> Session:
        # Ensure the key is always correct.
        if not self._session:
            self._session = self.kernel_manager.session.clone()
        self._session.key = self.kernel_manager.session.key
        return self._session

    async def connect(self):
        """A synchronous method for connecting to the kernel via a kernel session.
        This connection might take a few minutes, so we turn this into an
        asyncio task happening in parallel.
        """
        self.kernel_manager.add_listener(self.handle_outgoing_message)
        self.kernel_manager.broadcast_state()
        self.log.info("Kernel websocket is now listening to kernel.")

    def disconnect(self):
        self.kernel_manager.remove_listener(self.handle_outgoing_message)

    def handle_incoming_message(self, ws_message):
        """Handle the incoming WS message"""
        
        msg = json.loads(ws_message)
        channel_name = msg.pop("channel", None)
        if self.kernel_manager._client:
            self.kernel_manager.send_message(channel_name, msg)

    def handle_outgoing_message(self, socket_name, raw_msg):
        """Handle the ZMQ message."""
        try:            
            # Unpack the message a bit to determine the source and content.
            _, smsg = self.session.feed_identities(raw_msg)
            # Only deserialize the headers to determine the routing information.
            dmsg = self.session.deserialize(smsg, content=True)
            dmsg["channel"] = socket_name
            msg = json.dumps(dmsg, default=json_default)
            self.websocket_handler.write_message(msg, binary=isinstance(msg, bytes))
        except WebSocketClosedError:
            self.log.warning("A ZMQ message arrived on a closed websocket channel.")
            
            
    def _deserialize_message(self, websocket_msg): 
        return websocket_msg
            
    def _serialize_message(self, kernel_msg):
        return kernel_msg