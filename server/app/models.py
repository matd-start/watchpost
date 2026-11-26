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


class AlertState(SQLModel, table=True):
    """Estado por (regla, host): solo se notifica cuando cambia.

    `rule_name` es el nombre de la regla en `rules.toml`. Renombrar una regla
    empieza de cero, y eso está bien: es otra regla.
    """

    __tablename__ = "alert_states"
    __table_args__ = (Index("ux_alert_states_rule_host", "rule_name", "host_id", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    rule_name: str
    host_id: int = Field(foreign_key="hosts.id", index=True)
    state: str = "ok"  # "ok" | "firing"
    since: datetime = Field(default_factory=utcnow)
    last_notified_at: datetime | None = None
