class MPStatsCollectorError(RuntimeError):
    """Base error raised by the MPStats collector module."""


class MPStatsConfigurationError(MPStatsCollectorError):
    """Raised when credentials, selectors, or session state are unavailable."""
