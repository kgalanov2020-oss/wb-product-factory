class ProductContentError(RuntimeError):
    """Base error raised by the product content module."""


class ProductContentRepositoryError(ProductContentError):
    """Raised when product content persistence is unavailable."""
