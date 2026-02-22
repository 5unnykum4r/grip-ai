"""User-friendly exceptions for LLM provider errors.

These replace raw httpx/litellm tracebacks with clear, actionable
messages that tell the user exactly what went wrong and how to fix it.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all provider errors."""

    def __init__(self, message: str, *, provider: str = "", hint: str = "") -> None:
        self.provider = provider
        self.hint = hint
        super().__init__(message)


class AuthenticationError(ProviderError):
    """API key is missing, invalid, or expired."""


class RateLimitError(ProviderError):
    """Provider rate limit exceeded."""


class InsufficientQuotaError(ProviderError):
    """Account has insufficient credits or quota."""


class ModelNotFoundError(ProviderError):
    """Requested model does not exist on the provider."""


class ProviderConnectionError(ProviderError):
    """Cannot reach the provider's API endpoint."""


class ServerError(ProviderError):
    """Provider returned a 5xx server error."""


_STATUS_MAP: dict[int, tuple[type[ProviderError], str, str]] = {
    401: (
        AuthenticationError,
        "Authentication failed — your API key is invalid or missing.",
        "Run 'grip setup' to reconfigure your API key, or check your config file.",
    ),
    403: (
        AuthenticationError,
        "Access denied — your API key lacks permission for this resource.",
        "Verify your API key permissions on the provider's dashboard.",
    ),
    404: (
        ModelNotFoundError,
        "Model not found on this provider.",
        "Run 'grip config set agents.defaults.model MODEL_NAME' with a valid model, "
        "or check available models on your provider's docs.",
    ),
    422: (
        ProviderError,
        "The provider rejected the request payload.",
        "This may be a model compatibility issue. Try a different model.",
    ),
    429: (
        RateLimitError,
        "Rate limit exceeded — too many requests.",
        "Wait a moment and try again, or upgrade your plan with the provider.",
    ),
    402: (
        InsufficientQuotaError,
        "Insufficient credits or quota on your account.",
        "Add credits on your provider's billing page.",
    ),
    500: (ServerError, "Provider internal server error.", "Try again in a moment."),
    502: (ServerError, "Provider returned a bad gateway error.", "Try again in a moment."),
    503: (ServerError, "Provider is temporarily unavailable.", "Try again in a moment."),
    529: (ServerError, "Provider is overloaded.", "Try again in a moment."),
}


def raise_for_status(
    status_code: int,
    provider_name: str,
    api_base: str,
    model: str,
    raw_message: str = "",
) -> None:
    """Raise a friendly ProviderError based on the HTTP status code.

    Call this instead of httpx's resp.raise_for_status() to get
    actionable error messages instead of raw tracebacks.
    """
    if 200 <= status_code < 300:
        return

    exc_class, message, hint = _STATUS_MAP.get(
        status_code,
        (ProviderError, f"Unexpected HTTP {status_code} from provider.", ""),
    )

    full_message = (
        f"[{provider_name}] {message}"
        f"\n  Provider: {provider_name} ({api_base})"
        f"\n  Model:    {model}"
    )

    if raw_message:
        short = raw_message[:200].replace("\n", " ")
        full_message += f"\n  Detail:   {short}"

    raise exc_class(full_message, provider=provider_name, hint=hint)
