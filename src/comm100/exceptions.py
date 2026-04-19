"""Custom exception hierarchy for the Comm100 chatbot."""

from src.utils.exceptions import BotException


class Comm100Error(BotException):
    """Base for all Comm100-related errors."""


class Comm100AuthError(Comm100Error):
    """Authentication failed (401)."""


class Comm100ApiError(Comm100Error):
    """API request failed (non-auth)."""


class Comm100RateLimitError(Comm100ApiError):
    """Rate limit hit (429)."""


class ClaudeApiError(BotException):
    """Claude API call failed."""
