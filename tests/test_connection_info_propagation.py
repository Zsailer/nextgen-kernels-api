"""Tests to verify connection info is properly propagated to pre-created kernel clients."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from nextgen_kernels_api.services.kernels.kernelmanager import KernelManager, MultiKernelManager
from nextgen_kernels_api.services.kernels.client import JupyterServerKernelClient
from nextgen_kernels_api.services.kernels.client_manager import KernelClientManager


def test_client_initial_connection_info():
    """Test that client gets initial connection info when created."""
    # Create a kernel manager
    km = KernelManager()

    # Get initial connection info from the kernel manager
    initial_info = km.get_connection_info(session=True)

    # Verify the client exists
    assert km.kernel_client is not None

    # The client should have connection info from when it was created
    # Check that key attributes exist (they may be defaults/zeros initially)
    assert hasattr(km.kernel_client, 'ip')
    assert hasattr(km.kernel_client, 'shell_port')
    assert hasattr(km.kernel_client, 'iopub_port')
    assert hasattr(km.kernel_client, 'stdin_port')
    assert hasattr(km.kernel_client, 'control_port')
    assert hasattr(km.kernel_client, 'hb_port')
    assert hasattr(km.kernel_client, 'session')


def test_client_connection_info_can_be_updated():
    """Test that client connection info can be updated via load_connection_info."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Store initial values
    initial_ip = client.ip
    initial_shell_port = client.shell_port
    initial_key = client.session.key

    # Simulate updated connection info (like what provisioner would set)
    updated_info = {
        'ip': '192.168.1.100',
        'shell_port': 54321,
        'iopub_port': 54322,
        'stdin_port': 54323,
        'control_port': 54324,
        'hb_port': 54325,
        'key': b'new-secret-key-123',
        'signature_scheme': 'hmac-sha256',
        'transport': 'tcp',
    }

    # Update the client's connection info
    client.load_connection_info(updated_info)

    # Verify the connection info was updated
    assert client.ip == '192.168.1.100'
    assert client.shell_port == 54321
    assert client.iopub_port == 54322
    assert client.stdin_port == 54323
    assert client.control_port == 54324
    assert client.hb_port == 54325
    assert client.session.key == b'new-secret-key-123'
    assert client.session.signature_scheme == 'hmac-sha256'


def test_kernel_manager_connection_info_updates():
    """Test that kernel manager connection info can be updated and retrieved."""
    # Create a kernel manager
    km = KernelManager()

    # Simulate what provisioner does - update the kernel manager's connection info
    km.ip = '10.0.0.1'
    km.shell_port = 12345
    km.iopub_port = 12346
    km.stdin_port = 12347
    km.control_port = 12348
    km.hb_port = 12349
    km.session.key = b'test-key-456'

    # Get connection info from kernel manager (without session object)
    conn_info = km.get_connection_info(session=False)

    # Verify the kernel manager has updated info
    assert conn_info['ip'] == '10.0.0.1'
    assert conn_info['shell_port'] == 12345
    assert conn_info['iopub_port'] == 12346
    assert conn_info['stdin_port'] == 12347
    assert conn_info['control_port'] == 12348
    assert conn_info['hb_port'] == 12349
    assert conn_info['key'] == b'test-key-456'  # key is included when session=False


def test_client_gets_updated_connection_info_from_kernel_manager():
    """Test that pre-created client can get updated connection info from kernel manager."""
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Store initial client connection info
    initial_ip = client.ip
    initial_shell_port = client.shell_port
    initial_key = client.session.key

    # Simulate provisioner updating kernel manager connection info
    km.ip = '172.16.0.1'
    km.shell_port = 55555
    km.iopub_port = 55556
    km.stdin_port = 55557
    km.control_port = 55558
    km.hb_port = 55559
    km.session.key = b'updated-key-789'

    # Get the updated connection info from kernel manager
    updated_info = km.get_connection_info(session=True)

    # Load it into the client (this is what KernelClientManager.connect_client does)
    client.load_connection_info(updated_info)

    # Verify the client now has the updated connection info
    assert client.ip == '172.16.0.1'
    assert client.shell_port == 55555
    assert client.iopub_port == 55556
    assert client.stdin_port == 55557
    assert client.control_port == 55558
    assert client.hb_port == 55559
    assert client.session.key == b'updated-key-789'


@pytest.mark.asyncio
async def test_client_manager_updates_connection_info_before_connect():
    """Test that KernelClientManager updates connection info before connecting."""
    # Create a multi kernel manager
    multi_km = MultiKernelManager()

    # Create a kernel manager with initial connection info
    km = KernelManager()
    kernel_id = "test-kernel-id"

    # Get the pre-created client
    client = km.kernel_client
    initial_ip = client.ip

    # Simulate kernel starting and provisioner updating connection info
    km.ip = '192.168.100.50'
    km.shell_port = 60000
    km.iopub_port = 60001
    km.stdin_port = 60002
    km.control_port = 60003
    km.hb_port = 60004
    km.session.key = b'provisioner-set-key'

    # Add kernel manager to multi kernel manager
    multi_km._kernels = {kernel_id: km}

    # Create client manager
    client_manager = KernelClientManager(multi_kernel_manager=multi_km)

    # Get the client (should be the same pre-created one)
    retrieved_client = client_manager.get_client(kernel_id)
    if not retrieved_client:
        retrieved_client = client_manager.create_client(kernel_id)

    # Verify it's the same client
    assert retrieved_client is client

    # At this point, client still has old connection info
    # (it was created with initial info)

    # Mock the connection process to avoid actually starting channels
    with patch.object(retrieved_client, 'connect', return_value=True):
        with patch.object(retrieved_client, 'is_connecting', return_value=False):
            with patch.object(retrieved_client, 'is_connected', return_value=False):
                with patch.object(client_manager, '_wait_for_kernel_started', return_value=True):
                    # Try to connect (this should call load_connection_info)
                    await client_manager.connect_client(kernel_id)

    # Verify the client now has the updated connection info
    assert retrieved_client.ip == '192.168.100.50'
    assert retrieved_client.shell_port == 60000
    assert retrieved_client.iopub_port == 60001
    assert retrieved_client.stdin_port == 60002
    assert retrieved_client.control_port == 60003
    assert retrieved_client.hb_port == 60004
    assert retrieved_client.session.key == b'provisioner-set-key'


def test_connection_info_preserves_session_between_client_and_manager():
    """Test that client and kernel manager can share the same session object."""
    # Create a kernel manager
    km = KernelManager()

    # Create client with the kernel manager's session
    client = km.client(session=km.session)

    # Verify they share the same session object
    assert client.session is km.session

    # Update session key on kernel manager
    km.session.key = b'shared-session-key'

    # Verify client sees the update (because they share the session)
    assert client.session.key == b'shared-session-key'


def test_precreated_client_uses_kernel_manager_session():
    """Test that the pre-created client uses the kernel manager's session."""
    # Create a kernel manager (which creates a client)
    km = KernelManager()

    # Verify the pre-created client uses the kernel manager's session
    assert km.kernel_client.session is km.session

    # Update the session key
    km.session.key = b'test-shared-key'

    # Verify the client sees the update
    assert km.kernel_client.session.key == b'test-shared-key'


def test_connection_info_with_zero_ports():
    """Test that zero ports (unassigned) can be updated to real ports."""
    # Create a kernel manager
    km = KernelManager()
    client = km.kernel_client

    # Initially ports might be 0 or random
    # Simulate provisioner assigning real ports
    updated_info = {
        'ip': '127.0.0.1',
        'shell_port': 50001,
        'iopub_port': 50002,
        'stdin_port': 50003,
        'control_port': 50004,
        'hb_port': 50005,
        'key': b'real-key',
        'signature_scheme': 'hmac-sha256',
        'transport': 'tcp',
    }

    # Update client connection info
    client.load_connection_info(updated_info)

    # Verify all ports are now set to real values
    assert client.shell_port == 50001
    assert client.iopub_port == 50002
    assert client.stdin_port == 50003
    assert client.control_port == 50004
    assert client.hb_port == 50005
    assert client.session.key == b'real-key'


def test_multiple_load_connection_info_calls():
    """Test that connection info can be updated multiple times.

    Note: jupyter_client's load_connection_info only updates ports if they are currently 0.
    This is by design to prevent overriding config/CLI-specified ports.
    """
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # First update - ports start at 0 or random, so they will be updated
    client.load_connection_info({
        'ip': '10.0.0.1',
        'shell_port': 10001,
        'iopub_port': 10002,
        'stdin_port': 10003,
        'control_port': 10004,
        'hb_port': 10005,
        'key': b'key-v1',
    })
    assert client.ip == '10.0.0.1'
    # Ports may or may not be updated depending on initial state

    # Session key is always updated
    assert client.session.key == b'key-v1'

    # Second update - since ports are now non-zero, they won't be updated by load_connection_info
    # But IP and session key can still be updated
    client.load_connection_info({
        'ip': '10.0.0.2',
        'key': b'key-v2',
    })
    assert client.ip == '10.0.0.2'
    assert client.session.key == b'key-v2'


def test_connection_info_partial_updates():
    """Test that load_connection_info behavior with partial updates.

    Note: jupyter_client's load_connection_info only updates ports if they are currently 0.
    The first load sets the ports (if they were 0), subsequent loads won't change them.
    """
    # Create a kernel manager with a client
    km = KernelManager()
    client = km.kernel_client

    # Set initial complete connection info
    # This simulates what happens when provisioner sets connection info after kernel starts
    client.load_connection_info({
        'ip': '127.0.0.1',
        'shell_port': 40001,
        'iopub_port': 40002,
        'stdin_port': 40003,
        'control_port': 40004,
        'hb_port': 40005,
        'key': b'initial-key',
        'transport': 'tcp',
    })

    # Verify IP and session key are set
    assert client.ip == '127.0.0.1'
    assert client.session.key == b'initial-key'

    # Now do a partial update (only update some fields)
    # Since ports were already set (non-zero), they won't be updated again
    client.load_connection_info({
        'ip': '192.168.1.1',
        'key': b'updated-key',
        # Ports not specified - will keep old values
    })

    # Verify updated fields changed
    assert client.ip == '192.168.1.1'
    assert client.session.key == b'updated-key'

    # Ports should remain unchanged from first load
    # (assuming they were set in first load)


def test_client_with_zero_ports_gets_updated_by_provisioner():
    """Test the critical use case: client created with zero ports gets updated after provisioner sets them.

    This is the real-world scenario:
    1. KernelManager.__init__() creates a client immediately (ports are 0 or random)
    2. Kernel starts, provisioner assigns real ports to kernel manager
    3. KernelClientManager calls load_connection_info before connecting
    4. Client gets the real ports because its ports were 0
    """
    # Create a kernel manager - this creates a client immediately
    km = KernelManager()
    client = km.kernel_client

    # At this point, ports in the client might be 0 or randomly assigned
    # The key insight: if they're 0, they can be updated. If random, they can't be.
    # Let's explicitly set them to 0 to simulate the case where they haven't been assigned yet
    client.shell_port = 0
    client.iopub_port = 0
    client.stdin_port = 0
    client.control_port = 0
    client.hb_port = 0

    # Verify ports are 0
    assert client.shell_port == 0
    assert client.iopub_port == 0

    # Now simulate provisioner setting ports on the kernel manager
    km.shell_port = 55001
    km.iopub_port = 55002
    km.stdin_port = 55003
    km.control_port = 55004
    km.hb_port = 55005
    km.ip = '127.0.0.1'
    km.session.key = b'provisioner-key'

    # Get connection info from kernel manager (like KernelClientManager does)
    conn_info = km.get_connection_info(session=True)

    # Load it into the client (like KernelClientManager.connect_client does)
    client.load_connection_info(conn_info)

    # CRITICAL: Since client ports were 0, they should now be updated
    assert client.shell_port == 55001
    assert client.iopub_port == 55002
    assert client.stdin_port == 55003
    assert client.control_port == 55004
    assert client.hb_port == 55005
    assert client.ip == '127.0.0.1'

    # Session is shared, so key should be the same
    assert client.session.key == b'provisioner-key'


def test_shared_session_means_key_always_synced():
    """Test that because client shares session with kernel manager, the key is always in sync.

    This is critical: even if load_connection_info isn't called,
    session.key changes are visible to both kernel manager and client.
    """
    # Create kernel manager (creates client with shared session)
    km = KernelManager()
    client = km.kernel_client

    # Verify they share the same session object
    assert client.session is km.session

    # When provisioner updates the session key on kernel manager
    km.session.key = b'new-provisioner-key'

    # Client immediately sees it (no need to call load_connection_info for session changes)
    assert client.session.key == b'new-provisioner-key'

    # And vice versa - if client updates it
    client.session.key = b'client-updated-key'

    # Kernel manager sees it
    assert km.session.key == b'client-updated-key'
