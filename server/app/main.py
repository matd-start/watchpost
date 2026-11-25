"""Punto de entrada de la API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routers import hosts, ingest


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Watchpost", version="0.1.0", lifespan=lifespan)
app.include_router(ingest.router)
app.include_router(hosts.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
