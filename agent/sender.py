"""Envío de métricas al servidor: buffer acotado y reintento en el ciclo siguiente."""

import logging
from collections import deque
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

MAX_BUFFERED_POINTS = 500


@dataclass(frozen=True)
class Point:
    metric: str
    value: float
    ts: str


class Sender:
    """Envía lotes y conserva los puntos si el servidor no responde.

    El buffer es un `deque(maxlen=500)`: al llenarse descarta solo los más
    antiguos, que es exactamente la regla RF-04.
    """

    def __init__(self, base_url: str, api_key: str, host: str, os_name: str) -> None:
        self._host = host
        self._os = os_name
        self._buffer: deque[Point] = deque(maxlen=MAX_BUFFERED_POINTS)
        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=5.0,
        )

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def send(self, points: list[Point]) -> bool:
        """Encola y vacía. Devuelve False si el servidor no respondió."""
        self._buffer.extend(points)
        return self._flush()

    def _flush(self) -> bool:
        while self._buffer:
            batch = list(self._buffer)
            payload = {
                "host": self._host,
                "os": self._os,
                "points": [
                    {"metric": point.metric, "value": point.value, "ts": point.ts}
                    for point in batch
                ],
            }
            try:
                self._client.post("/api/v1/ingest", json=payload).raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "Envío fallido (%s). Quedan %s puntos en el buffer.", exc, self.pending
                )
                return False
            # Se quitan solo los que ya viajaron: si entraron nuevos, se quedan.
            for _ in batch:
                self._buffer.popleft()
        return True

    def close(self) -> None:
        self._client.close()
