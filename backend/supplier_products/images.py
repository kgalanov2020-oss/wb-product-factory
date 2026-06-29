from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx


PRODUCT_IMAGE_PATTERN = re.compile(
    r"/upload/resize_cache/iblock/[^\"']+/(?:900_900_1|1200_1200_1)/[^\"']+\.(?:jpg|jpeg|png|webp)",
    re.IGNORECASE,
)


async def fetch_zvezda_product_images(source_url: str, limit: int = 20) -> list[str]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(source_url)
    response.raise_for_status()
    urls: list[str] = []
    for match in PRODUCT_IMAGE_PATTERN.findall(response.text):
        absolute = urljoin(str(response.url), match)
        if absolute not in urls and _is_product_like_image(absolute):
            urls.append(absolute)
        if len(urls) >= limit:
            break
    return urls


def _is_product_like_image(url: str) -> bool:
    lowered = url.lower()
    ignored = ("catalogue", "katalog", "futbolka", "kusachki", "pintset", "kistey", "nozh")
    return not any(marker in lowered for marker in ignored)
