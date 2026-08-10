import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from brain_farm.app.database.models import DataFieldCache
from brain_farm.app.services.brain_client import BrainClient

logger = logging.getLogger("brain_farm.field_manager")

# In case caching is empty, fall back to these high-value default quant fields
DEFAULT_FIELDS = [
    {"id": "close", "name": "Close Price", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
    {"id": "open", "name": "Open Price", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
    {"id": "volume", "name": "Volume", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
    {"id": "vwap", "name": "Volume Weighted Average Price", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
    {"id": "ebit", "name": "Earnings Before Interest and Taxes", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
    {"id": "capex", "name": "Capital Expenditures", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
    {"id": "total_assets", "name": "Total Assets", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
    {"id": "revenue", "name": "Revenue", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
    {"id": "net_income", "name": "Net Income", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
    {"id": "eps_estimate", "name": "EPS Estimate", "dataset": "ANALYST_ESTIMATES", "category": "Estimates", "type": "FLOAT"},
    {"id": "sales", "name": "Total Sales", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"}
]

class FieldManager:
    """Manages retrieving, caching, searching, and marking data fields as favorites."""

    @staticmethod
    async def get_all_fields(db: AsyncSession) -> List[DataFieldCache]:
        """Fetch all fields stored to database cache."""
        result = await db.execute(select(DataFieldCache))
        fields = list(result.scalars().all())
        
        # If cache is empty, populate default fields
        if not fields:
            logger.info("Database cache is empty. Seeding defaults.")
            await FieldManager.seed_default_fields(db)
            result = await db.execute(select(DataFieldCache))
            fields = list(result.scalars().all())
            
        return fields

    @staticmethod
    async def seed_default_fields(db: AsyncSession):
        """Seeds default fields into the cache."""
        for fd in DEFAULT_FIELDS:
            cache_entry = DataFieldCache(
                id=fd["id"],
                name=fd["name"],
                dataset=fd["dataset"],
                category=fd["category"],
                region="USA",
                universe="TOP3000",
                type=fd["type"],
                is_favorite=False
            )
            # Merge to prevent duplicate keys if row got created in the interim
            await db.merge(cache_entry)
        await db.commit()

    @staticmethod
    async def sync_cache_with_api(db: AsyncSession, client: BrainClient, region: str, universe: str) -> int:
        """Fetches from API, clears old cache, and stores new fields in the DB."""
        try:
            logger.info(f"Syncing fields cache with API for region={region}, universe={universe}")
            response_data = await client.get_data_fields(region=region, universe=universe, limit=100)
            results = response_data.get("results", [])
            
            if not results:
                logger.warning("API returned 0 fields. Cache update skipped.")
                return 0

            # Delete cache fields of the same region/universe
            await db.execute(
                delete(DataFieldCache).where(
                    (DataFieldCache.region == region) & 
                    (DataFieldCache.universe == universe) & 
                    (DataFieldCache.is_favorite == False)  # Keep favorites
                )
            )

            count = 0
            for field in results:
                # Basic fields mapper
                cache_entry = DataFieldCache(
                    id=field.get("id"),
                    name=field.get("name", field.get("id", "")),
                    dataset=field.get("dataset", "UNKNOWN"),
                    category=field.get("category", "UNKNOWN"),
                    region=region,
                    universe=universe,
                    description=field.get("description", ""),
                    type=field.get("type", "FLOAT"),
                    is_favorite=False
                )
                await db.merge(cache_entry)
                count += 1

            await db.commit()
            logger.info(f"Cached {count} fields from API.")
            return count
        except Exception:
            logger.exception("Cache synchronizer failed")
            return 0

    @staticmethod
    async def toggle_favorite(db: AsyncSession, field_id: str) -> bool:
        """Toggles the favorite state of a data field."""
        result = await db.execute(select(DataFieldCache).where(DataFieldCache.id == field_id))
        field = result.scalar_one_or_none()
        if not field:
            return False
            
        field.is_favorite = not field.is_favorite
        await db.commit()
        return field.is_favorite

    @staticmethod
    async def search_fields(db: AsyncSession, query: str, favorite_only: bool = False) -> List[DataFieldCache]:
        """Search and filter cached fields."""
        # Ensure database is seeded with defaults if cache is empty
        result_check = await db.execute(select(DataFieldCache).limit(1))
        if not result_check.scalar_one_or_none():
            logger.info("Database cache is empty during search. Seeding defaults.")
            await FieldManager.seed_default_fields(db)

        stmt = select(DataFieldCache)
        if favorite_only:
            stmt = stmt.where(DataFieldCache.is_favorite == True)
        
        result = await db.execute(stmt)
        fields = list(result.scalars().all())
        
        if not query:
            return fields
            
        query = query.lower()
        filtered = [
            f for f in fields 
            if query in f.id.lower() or query in f.name.lower() or query in f.category.lower() or query in f.dataset.lower()
        ]
        return filtered
