import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

import pandas as pd

from db import get_engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_NAME = "complete-russian-database-cleaned.csv"
TABLE = "heatmap_data"

TAG_RE = re.compile(r"<[^>]+>")
# "Vladimir" city vs Vladimir Putin etc. Strip person names before matching.
PERSON_NOISE = re.compile(
    r"(vladimir|владимир)\s+(putin|zelensk\w*|solovyov|путин\w*|зеленск\w*|соловьев\w*)"
)
RU_ENDINGS = "аяьйоеыи"
MSK = timezone(timedelta(hours=3))  # Moscow: UTC+3, no DST, no tz database needed


def norm(text):
    """lowercase + ё->е so 'Орёл' and 'Орел' both match."""
    return (text or "").lower().replace("ё", "е")


def clean(text):
    text = TAG_RE.sub(" ", text or "")  # drop html, hrefs would false-match
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def term_regex(term):
    """Whole-word for latin. Cyrillic: stem + up to 3 letters (declension)."""
    if not isinstance(term, str):  # NaN from CSV
        return None
    term = norm(term).strip()
    if not term:
        return None
    if re.search(r"[а-я]", term):
        stem = term[:-1] if len(term) > 4 and term[-1] in RU_ENDINGS else term
        return re.escape(stem) + r"\w{0,3}"
    return re.escape(term)


def build_pattern(row):
    parts = [p for p in (term_regex(row["Name"]), term_regex(row["Russianname"])) if p]
    if not parts:
        return None  # empty alternation would match EVERY article
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")


def prepare_articles(news_data):
    prepared, seen_titles = [], set()
    for a in news_data.get("articles", []):
        title = clean(a.get("title"))
        if not title or title in seen_titles:  # syndicated dupes
            continue
        seen_titles.add(title)
        text = norm(f"{title} {clean(a.get('description'))}")
        prepared.append((PERSON_NOISE.sub(" ", text), title))
    return prepared


def score_locations(df_locations, articles):
    counts, headlines = [], []
    for _, row in df_locations.iterrows():
        pattern = build_pattern(row)
        found = [t for text, t in articles if pattern and pattern.search(text)]
        counts.append(len(found))
        headlines.append(json.dumps(found, ensure_ascii=False))  # JSON list, like India
    out = df_locations.copy()
    out["news_count"] = counts
    out["headlines"] = headlines
    return out


def process_and_push_to_db(news_data):
    """Raises on any failure. Returns number of rows pushed."""
    df_locations = pd.read_csv(os.path.join(BASE_DIR, CSV_NAME))
    # Cities col = whole-region village list. Generic words. False positives. Not used.
    df_locations = df_locations.drop(columns=["Cities"], errors="ignore")

    articles = prepare_articles(news_data)
    print(f"Loaded {len(articles)} unique articles. Scanning {len(df_locations)} cities...")
    if not articles:
        raise RuntimeError("0 articles fetched. Not touching the database. Check feed errors above.")

    df_final = score_locations(df_locations, articles)
    df_final = df_final[df_final["news_count"] > 0].sort_values("news_count", ascending=False)
    if df_final.empty:
        raise RuntimeError(f"{len(articles)} articles but 0 city matches. Not touching the database.")
    # Same format as India (12h AM/PM). Moscow time instead of IST.
    df_final["last_updated"] = datetime.now(MSK).strftime("%Y-%m-%d %I:%M:%S %p")
    df_final["State"] = df_final["Federal subject"]  # India-style key

    print("Connecting to database...")
    # One transaction: Postgres DDL is transactional, so readers see old table
    # until commit. No empty-table window. Failure rolls back, old data stays.
    with get_engine().begin() as conn:
        df_final.to_sql(TABLE, conn, if_exists="replace", index=False)
    print(f"DONE. Pushed {len(df_final)} active cities.")
    return len(df_final)