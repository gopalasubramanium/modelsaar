"""Backend adapters. Add a runtime by subclassing BaseAdapter and registering it."""

from .base import AdapterError, BaseAdapter, UpstreamResponse, UpstreamStream
from .ollama import OllamaAdapter
from .openai_compat import OpenAICompatAdapter

ADAPTER_TYPES = {
    "ollama": OllamaAdapter,
    "openai_compatible": OpenAICompatAdapter,
}


def register_adapter(type_name: str, cls: type[BaseAdapter]) -> None:
    """Plugin hook: register an additional adapter type without touching the router."""
    ADAPTER_TYPES[type_name] = cls


__all__ = [
    "ADAPTER_TYPES",
    "AdapterError",
    "BaseAdapter",
    "OllamaAdapter",
    "OpenAICompatAdapter",
    "UpstreamResponse",
    "UpstreamStream",
    "register_adapter",
]
