"""Tests for kernel client creation on kernel manager initialization."""

import pytest
from unittest.mock import Mock, MagicMock
from nextgen_kernels_api.services.kernels.kernelmanager import KernelManager
from nextgen_kernels_api.services.kernels.client import JupyterServerKernelClient
from nextgen_kernels_api.services.kernels.client_manager import KernelClientManager
from nextgen_kernels_api.gateway.managers import GatewayKernelManager, GatewayKernelClient


def test_kernel_manager_creates_client_on_init():
    """Test that KernelManager creates a kernel_client on initialization."""
    # Create a kernel manager
    km = KernelManager()

    # Verify that kernel_client was created
    assert km.kernel_client is not None
    assert isinstance(km.kernel_client, JupyterServerKernelClient)


def test_kernel_manager_client_uses_configured_class():
    """Test that KernelManager uses the configured client_class."""
    # Create a kernel manager with default client class
    km = KernelManager()

    # Verify the client is the correct type
    assert isinstance(km.kernel_client, km.client_class)


def test_gateway_kernel_manager_creates_client_on_init():
    """Test that GatewayKernelManager creates a kernel_client on initialization."""
    # Create a mock connection info since gateway manager needs it
    connection_info = {
        'ip': '127.0.0.1',
        'shell_port': 5555,
        'iopub_port': 5556,
        'stdin_port': 5557,
        'control_port': 5558,
        'hb_port': 5559,
        'key': b'test-key',
        'transport': 'tcp',
        'signature_scheme': 'hmac-sha256',
    }

    # Create a gateway kernel manager
    gkm = GatewayKernelManager(connection_info=connection_info)

    # Verify that kernel_client was created
    assert gkm.kernel_client is not None
    assert isinstance(gkm.kernel_client, GatewayKernelClient)


def test_client_manager_uses_precreated_client():
    """Test that KernelClientManager uses the kernel manager's pre-created client."""
    from nextgen_kernels_api.services.kernels.kernelmanager import MultiKernelManager

    # Create a multi kernel manager
    multi_km = MultiKernelManager()

    # Create a kernel manager
    km = KernelManager()
    kernel_id = "test-kernel-id"

    # Get the pre-created client for comparison
    expected_client = km.kernel_client

    # Add the kernel manager to the multi kernel manager's _kernels dict
    multi_km._kernels = {kernel_id: km}

    # Create client manager
    client_manager = KernelClientManager(multi_kernel_manager=multi_km)

    # Create client through the manager
    client = client_manager.create_client(kernel_id)

    # Verify the client manager used the pre-created client
    assert client is expected_client
    assert client is km.kernel_client


def test_client_manager_fallback_when_no_precreated_client():
    """Test that KernelClientManager falls back to creating a new client when kernel_client doesn't exist."""
    from nextgen_kernels_api.services.kernels.kernelmanager import MultiKernelManager

    # Create a mock kernel manager without kernel_client property
    mock_km = MagicMock()
    # Make sure it doesn't have kernel_client attribute
    if hasattr(mock_km, 'kernel_client'):
        del mock_km.kernel_client

    # Create a mock client that will be returned by mock_km.client()
    mock_client = MagicMock(spec=JupyterServerKernelClient)
    mock_km.client.return_value = mock_client
    mock_km.session = MagicMock()

    # Create multi kernel manager
    multi_km = MultiKernelManager()
    kernel_id = "test-kernel-id"
    multi_km._kernels = {kernel_id: mock_km}

    # Create client manager
    client_manager = KernelClientManager(multi_kernel_manager=multi_km)

    # Create client
    client = client_manager.create_client(kernel_id)

    # Verify the fallback was used
    assert client is mock_client
    mock_km.client.assert_called_once()


def test_client_manager_fallback_when_precreated_client_is_none():
    """Test that KernelClientManager falls back when kernel_client exists but is None."""
    from nextgen_kernels_api.services.kernels.kernelmanager import MultiKernelManager

    # Create a mock kernel manager with kernel_client = None
    mock_km = MagicMock()
    mock_km.kernel_client = None

    # Create a mock client that will be returned by mock_km.client()
    mock_client = MagicMock(spec=JupyterServerKernelClient)
    mock_km.client.return_value = mock_client
    mock_km.session = MagicMock()

    # Create multi kernel manager
    multi_km = MultiKernelManager()
    kernel_id = "test-kernel-id"
    multi_km._kernels = {kernel_id: mock_km}

    # Create client manager
    client_manager = KernelClientManager(multi_kernel_manager=multi_km)

    # Create client
    client = client_manager.create_client(kernel_id)

    # Verify the fallback was used
    assert client is mock_client
    mock_km.client.assert_called_once()
