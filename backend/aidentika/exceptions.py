class AidentikaError(RuntimeError):
    """Base error raised by the Aidentika module."""


class AidentikaConfigurationError(AidentikaError):
    """Raised when Aidentika credentials are unavailable."""


class AidentikaAPIError(AidentikaError):
    """Raised when Aidentika returns an unsuccessful response."""
