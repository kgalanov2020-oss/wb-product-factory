from .collector import PlaywrightMPStatsCollector
from .models import CollectionRequest, CollectionResult
from .repository import CollectionRepository


class MPStatsCollectorService:
    def __init__(
        self,
        collector: PlaywrightMPStatsCollector,
        repository: CollectionRepository,
    ) -> None:
        self._collector = collector
        self._repository = repository

    async def collect(self, request: CollectionRequest) -> CollectionResult:
        collection = await self._collector.collect(request)
        persisted = await self._repository.save(collection)
        return CollectionResult(collection=collection, persisted=persisted)

