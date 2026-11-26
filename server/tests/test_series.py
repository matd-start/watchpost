"""Pruebas de la serie histórica: cubos, bordes y errores.

Se siembran fechas fijas en el pasado para poder afirmar valores exactos:
con `datetime.now()` los cubos cambiarían en cada ejecución.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from server.app.config import get_settings
from server.app.services.metrics import step_for

HEADERS = {"X-API-Key": get_settings().api_key}
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def send_points(
    client: TestClient,
    points: list[tuple[datetime, float]],
    host: str = "laptop-01",
) -> None:
    """Siembra puntos con su `ts` real a través de la API de ingesta."""
    payload = {
        "host": host,
        "points": [
            {"metric": "cpu.percent", "value": value, "ts": moment.isoformat()}
            for moment, value in points
        ],
    }
    response = client.post("/api/v1/ingest", json=payload, headers=HEADERS)
    assert response.status_code == 202


def get_series(
    client: TestClient,
    start: datetime,
    end: datetime,
    metric: str = "cpu.percent",
    host: str = "laptop-01",
) -> dict:
    response = client.get(
        f"/api/v1/hosts/{host}/metrics",
        params={"metric": metric, "from": start.isoformat(), "to": end.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("span", "expected_step"),
    [
        (timedelta(minutes=15), 10),
        (timedelta(hours=1), 60),
        (timedelta(hours=24), 300),
        (timedelta(days=7), 3600),
    ],
)
def test_step_grows_with_the_range(span: timedelta, expected_step: int) -> None:
    """La tabla de cubos es la regla de negocio: si cambia sin querer, esto avisa."""
    assert step_for(span) == expected_step


def test_points_in_the_same_bucket_are_summarised(client: TestClient) -> None:
    send_points(
        client,
        [
            (BASE + timedelta(seconds=10), 10),
            (BASE + timedelta(seconds=20), 20),
            (BASE + timedelta(seconds=30), 50),
        ],
    )

    body = get_series(client, BASE, BASE + timedelta(minutes=30))

    assert body["step_seconds"] == 60
    assert len(body["points"]) == 1
    bucket = body["points"][0]
    assert datetime.fromisoformat(bucket["bucket_start"]) == BASE
    assert bucket["avg"] == pytest.approx(26.67)
    assert bucket["min"] == 10
    assert bucket["max"] == 50
    assert bucket["count"] == 3


def test_each_bucket_reports_its_own_count(client: TestClient) -> None:
    """El cubo parcial se delata por `count`: por eso no basta con la media."""
    send_points(
        client,
        [
            (BASE + timedelta(seconds=10), 10),
            (BASE + timedelta(seconds=40), 30),
            (BASE + timedelta(minutes=1, seconds=15), 60),
        ],
    )

    points = get_series(client, BASE, BASE + timedelta(minutes=30))["points"]

    assert [point["count"] for point in points] == [2, 1]
    assert [point["avg"] for point in points] == [20, 60]


def test_a_point_exactly_on_the_bucket_edge_opens_the_next_bucket(client: TestClient) -> None:
    send_points(client, [(BASE + timedelta(minutes=1), 42)])

    points = get_series(client, BASE, BASE + timedelta(minutes=30))["points"]

    assert datetime.fromisoformat(points[0]["bucket_start"]) == BASE + timedelta(minutes=1)


def test_the_end_of_the_window_is_exclusive(client: TestClient) -> None:
    """Un punto en `to` pertenece a la petición siguiente, no a las dos."""
    send_points(
        client,
        [
            (BASE + timedelta(seconds=30), 10),
            (BASE + timedelta(minutes=20), 99),
        ],
    )

    points = get_series(client, BASE, BASE + timedelta(minutes=20))["points"]

    assert len(points) == 1
    assert points[0]["max"] == 10


def test_naive_timestamps_are_read_as_utc(client: TestClient) -> None:
    send_points(client, [(BASE + timedelta(seconds=20), 30)])

    response = client.get(
        "/api/v1/hosts/laptop-01/metrics",
        params={
            "metric": "cpu.percent",
            "from": "2026-01-01T00:00:00",
            "to": "2026-01-01T00:30:00",
        },
    )

    body = response.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["count"] == 1


def test_the_window_is_echoed_back(client: TestClient) -> None:
    send_points(client, [(BASE + timedelta(seconds=20), 30)])

    body = get_series(client, BASE, BASE + timedelta(minutes=30))

    assert datetime.fromisoformat(body["from"]) == BASE
    assert datetime.fromisoformat(body["to"]) == BASE + timedelta(minutes=30)
    assert body["metric"] == "cpu.percent"
    assert body["host"] == "laptop-01"


def test_a_range_without_data_is_empty_not_an_error(client: TestClient) -> None:
    """Un host recién registrado no es un 404: es que aún no hay historia."""
    send_points(client, [(BASE - timedelta(days=1), 10)])

    response = client.get(
        "/api/v1/hosts/laptop-01/metrics",
        params={
            "metric": "cpu.percent",
            "from": BASE.isoformat(),
            "to": (BASE + timedelta(minutes=10)).isoformat(),
        },
    )

    assert response.status_code == 200
    assert response.json()["points"] == []


def test_unknown_host_returns_404(client: TestClient) -> None:
    response = client.get(
        "/api/v1/hosts/fantasma/metrics",
        params={
            "metric": "cpu.percent",
            "from": BASE.isoformat(),
            "to": (BASE + timedelta(minutes=10)).isoformat(),
        },
    )

    assert response.status_code == 404


def test_inverted_range_returns_422(client: TestClient) -> None:
    send_points(client, [(BASE, 10)])

    response = client.get(
        "/api/v1/hosts/laptop-01/metrics",
        params={
            "metric": "cpu.percent",
            "from": (BASE + timedelta(minutes=10)).isoformat(),
            "to": BASE.isoformat(),
        },
    )

    assert response.status_code == 422


def test_range_longer_than_the_limit_returns_422(client: TestClient) -> None:
    send_points(client, [(BASE, 10)])

    response = client.get(
        "/api/v1/hosts/laptop-01/metrics",
        params={
            "metric": "cpu.percent",
            "from": (BASE - timedelta(days=32)).isoformat(),
            "to": BASE.isoformat(),
        },
    )

    assert response.status_code == 422
    assert "31" in response.json()["detail"]


def test_unknown_metric_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/hosts/laptop-01/metrics",
        params={
            "metric": "temperatura.nuclear",
            "from": BASE.isoformat(),
            "to": (BASE + timedelta(minutes=10)).isoformat(),
        },
    )

    assert response.status_code == 422
