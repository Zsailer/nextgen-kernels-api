# Provisioner-to-Kernel Client Registry Design

## Executive Summary

A registry system has been implemented to enable dynamic mapping between kernel provisioners and their corresponding kernel clients. This allows external packages to register custom kernel clients for specific provisioners without modifying core code.

## Implementation Status

### ✅ Completed: KernelClientRegistry Class

The [`KernelClientRegistry`](../nextgen_kernels_api/services/kernels/kernel_client_registry.py) class has been implemented with the following features:

#### 1. **Programmatic Registration**
```python
from nextgen_kernels_api.services.kernels.kernel_client_registry import KernelClientRegistry
from jupyter_server.saturn.provisioners.spark_provisioner import SparkProvisioner
from jupyter_server_documents.kernel_client import DocumentAwareSparkProvisionerAwareKernelClient

# Register a specific provisioner-client mapping
KernelClientRegistry.register(SparkProvisioner, DocumentAwareSparkProvisionerAwareKernelClient)
```

#### 2. **Entry Point Discovery**
```toml
# In pyproject.toml of external package
[project.entry-points.jupyter_kernel_client_registry]
"jupyter_server.saturn.provisioners.spark_provisioner:SparkProvisioner" = 
    "jupyter_server_documents.kernel_client:DocumentAwareSparkProvisionerAwareKernelClient"
```

The registry automatically discovers and loads these registrations using `auto_discover_registrations()`.

#### 3. **Smart Lookup Strategy**
The registry uses a three-tier fallback strategy:
1. **Exact Match**: Direct provisioner class → kernel client mapping
2. **Inheritance Match**: Base class of provisioner → kernel client mapping
3. **Fallback**: Default kernel client if no match found

#### 4. **String-Based Registration**
For lazy loading and configuration scenarios (supports both `module:Class` and `module.Class` formats):
```python
KernelClientRegistry.register_from_string(
    'module.provisioner:ClassName',
    'module.client:ClassName'
)
```

## Design Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Init                         │
│  - Initializes KernelClientRegistry                         │
│  - Sets fallback client                                     │
│  - Calls auto_discover_registrations()                      │
│  - Applies configuration mappings                           │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│              KernelClientRegistry                           │
│  - _registry: Dict[Provisioner, Client]                     │
│  - _fallback_client: Type[KernelClient]                     │
│  - register()                                               │
│  - get_client_for_provisioner()                             │
│  - auto_discover_registrations()                            │
│  - apply_config_mappings()                                  │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│         ProvisionerAwareKernelManager                                       │
│  - Queries registry for kernel client class                 │
│  - Creates appropriate kernel client based on provisioner   │
└────────────────┬────────────────────────────────────────────┘
            
```

## API Reference

### Class: KernelClientRegistry

#### Methods

##### `register(provisioner_class, client_class)`
Register a kernel client for a specific provisioner type.

**Parameters:**
- `provisioner_class`: The provisioner class to register
- `client_class`: The kernel client class to use with this provisioner

**Example:**
```python
KernelClientRegistry.register(SparkProvisioner, DocumentAwareSparkProvisionerAwareKernelClient)
```

##### `register_from_string(provisioner_class_name, client_class_name)`
Register using fully qualified class name strings. Supports both `module:Class` and `module.Class` formats.

**Parameters:**
- `provisioner_class_name`: Fully qualified provisioner class name
- `client_class_name`: Fully qualified kernel client class name

##### `get_client_for_provisioner(provisioner)`
Get the appropriate kernel client class for a provisioner instance.

**Returns:** The kernel client class, or fallback client if no match found

**Lookup Strategy:**
1. Exact match on provisioner class type
2. Match on any base class of the provisioner
3. Return fallback client if set
4. Return None if no match found

##### `set_fallback_client(client_class)`
Set the fallback kernel client class to use when no mapping exists.

##### `auto_discover_registrations()`
Auto-discover and register kernel clients from entry points in the `jupyter_kernel_client_registry` group.

##### `apply_config_mappings()`
Apply `provisioner_client_mappings` from configuration.

##### `get_registered_mappings()`
Get all registered provisioner-client mappings as strings.

##### `clear_registry()`
Clear all registered mappings. Primarily useful for testing.

## Usage Examples

### For Extension Developers

#### Registering a Custom Client

```python
# In your extension package initialization
from nextgen_kernels_api.services.kernels.kernel_client_registry import KernelClientRegistry
from your_package.provisioner import CustomProvisioner
from your_package.client import CustomDocumentAwareClient

def initialize_extension():
    """Called during extension initialization."""
    KernelClientRegistry.register(
        CustomProvisioner,
        CustomDocumentAwareClient
    )
```

#### Via Entry Points

```toml
# In pyproject.toml
[project.entry-points.jupyter_kernel_client_registry]
"your_package.provisioner:CustomProvisioner" = "your_package.client:CustomDocumentAwareClient"
```

## Pending Implementation Tasks

### 🔨 High Priority

#### 1. **ProvisionerAwareKernelManager**
Extends KernelManager that uses the registry to select clients:

```python
class ProvisionerAwareKernelManager(KernelManager):
    """Kernel manager that dynamically selects client based on provisioner."""
    
    async def select_client(self):
        """Select client class from registry based on provisioner type."""
        if self.provisioner:
            # Query registry for appropriate client
            client_class = KernelClientRegistry.get_client_for_provisioner(
                self.provisioner
            )
            if client_class:
                self.client_class = client_class
                self.client_factory = client_class

```

#### 2. **Application Integration**
Update application initialization to:
- Initialize the registry
- Set fallback client
- Call `auto_discover_registrations()`
- Apply configuration mappings
- Use ProvisionerAwareKernelManager

#### 3. **Migration Path**
Provide migration guide for existing hardcoded implementations like `SparkProvisionerAwareKernelManager`.

### 📚 Documentation Needs

- ✅ API documentation (this document)
- ✅ Configuration examples in jupyter_config.py
- User guide for extension developers
- Migration guide from hardcoded implementations

### 🧪 Testing Needs

- Unit tests for registry operations
- Integration tests with different provisioners
- Entry point discovery tests

## Design Decisions

### 1. **Module Location**
The registry is located in `nextgen-kernels-api` to make it available as a general-purpose mechanism that any package can use.

### 2. **Singleton Pattern**
Uses `SingletonConfigurable` following the same pattern as `KernelProvisionerFactory`. Configuration is applied when the singleton is first created.

### 3. **Entry Point Format**
Both entry point name (provisioner) and value (kernel client) use standard Python entry point format: `module.path:ClassName`

### 4. **Client Selection Architecture**
The base `KernelManager` provides a `select_client()` hook method that subclasses can override. This provides clean separation between:
- Base behavior: connecting and managing kernel clients
- Extensibility: customizing which client class to use

### 5. **Fallback Behavior**
Graceful fallback to configured `fallback_client_class` (default: `JupyterServerKernelClient`) when no provisioner match is found. Logs debug information for troubleshooting.

### 6. **Inheritance Matching**
The registry supports inheritance-based matching by default. If `SparkProvisioner` is registered, subclasses automatically match.

**Pros:**
- Flexible, works with subclasses
- Reduces registration burden

**Cons:**
- May match unintentionally
- Order-dependent if multiple base classes registered

### 7. **String Format Flexibility**
`register_from_string()` supports both `module:Class` (standard entry point format) and `module.Class` (dot notation) for backward compatibility.

### 8. **Connection Info Delegation**
`ProvisionerAwareKernelManager.get_connection_info()` delegates to provisioner when available, enabling provisioner-specific connection details (ZMQ ports, WebSocket URLs, etc.).

## Future Enhancements

1. **Conflict Detection**: Warn when multiple registrations exist for the same provisioner
2. **Version Compatibility**: Support versioning between provisioners and clients
3. **Multiple Clients**: Support multiple clients per provisioner based on additional criteria
4. **Registration Callbacks**: Allow callbacks when new registrations are added
5. **Registry Introspection**: Better tools for viewing and debugging registered mappings

## See Also

- [KernelClientRegistry Implementation](../nextgen_kernels_api/services/kernels/kernel_client_registry.py)
- [Jupyter Client Documentation](https://jupyter-client.readthedocs.io/)
- [Entry Points Guide](https://packaging.python.org/en/latest/specifications/entry-points/)
