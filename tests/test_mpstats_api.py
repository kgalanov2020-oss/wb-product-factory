from decimal import Decimal

from backend.supplier_products.mpstats_api import _normalize_row


def test_normalize_mpstats_row_uses_sku_period_stats() -> None:
    row = {
        "id": 460472568,
        "name": "Конструктор модель военного танка",
        "brand": {"name": "Test brand"},
        "seller": {"name": "Test seller"},
        "url": "https://www.wildberries.ru/catalog/460472568/detail.aspx",
        "mpstats_full": {
            "name": "Конструктор модель военного танка спецназа",
            "brand": "Test brand",
            "seller": {"id": 1, "name": "Test seller"},
            "link": "https://www.wildberries.ru/catalog/460472568/detail.aspx",
            "price": {"price": 2100, "final_price": 711, "wallet_price": 696},
            "balance": 23,
            "subject": {"id": 117, "name": "Игрушки / Конструкторы"},
            "period_stats": {"sales": 133, "revenue": 110559},
        },
    }

    normalized = _normalize_row(row)

    assert normalized["price"] == Decimal("711")
    assert normalized["sales"] == 133
    assert normalized["revenue"] == Decimal("110559")
    assert normalized["supplier"] == "Test seller"
    assert normalized["subject"] == "Игрушки / Конструкторы"
    assert normalized["stock"] == 23
