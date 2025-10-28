"""Tests to verify that listeners can be added before kernel client connection."""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock
from nextgen_kernels_api.services.kernels.kernelmanager import KernelManager, MultiKernelManager
from nextgen_kernels_api.services.kernels.client import JupyterServerKernelClient
from nextgen_kernels_api.services.kernels.client_manager import KernelClientManager


def test_kernel_client_created_before_connection():
    """Test that kernel client is created immediately, before connection."""
    # Create a kernel manager
    km = KernelManager()

    # Verify that kernel_client exists
    assert km.kernel_client is not None
    assert isinstance(km.kernel_client, JupyterServerKernelClient)

    # Verify that the client channels are not started yet
    # (is_alive() is async, so we check the internal state instead)
    assert not km.kernel_client._connection_ready


def test_listener_can_be_added_before_connection():
    """Test that listeners can be added to the kernel client before connection."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Verify client exists but is not connected
    assert client is not None
    assert not client._connection_ready

    # Create a mock listener callback
    listener_callback = Mock()

    # Add listener before connection - this should work without errors
    client.add_listener(listener_callback)

    # Verify the listener was added
    assert listener_callback in client._listeners
    assert len(client._listeners) == 1


def test_multiple_listeners_can_be_added_before_connection():
    """Test that multiple listeners with different filters can be added before connection."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Create multiple mock listeners
    listener1 = Mock()
    listener2 = Mock()
    listener3 = Mock()

    # Add listeners with different filters before connection
    client.add_listener(listener1)  # No filter - receives all messages
    client.add_listener(listener2, msg_types=[("status", "iopub")])  # Only status messages
    client.add_listener(listener3, exclude_msg_types=[("status", "iopub")])  # All except status

    # Verify all listeners were added
    assert listener1 in client._listeners
    assert listener2 in client._listeners
    assert listener3 in client._listeners
    assert len(client._listeners) == 3

    # Verify filter configurations are correct
    assert client._listeners[listener1]['msg_types'] is None
    assert client._listeners[listener1]['exclude_msg_types'] is None

    assert client._listeners[listener2]['msg_types'] == {("status", "iopub")}
    assert client._listeners[listener2]['exclude_msg_types'] is None

    assert client._listeners[listener3]['msg_types'] is None
    assert client._listeners[listener3]['exclude_msg_types'] == {("status", "iopub")}


@pytest.mark.asyncio
async def test_listener_receives_messages_after_connection():
    """Test that listeners added before connection receive messages after connection."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Create a mock listener
    messages_received = []

    async def listener_callback(channel_name, msg):
        messages_received.append((channel_name, msg))

    # Add listener before connection
    client.add_listener(listener_callback)

    # Simulate a message being routed to listeners
    # (We're testing the routing mechanism, not actual kernel connection)
    test_msg = [
        client.session.pack({"msg_id": "test-123", "msg_type": "status"}),  # header
        client.session.pack({}),  # parent_header
        client.session.pack({}),  # metadata
        client.session.pack({"execution_state": "idle"}),  # content
    ]

    # Route the message to listeners
    await client._route_to_listeners("iopub", test_msg)

    # Verify the listener received the message
    assert len(messages_received) == 1
    assert messages_received[0][0] == "iopub"
    assert messages_received[0][1] == test_msg


@pytest.mark.asyncio
async def test_filtered_listener_only_receives_matching_messages():
    """Test that filtered listeners only receive messages matching their filter."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Track messages received by each listener
    all_messages = []
    status_messages = []
    non_status_messages = []

    async def all_listener(channel_name, msg):
        all_messages.append((channel_name, msg))

    async def status_listener(channel_name, msg):
        status_messages.append((channel_name, msg))

    async def non_status_listener(channel_name, msg):
        non_status_messages.append((channel_name, msg))

    # Add listeners with different filters
    client.add_listener(all_listener)  # Receives all
    client.add_listener(status_listener, msg_types=[("status", "iopub")])  # Only status
    client.add_listener(non_status_listener, exclude_msg_types=[("status", "iopub")])  # No status

    # Create a status message
    status_msg = [
        client.session.pack({"msg_id": "test-1", "msg_type": "status"}),
        client.session.pack({}),
        client.session.pack({}),
        client.session.pack({"execution_state": "idle"}),
    ]

    # Create an execute_result message
    execute_msg = [
        client.session.pack({"msg_id": "test-2", "msg_type": "execute_result"}),
        client.session.pack({}),
        client.session.pack({}),
        client.session.pack({"data": {}}),
    ]

    # Route status message
    await client._route_to_listeners("iopub", status_msg)

    # Verify routing
    assert len(all_messages) == 1  # Receives everything
    assert len(status_messages) == 1  # Receives only status
    assert len(non_status_messages) == 0  # Excludes status

    # Route execute_result message
    await client._route_to_listeners("iopub", execute_msg)

    # Verify routing
    assert len(all_messages) == 2  # Receives everything
    assert len(status_messages) == 1  # Still only has status message
    assert len(non_status_messages) == 1  # Now has execute_result


def test_client_manager_provides_pre_created_client_with_listeners():
    """Test that KernelClientManager provides the pre-created client that already has listeners."""
    # Create a multi kernel manager
    multi_km = MultiKernelManager()

    # Create a kernel manager
    km = KernelManager()
    kernel_id = "test-kernel-id"

    # Add a listener to the kernel manager's client BEFORE it's registered with client manager
    pre_listener = Mock()
    km.kernel_client.add_listener(pre_listener)

    # Add the kernel manager to the multi kernel manager
    multi_km._kernels = {kernel_id: km}

    # Create client manager
    client_manager = KernelClientManager(multi_kernel_manager=multi_km)

    # Get the client through the manager
    client = client_manager.create_client(kernel_id)

    # Verify it's the same client that already has the listener
    assert client is km.kernel_client
    assert pre_listener in client._listeners
    assert len(client._listeners) == 1


@pytest.mark.asyncio
async def test_queued_messages_during_startup():
    """Test that messages are queued if sent before connection is ready."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Verify connection is not ready
    assert not client._connection_ready

    # Try to handle an incoming message
    test_msg = [
        client.session.pack({"msg_id": "test-123", "msg_type": "execute_request"}),
        client.session.pack({}),
        client.session.pack({"cellId": "test-cell"}),
        client.session.pack({"code": "print('hello')"}),
    ]

    # Handle incoming message before connection ready
    client.handle_incoming_message("shell", test_msg)

    # Verify message was queued
    assert len(client._queued_messages) == 1
    assert client._queued_messages[0] == ("shell", test_msg)


def test_listener_state_preserved_across_client_manager_operations():
    """Test that listener state is preserved when using client manager."""
    # Create a multi kernel manager
    multi_km = MultiKernelManager()

    # Create a kernel manager
    km = KernelManager()
    kernel_id = "test-kernel-id"

    # Add multiple listeners with different configurations
    listener1 = Mock()
    listener2 = Mock()
    km.kernel_client.add_listener(listener1)
    km.kernel_client.add_listener(listener2, msg_types=[("status", "iopub")])

    # Store the original client ID
    original_client_id = id(km.kernel_client)

    # Add to multi kernel manager
    multi_km._kernels = {kernel_id: km}

    # Create client manager and get the client
    client_manager = KernelClientManager(multi_kernel_manager=multi_km)
    retrieved_client = client_manager.create_client(kernel_id)

    # Verify it's the exact same object (not a copy)
    assert id(retrieved_client) == original_client_id
    assert retrieved_client is km.kernel_client

    # Verify all listeners are still present
    assert len(retrieved_client._listeners) == 2
    assert listener1 in retrieved_client._listeners
    assert listener2 in retrieved_client._listeners

    # Verify filter configuration is preserved
    assert retrieved_client._listeners[listener1]['msg_types'] is None
    assert retrieved_client._listeners[listener2]['msg_types'] == {("status", "iopub")}
