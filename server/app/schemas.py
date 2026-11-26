"""Formatos de entrada y salida de la API.

Los modelos de Pydantic son el contrato: lo que entra se valida aquí y no en la base de datos.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

METRICS = ("cpu.percent", "mem.percent", "disk.percent")

MetricName = Literal["cpu.percent", "mem.percent", "disk.percent"]


class PointIn(BaseModel):
    metric: MetricName
    value: float = Field(ge=0)
    ts: datetime | None = None

    @model_validator(mode="after")
    def check_percent_range(self) -> "PointIn":
        """RN-02: los porcentajes van de 0 a 100."""
        if self.metric.endswith(".percent") and self.value > 100:
            raise ValueError(f"{self.metric} debe estar entre 0 y 100, llegó {self.value}")
        return self


class IngestRequest(BaseModel):
    host: str = Field(min_length=1, max_length=100)
    os: str | None = Field(default=None, max_length=200)
    points: list[PointIn] = Field(min_length=1, max_length=500)


class IngestResponse(BaseModel):
    host: str
    accepted: int


class HostOut(BaseModel):
    name: str
    os: str | None
    status: Literal["online", "offline"]
    last_seen_at: datetime


class LatestOut(BaseModel):
    host: str
    values: dict[str, float]


class BucketOut(BaseModel):
    """Un cubo de agregación: no es un instante, es un intervalo resumido.

    `count` permite distinguir un cubo completo de uno parcial (el primero y el
    último de cualquier ventana suelen serlo).
    """

    bucket_start: datetime
    avg: float
    min: float
    max: float
    count: int


class SeriesOut(BaseModel):
    """Serie de tiempo ya reducida: como mucho unos cientos de cubos."""

    # `from` es palabra reservada en Python; en el JSON se sigue llamando "from".
    model_config = ConfigDict(populate_by_name=True)

    host: str
    metric: MetricName
    step_seconds: int
    from_: datetime = Field(alias="from")
    to: datetime
    points: list[BucketOut]
