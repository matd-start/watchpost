"""Configuración común de las pruebas de la API.

El entorno se prepara antes de importar la app, porque la configuración se lee al importar.
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

_TMP_DIR = Path(tempfile.mkdtemp(prefix="watchpost-test-"))
os.environ["WATCHPOST_DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["WATCHPOST_API_KEY"] = "clave-de-prueba"

from server.app.db import engine  # noqa: E402
from server.app.main import app  # noqa: E402


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Cada prueba arranca con la base de datos vacía."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    with Session(engine) as db_session:
        yield db_session
