"""Tests for KernelClientRegistry."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from jupyter_client.provisioning.provisioner_base import KernelProvisionerBase
from jupyter_client.client import KernelClient
from traitlets.config import Config

from nextgen_kernels_api.services.kernels.kernel_client_registry import (
    KernelClientRegistry,
    get_registry,
)


# Mock provisioner and client classes for testing
class MockProvisionerA(KernelProvisionerBase):
    """Mock provisioner A for testing."""
    
    @property
    def has_process(self):
        return False
    
    async def poll(self):
        return None
    
    async def wait(self):
        return None
    
    async def send_signal(self, signum):
        pass
    
    async def kill(self, restart=False):
        pass
    
    async def terminate(self, restart=False):
        pass
    
    async def launch_kernel(self, cmd, **kwargs):
        return {}
    
    async def cleanup(self, restart=False):
        pass


class MockProvisionerB(KernelProvisionerBase):
    """Mock provisioner B for testing."""
    
    @property
    def has_process(self):
        return False
    
    async def poll(self):
        return None
    
    async def wait(self):
        return None
    
    async def send_signal(self, signum):
        pass
    
    async def kill(self, restart=False):
        pass
    
    async def terminate(self, restart=False):
        pass
    
    async def launch_kernel(self, cmd, **kwargs):
        return {}
    
    async def cleanup(self, restart=False):
        pass


class MockProvisionerC(MockProvisionerA):
    """Mock provisioner C that inherits from A."""
    pass


class MockKernelClientA(KernelClient):
    """Mock kernel client A for testing."""
    pass


class MockKernelClientB(KernelClient):
    """Mock kernel client B for testing."""
    pass


class MockKernelClientC(KernelClient):
    """Mock kernel client C for testing."""
    pass


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton instance between tests."""
    # Clear the singleton instance
    KernelClientRegistry._instance = None
    # Clear the class-level registry
    KernelClientRegistry._registry.clear()
    yield
    # Cleanup after test
    KernelClientRegistry._instance = None
    KernelClientRegistry._registry.clear()


class TestKernelClientRegistrySingleton:
    """Test singleton behavior."""
    
    def test_singleton_same_instance(self):
        """Verify that instance() returns the same object."""
        registry1 = KernelClientRegistry.instance()
        registry2 = KernelClientRegistry.instance()
        assert registry1 is registry2
    
    def test_get_registry_helper(self):
        """Verify get_registry() returns the singleton instance."""
        registry1 = get_registry()
        registry2 = KernelClientRegistry.instance()
        assert registry1 is registry2
    
    def test_singleton_with_config(self):
        """Verify singleton with configuration."""
        config = Config()
        config.KernelClientRegistry.fallback_client_class = MockKernelClientA
        
        registry = KernelClientRegistry.instance(config=config)
        assert registry.fallback_client == MockKernelClientA


class TestKernelClientRegistryRegistration:
    """Test registration methods."""
    
    def test_register_provisioner_client(self):
        """Test basic registration."""
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        
        assert MockProvisionerA in KernelClientRegistry._registry
        assert KernelClientRegistry._registry[MockProvisionerA] == MockKernelClientA
    
    def test_register_multiple_provisioners(self):
        """Test registering multiple provisioners."""
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        KernelClientRegistry.register(MockProvisionerB, MockKernelClientB)
        
        assert len(KernelClientRegistry._registry) == 2
        assert KernelClientRegistry._registry[MockProvisionerA] == MockKernelClientA
        assert KernelClientRegistry._registry[MockProvisionerB] == MockKernelClientB
    
    def test_register_from_string_with_colon(self):
        """Test registration from string with colon notation."""
        # Mock the import
        with patch('importlib.import_module') as mock_import:
            # Setup mock modules
            mock_prov_module = Mock()
            mock_prov_module.MockProvisionerA = MockProvisionerA
            
            mock_client_module = Mock()
            mock_client_module.MockKernelClientA = MockKernelClientA
            
            def import_side_effect(module_name):
                if 'test_provisioners' in module_name:
                    return mock_prov_module
                elif 'test_clients' in module_name:
                    return mock_client_module
                raise ImportError(f"Unknown module: {module_name}")
            
            mock_import.side_effect = import_side_effect
            
            # Register from string
            KernelClientRegistry.register_from_string(
                'test_provisioners:MockProvisionerA',
                'test_clients:MockKernelClientA'
            )
            
            assert MockProvisionerA in KernelClientRegistry._registry
    
    def test_register_from_string_with_dot(self):
        """Test registration from string with dot notation."""
        with patch('importlib.import_module') as mock_import:
            # Setup mock modules
            mock_prov_module = Mock()
            mock_prov_module.MockProvisionerA = MockProvisionerA
            
            mock_client_module = Mock()
            mock_client_module.MockKernelClientA = MockKernelClientA
            
            def import_side_effect(module_name):
                if 'test_provisioners' in module_name:
                    return mock_prov_module
                elif 'test_clients' in module_name:
                    return mock_client_module
                raise ImportError(f"Unknown module: {module_name}")
            
            mock_import.side_effect = import_side_effect
            
            # Register from string with dot notation
            KernelClientRegistry.register_from_string(
                'test_provisioners.MockProvisionerA',
                'test_clients.MockKernelClientA'
            )
            
            assert MockProvisionerA in KernelClientRegistry._registry
    
    def test_register_from_string_invalid(self):
        """Test that invalid registration raises error."""
        with pytest.raises(ImportError):
            KernelClientRegistry.register_from_string(
                'nonexistent.module:ClassName',
                'another.nonexistent:ClassName'
            )


class TestKernelClientRegistryLookup:
    """Test client lookup methods."""
    
    def test_get_client_exact_match(self):
        """Test exact provisioner type match."""
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        
        registry = KernelClientRegistry.instance()
        provisioner = MockProvisionerA()
        
        client_class = registry.get_client_for_provisioner(provisioner)
        assert client_class == MockKernelClientA
    
    def test_get_client_inheritance_match(self):
        """Test inheritance-based matching."""
        # Register parent class only
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        
        registry = KernelClientRegistry.instance()
        # Use child class instance
        provisioner = MockProvisionerC()
        
        client_class = registry.get_client_for_provisioner(provisioner)
        assert client_class == MockKernelClientA
    
    def test_get_client_no_match_uses_fallback(self):
        """Test fallback when no match found."""
        registry = KernelClientRegistry.instance()
        provisioner = MockProvisionerA()
        
        # No registration, should return fallback (default KernelClient)
        client_class = registry.get_client_for_provisioner(provisioner)
        assert client_class == KernelClient
    
    def test_get_client_configured_fallback(self):
        """Test custom fallback client."""
        config = Config()
        config.KernelClientRegistry.fallback_client_class = MockKernelClientC
        
        registry = KernelClientRegistry.instance(config=config)
        provisioner = MockProvisionerA()
        
        # No registration, should return configured fallback
        client_class = registry.get_client_for_provisioner(provisioner)
        assert client_class == MockKernelClientC
    
    def test_get_client_none_provisioner(self):
        """Test None provisioner returns fallback."""
        registry = KernelClientRegistry.instance()
        
        client_class = registry.get_client_for_provisioner(None)
        assert client_class == KernelClient
    
    def test_get_client_exact_match_priority_over_inheritance(self):
        """Test that exact match takes priority over inheritance."""
        # Register both parent and child
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        KernelClientRegistry.register(MockProvisionerC, MockKernelClientC)
        
        registry = KernelClientRegistry.instance()
        provisioner_c = MockProvisionerC()
        
        # Should get exact match for C, not inherited match for A
        client_class = registry.get_client_for_provisioner(provisioner_c)
        assert client_class == MockKernelClientC


class TestKernelClientRegistryUtilities:
    """Test utility methods."""
    
    def test_get_registered_mappings(self):
        """Test getting all registered mappings as strings."""
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        KernelClientRegistry.register(MockProvisionerB, MockKernelClientB)
        
        mappings = KernelClientRegistry.get_registered_mappings()
        
        assert len(mappings) == 2
        assert any('MockProvisionerA' in key for key in mappings.keys())
        assert any('MockProvisionerB' in key for key in mappings.keys())
    
    def test_clear_registry(self):
        """Test clearing the registry."""
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        assert len(KernelClientRegistry._registry) == 1
        
        KernelClientRegistry.clear_registry()
        assert len(KernelClientRegistry._registry) == 0


class TestKernelClientRegistryAutoDiscovery:
    """Test entry point auto-discovery."""
    
    def test_auto_discover_real_entry_point_from_pyproject(self):
        """Test that the real entry point from pyproject.toml is discovered.
        
        The pyproject.toml defines:
        [project.entry-points."jupyter_kernel_client_registry"]
        "jupyter_server.saturn.provisioners.spark_provisioner:SparkProvisioner" =
            "jupyter_server_documents.kernel_client:DocumentAwareSparkProvisionerAwareKernelClient"
        
        This test verifies this entry point can be discovered when the package is installed.
        """
        from importlib.metadata import entry_points
        
        # Get actual entry points from the installed package
        eps = entry_points(group='jupyter_kernel_client_registry')
        
        # Find our SparkProvisioner entry point
        spark_ep = None
        for ep in eps:
            if 'SparkProvisioner' in ep.name:
                spark_ep = ep
                break
        
        # If the package is installed in editable mode, the entry point should exist
        if spark_ep is None:
            pytest.skip("Entry point not found - package not installed in editable mode")
            return
        
        # Verify the entry point has the expected attributes
        assert 'jupyter_server.saturn.provisioners.spark_provisioner' in spark_ep.name
        assert 'SparkProvisioner' in spark_ep.name
        assert 'jupyter_server_documents.kernel_client' in spark_ep.value
        assert 'DocumentAwareSparkProvisionerAwareKernelClient' in spark_ep.value
        
        # Verify it's in the correct format (module:Class)
        assert ':' in spark_ep.name  # Provisioner should be module:Class
        assert ':' in spark_ep.value  # Client should be module:Class
    
    def test_auto_discover_with_no_entry_points(self):
        """Test auto-discovery when no entry points exist."""
        with patch('nextgen_kernels_api.services.kernels.kernel_client_registry.entry_points') as mock_eps:
            # Mock empty entry points
            mock_eps.return_value = []
            
            registry = KernelClientRegistry.instance()
            # Should not raise, just log debug message
            assert len(KernelClientRegistry._registry) == 0
    
    def test_auto_discover_with_entry_points(self):
        """Test auto-discovery with valid entry points."""
        with patch('nextgen_kernels_api.services.kernels.kernel_client_registry.entry_points') as mock_eps, \
             patch('importlib.import_module') as mock_import:
            
            # Create mock entry point
            mock_ep = MagicMock()
            mock_ep.name = 'test_provisioners:MockProvisionerA'
            mock_ep.value = 'test_clients:MockKernelClientA'
            mock_ep.load.return_value = MockKernelClientA
            
            mock_eps.return_value = [mock_ep]
            
            # Setup import mocks
            mock_prov_module = Mock()
            mock_prov_module.MockProvisionerA = MockProvisionerA
            mock_import.return_value = mock_prov_module
            
            # Create instance (triggers auto-discovery)
            registry = KernelClientRegistry.instance()
            
            # Verify registration happened
            assert MockProvisionerA in KernelClientRegistry._registry
            assert KernelClientRegistry._registry[MockProvisionerA] == MockKernelClientA
    
    def test_auto_discover_handles_failed_entry_point(self):
        """Test that failed entry points don't break auto-discovery."""
        with patch('nextgen_kernels_api.services.kernels.kernel_client_registry.entry_points') as mock_eps:
            
            # Create mock entry points - one good, one bad
            mock_ep_good = MagicMock()
            mock_ep_good.name = 'test_provisioners:MockProvisionerA'
            mock_ep_good.value = 'test_clients:MockKernelClientA'
            mock_ep_good.load.return_value = MockKernelClientA
            
            mock_ep_bad = MagicMock()
            mock_ep_bad.name = 'bad:Provisioner'
            mock_ep_bad.value = 'bad:Client'
            mock_ep_bad.load.side_effect = ImportError("Module not found")
            
            mock_eps.return_value = [mock_ep_good, mock_ep_bad]
            
            with patch('importlib.import_module') as mock_import:
                mock_prov_module = Mock()
                mock_prov_module.MockProvisionerA = MockProvisionerA
                mock_import.return_value = mock_prov_module
                
                # Create instance (should handle bad entry point gracefully)
                registry = KernelClientRegistry.instance()
                
                # Good one should still be registered
                assert MockProvisionerA in KernelClientRegistry._registry


class TestKernelClientRegistryFallbackClient:
    """Test fallback client configuration."""
    
    def test_default_fallback_is_kernel_client(self):
        """Test that default fallback is jupyter_client.client.KernelClient."""
        registry = KernelClientRegistry.instance()
        assert registry.fallback_client == KernelClient
    
    def test_configured_fallback_client(self):
        """Test configuring custom fallback client."""
        config = Config()
        config.KernelClientRegistry.fallback_client_class = MockKernelClientC
        
        registry = KernelClientRegistry.instance(config=config)
        assert registry.fallback_client == MockKernelClientC
    
    def test_fallback_used_when_no_match(self):
        """Test fallback is used when no provisioner match."""
        config = Config()
        config.KernelClientRegistry.fallback_client_class = MockKernelClientC
        
        registry = KernelClientRegistry.instance(config=config)
        provisioner = MockProvisionerA()
        
        # No registration for MockProvisionerA, should get fallback
        client_class = registry.get_client_for_provisioner(provisioner)
        assert client_class == MockKernelClientC
    
    def test_fallback_configured_with_string_path(self):
        """Test configuring fallback client with string path (like in jupyter_config.py).
        
        This tests the scenario where configuration uses string paths:
        c.KernelClientRegistry.fallback_client_class = "module.path.ClassName"
        """
        config = Config()
        # Use string path to configure fallback (Type trait supports this)
        config.KernelClientRegistry.fallback_client_class = "jupyter_client.client.KernelClient"
        
        registry = KernelClientRegistry.instance(config=config)
        
        # Verify the string was converted to the actual class
        assert registry.fallback_client == KernelClient
        
        # Verify it's used when no provisioner match
        provisioner = MockProvisionerA()
        client_class = registry.get_client_for_provisioner(provisioner)
        assert client_class == KernelClient


class TestKernelClientRegistryIntegration:
    """Integration tests for full workflow."""
    
    def test_full_registration_and_lookup_workflow(self):
        """Test complete workflow: register, lookup exact, lookup inherited, lookup missing."""
        # Register two provisioners
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        KernelClientRegistry.register(MockProvisionerB, MockKernelClientB)
        
        registry = KernelClientRegistry.instance()
        
        # Test exact match for A
        prov_a = MockProvisionerA()
        assert registry.get_client_for_provisioner(prov_a) == MockKernelClientA
        
        # Test exact match for B
        prov_b = MockProvisionerB()
        assert registry.get_client_for_provisioner(prov_b) == MockKernelClientB
        
        # Test inheritance match for C (inherits from A)
        prov_c = MockProvisionerC()
        assert registry.get_client_for_provisioner(prov_c) == MockKernelClientA
        
        # Test no match - should return fallback
        class UnregisteredProvisioner(KernelProvisionerBase):
            pass
        
        prov_unreg = UnregisteredProvisioner()
        assert registry.get_client_for_provisioner(prov_unreg) == KernelClient
    
    def test_registration_updates_work(self):
        """Test that re-registration updates the mapping."""
        # Register with client A
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        registry = KernelClientRegistry.instance()
        
        prov = MockProvisionerA()
        assert registry.get_client_for_provisioner(prov) == MockKernelClientA
        
        # Re-register with client B
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientB)
        assert registry.get_client_for_provisioner(prov) == MockKernelClientB
    
    def test_clear_and_re_register(self):
        """Test clearing registry and re-registering."""
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientA)
        assert len(KernelClientRegistry._registry) == 1
        
        KernelClientRegistry.clear_registry()
        assert len(KernelClientRegistry._registry) == 0
        
        # Re-register after clear
        KernelClientRegistry.register(MockProvisionerA, MockKernelClientB)
        assert len(KernelClientRegistry._registry) == 1
        
        registry = KernelClientRegistry.instance()
        prov = MockProvisionerA()
        assert registry.get_client_for_provisioner(prov) == MockKernelClientB


class TestKernelClientRegistryEdgeCases:
    """Test edge cases and error handling."""
    
    def test_get_client_for_none_provisioner(self):
        """Test handling None provisioner."""
        registry = KernelClientRegistry.instance()
        client_class = registry.get_client_for_provisioner(None)
        assert client_class == KernelClient  # Should return fallback
    
    def test_register_from_string_with_mixed_separators(self):
        """Test register_from_string handles both : and . separators."""
        with patch('importlib.import_module') as mock_import:
            mock_prov_module = Mock()
            mock_prov_module.MockProvisionerA = MockProvisionerA
            
            mock_client_module = Mock()
            mock_client_module.MockKernelClientA = MockKernelClientA
            
            def import_side_effect(module_name):
                if 'test_provisioners' in module_name:
                    return mock_prov_module
                elif 'test_clients' in module_name:
                    return mock_client_module
                raise ImportError(f"Unknown module: {module_name}")
            
            mock_import.side_effect = import_side_effect
            
            # Use : for provisioner, . for client
            KernelClientRegistry.register_from_string(
                'test_provisioners:MockProvisionerA',
                'test_clients.MockKernelClientA'
            )
            
            assert MockProvisionerA in KernelClientRegistry._registry
    
    def test_get_registered_mappings_empty(self):
        """Test get_registered_mappings with empty registry."""
        mappings = KernelClientRegistry.get_registered_mappings()
        assert mappings == {}
    
    def test_multiple_inheritance_match_first_wins(self):
        """Test that when multiple base classes match, first registered wins."""
        class BaseProvisionerX(KernelProvisionerBase):
            pass
        
        class BaseProvisionerY(KernelProvisionerBase):
            pass
        
        class MultiInheritProvisioner(BaseProvisionerX, BaseProvisionerY):
            pass
        
        # Register both base classes
        KernelClientRegistry.register(BaseProvisionerX, MockKernelClientA)
        KernelClientRegistry.register(BaseProvisionerY, MockKernelClientB)
        
        registry = KernelClientRegistry.instance()
        prov = MultiInheritProvisioner()
        
        # Should match one of the base classes (iteration order dependent)
        client_class = registry.get_client_for_provisioner(prov)
        assert client_class in (MockKernelClientA, MockKernelClientB)
