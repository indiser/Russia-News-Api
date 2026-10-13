import asyncio
import sys

from fetch_news import get_all_news
from process_russia_data import process_and_push_to_db


async def seed_database():
    print("1. Fetching fresh news...")
    news_data = await get_all_news()

    print("\n2. Matching cities and pushing to database...")
    rows = await asyncio.to_thread(process_and_push_to_db, news_data)

    print(f"\nSeeding complete. Table 'heatmap_data' has {rows} rows.")


if __name__ == "__main__":
    try:
        asyncio.run(seed_database())
    except Exception as e:
        print(f"\nSEEDING FAILED: {type(e).__name__}: {e}")
        sys.exit(1)