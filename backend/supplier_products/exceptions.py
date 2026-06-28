class SupplierProductError(RuntimeError):
    """Base error raised by supplier product workflows."""


class SupplierProductRepositoryError(SupplierProductError):
    """Raised when supplier product persistence is unavailable."""


class SupplierPriceListError(SupplierProductError):
    """Raised when a supplier price list cannot be parsed."""
