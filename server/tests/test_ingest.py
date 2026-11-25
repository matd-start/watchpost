"""Pruebas de integración de la API: HTTP de verdad contra una base de datos temporal."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, select

from server.app.config import get_settings
from server.app.db import engine
from server.app.models import Host, MetricPoint, utcnow

HEADERS = {"X-API-Key": get_settings().api_key}


def payload(**overrides) -> dict:
    data = {
        "host": "laptop-01",
        "os": "Windows 11",
        "points": [
            {"metric": "cpu.percent", "value": 23.5},
            {"metric": "mem.percent", "value": 61.2},
        ],
    }
    data.update(overrides)
    return data


def count_points() -> int:
    with Session(engine) as session:
        return session.exec(select(func.count(MetricPoint.id))).one()


def test_ingest_accepts_a_valid_batch(client: TestClient) -> None:
    response = client.post("/api/v1/ingest", json=payload(), headers=HEADERS)

    assert response.status_code == 202
    assert response.json() == {"host": "laptop-01", "accepted": 2}
    assert count_points() == 2


def test_ingest_without_api_key_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/ingest", json=payload())

    assert response.status_code == 401
    assert count_points() == 0


def test_ingest_with_wrong_api_key_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/ingest", json=payload(), headers={"X-API-Key": "otra"})

    assert response.status_code == 401


def test_percent_above_100_is_rejected(client: TestClient) -> None:
    bad = payload(points=[{"metric": "cpu.percent", "value": 150}])

    response = client.post("/api/v1/ingest", json=bad, headers=HEADERS)

    assert response.status_code == 422


def test_timestamp_in_the_future_is_rejected(client: TestClient) -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    bad = payload(points=[{"metric": "cpu.percent", "value": 10, "ts": future}])

    response = client.post("/api/v1/ingest", json=bad, headers=HEADERS)

    assert response.status_code == 422
    assert "futuro" in response.json()["detail"]


def test_unknown_host_is_registered(client: TestClient) -> None:
    client.post("/api/v1/ingest", json=payload(host="nueva-maquina"), headers=HEADERS)

    hosts = client.get("/api/v1/hosts").json()

    assert [host["name"] for host in hosts] == ["nueva-maquina"]


def test_host_is_online_right_after_reporting(client: TestClient) -> None:
    client.post("/api/v1/ingest", json=payload(), headers=HEADERS)

    host = client.get("/api/v1/hosts").json()[0]

    assert host["status"] == "online"


def test_host_goes_offline_after_the_threshold(client: TestClient, session: Session) -> None:
    client.post("/api/v1/ingest", json=payload(), headers=HEADERS)
    host = session.exec(select(Host)).one()
    host.last_seen_at = utcnow() - timedelta(seconds=120)
    session.add(host)
    session.commit()

    status = client.get("/api/v1/hosts").json()[0]["status"]

    assert status == "offline"


def test_repeated_batch_does_not_duplicate_points(client: TestClient) -> None:
    """El agente reenvía el mismo lote con los mismos `ts`: no deben duplicarse."""
    ts = datetime.now(UTC).isoformat()
    batch = payload(
        points=[
            {"metric": "cpu.percent", "value": 23.5, "ts": ts},
            {"metric": "mem.percent", "value": 61.2, "ts": ts},
        ]
    )
    client.post("/api/v1/ingest", json=batch, headers=HEADERS)
    client.post("/api/v1/ingest", json=batch, headers=HEADERS)

    assert count_points() == 2


def test_latest_returns_the_most_recent_value(client: TestClient) -> None:
    now = datetime.now(UTC)
    older = (now - timedelta(minutes=2)).isoformat()
    newer = now.isoformat()
    point_older = payload(points=[{"metric": "cpu.percent", "value": 10, "ts": older}])
    point_newer = payload(points=[{"metric": "cpu.percent", "value": 90, "ts": newer}])
    client.post("/api/v1/ingest", json=point_older, headers=HEADERS)
    client.post("/api/v1/ingest", json=point_newer, headers=HEADERS)

    response = client.get("/api/v1/hosts/laptop-01/latest")

    assert response.status_code == 200
    assert response.json()["values"]["cpu.percent"] == 90


def test_latest_for_unknown_host_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/hosts/fantasma/latest")

    assert response.status_code == 404
