import asyncio
from typing import List, Tuple, Optional
from tornado.websocket import WebSocketClosedError
from traitlets import List as TraitletsList, Tuple as TraitletsTuple
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
)
from jupyter_server.services.kernels.connection.base import deserialize_msg_from_ws_v1, serialize_msg_to_ws_v1


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

    def _get_kernel_client(self):
        """Get the kernel client directly from the kernel manager.

        The kernel client is now a property on the kernel manager itself,
        created immediately when the kernel manager is instantiated.

        Note: self.kernel_manager is actually the parent, which is the specific
        KernelManager instance for this kernel (not the MultiKernelManager).
        """
        try:
            # self.kernel_manager is the specific KernelManager for this kernel
            km = self.kernel_manager
            if not km:
                raise RuntimeError(f"No kernel manager found for kernel {self.kernel_id}")

            # Get the pre-created kernel client from the kernel manager
            if not hasattr(km, 'kernel_client') or km.kernel_client is None:
                raise RuntimeError(f"Kernel manager for {self.kernel_id} has no kernel_client")

            return km.kernel_client

        except Exception as e:
            raise RuntimeError(f"Failed to get kernel client for kernel {self.kernel_id}: {e}")

    async def connect(self):
        """Connect to the kernel via a kernel session with deferred channel connection.

        The client connection is now handled by the kernel manager in post_start_kernel().
        The websocket just needs to add itself as a listener to receive messages.
        """
        # Get the client from the kernel manager
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

        self.log.info(f"Kernel websocket connected and listening for kernel {self.kernel_id}")

    def disconnect(self):
        """Disconnect the websocket from the kernel client."""
        try:
            # Get the kernel client from the kernel manager
            client = self._get_kernel_client()
            if client:
                # Remove this websocket's listener from the client
                client.remove_listener(self.handle_outgoing_message)
        except Exception as e:
            self.log.warning(f"Failed to disconnect websocket for kernel {self.kernel_id}: {e}")

    def handle_incoming_message(self, incoming_msg):
        """Handle the incoming WS message"""
        channel_name, msg_list = deserialize_msg_from_ws_v1(incoming_msg)

        try:
            # Get the kernel client from the kernel manager
            client = self._get_kernel_client()
            if client:
                client.handle_incoming_message(channel_name, msg_list)
        except Exception as e:
            self.log.error(f"Failed to handle incoming message for kernel {self.kernel_id}: {e}")

    def handle_outgoing_message(self, channel_name, msg):
        """Handle the Kernel Socket message."""
        try:
            # Note: The message received here should be the 4 core message frames
            # [header, parent_header, metadata, content, ...buffers]
            # after identities, delimiter, and signature have been stripped

            # Validate message has content before processing
            if not msg or len(msg) == 0:
                return

            # Serialize to websocket format and send
            bin_msg = serialize_msg_to_ws_v1(msg, channel_name)
            self.websocket_handler.write_message(bin_msg, binary=True)
        except WebSocketClosedError:
            self.log.warning("A Kernel Socket message arrived on a closed websocket channel.")
        except Exception as err:
            self.log.error(f"Error handling outgoing message on {channel_name}: {err}")