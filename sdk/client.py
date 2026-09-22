from typing import Dict, List, Optional


class HermesClient:
    """A client for interacting with the Hermes service."""
    def __init__(self, api_key: str):
        self.api_key = api_key
        if not api_key:
            raise ValueError("API key must be provided.")

    def send_request(self, endpoint: str, data: Dict) -> Dict:
        """Send a request to the specified endpoint."""
        try:
            # Simulate sending a request
            return {"status": "success", "data": data}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class ConfigBuilder:
    """A builder for configuration settings."""
    def __init__(self):
        self.config = {}

    def set_config(self, key: str, value: any):
        """Set a configuration value."""
        self.config[key] = value

    def build(self) -> Dict:
        """Build and return the configuration."""
        return self.config


class StreamResponse:
    """Handles streaming responses."""
    def __init__(self, stream_data: List[str]):
        self.stream_data = stream_data

    def process_stream(self):
        """Process the stream data."""
        for data in self.stream_data:
            yield data


__all__ = ['HermesClient', 'ConfigBuilder', 'StreamResponse']