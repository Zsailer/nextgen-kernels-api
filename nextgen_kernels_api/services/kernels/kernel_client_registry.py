"""Kernel client registry for mapping provisioners to kernel clients.

This module provides a central registry system that maps kernel provisioner types
to their corresponding kernel client implementations. This enables:
- Dynamic selection of kernel clients based on provisioner type
- External packages to register their own provisioner-client mappings
- Configuration-based registration for deployment flexibility
"""

import importlib
import logging
import typing as t
from importlib.metadata import entry_points
from jupyter_client.provisioning import KernelProvisionerBase
from jupyter_client.client import KernelClient
from traitlets.config import SingletonConfigurable
from traitlets import Type as TraitType

from nextgen_kernels_api.services.kernels.client import JupyterServerKernelClient

logger = logging.getLogger(__name__)


class KernelClientRegistry(SingletonConfigurable):
    """Central registry (singleton) for mapping provisioner types to kernel clients.
    
    This registry maintains mappings between kernel provisioner classes and their
    corresponding kernel client classes. It supports multiple registration methods:
    
    1. Programmatic registration via register()
    2. Configuration-based registration via provisioner_client_mappings trait
    3. Entry point discovery via auto_discover_registrations()
    
    Example usage:
        # Register a mapping programmatically
        KernelClientRegistry.register(SparkProvisioner, SparkKernelClient)
        
        # Get client for a provisioner instance
        client_class = KernelClientRegistry.get_client_for_provisioner(provisioner)
    """
    
    fallback_client_class = TraitType(
        default_value=JupyterServerKernelClient,
        klass='jupyter_client.client.KernelClient',
        config=True,
        help="""
        The fallback kernel client class to use when no provisioner-specific
        mapping is found. Defaults to nextgen_kernels_api.services.kernels.client.JupyterServerKernelClient.
        
        Can be configured with a string path to the class:
            c.KernelClientRegistry.fallback_client_class = "jupyter_server_documents.kernel_client.DocumentAwareKernelClient"
        
        Or with a class object directly in code:
            c.KernelClientRegistry.fallback_client_class = MyCustomKernelClient
        """
    )
    
    # Class-level registry for programmatic registrations
    _registry: t.Dict[t.Type[KernelProvisionerBase], t.Type[KernelClient]] = {}
    _initialized: bool = False

    def __init__(self, **kwargs: t.Any) -> None:
        """Initialize the kernel client registry and auto-discover registrations."""
        super().__init__(**kwargs)
        
        # Auto-discover registrations from entry points
        self.auto_discover_registrations()
    
    @property
    def fallback_client(self) -> t.Type[KernelClient]:
        """Get the fallback client class.
        
        Returns the configured fallback_client_class, which defaults to
        jupyter_client.client.KernelClient if not set.
        """
        return self.fallback_client_class
    
    @classmethod
    def register(cls,
                 provisioner_class: t.Type[KernelProvisionerBase],
                 client_class: t.Type[KernelClient]) -> None:
        """Register a kernel client for a specific provisioner type.
        
        Parameters
        ----------
        provisioner_class : Type[KernelProvisionerBase]
            The provisioner class to register
        client_class : Type[KernelClient]
            The kernel client class to use with this provisioner
            
        Example
        -------
        >>> from jupyter_server.saturn.provisioners.spark_provisioner import SparkProvisioner
        >>> from jupyter_server_documents.kernel_client import DocumentAwareSparkProvisionerAwareKernelClient
        >>> KernelClientRegistry.register(SparkProvisioner, DocumentAwareSparkProvisionerAwareKernelClient)
        """
        cls._registry[provisioner_class] = client_class
        logger.info(f"Registered {client_class.__name__} for {provisioner_class.__name__}")
    
    @classmethod
    def register_from_string(cls, provisioner_class_name: str, client_class_name: str) -> None:
        """Register a mapping using fully qualified class name strings.
        
        This is useful for configuration-based registration where classes
        may not be imported yet. Supports both 'module.Class' and 'module:Class' formats.
        
        Parameters
        ----------
        provisioner_class_name : str
            Fully qualified name of the provisioner class
            Formats: 'module.Class' or 'module:Class'
        client_class_name : str
            Fully qualified name of the kernel client class
            Formats: 'module.Class' or 'module:Class'
            
        Raises
        ------
        ImportError
            If either class cannot be imported
        AttributeError
            If the class name is not found in the module
        """
        try:
            # Parse provisioner class name (handle both '.' and ':' separators)
            if ':' in provisioner_class_name:
                prov_module_name, prov_class_name = provisioner_class_name.rsplit(':', 1)
            else:
                prov_module_name, prov_class_name = provisioner_class_name.rsplit('.', 1)
            
            prov_module = importlib.import_module(prov_module_name)
            provisioner_class = getattr(prov_module, prov_class_name)
            
            # Parse client class name (handle both '.' and ':' separators)
            if ':' in client_class_name:
                client_module_name, client_class_name_only = client_class_name.rsplit(':', 1)
            else:
                client_module_name, client_class_name_only = client_class_name.rsplit('.', 1)
            
            client_module = importlib.import_module(client_module_name)
            client_class = getattr(client_module, client_class_name_only)
            
            # Register the mapping
            cls.register(provisioner_class, client_class)
            
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to register mapping {provisioner_class_name} -> {client_class_name}: {e}")
            raise
    
    def get_client_for_provisioner(self,
                                   provisioner: t.Optional[KernelProvisionerBase]) -> t.Type[KernelClient]:
        """Get the appropriate kernel client class for a provisioner instance.
        
        Uses the following lookup strategy:
        1. Exact match on provisioner class type
        2. Match on any base class of the provisioner
        3. Return configured fallback client (defaults to KernelClient)
        
        Parameters
        ----------
        provisioner : Optional[KernelProvisionerBase]
            The provisioner instance to find a client for
            
        Returns
        -------
        Type[KernelClient]
            The kernel client class to use. Always returns a valid client class,
            falling back to the configured fallback_client_class if no match found.
            
        Example
        -------
        >>> registry = KernelClientRegistry.instance()
        >>> client_class = registry.get_client_for_provisioner(spark_provisioner)
        >>> client = client_class(session=session)
        
        Configuration
        -------------
        In jupyter_config.py:
            c.KernelClientRegistry.fallback_client_class = MyCustomKernelClient
        """
        if provisioner is None:
            return self.fallback_client
        
        provisioner_type = type(provisioner)
        
        # Try exact match first
        if provisioner_type in self._registry:
            logger.debug(f"Found exact match for {provisioner_type.__name__}")
            return self._registry[provisioner_type]
        
        # Try matching on base classes (inheritance-based matching)
        for prov_class, client_class in self._registry.items():
            if isinstance(provisioner, prov_class):
                logger.debug(f"Found inheritance match: {provisioner_type.__name__} "
                           f"is a {prov_class.__name__}")
                return client_class
        
        # No match found, return fallback
        logger.debug(f"No registry match for {provisioner_type.__name__}, using fallback: {self.fallback_client.__name__}")
        return self.fallback_client
    
    @classmethod
    def get_registered_mappings(cls) -> t.Dict[str, str]:
        """Get all registered provisioner-client mappings as strings.
        
        Returns
        -------
        Dict[str, str]
            Dictionary mapping provisioner class names to client class names
        """
        return {
            f"{prov.__module__}.{prov.__name__}": f"{client.__module__}.{client.__name__}"
            for prov, client in cls._registry.items()
        }
    
    @classmethod
    def clear_registry(cls) -> None:
        """Clear all registered mappings. Primarily useful for testing."""
        cls._registry.clear()
        logger.info("Cleared kernel client registry")
    
    def auto_discover_registrations(self) -> None:
        """Auto-discover and register kernel clients from entry points.
        
        This method looks for entry points in the 'jupyter_kernel_client_registry'
        group and registers them. Entry points use the provisioner class reference
        as the name and kernel client class reference as the value.
        
        Entry points should be defined in external packages like:
        
        In pyproject.toml:
        ```toml
        [project.entry-points.jupyter_kernel_client_registry]
        "jupyter_server.saturn.provisioners.spark_provisioner:SparkProvisioner" =
            "jupyter_server_documents.kernel_client:DocumentAwareSparkProvisionerAwareKernelClient"
        ```
        
        In setup.py:
        ```python
        entry_points={
            'jupyter_kernel_client_registry': [
                'provisioners.spark_provisioner:SparkProvisioner = '
                'jupyter_server_documents.kernel_client:DocumentAwareSparkProvisionerAwareKernelClient',
            ]
        }
        ```
        
        Both name and value use the standard Python entry point format: 'module.path:ClassName'
        """
        try:
            # Get entry points for the jupyter_kernel_client_registry group
            # Python 3.10+ returns an EntryPoints object with select method
            eps = entry_points(group='jupyter_kernel_client_registry')
            
            if not eps:
                self.log.debug("No entry points found for 'jupyter_kernel_client_registry'")
                return
            
            self.log.info(f"Discovering kernel client registrations from {len(eps)} entry points")
            
            for entry_point in eps:
                try:
                    # Entry point name is the provisioner class reference (module:Class format)
                    provisioner_class_ref = entry_point.name
                    
                    # Use entry_point.load() to directly get the kernel client class
                    client_class = entry_point.load()
                    
                    # Parse and import the provisioner class from the name
                    if ':' in provisioner_class_ref:
                        prov_module_name, prov_class_name = provisioner_class_ref.rsplit(':', 1)
                    else:
                        # Fallback to dot notation
                        prov_module_name, prov_class_name = provisioner_class_ref.rsplit('.', 1)
                    
                    prov_module = importlib.import_module(prov_module_name)
                    provisioner_class = getattr(prov_module, prov_class_name)
                    
                    self.log.debug(
                        f"Registering from entry point: {provisioner_class.__name__} -> {client_class.__name__}"
                    )
                    
                    # Register directly with class objects
                    self.register(provisioner_class, client_class)
                    
                    self.log.info(
                        f"Successfully registered from entry point: {entry_point.name}"
                    )
                    
                except Exception as e:
                    self.log.warning(
                        f"Failed to load entry point '{entry_point.name}' "
                        f"with value '{entry_point.value}': {e}"
                    )
                    
        except Exception as e:
            logger.warning(f"Error during entry point discovery: {e}")


# Convenience function to get the singleton instance
def get_registry(config: t.Optional[t.Any] = None) -> KernelClientRegistry:
    """Get the global kernel client registry singleton instance.
    
    This is a convenience wrapper around KernelClientRegistry.instance().
    
    Parameters
    ----------
    config : Optional[Any]
        Traitlets configuration object to apply to the registry.
        Only used on first call when creating the singleton instance.
        
    Returns
    -------
    KernelClientRegistry
        The global registry singleton instance
        
    Example
    -------
    >>> registry = get_registry()
    >>> # or equivalently:
    >>> registry = KernelClientRegistry.instance()
    """
    return KernelClientRegistry.instance(config=config)
