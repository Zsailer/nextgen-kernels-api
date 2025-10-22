import asyncio
import time
import typing as t
from datetime import datetime, timezone

from traitlets import HasTraits
from jupyter_client.asynchronous.client import AsyncKernelClient
from jupyter_client.channelsabc import ChannelABC
from .states import ExecutionStates
from .cache import KernelMessageCache


def _extract_message_id_and_cache(client, result, method_name, kwargs):
    """Helper function to extract message ID and cache the message."""
    # Extract message ID from the result
    msg_id = None
    msg_type = None

    if hasattr(result, 'header') and hasattr(result.header, 'get'):
        msg_id = result.header.get('msg_id')
        msg_type = result.header.get('msg_type')
    elif hasattr(result, 'header') and 'msg_id' in result.header:
        msg_id = result.header['msg_id']
        msg_type = result.header.get('msg_type')
    elif isinstance(result, dict) and 'header' in result:
        header = result['header']
        msg_id = header.get('msg_id')
        msg_type = header.get('msg_type')
    elif hasattr(result, 'msg_id'):
        msg_id = result.msg_id
        msg_type = getattr(result, 'msg_type', None)
    elif isinstance(result, str):
        # Some methods return just the message ID string
        msg_id = result
        msg_type = method_name + '_request'

    # Cache the outgoing message if we found an ID
    if msg_id and hasattr(client, 'message_cache'):
        # Determine channel based on method name
        channel = client._get_channel_for_method(method_name)

        # Extract cell_id from kwargs if available (common in execute requests)
        cell_id = None
        if 'metadata' in kwargs and isinstance(kwargs['metadata'], dict):
            cell_id = kwargs['metadata'].get('cellId')

        client.message_cache.add({
            "msg_id": msg_id,
            "channel": channel,
            "cell_id": cell_id,
            "msg_type": msg_type,
            "method": method_name,
            "outgoing": True  # Mark as outgoing message
        })


class JupyterServerKernelClientMixin(HasTraits):
    """Simple mixin that adds listener functionality to AsyncKernelClient."""

    # Track kernel execution state (simplified - just a string)
    execution_state: str = ExecutionStates.UNKNOWN.value

    # Track kernel activity
    last_activity: datetime = None

    # Track last status message time per channel (shell and control)
    last_shell_status_time: datetime = None
    last_control_status_time: datetime = None

    # Connection test configuration
    connection_test_timeout: float = 120.0  # Total timeout for connection test in seconds
    connection_test_check_interval: float = 1.0  # How often to check for messages in seconds
    connection_test_retry_interval: float = 10.0  # How often to retry kernel_info requests in seconds

    # Set of listener functions - don't use Traitlets Set, just plain Python set
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listeners = set()
        self._listening = False

        # Connection state tracking
        self._connecting = False
        self._connection_ready = False
        self._connection_ready_event = asyncio.Event()

        # Message queue for messages received before connection is ready
        self._queued_messages = []
        self._max_queue_size = 1000  # Prevent memory issues

        # Message cache for tracking outgoing messages
        self.message_cache = KernelMessageCache(parent=self)

        # Flag to track if methods are wrapped
        self._methods_wrapped = False

        # Ensure upstream methods are wrapped to track outgoing messages
        self._ensure_methods_wrapped()

    def add_listener(self, callback: t.Callable[[str, list[bytes]], None]):
        """Add a listener to be called when messages are received.

        Args:
            callback: Function that takes (channel_name, msg_bytes) as arguments
        """
        self._listeners.add(callback)

    def remove_listener(self, callback: t.Callable[[str, list[bytes]], None]):
        """Remove a listener."""
        self._listeners.discard(callback)

    def _get_channel_for_method(self, method_name: str) -> str:
        """Determine which channel a kernel client method uses."""
        # Most kernel methods use the shell channel
        shell_methods = {
            'execute', 'execute_interactive', 'complete', 'inspect',
            'history', 'is_complete', 'comm_info', 'kernel_info'
        }

        # Control channel methods (typically for shutdown/restart)
        control_methods = {'shutdown', 'restart'}

        # Input methods use stdin channel
        stdin_methods = {'input'}

        if method_name in control_methods:
            return 'control'
        elif method_name in stdin_methods:
            return 'stdin'
        else:
            # Default to shell channel for most methods
            return 'shell'

    def _wrap_upstream_methods(self):
        """Wrap upstream kernel client methods to track outgoing messages."""
        # Methods to wrap for message tracking
        methods_to_wrap = {
            'execute', 'execute_interactive', 'complete', 'inspect',
            'history', 'is_complete', 'comm_info', 'kernel_info',
            'shutdown', 'restart'
        }

        for method_name in methods_to_wrap:
            if hasattr(self, method_name):
                original_method = getattr(self, method_name)

                # Create a wrapper that uses the same logic as the decorators
                if asyncio.iscoroutinefunction(original_method):
                    def create_async_wrapper(client, orig_method, name):
                        async def async_wrapper(*args, **kwargs):
                            result = await orig_method(*args, **kwargs)
                            _extract_message_id_and_cache(client, result, name, kwargs)
                            return result
                        return async_wrapper
                    wrapped_method = create_async_wrapper(self, original_method, method_name)
                else:
                    def create_sync_wrapper(client, orig_method, name):
                        def sync_wrapper(*args, **kwargs):
                            result = orig_method(*args, **kwargs)
                            _extract_message_id_and_cache(client, result, name, kwargs)
                            return result
                        return sync_wrapper
                    wrapped_method = create_sync_wrapper(self, original_method, method_name)

                # Preserve the original method attributes
                wrapped_method.__name__ = method_name
                wrapped_method.__qualname__ = f"{self.__class__.__name__}.{method_name}"
                wrapped_method.__doc__ = getattr(original_method, '__doc__', None)

                # Replace the method with our wrapped version
                setattr(self, method_name, wrapped_method)

    def _ensure_methods_wrapped(self):
        """Ensure upstream methods are wrapped - call this after initialization."""
        if not self._methods_wrapped:
            self._wrap_upstream_methods()
            self._methods_wrapped = True

    def mark_connection_ready(self):
        """Mark the connection as ready and process queued messages."""
        if not self._connection_ready:
            self._connecting = False
            self._connection_ready = True
            self._connection_ready_event.set()

            # Process queued messages
            asyncio.create_task(self._process_queued_messages())

    async def wait_for_connection_ready(self, timeout: float = 30.0) -> bool:
        """Wait for the connection to be ready."""
        try:
            await asyncio.wait_for(self._connection_ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _process_queued_messages(self):
        """Process all messages that were queued during startup."""
        self.log.info(f"Processing {len(self._queued_messages)} queued messages")

        queued_messages = self._queued_messages.copy()
        self._queued_messages.clear()

        for channel_name, msg in queued_messages:
            try:
                # Send queued messages to the kernel (these are incoming from websockets)
                self._send_message(channel_name, msg)
            except Exception as e:
                self.log.error(f"Error processing queued message: {e}")

    def _queue_message_if_not_ready(self, channel_name: str, msg: list[bytes]) -> bool:
        """Queue a message if connection is not ready. Returns True if queued."""
        if not self._connection_ready:
            if len(self._queued_messages) < self._max_queue_size:
                self._queued_messages.append((channel_name, msg))
                return True
            else:
                # Queue is full, drop oldest message
                self._queued_messages.pop(0)
                self._queued_messages.append((channel_name, msg))
                self.log.warning("Message queue full, dropping oldest message")
                return True
        return False

    def _send_message(self, channel_name: str, msg: list[bytes]):
        # Route message to the appropriate kernel channel
        try:
            channel = getattr(self, f"{channel_name}_channel", None)
            channel.session.send_raw(channel.socket, msg)

        except Exception as e:
            self.log.warn("Error handling incoming message.")

    def handle_incoming_message(self, channel_name: str, msg: list[bytes]):
        """Handle incoming kernel messages and cache them for response mapping.

        This method processes incoming kernel messages and caches them so that
        response messages can be mapped back to the source channel.

        Args:
            channel_name: The channel the message came from ('shell', 'iopub', etc.)
            msg: The raw message bytes (already deserialized from websocket format)
        """
        # Validate message has content
        if not msg or len(msg) == 0:
            return

        # Cache the message ID and its channel so that any response message
        # can be mapped back to the source channel
        try:
            header = self.session.unpack(msg[0])
            msg_id = header["msg_id"]
            msg_type = header.get("msg_type")
            metadata = self.session.unpack(msg[2])
            cell_id = metadata.get("cellId")

            self.message_cache.add({
                "msg_id": msg_id,
                "channel": channel_name,
                "cell_id": cell_id,
                "msg_type": msg_type,
                "outgoing": False  # Mark as incoming message
            })
        except Exception as e:
            self.log.debug(f"Error caching incoming message: {e}")

        # If connection is not ready, queue the message
        if self._queue_message_if_not_ready(channel_name, msg):
            return

        self._send_message(channel_name, msg)


    def handle_outgoing_message(self, channel_name: str, msg: list[bytes]):
        """Public API for manufacturing messages to send to kernel client listeners.

        This allows external code to simulate kernel messages and send them to all
        registered listeners, useful for testing and message injection.

        Args:
            channel_name: The channel the message came from ('shell', 'iopub', etc.)
            msg: The raw message bytes
        """
        # Same as handle_incoming_message - route to all listeners
        asyncio.create_task(self._route_to_listeners(channel_name, msg))

    async def _route_to_listeners(self, channel_name: str, msg: list[bytes]):
        """Route message to all registered listeners."""
        if not self._listeners:
            return

        # Debug: log message type being routed
        try:
            header = self.session.unpack(msg[0]) if msg and len(msg) > 0 else {}
            msg_type = header.get('msg_type', 'unknown')
            self.log.debug(f"Routing {channel_name} message ({msg_type}) to {len(self._listeners)} listeners")
        except Exception:
            pass

        # Create tasks for all listeners
        tasks = []
        for listener in self._listeners:
            task = asyncio.create_task(self._call_listener(listener, channel_name, msg))
            tasks.append(task)

        # Wait for all listeners to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _call_listener(self, listener: t.Callable, channel_name: str, msg: list[bytes]):
        """Call a single listener, ensuring it's async and handling errors."""
        try:
            result = listener(channel_name, msg)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            self.log.error(f"Error in listener {listener}: {e}")

    def _update_execution_state_from_status(self, channel_name: str, msg_dict: dict, parent_msg_id: str = None, execution_state: str = None):
        """Update execution state from a status message if it originated from shell channel.

        This method checks if a status message on the iopub channel originated from a shell
        channel request before updating the execution state. This prevents control channel
        status messages from affecting execution state tracking.

        Additionally tracks the last time we received status messages from shell and control
        channels for connection monitoring purposes.

        Args:
            channel_name: The channel the message came from (should be 'iopub')
            msg_dict: The deserialized message dictionary
            parent_msg_id: Optional parent message ID (extracted if not provided)
            execution_state: Optional execution state (extracted if not provided)
        """
        if channel_name != "iopub" or msg_dict.get("msg_type") != "status":
            return

        try:
            # Extract parent_msg_id if not provided
            if parent_msg_id is None:
                parent_header = msg_dict.get("parent_header", {})
                if isinstance(parent_header, bytes):
                    parent_header = self.session.unpack(parent_header)
                parent_msg_id = parent_header.get("msg_id")

            # Check if parent message came from shell or control channel using message cache
            if parent_msg_id and parent_msg_id in self.message_cache:
                cached_msg = self.message_cache[parent_msg_id]
                parent_channel = cached_msg.get("channel")

                # Track last status message time for both shell and control channels
                current_time = datetime.now(timezone.utc)
                if parent_channel == "shell":
                    self.last_shell_status_time = current_time
                    self.last_activity = current_time
                elif parent_channel == "control":
                    self.last_control_status_time = current_time

                # Only update execution state if message came from shell channel
                if parent_channel == "shell":
                    # Extract execution_state if not provided
                    if execution_state is None:
                        content = msg_dict.get("content", {})
                        if isinstance(content, bytes):
                            content = self.session.unpack(content)
                        execution_state = content.get("execution_state")

                    if execution_state:
                        old_state = self.execution_state
                        self.execution_state = execution_state
                        self.log.debug(f"Execution state: {old_state} -> {execution_state}")
            else:
                # Extract execution_state to log what we're ignoring
                if execution_state is None:
                    content = msg_dict.get("content", {})
                    if isinstance(content, bytes):
                        content = self.session.unpack(content)
                    execution_state = content.get("execution_state")
                self.log.debug(f"Ignoring status message - parent not in cache (state would be: {execution_state})")
        except Exception as e:
            self.log.debug(f"Error updating execution state from status message: {e}")

    async def broadcast_state(self):
        """Broadcast current kernel execution state to all listeners.

        This method creates and sends a status message to all kernel listeners
        (typically WebSocket connections) to inform them of the current kernel
        execution state.

        The status message is manufactured using the session's message format
        and sent through the normal listener routing mechanism.
        """
        try:
            # Create status message as a dict
            parent_header = self.session.msg_header("status")
            msg_dict = self.session.msg("status", content={"execution_state": self.execution_state}, parent=parent_header)

            # Serialize using session.serialize to create a proper ZMQ message format
            # This returns the full message including signature, just like recv_multipart() would
            # We need to drop the signature and identities (first 2 elements)
            msg_parts = self.session.serialize(msg_dict)[2:]

            # Send to listeners - same format as messages from the kernel
            self.handle_outgoing_message("iopub", msg_parts)

        except Exception as e:
            self.log.warning(f"Failed to broadcast state: {e}")

    async def start_listening(self):
        """Start listening for messages and monitoring channels."""
        # Start background tasks to monitor channels for messages
        self._monitoring_tasks = []
        self._listening = True

        # Monitor each channel for incoming messages
        for channel_name in ['iopub', 'shell', 'stdin', 'control']:
            channel = getattr(self, f"{channel_name}_channel", None)
            if channel and channel.is_alive():
                task = asyncio.create_task(self._monitor_channel_messages(channel_name, channel))
                self._monitoring_tasks.append(task)

        self.log.info(f"Started listening with {len(self._listeners)} listeners")

    async def stop_listening(self):
        """Stop listening for messages."""
        # Stop monitoring tasks
        if hasattr(self, '_monitoring_tasks'):
            for task in self._monitoring_tasks:
                task.cancel()
            self._monitoring_tasks = []

        self.log.info(f"Stopped listening")

    async def _monitor_channel_messages(self, channel_name: str, channel: ChannelABC):
        """Monitor a channel for incoming messages and route them to listeners."""
        try:
            while channel.is_alive():
                try:
                    # Check if there's a message ready (non-blocking)
                    has_message = await channel.msg_ready()
                    if has_message:
                        msg = await channel.socket.recv_multipart()

                        # For deserialization and state tracking, use feed_identities to strip routing frames
                        idents, msg_list = channel.session.feed_identities(msg)

                        # Deserialize WITHOUT content for performance (content=False)
                        msg_dict = channel.session.deserialize(msg_list, content=False)

                        # Update execution state from status messages
                        self._update_execution_state_from_status(channel_name, msg_dict)

                        # Route to listeners with msg_list (after feed_identities removes identity frames and delimiter)
                        # msg_list should have format: [signature, header, parent_header, metadata, content, ...buffers]
                        # But for v1 websocket protocol, we don't want the signature - skip it
                        if msg_list and len(msg_list) > 4:
                            # Has signature as first element - skip it
                            await self._route_to_listeners(channel_name, msg_list[1:])
                        else:
                            # Already just the 4 message parts
                            await self._route_to_listeners(channel_name, msg_list)

                except Exception as e:
                    # Log the error instead of silently ignoring it
                    self.log.debug(f"Error processing message in {channel_name}: {e}")
                    continue  # Continue with next message instead of breaking

                # Small sleep to avoid busy waiting
                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.error(f"Channel monitoring failed for {channel_name}: {e}")

    async def _test_kernel_communication(self, timeout: float = None) -> bool:
        """Test kernel communication by monitoring execution state and sending kernel_info requests.

        This method uses a robust heuristic to determine if the kernel is connected:
        1. Checks if execution state is 'idle' (indicates shell channel is responding)
        2. Sends kernel_info requests to both shell and control channels in parallel
        3. Monitors for status message responses from either channel
        4. Retries periodically if no response is received
        5. Considers kernel connected if we receive any status messages, even if state is 'busy'

        Args:
            timeout: Total timeout for connection test in seconds (uses connection_test_timeout if not provided)

        Returns:
            bool: True if communication test successful, False otherwise
        """
        if timeout is None:
            timeout = self.connection_test_timeout

        start_time = time.time()
        connection_attempt_time = datetime.now(timezone.utc)

        self.log.info("Starting kernel communication test")

        # Give the kernel a moment to be ready to receive messages
        # Heartbeat beating doesn't guarantee the kernel is ready for requests
        await asyncio.sleep(0.5)

        # Send initial kernel_info requests immediately
        try:
            await asyncio.gather(
                self._send_kernel_info_shell(),
                self._send_kernel_info_control(),
                return_exceptions=True
            )
        except Exception as e:
            self.log.debug(f"Error sending initial kernel_info requests: {e}")

        last_kernel_info_time = time.time()

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time

            # Check if execution state is idle (shell channel responding and kernel ready)
            if self.execution_state == ExecutionStates.IDLE.value:
                self.log.info("Kernel communication test succeeded: execution state is idle")
                return True

            # Check if we've received any status messages since connection attempt
            # This indicates the kernel is connected, even if busy executing something
            if self.last_shell_status_time and self.last_shell_status_time > connection_attempt_time:
                self.log.info("Kernel communication test succeeded: received shell status message")
                return True

            if self.last_control_status_time and self.last_control_status_time > connection_attempt_time:
                self.log.info("Kernel communication test succeeded: received control status message")
                return True

            # Send kernel_info requests at regular intervals
            time_since_last_request = time.time() - last_kernel_info_time
            if time_since_last_request >= self.connection_test_retry_interval:
                self.log.debug(f"Sending kernel_info requests to shell and control channels (elapsed: {elapsed:.1f}s)")

                try:
                    # Send kernel_info to both channels in parallel (no reply expected)
                    await asyncio.gather(
                        self._send_kernel_info_shell(),
                        self._send_kernel_info_control(),
                        return_exceptions=True
                    )
                    last_kernel_info_time = time.time()
                except Exception as e:
                    self.log.debug(f"Error sending kernel_info requests: {e}")

            # Wait before next check
            await asyncio.sleep(self.connection_test_check_interval)

        self.log.error(f"Kernel communication test failed: no response after {timeout}s")
        return False

    async def _send_kernel_info_shell(self):
        """Send kernel_info request on shell channel (no reply expected)."""
        try:
            if hasattr(self, 'kernel_info'):
                # Send without waiting for reply
                self.kernel_info(reply=False)
        except Exception as e:
            self.log.debug(f"Error sending kernel_info on shell channel: {e}")

    async def _send_kernel_info_control(self):
        """Send kernel_info request on control channel (no reply expected)."""
        try:
            # Control channel kernel_info - we just want to trigger a status message
            if hasattr(self.control_channel, 'send'):
                msg = self.session.msg('kernel_info_request')
                msg_id = msg['header']['msg_id']

                # Manually cache this message with control channel
                # We can't use _extract_message_id_and_cache because it determines channel
                # based on method name, and kernel_info defaults to shell channel
                self.message_cache.add({
                    "msg_id": msg_id,
                    "channel": "control",
                    "cell_id": None,
                    "msg_type": "kernel_info_request",
                    "method": "kernel_info",
                    "outgoing": True
                })

                self.control_channel.send(msg)
        except Exception as e:
            self.log.debug(f"Error sending kernel_info on control channel: {e}")

    async def connect(self) -> bool:
        """Connect to the kernel and verify communication.

        This method:
        1. Starts all channels
        2. Begins listening for messages
        3. Waits for heartbeat to confirm connectivity
        4. Tests kernel communication with configurable retries
        5. Marks connection as ready

        Returns:
            bool: True if connection successful, False otherwise
        """
        if self._connecting:
            return await self.wait_for_connection_ready()

        if self._connection_ready:
            return True

        self._connecting = True

        try:
            self.execution_state = ExecutionStates.BUSY.value
            self.last_activity = datetime.now(timezone.utc)

            # Handle both sync and async versions of start_channels
            result = self.start_channels()
            if asyncio.iscoroutine(result):
                await result

            # Verify channels are running.
            assert self.channels_running

            # Start our listening
            await self.start_listening()

            # Unpause heartbeat channel if method exists
            if hasattr(self.hb_channel, 'unpause'):
                self.hb_channel.unpause()

            # Wait for heartbeat
            attempt = 0
            max_attempts = 10
            while not self.hb_channel.is_beating():
                attempt += 1
                if attempt > max_attempts:
                    raise Exception("The kernel took too long to connect to the Kernel Sockets.")
                await asyncio.sleep(0.1)

            # Test kernel communication (handles retries internally)
            if not await self._test_kernel_communication():
                self.log.error(f"Kernel communication test failed after {self.connection_test_timeout}s timeout")
                return False

            # Mark connection as ready and process queued messages
            self.mark_connection_ready()

            # Update execution state to idle if it's not already set
            # (it might already be idle if we received a status message during connection test)
            if self.execution_state == ExecutionStates.BUSY.value:
                self.execution_state = ExecutionStates.IDLE.value
                self.last_activity = datetime.now(timezone.utc)

            self.log.info(f"Successfully connected to kernel")
            return True

        except Exception as e:
            self.log.error(f"Failed to connect to kernel: {e}")
            self._connecting = False
            return False

    def is_connecting(self) -> bool:
        """Check if the kernel is currently attempting to connect.

        Returns:
            bool: True if connection is in progress, False otherwise
        """
        return self._connecting

    def is_connected(self) -> bool:
        """Check if the kernel is connected and communicating.

        A kernel is considered connected if:
        1. Connection is marked as ready
        2. Heartbeat is active (if available)

        Returns:
            bool: True if connected and communicating, False otherwise
        """
        if not self._connection_ready:
            return False

        # Check heartbeat if available
        return self.hb_channel.is_beating()

    async def disconnect(self):
        """Disconnect from the kernel and reset connection state.

        This method:
        1. Stops listening for messages
        2. Stops all channels
        3. Resets connection state flags
        4. Clears channel references

        Note: Does not remove listeners - they will be preserved for reconnection.
        """
        # Stop listening for messages
        await self.stop_listening()

        # Stop all channels
        self.stop_channels()

        # Reset connection state
        self._connecting = False
        self._connection_ready = False
        self._connection_ready_event.clear()

        # Clear channel references
        self._shell_channel = None
        self._iopub_channel = None
        self._stdin_channel = None
        self._control_channel = None
        self._hb_channel = None

        self.log.info("Disconnected from kernel")

    async def reconnect(self) -> bool:
        """Reconnect to the kernel.

        This is a convenience method that disconnects and then connects again.
        Useful for recovering from stale connections or network issues.

        Returns:
            bool: True if reconnection successful, False otherwise
        """
        self.log.info("Reconnecting to kernel...")
        await self.disconnect()
        return await self.connect()


class JupyterServerKernelClient(JupyterServerKernelClientMixin, AsyncKernelClient):
    """
    A simplified kernel client with listener functionality and message queuing.
    """