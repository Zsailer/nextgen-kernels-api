"""Gateway kernel manager that integrates with our kernel monitoring system."""

import asyncio
from jupyter_server.gateway.managers import GatewayMappingKernelManager
from jupyter_server.gateway.managers import GatewayKernelManager as _GatewayKernelManager
from jupyter_server.gateway.managers import GatewayKernelClient as _GatewayKernelClient
from traitlets import default

from ..services.kernels.state_mixin import KernelManagerStateMixin
from ..services.kernels.client import JupyterServerKernelClientMixin


class GatewayKernelClient(JupyterServerKernelClientMixin, _GatewayKernelClient):
    """
    Gateway kernel client that combines our monitoring capabilities with gateway support.

    This client inherits from:
    - JupyterServerKernelClientMixin: Provides kernel monitoring capabilities, message caching,
      and execution state tracking that integrates with our kernel monitor system
    - GatewayKernelClient: Provides gateway communication capabilities for remote kernels

    The combination allows remote gateway kernels to be monitored with the same level of
    detail as local kernels, including heartbeat monitoring, execution state tracking,
    and kernel lifecycle management.
    """

    async def _test_kernel_communication(self, timeout: float = 10.0) -> bool:
        """Skip kernel_info test for gateway kernels.

        Gateway kernels handle communication differently and the kernel_info
        test can hang due to message routing differences.

        Returns:
            bool: Always returns True for gateway kernels
        """
        return True

    def _send_message(self, channel_name: str, msg: list[bytes]):
        # Send to gateway channel
        try:
            channel = getattr(self, f"{channel_name}_channel", None)
            if channel and hasattr(channel, 'send'):
                # Convert raw message to gateway format
                header = self.session.unpack(msg[0])
                parent_header = self.session.unpack(msg[1])
                metadata = self.session.unpack(msg[2])
                content = self.session.unpack(msg[3])

                full_msg = {
                    'header': header,
                    'parent_header': parent_header,
                    'metadata': metadata,
                    'content': content,
                    'buffers': msg[4:] if len(msg) > 4 else [],
                    'channel': channel_name,
                    'msg_id': header.get('msg_id'),
                    'msg_type': header.get('msg_type')
                }

                channel.send(full_msg)
        except Exception as e:
            self.log.warn(f"Error handling incoming message on gateway: {e}")

    async def _monitor_channel_messages(self, channel_name: str, channel):
        """Monitor a gateway channel for incoming messages."""
        try:
            while channel.is_alive():
                try:
                    # Get message from gateway channel queue
                    message = await channel.get_msg()

                    # Update execution state from status messages
                    # Gateway messages are already deserialized dicts
                    self._update_execution_state_from_status(
                        channel_name,
                        message,
                        parent_msg_id=message.get("parent_header", {}).get("msg_id"),
                        execution_state=message.get("content", {}).get("execution_state")
                    )

                    # Serialize message to standard format for listeners
                    # Gateway messages are dicts, convert to list[bytes] format
                    msg_list = self.session.serialize(message)
                    # Drop DELIM and signature
                    msg_list = msg_list[2:]
                    
                    # Route to listeners
                    await self._route_to_listeners(channel_name, msg_list)

                except asyncio.TimeoutError:
                    # No message available, continue loop
                    continue
                except Exception as e:
                    self.log.debug(f"Error processing gateway message in {channel_name}: {e}")
                    continue

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.error(f"Gateway channel monitoring failed for {channel_name}: {e}")


class GatewayKernelManager(KernelManagerStateMixin, _GatewayKernelManager):
    """
    Gateway kernel manager that uses our enhanced gateway kernel client with state tracking.

    This manager inherits from jupyter_server's GatewayKernelManager and configures it
    to use our GatewayKernelClient, which provides:

    - Gateway communication capabilities for remote kernels
    - Kernel monitoring integration (heartbeat, execution state tracking)
    - Message caching and state management
    - Full compatibility with our kernel monitor extension
    - Automatic lifecycle state tracking via KernelManagerStateMixin

    When jupyter_server is configured to use a gateway, this manager ensures that
    remote kernels receive the same level of monitoring as local kernels.
    """
    # Configure the manager to use our enhanced gateway client
    client_class = GatewayKernelClient
    client_factory = GatewayKernelClient


class GatewayMultiKernelManager(GatewayMappingKernelManager):
    """Custom kernel manager that uses enhanced monitoring kernel manager."""
    
    @default("kernel_manager_class")
    def _default_kernel_manager_class(self):
        return "nextgen_kernels_api.gateway.manager.GatewayKernelManager"

    def start_watching_activity(self, kernel_id):
        pass
    
    def stop_buffering(self, kernel_id):
        pass

