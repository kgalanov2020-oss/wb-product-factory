from __future__ import annotations

import asyncio
from typing import Protocol

from supabase import Client, create_client

from backend.config import Settings

from .models import MPStatsSnapshot


class CollectionRepository(Protocol):
    async def save(self, collection: MPStatsSnapshot) -> bool: ...


class NullCollectionRepository:
    async def save(self, collection: MPStatsSnapshot) -> bool:
        return False


class SupabaseCollectionRepository:
    def __init__(self, client: Client, table: str) -> None:
        self._client = client
        self._table = table

    @classmethod
    def from_settings(cls, settings: Settings) -> SupabaseCollectionRepository:
        if not settings.supabase_configured:
            raise ValueError("Supabase is not configured")
        key = settings.supabase_api_secret
        assert settings.supabase_url is not None and key is not None
        client = create_client(str(settings.supabase_url), key.get_secret_value())
        return cls(client, settings.supabase_mpstats_table)

    async def save(self, collection: MPStatsSnapshot) -> bool:
        payload = collection.model_dump(mode="json")
        await asyncio.to_thread(lambda: self._client.table(self._table).insert(payload).execute())
        return True
