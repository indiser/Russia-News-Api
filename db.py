import os
import re

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

_engine = None


def get_engine():
    """One engine per process. Raises clear error if misconfigured."""
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL missing. Put it in .env next to these scripts.")
        # requirements.txt has psycopg v3. Bare postgres(ql):// makes SQLAlchemy
        # load psycopg2 -> ModuleNotFoundError. Force the v3 driver.
        url = re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", url, count=1)
        _engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)
    return _engine