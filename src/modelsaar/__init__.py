"""ModelSaar - intelligent routing for local AI models.

One OpenAI-compatible endpoint that selects the most suitable *eligible* local
deployment per request, explains the decision, and preserves the client's
semantics (tools, media, schemas, streaming).
"""

__version__ = "0.1.0"
CONFIG_VERSION = 1
