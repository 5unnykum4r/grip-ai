"""grip - Async-first agentic AI platform."""

import logging as _logging

# Silence LiteLLM's import-time warnings about failing to pre-load the
# bedrock-runtime / sagemaker-runtime stream shapes (botocore isn't installed
# and those providers are unused). These fire from the "LiteLLM" logger at
# WARNING level the moment litellm is imported, so the threshold must be raised
# here — before any grip submodule pulls litellm in.
_logging.getLogger("LiteLLM").setLevel(_logging.ERROR)

__version__ = "1.6.0"
