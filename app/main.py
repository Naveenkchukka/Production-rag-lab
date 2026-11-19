"""FastAPI entry point and initial liveness/readiness endpoints."""

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Request
from psycopg_pool import ConnectionPool, PoolTimeout

from app.db.connection import create_pool
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Establish a shared, bounded connection pool before accepting requests.
    pool = create_pool(get_settings())
    pool.open(wait=True, timeout=10)
    app.state.db_pool = pool
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="HarborDesk RAG API", version="0.1.0", lifespan=lifespan)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Confirm that the HTTP process can respond; this does not check Postgres."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness(request: Request) -> dict[str, str]:
    """Confirm Postgres is reachable through the restricted runtime role."""
    pool: ConnectionPool = request.app.state.db_pool
    try:
        with pool.connection() as connection:
            row = connection.execute("SELECT current_user").fetchone()
    except (psycopg.Error, PoolTimeout) as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {
        "status": "ok",
        "database": "ok",
        "database_role": row[0],
        "tenant_context_required": "true",
    }
