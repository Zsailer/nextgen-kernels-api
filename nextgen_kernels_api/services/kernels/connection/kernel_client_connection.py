import asyncio
from typing import List, Tuple, Optional
from tornado.websocket import WebSocketClosedError
from traitlets import List as TraitletsList, Tuple as TraitletsTuple
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
)
from jupyter_server.services.kernels.connection.base import deserialize_msg_from_ws_v1, serialize_msg_to_ws_v1
from ..client_manager import KernelClientManager


class KernelClientWebsocketConnection(BaseKernelWebsocketConnection):

    kernel_ws_protocol = "v1.kernel.websocket.jupyter.org"

    # Configurable message filtering traits
    msg_types = TraitletsList(
        trait=TraitletsTuple(),
        default_value=None,
        allow_none=True,
        config=True,
        help="""
        List of (msg_type, channel) tuples to include for this websocket connection.
        If None (default), all messages are sent. If specified, only messages matching
        these (msg_type, channel) pairs will be sent to the websocket.

        Example: [("status", "iopub"), ("execute_reply", "shell")]
        """
    )

    exclude_msg_types = TraitletsList(
        trait=TraitletsTuple(),
        default_value=None,
        allow_none=True,
        config=True,
        help="""
        List of (msg_type, channel) tuples to exclude for this websocket connection.
        If None (default), no messages are excluded. If specified, messages matching
        these (msg_type, channel) pairs will NOT be sent to the websocket.

        Example: [("status", "iopub")]

        Note: Cannot be used together with msg_types. If both are specified,
        msg_types takes precedence.
        """
    )

    def _get_client_manager(self):
        """Get the kernel client manager instance."""
        return KernelClientManager.instance()

    def _get_kernel_client(self):
        """Get the kernel client from the client manager."""
        try:
            client_manager = self._get_client_manager()

            # First check if client already exists
            if client_manager.has_client(self.kernel_id):
                return client_manager.get_client(self.kernel_id)

            # Create new client if not found
            client = client_manager.create_client(self.kernel_id)
            if not client:
                raise RuntimeError(f"No kernel client found in manager for kernel {self.kernel_id}")
            return client
        except Exception as e:
            raise RuntimeError(f"Failed to get kernel client from manager for kernel {self.kernel_id}: {e}")

    async def connect(self):
        """Connect to the kernel via a kernel session with deferred channel connection.

        The key change: Create the client immediately but defer actual channel connection
        until the kernel is ready. Messages received before the connection is ready
        will be queued and processed once the connection is established.
        """
        # Get or create the client
        client = self._get_kernel_client()

        # Add websocket listener immediately (messages will be queued if not ready)
        # Use configured message filtering if specified
        if self.msg_types is not None:
            # Convert list of tuples to list for the API
            msg_types_list = [tuple(item) for item in self.msg_types] if self.msg_types else None
            client.add_listener(self.handle_outgoing_message, msg_types=msg_types_list)
        elif self.exclude_msg_types is not None:
            # Convert list of tuples to list for the API
            exclude_msg_types_list = [tuple(item) for item in self.exclude_msg_types] if self.exclude_msg_types else None
            client.add_listener(self.handle_outgoing_message, exclude_msg_types=exclude_msg_types_list)
        else:
            # No filtering - listen to all messages (default)
            client.add_listener(self.handle_outgoing_message)

        # Broadcast current kernel state to this websocket immediately
        # This ensures websockets that connect during/after restart get the current state
        await client.broadcast_state()

        # Start the background connection process (don't await it)
        # This allows the websocket to be responsive immediately while
        # the kernel finishes starting up
        self._background_task = asyncio.create_task(self._background_connect())
        self.log.info(f"Kernel websocket is now listening to kernel (connection pending).")

    async def _background_connect(self):
        """Background task to connect the client once the kernel is ready."""
        try:
            # Verify kernel manager still exists for this kernel
            try:
                kernel_manager = self.kernel_manager.get_kernel(self.kernel_id)
                if not kernel_manager:
                    self.log.debug(f"Kernel {self.kernel_id} no longer exists, aborting background connection")
                    return
            except Exception:
                self.log.debug(f"Kernel {self.kernel_id} not found, aborting background connection")
                return

            # This will wait for kernel to be started, then connect channels
            client_manager = self._get_client_manager()
            success = await client_manager.connect_client(self.kernel_id)

            if success:
                self.log.info(f"Background connection successful for kernel {self.kernel_id}")
            else:
                self.log.warning(f"Background connection failed for kernel {self.kernel_id}")

        except asyncio.CancelledError:
            self.log.debug(f"Background connection cancelled for kernel {self.kernel_id}")
            raise
        except Exception as e:
            self.log.error(f"Background connection error for kernel {self.kernel_id}: {e}")

    def disconnect(self):
        # Cancel the background connection task if it's still running
        if hasattr(self, '_background_task') and self._background_task and not self._background_task.done():
            self._background_task.cancel()

        try:
            client_manager = self._get_client_manager()
            # Only remove listener if client exists, don't try to create it
            if client_manager.has_client(self.kernel_id):
                client = client_manager.get_client(self.kernel_id)
                client.remove_listener(self.handle_outgoing_message)
        except Exception as e:
            self.log.debug(f"Failed to disconnect websocket: {e}")

    def handle_incoming_message(self, incoming_msg):
        """Handle the incoming WS message"""
        channel_name, msg_list = deserialize_msg_from_ws_v1(incoming_msg)

        # Debug: log incoming message type from websocket
        try:
            if msg_list and len(msg_list) > 0:
                from jupyter_server.services.kernels.connection.base import BaseKernelWebsocketConnection
                # msg_list format is [header, parent_header, metadata, content, ...buffers]
                header = self.websocket_handler.session.unpack(msg_list[0])
                msg_type = header.get('msg_type', 'unknown')
                self.log.debug(f"Received {channel_name} message from websocket: {msg_type}")
        except Exception:
            pass

        try:
            client_manager = self._get_client_manager()
            # Only handle message if client exists, don't try to create it
            if client_manager.has_client(self.kernel_id):
                client = client_manager.get_client(self.kernel_id)
                client.handle_incoming_message(channel_name, msg_list)
            else:
                self.log.debug(f"Received message for kernel {self.kernel_id} but client no longer exists")
        except Exception as e:
            self.log.error(f"Failed to handle incoming message: {e}")

    def handle_outgoing_message(self, channel_name, msg):
        """Handle the Kernel Socket message."""
        try:
            # Note: The message received here should be the 4 core message frames
            # [header, parent_header, metadata, content, ...buffers]
            # after identities, delimiter, and signature have been stripped

            # Validate message has content before processing
            if not msg or len(msg) == 0:
                self.log.debug(f"Received empty message on channel {channel_name}")
                return

            # Debug: log shell channel messages to check if kernel_info_reply is being sent
            if channel_name == "shell":
                try:
                    from jupyter_server.services.kernels.connection.base import deserialize_msg_from_ws_v1
                    header = self.websocket_handler.session.unpack(msg[0]) if msg else {}
                    msg_type = header.get('msg_type', 'unknown')
                    self.log.debug(f"Sending shell message to websocket: {msg_type}")
                except Exception:
                    pass

            # Serialize to websocket format and send
            bin_msg = serialize_msg_to_ws_v1(msg, channel_name)
            self.websocket_handler.write_message(bin_msg, binary=True)
        except WebSocketClosedError:
            self.log.warning("A Kernel Socket message arrived on a closed websocket channel.")
        except Exception as err:
            self.log.error(f"Error handling outgoing message on {channel_name}: {err}")
            import traceback
            self.log.debug(f"Traceback: {traceback.format_exc()}")