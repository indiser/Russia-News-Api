import hmac
import json
import os

import pandas as pd
from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from db import get_engine
from fetch_news import get_all_news
from process_russia_data import process_and_push_to_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title="Internal Russia News API",
    description="Serverless API for fetching processed Russian heatmap data.",
)

# allow_origins="*" + allow_credentials=True is invalid per CORS spec. No cookies used.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def parse_record(record):
    """headlines stored as JSON string. Unpack to real list."""
    try:
        record["headlines"] = json.loads(record["headlines"])
    except (TypeError, ValueError, KeyError):
        record["headlines"] = []
    return record


def query_df(sql, **params):
    try:
        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except RuntimeError as e:  # DATABASE_URL missing
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {type(e).__name__}")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    path = os.path.join(BASE_DIR, "favicon.ico")
    if not os.path.exists(path):
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/")
def root():
    return {"message": "Russia News API is live. Go to '/api/news' or '/api/news/city_name'. Hit /docs for documentation."}


@app.get("/api/news")
def get_news():
    """Serves the latest heatmap data with clean, structured arrays."""
    df = query_df("SELECT * FROM heatmap_data")
    df = df.astype(object).where(df.notna(), "")
    return [parse_record(r) for r in df.to_dict(orient="records")]


@app.get("/api/news/{city}")
def get_news_by_city(city: str):
    """Fetch news for one city by English or Russian name, case-insensitive."""
    df = query_df(
        'SELECT * FROM heatmap_data WHERE lower("Name") = lower(:c) OR lower("Russianname") = lower(:c) LIMIT 1',
        c=city.strip(),
    )
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No news found for city: {city}")
    df = df.astype(object).where(df.notna(), "")
    return parse_record(df.to_dict(orient="records")[0])


@app.get("/api/cron/update")
async def trigger_update(authorization: str = Header(None)):
    """Manual trigger to refresh the database. GitHub Actions runs seed.py on schedule."""
    secret = os.environ.get("CRON_SECRET")
    # Old code: unset secret -> "Bearer None" passed auth. Refuse instead.
    if not secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured.")
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(status_code=401, detail="Unauthorized.")

    try:
        news_data = await get_all_news()
        # pandas/regex/DB are blocking. Keep them off the event loop.
        rows = await run_in_threadpool(process_and_push_to_db, news_data)
        return {"status": "success", "message": "Database updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")


@app.get("/api/health")
def health_check():
    df = query_df("SELECT last_updated FROM heatmap_data LIMIT 1")
    if df.empty:
        return {"status": "empty", "last_updated": None}
    return {"status": "healthy", "last_updated": str(df["last_updated"].iloc[0])}