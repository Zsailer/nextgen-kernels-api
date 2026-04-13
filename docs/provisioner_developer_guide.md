# Provisioner Developer Guide: Connection Info Pattern

This guide shows you how to create a custom kernel provisioner and matching kernel client that communicate through the extensible `connection_info` pattern.

## Table of Contents
1. [Quick Start](#quick-start)
2. [Complete Working Example](#complete-working-example)
3. [Step-by-Step Explanation](#step-by-step-explanation)
4. [Testing Your Implementation](#testing-your-implementation)
5. [Common Patterns](#common-patterns)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

Creating a custom provisioner involves 4 steps:

1. **Create Provisioner** - Launches kernel and stores connection details in `_connection_info`
2. **Create Client** - Loads connection details from `connection_info` and connects
3. **Register Mapping** - Tell the registry which client goes with your provisioner
4. **Use ProvisionerAwareKernelManager** - Automatically selects your client

---

## Complete Working Example

Here's a complete, working example of a Docker-based provisioner and client:

### 1. The Provisioner (`docker_provisioner.py`)

```python
"""Docker-based kernel provisioner."""
from typing import Dict, Any, List
from jupyter_client.provisioning import KernelProvisionerBase
from jupyter_client.connect import KernelConnectionInfo
import docker


class DockerProvisioner(KernelProvisionerBase):
    """Provisions kernels in Docker containers.
    
    This provisioner:
    - Launches kernels in isolated Docker containers
    - Stores container ID and IP in connection_info
    - Exposes kernel ports from the container
    """
    
    def __init__(self, **kwargs):
        """Initialize the Docker provisioner."""
        super().__init__(**kwargs)
        
        # STEP 1: Initialize connection_info storage
        self._connection_info: Dict[str, Any] = {}
        
        # Docker-specific attributes
        self.docker_client = docker.from_env()
        self.container = None
        self.container_ip = None
    
    @property
    def has_process(self) -> bool:
        """Check if container is running."""
        return self.container is not None
    
    async def poll(self) -> int | None:
        """Check if container is still running."""
        if self.container:
            self.container.reload()
            if self.container.status == "running":
                return None  # Still running
            return 1  # Container stopped
        return 0
    
    async def launch_kernel(self, cmd: List[str], **kwargs: Any) -> KernelConnectionInfo:
        """Launch kernel in Docker container.
        
        This is where we:
        1. Start the Docker container
        2. Get container IP and ports
        3. Store connection details in _connection_info
        4. Return connection_info for the client
        """
        # Get Docker image from environment
        env = kwargs.get("env", {})
        image = env.get("KERNEL_DOCKER_IMAGE", "jupyter/base-notebook:latest")
        
        self.log.info(f"Launching kernel in Docker image: {image}")
        
        # Start container with kernel command
        self.container = self.docker_client.containers.run(
            image,
            command=cmd,
            detach=True,
            network_mode="bridge",
            ports={
                '5555/tcp': None,  # shell_port
                '5556/tcp': None,  # iopub_port  
                '5557/tcp': None,  # stdin_port
                '5558/tcp': None,  # control_port
                '5559/tcp': None,  # hb_port
            },
            environment={
                'JPY_SESSION_NAME': env.get('JPY_SESSION_NAME', 'kernel'),
            }
        )
        
        # Reload to get network info
        self.container.reload()
        
        # Get container IP
        self.container_ip = self.container.attrs['NetworkSettings']['IPAddress']
        
        # Get parent kernel manager for session key
        km = self.parent
        
        # STEP 2: Store ALL connection details in _connection_info
        # This is the key part - store everything the client needs!
        self._connection_info = {
            # Docker-specific fields
            "docker_container_id": self.container.id,
            "docker_container_ip": self.container_ip,
            "docker_image": image,
            
            # Standard ZMQ ports (exposed from container)
            "shell_port": 5555,
            "iopub_port": 5556,
            "stdin_port": 5557,
            "control_port": 5558,
            "hb_port": 5559,
            "ip": self.container_ip,
            "transport": "tcp",
            
            # Security (recommended for all provisioners)
            "key": km.session.key if km else b"",
            "signature_scheme": "hmac-sha256",
        }
        
        self.log.info(
            f"Docker kernel started: container={self.container.id[:12]}, "
            f"ip={self.container_ip}"
        )
        
        # STEP 3: Return connection_info
        return self.connection_info
    
    @property
    def connection_info(self) -> KernelConnectionInfo:
        """Expose connection_info for KernelManager.
        
        This property is accessed by KernelManager.get_connection_info()
        to provide connection details to the kernel client.
        
        IMPORTANT: Must be a @property, not a regular method!
        """
        return self._connection_info
    
    async def kill(self, restart: bool = False) -> None:
        """Kill the Docker container."""
        if self.container:
            self.log.info(f"Killing Docker container: {self.container.id[:12]}")
            try:
                self.container.stop(timeout=5)
                self.container.remove()
            except Exception as e:
                self.log.warning(f"Error stopping container: {e}")
            finally:
                self.container = None
    
    async def terminate(self, restart: bool = False) -> None:
        """Terminate the Docker container gracefully."""
        await self.kill(restart=restart)
    
    async def cleanup(self, restart: bool = False) -> None:
        """Cleanup Docker resources."""
        if not restart and self.container:
            try:
                self.container.remove(force=True)
            except Exception as e:
                self.log.warning(f"Error during cleanup: {e}")
```

### 2. The Client (`docker_client.py`)

```python
"""Kernel client for Docker-based kernels."""
from jupyter_client.asynchronous.client import AsyncKernelClient
from jupyter_client.connect import KernelConnectionInfo


class DockerKernelClient(AsyncKernelClient):
    """Kernel client that connects to Docker container kernels.
    
    This client:
    - Loads Docker container connection details from connection_info
    - Connects to kernel ports on the container IP
    - Validates that required fields are present
    """
    
    def __init__(self, **kwargs):
        """Initialize the Docker kernel client."""
        super().__init__(**kwargs)
        # Docker-specific attributes
        self.container_id = None
        self.container_ip = None
        self.docker_image = None
    
    def load_connection_info(self, info: KernelConnectionInfo) -> None:
        """Load connection information from DockerProvisioner.
        
        This is where the client receives and interprets the connection_info
        dictionary that was stored by DockerProvisioner.launch_kernel().
        
        Args:
            info: Connection info dictionary from DockerProvisioner.connection_info
                 Expected fields:
                 - docker_container_id: Container ID
                 - docker_container_ip: Container IP address
                 - shell_port, iopub_port, stdin_port, control_port, hb_port
                 - key: Session key for message signing
        """
        # STEP 1: Validate required fields
        required_fields = ["docker_container_ip", "shell_port", "iopub_port"]
        missing = [f for f in required_fields if f not in info]
        if missing:
            raise ValueError(
                f"DockerKernelClient requires {missing} in connection_info. "
                f"These should be provided by DockerProvisioner. "
                f"Available fields: {list(info.keys())}"
            )
        
        # STEP 2: Load Docker-specific fields
        self.container_id = info.get("docker_container_id")
        self.container_ip = info["docker_container_ip"]
        self.docker_image = info.get("docker_image")
        
        self.log.info(
            f"Loading connection to Docker container: "
            f"id={self.container_id[:12] if self.container_id else 'unknown'}, "
            f"ip={self.container_ip}"
        )
        
        # STEP 3: Load standard ZMQ connection fields
        self.ip = info["docker_container_ip"]  # Use container IP
        self.shell_port = info["shell_port"]
        self.iopub_port = info["iopub_port"]
        self.stdin_port = info.get("stdin_port", 0)
        self.control_port = info.get("control_port", 0)
        self.hb_port = info.get("hb_port", 0)
        self.transport = info.get("transport", "tcp")
        
        # STEP 4: Load session key for message signing
        if "key" in info:
            key = info["key"]
            if isinstance(key, str):
                key = key.encode()
            if isinstance(key, bytes):
                self.session.key = key
                self.log.debug("Loaded session key from connection_info")
        
        self.log.debug(
            f"Loaded connection info: {self.ip}:{self.shell_port} "
            f"(container {self.container_id[:12] if self.container_id else 'unknown'})"
        )
    
    async def connect(self) -> bool:
        """Connect to the Docker container kernel.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Validate connection info was loaded
            if not self.container_ip:
                raise ValueError(
                    "Connection info not loaded. "
                    "Call load_connection_info() first."
                )
            
            self.log.info(
                f"Connecting to Docker kernel at {self.container_ip}:{self.shell_port}"
            )
            
            # Use parent's connect logic (starts channels)
            result = self.start_channels()
            if asyncio.iscoroutine(result):
                await result
            
            # Verify channels are running
            if not self.channels_running:
                self.log.error("Channels failed to start")
                return False
            
            self.log.info(
                f"Successfully connected to Docker kernel "
                f"(container {self.container_id[:12] if self.container_id else 'unknown'})"
            )
            return True
            
        except Exception as e:
            self.log.error(f"Failed to connect to Docker kernel: {e}")
            return False
```

### 3. Registration (`__init__.py`)

```python
"""Docker kernel provisioner package.

This package provides a Docker-based kernel provisioner and client.
"""
from nextgen_kernels_api.services.kernels.kernel_client_registry import (
    KernelClientRegistry
)
from .docker_provisioner import DockerProvisioner
from .docker_client import DockerKernelClient


# STEP 4: Register the provisioner → client mapping
# This tells the system: "When you see DockerProvisioner, use DockerKernelClient"
KernelClientRegistry.register(DockerProvisioner, DockerKernelClient)

# Log registration for debugging
import logging
logger = logging.getLogger(__name__)
logger.info("Registered DockerProvisioner → DockerKernelClient mapping")


# Export for easy importing
__all__ = ['DockerProvisioner', 'DockerKernelClient']
```

### 4. Usage Example

```python
"""Example of using the Docker provisioner."""
from nextgen_kernels_api.services.kernels.kernelmanager import (
    ProvisionerAwareKernelManager
)
from jupyter_client import KernelSpecManager
from my_package import DockerProvisioner  # This auto-registers the mapping


async def main():
    # Create kernel spec manager
    kernel_spec_manager = KernelSpecManager()
    
    # Create kernel manager with Docker provisioner
    # ProvisionerAwareKernelManager will automatically:
    # 1. Use DockerProvisioner to launch the kernel
    # 2. Look up DockerKernelClient from the registry
    # 3. Load connection_info from DockerProvisioner
    # 4. Connect DockerKernelClient to the kernel
    kernel_manager = ProvisionerAwareKernelManager(
        kernel_name="python3",
        kernel_spec_manager=kernel_spec_manager,
    )
    
    # Set Docker image via environment
    kernel_manager.kernel_spec.env = {
        "KERNEL_DOCKER_IMAGE": "jupyter/scipy-notebook:latest"
    }
    
    # Start the kernel
    kernel_id = await kernel_manager.start_kernel()
    print(f"Kernel started with ID: {kernel_id}")
    
    # The kernel client is now connected!
    assert kernel_manager.kernel_client.channels_running
    print(f"Connected to Docker kernel at {kernel_manager.kernel_client.container_ip}")
    
    # Use the kernel
    msg_id = kernel_manager.kernel_client.execute("print('Hello from Docker!')")
    
    # ... do work ...
    
    # Shutdown
    await kernel_manager.shutdown_kernel()
    print("Kernel shut down")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## Step-by-Step Explanation

### How Connection Info Flows

```
1. User starts kernel
   ↓
2. ProvisionerAwareKernelManager._async_start_kernel()
   ↓
3. DockerProvisioner.launch_kernel()
   - Starts Docker container
   - Stores connection details in _connection_info
   - Returns connection_info
   ↓
4. ProvisionerAwareKernelManager looks up client in registry
   - Finds DockerKernelClient for DockerProvisioner
   - Sets client_class = DockerKernelClient
   ↓
5. KernelManager._async_post_start_kernel()
   ↓
6. KernelManager.get_connection_info()
   - Delegates to provisioner.connection_info
   - Returns DockerProvisioner._connection_info
   ↓
7. DockerKernelClient.load_connection_info(info)
   - Receives connection_info dictionary
   - Loads container_ip, ports, session key
   ↓
8. DockerKernelClient.connect()
   - Uses loaded connection info to connect
   - Starts ZMQ channels to container
```

### Key Points

1. **Provisioner stores, Client loads**
   - Provisioner: `self._connection_info = {fields...}`
   - Client: `self.field = info["field"]`

2. **connection_info is the contract**
   - Provisioner decides what fields to include
   - Client validates and loads those fields
   - No other component needs to know the details

3. **Registry connects them**
   - `KernelClientRegistry.register(DockerProvisioner, DockerKernelClient)`
   - `ProvisionerAwareKernelManager` uses registry to select client

4. **KernelManager delegates**
   - `KernelManager.get_connection_info()` → `provisioner.connection_info`
   - KernelManager doesn't need Docker-specific knowledge

---

## Testing Your Implementation

### Test 1: Provisioner Stores Connection Info

```python
import asyncio
from my_package import DockerProvisioner

async def test_provisioner():
    # Create provisioner
    provisioner = DockerProvisioner()
    
    # Launch kernel
    connection_info = await provisioner.launch_kernel(
        cmd=["python", "-m", "ipykernel"],
        env={"KERNEL_DOCKER_IMAGE": "jupyter/base-notebook"}
    )
    
    # Verify connection_info has required fields
    assert "docker_container_id" in connection_info
    assert "docker_container_ip" in connection_info
    assert "shell_port" in connection_info
    assert "key" in connection_info
    
    print("✓ Provisioner correctly stores connection_info")
    print(f"  Container ID: {connection_info['docker_container_id'][:12]}")
    print(f"  Container IP: {connection_info['docker_container_ip']}")
    
    # Cleanup
    await provisioner.kill()

asyncio.run(test_provisioner())
```

### Test 2: Client Loads Connection Info

```python
from my_package import DockerProvisioner, DockerKernelClient

async def test_client():
    # Create and launch
    provisioner = DockerProvisioner()
    connection_info = await provisioner.launch_kernel(
        cmd=["python", "-m", "ipykernel"],
        env={}
    )
    
    # Create client and load connection info
    client = DockerKernelClient()
    client.load_connection_info(connection_info)
    
    # Verify client loaded fields correctly
    assert client.container_ip == connection_info["docker_container_ip"]
    assert client.shell_port == connection_info["shell_port"]
    assert client.session.key == connection_info["key"]
    
    print("✓ Client correctly loads connection_info")
    print(f"  Client IP: {client.ip}")
    print(f"  Client ports: {client.shell_port}, {client.iopub_port}")
    
    # Cleanup
    await provisioner.kill()

asyncio.run(test_client())
```

### Test 3: Registry Mapping

```python
from nextgen_kernels_api.services.kernels.kernel_client_registry import (
    KernelClientRegistry
)
from my_package import DockerProvisioner, DockerKernelClient

def test_registry():
    # Check mapping is registered
    provisioner = DockerProvisioner()
    client_class = KernelClientRegistry.get_client_for_provisioner(provisioner)
    
    assert client_class == DockerKernelClient
    print("✓ Registry correctly maps DockerProvisioner → DockerKernelClient")
    
    # List all mappings
    mappings = KernelClientRegistry.get_registered_mappings()
    print(f"  All mappings: {mappings}")

test_registry()
```

### Test 4: End-to-End

```python
from nextgen_kernels_api.services.kernels.kernelmanager import (
    ProvisionerAwareKernelManager
)

async def test_end_to_end():
    # Create manager
    manager = ProvisionerAwareKernelManager()
    
    # Start kernel
    kernel_id = await manager.start_kernel()
    
    # Verify correct client was selected
    assert isinstance(manager.kernel_client, DockerKernelClient)
    print("✓ ProvisionerAwareKernelManager selected DockerKernelClient")
    
    # Verify connection
    assert manager.kernel_client.channels_running
    print("✓ Client successfully connected to kernel")
    
    # Execute code
    msg_id = manager.kernel_client.execute("print('Hello!')")
    print(f"✓ Executed code, msg_id: {msg_id}")
    
    # Cleanup
    await manager.shutdown_kernel()
    print("✓ Kernel shut down successfully")

asyncio.run(test_end_to_end())
```

---

## Common Patterns

### Pattern 1: WebSocket-based (like SparkProvisioner)

```python
# Provisioner
self._connection_info = {
    "ws_url": "ws://gateway-server/api/kernels/abc-123/channels",
    "key": km.session.key,
    "signature_scheme": "hmac-sha256",
}

# Client
def load_connection_info(self, info):
    if "ws_url" not in info:
        raise ValueError("WebSocket URL required")
    self.ws_url = info["ws_url"]
```

### Pattern 2: REST API-based

```python
# Provisioner
self._connection_info = {
    "api_endpoint": "https://kernel-service.com/api/v1",
    "kernel_id": "kernel-abc-123",
    "auth_token": "Bearer xyz...",
    "key": km.session.key,
}

# Client
def load_connection_info(self, info):
    self.api_endpoint = info["api_endpoint"]
    self.kernel_id = info["kernel_id"]
    self.auth_token = info.get("auth_token", "")
```

### Pattern 3: SSH-based

```python
# Provisioner
self._connection_info = {
    "ssh_host": "remote-server.example.com",
    "ssh_port": 22,
    "ssh_username": "jupyter",
    "kernel_ports": {
        "shell": 5555,
        "iopub": 5556,
        "stdin": 5557,
        "control": 5558,
        "hb": 5559,
    },
    "key": km.session.key,
}

# Client
def load_connection_info(self, info):
    self.ssh_host = info["ssh_host"]
    self.ssh_port = info.get("ssh_port", 22)
    ports = info["kernel_ports"]
    self.shell_port = ports["shell"]
    # ... etc
```

---

## Troubleshooting

### Problem: `ValueError: DockerKernelClient requires 'docker_container_ip'`

**Cause:** Provisioner didn't store required field in `connection_info`

**Solution:** Check provisioner's `launch_kernel()`:
```python
# Make sure this line exists and includes all required fields
self._connection_info = {
    "docker_container_ip": self.container_ip,  # ← This field is required
    # ... other fields
}
```

### Problem: Client gets wrong type (not DockerKernelClient)

**Cause:** Registry mapping not registered

**Solution:** Ensure registration happens on import:
```python
# In __init__.py
from nextgen_kernels_api.services.kernels.kernel_client_registry import KernelClientRegistry
from .docker_provisioner import DockerProvisioner
from .docker_client import DockerKernelClient

# This line MUST execute
KernelClientRegistry.register(DockerProvisioner, DockerKernelClient)
```

### Problem: `connection_info` is empty `{}`

**Cause:** Not storing connection_info in `launch_kernel()`

**Solution:** Add storage in `launch_kernel()`:
```python
async def launch_kernel(self, cmd, **kwargs):
    # ... launch kernel ...
    
    # ADD THIS:
    self._connection_info = {
        "my_field": value,
        # ... other fields
    }
    
    return self.connection_info  # Returns what we just stored
```

### Problem: Using base `KernelManager` instead of `ProvisionerAwareKernelManager`

**Cause:** Wrong manager class

**Solution:**
```python
# WRONG
from jupyter_client import KernelManager
manager = KernelManager()  # Won't use registry!

# CORRECT
from nextgen_kernels_api.services.kernels.kernelmanager import ProvisionerAwareKernelManager
manager = ProvisionerAwareKernelManager()  # Uses registry!
```

---

## Reference Documentation

- [Connection Info Pattern Overview](connection_info_pattern.md)
- [Kernel Client Registry Design](provisioner_client_registry_design.md)
- [LocalProvisioner Example](../jupyter_client/jupyter_client/provisioning/local_provisioner.py)
- [SparkProvisioner Example](../jupyter_server/saturn/provisioners/spark_provisioner.py)

---

## Summary Checklist

When implementing a custom provisioner:

- [ ] Initialize `_connection_info = {}` in `__init__()`
- [ ] Store connection details in `_connection_info` during `launch_kernel()`
- [ ] Expose via `@property connection_info` (not regular method!)
- [ ] Include `"key"` field for message signing
- [ ] Create matching client with `load_connection_info()` method
- [ ] Validate required fields in client's `load_connection_info()`
- [ ] Register mapping: `KernelClientRegistry.register(Provisioner, Client)`
- [ ] Test with `ProvisionerAwareKernelManager`
- [ ] Verify connection info flows correctly
- [ ] Document what fields your `connection_info` contains

You now have everything needed to create custom provisioners!
