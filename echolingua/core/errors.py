class EchoLinguaError(Exception):
    """Base exception for EchoLingua."""


class ConfigError(EchoLinguaError):
    """Raised when configuration is invalid."""


class ValidationError(EchoLinguaError):
    """Raised when sentence input validation fails."""


class ProviderError(EchoLinguaError):
    """Raised when provider setup or execution fails."""
