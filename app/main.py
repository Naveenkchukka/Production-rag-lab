"""FastAPI entry point and initial liveness/readiness endpoints."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from psycopg_pool import ConnectionPool, PoolTimeout

from app.db.connection import create_pool
from app.answers.generator import generate_answer
from app.embeddings.client import OpenAIEmbedder
from app.retrieval.demo import DEMO_USERS
from app.retrieval.search import retrieve_chunks
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Establish a shared, bounded connection pool before accepting requests.
    settings = get_settings()
    pool = create_pool(settings)
    pool.open(wait=True, timeout=10)
    app.state.settings = settings
    app.state.db_pool = pool
    app.state.embedder = OpenAIEmbedder(settings)
    try:
        yield
    finally:
        app.state.embedder.close()
        pool.close()


app = FastAPI(title="HarborDesk RAG Lab", version="0.2.0", lifespan=lifespan)


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    principal: Literal["public", "employee", "hr"] = "public"
    top_k: int = Field(default=5, ge=1, le=10)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def question_page() -> str:
    """Serve the local question-and-answer page."""
    page = Path(__file__).parent / "web" / "index.html"
    return page.read_text(encoding="utf-8")


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


@app.post("/api/ask", tags=["rag"])
def ask_question(payload: AskRequest, request: Request) -> dict:
    """Answer one question using the selected local demo principal."""
    question = payload.query.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question must not be empty")

    embedder: OpenAIEmbedder = request.app.state.embedder
    query_vector = embedder.embed([question])[0]
    settings = request.app.state.settings
    pool: ConnectionPool = request.app.state.db_pool
    try:
        passages = retrieve_chunks(
            pool,
            organization_id=str(settings.rag_organization_id),
            user_id=DEMO_USERS[payload.principal],
            question=question,
            query_embedding=query_vector,
            top_k=payload.top_k,
        )
        answer = generate_answer(settings, question, passages)
    except (psycopg.Error, PoolTimeout) as exc:
        raise HTTPException(status_code=503, detail="The database is temporarily unavailable") from exc
    return {"principal": payload.principal, **answer}
