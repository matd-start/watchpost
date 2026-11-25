"""Tablas de la base de datos."""

from datetime import UTC, datetime

from sqlmodel import Field, Index, SQLModel


def utcnow() -> datetime:
    """UTC con zona: SQLModel la exige y la devuelve siempre en UTC."""
    return datetime.now(UTC)


class Host(SQLModel, table=True):
    __tablename__ = "hosts"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    os: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


class MetricPoint(SQLModel, table=True):
    __tablename__ = "metric_points"
    # El índice único también sirve para las consultas por (host, métrica, ts),
    # y de paso hace idempotente la ingesta: un punto repetido se ignora.
    __table_args__ = (
        Index("ux_metric_points_host_metric_ts", "host_id", "metric", "ts", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    host_id: int = Field(foreign_key="hosts.id", index=True)
    metric: str
    value: float
    ts: datetime = Field(default_factory=utcnow)
