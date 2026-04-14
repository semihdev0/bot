"""Custom exception hierarchy for the bonus bot."""


class BotException(Exception):
    """Base exception for all bot errors."""


class ConfigurationError(BotException):
    """Invalid configuration files - fail fast at startup."""


class BrowserError(BotException):
    """Browser crashed or context lost."""


class SessionExpiredError(BrowserError):
    """Login session has expired, need to re-login."""


class PageLoadError(BrowserError):
    """Page didn't load within the expected timeout."""


class NavigationError(BotException):
    """Expected page structure not found."""


class RuleEvaluationError(BotException):
    """Error during rule evaluation (e.g., unknown field)."""


class ActionExecutionError(BotException):
    """Failed to execute approve/reject action on the page."""
