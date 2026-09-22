from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class NormalizedModelResponse(BaseModel):
    """
    Normalized response structure across all model providers.
    Provides uniform access to generated content, token usage, latency,
    cost, and provider metadata.
    """
    text: str = ""
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None
    raw_response: str = ""
    cost_usd: float = 0.0
    lifecycle_state: str = "UNKNOWN"
    success: bool = True

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.text == other
        return super().__eq__(other)

    def strip(self, *args: Any, **kwargs: Any) -> str:
        return self.text.strip(*args, **kwargs)

    def split(self, *args: Any, **kwargs: Any) -> list[str]:
        return self.text.split(*args, **kwargs)

    def startswith(self, *args: Any, **kwargs: Any) -> bool:
        return self.text.startswith(*args, **kwargs)

    def endswith(self, *args: Any, **kwargs: Any) -> bool:
        return self.text.endswith(*args, **kwargs)

    def lower(self) -> str:
        return self.text.lower()

    def upper(self) -> str:
        return self.text.upper()

    def __contains__(self, item: Any) -> bool:
        return item in self.text

    def __getitem__(self, item: Any) -> Any:
        return self.text[item]

class ModelProvider:
    """Abstract base class for all HERMES model providers."""

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> NormalizedModelResponse:
        """
        Generate a completion for the given prompt and system instructions.
        Returns a NormalizedModelResponse.
        """
        raise NotImplementedError("Subclasses must implement generate()")

    async def is_available(self) -> bool:
        """Check if the provider endpoint is reachable and ready."""
        return True

