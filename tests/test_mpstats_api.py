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


def test_normalize_mpstats_row_keeps_orders_and_buyouts_separate() -> None:
    row = {
        "id": 909634410,
        "name": "Сборная модель 7270 Вертолет Ми-26",
        "brand": {"name": "Звезда"},
        "seller": {"name": "ИП Багдасарян В С"},
        "mpstats_details": {
            "month": {
                "price": {"final_price": 2347},
                "period_stats": {
                    "orders": 4,
                    "orders_sum": 13588,
                    "sales": 3,
                    "revenue": 12423,
                },
            },
            "quarter": {
                "period_stats": {
                    "orders": 4,
                    "orders_sum": 13588,
                    "sales": 3,
                    "revenue": 12423,
                },
            },
        },
    }

    normalized = _normalize_row(row)

    assert normalized["sales"] == 4
    assert normalized["revenue"] == Decimal("13588")
    assert normalized["buyouts"] == 3
    assert normalized["buyout_revenue"] == Decimal("12423")
    assert normalized["periods"]["month"]["sales"] == 4
    assert normalized["periods"]["month"]["revenue"] == Decimal("13588")
    assert normalized["periods"]["month"]["buyouts"] == 3
    assert normalized["periods"]["month"]["buyout_revenue"] == Decimal("12423")
