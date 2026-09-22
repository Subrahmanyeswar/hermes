import importlib.util
import os
import sys

class PluginManager:
    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.plugins = {}  # Maps plugin name to plugin instance or module

    def load_plugin(self, plugin_name, plugin_file):
        # Load the plugin module
        spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Check for required hooks
        if not hasattr(module, 'plugin_init'):
            raise AttributeError(f"Plugin {plugin_name} does not have required hook 'plugin_init'")
        if not hasattr(module, 'plugin_request'):
            raise AttributeError(f"Plugin {plugin_name} does not have required hook 'plugin_request'")
        if not hasattr(module, 'plugin_shutdown'):
            raise AttributeError(f"Plugin {plugin_name} does not have required hook 'plugin_shutdown'")

        # Initialize the plugin
        init_func = getattr(module, 'plugin_init')
        init_func()

        # Store the plugin module
        self.plugins[plugin_name] = module

    def handle_request(self, request_data):
        for plugin_name, plugin_module in self.plugins.items():
            try:
                request_func = getattr(plugin_module, 'plugin_request', None)
                if request_func:
                    request_func(request_data)
            except Exception as e:
                print(f"Plugin {plugin_name} failed: {e}")
                # Continue with other plugins

    def shutdown_plugins(self):
        for plugin_name, plugin_module in self.plugins.items():
            try:
                shutdown_func = getattr(plugin_module, 'plugin_shutdown', None)
                if shutdown_func:
                    shutdown_func()
            except Exception as e:
                print(f"Plugin {plugin_name} shutdown failed: {e}")

# Example usage
if __name__ == "__main__":
    manager = PluginManager("plugins/")  # Assume plugins directory
    # Load a plugin
    manager.load_plugin("my_plugin", "plugins/my_plugin.py")
    # Handle a request
    manager.handle_request({"data": "example"})
    # Shutdown
    manager.shutdown_plugins()