"""Conexión a SQLite y sesión por petición."""

from collections.abc import Generator
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()

_db_path = Path(settings.database_url.removeprefix("sqlite:///"))
_db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    # FastAPI atiende cada petición en un hilo distinto; SQLite necesita permiso explícito.
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    """WAL permite leer mientras se escribe; busy_timeout evita el error 'database is locked'."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Se inyecta con `Depends(get_session)`: las pruebas pueden usar otra base de datos."""
    with Session(engine) as session:
        yield session


# Inyección de dependencias (la "D" de SOLID): los routers piden una sesión, no la construyen.
SessionDep = Annotated[Session, Depends(get_session)]
