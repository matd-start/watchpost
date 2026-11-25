"""Reglas de negocio de métricas: ingesta, consulta y estado del host.

Recibe una sesión de base de datos y devuelve datos. Los routers solo traducen
eso a HTTP; por eso este módulo se puede probar sin levantar el servidor.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..config import get_settings
from ..models import Host, MetricPoint, utcnow
from ..schemas import METRICS, HostOut, IngestRequest

MAX_FUTURE_SKEW = timedelta(minutes=5)


class FutureTimestampError(ValueError):
    """Un punto con fecha demasiado en el futuro: el reloj del host está desfasado (RN-03)."""


class HostNotFoundError(LookupError):
    """No hay ningún host con ese nombre."""


def to_utc(moment: datetime) -> datetime:
    """Normaliza a UTC. Si llega sin zona, se asume que ya está en UTC (RNF-09)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _check_timestamps(payload: IngestRequest, now: datetime) -> None:
    for point in payload.points:
        ts = to_utc(point.ts) if point.ts else now
        if ts - now > MAX_FUTURE_SKEW:
            raise FutureTimestampError(
                f"{point.metric} tiene fecha {ts.isoformat()}, más de 5 minutos en el futuro"
            )


def _get_or_create_host(session: Session, payload: IngestRequest, now: datetime) -> Host:
    """RF-06: un host desconocido se registra solo."""
    host = session.exec(select(Host).where(Host.name == payload.host)).first()
    if host is None:
        host = Host(name=payload.host, os=payload.os, last_seen_at=now)
        session.add(host)
        session.flush()  # hace falta el id para los puntos
        return host
    host.last_seen_at = now
    if payload.os:
        host.os = payload.os
    return host


def ingest(session: Session, payload: IngestRequest) -> int:
    """Guarda el lote y devuelve cuántos puntos se aceptaron."""
    now = utcnow()
    _check_timestamps(payload, now)
    host = _get_or_create_host(session, payload, now)

    rows = [
        {
            "host_id": host.id,
            "metric": point.metric,
            "value": point.value,
            "ts": to_utc(point.ts) if point.ts else now,
        }
        for point in payload.points
    ]
    # ON CONFLICT DO NOTHING: si el agente reintenta un lote que ya llegó,
    # no se duplican filas. Idempotencia a cambio de una línea.
    statement = (
        sqlite_insert(MetricPoint)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["host_id", "metric", "ts"])
    )
    session.execute(statement)
    session.commit()
    return len(rows)


def list_hosts(session: Session) -> list[HostOut]:
    """RF-09 y RN-04: el estado se calcula, no se guarda."""
    threshold = timedelta(seconds=get_settings().online_threshold_seconds)
    now = utcnow()
    hosts = session.exec(select(Host).order_by(Host.name)).all()
    return [
        HostOut(
            name=host.name,
            os=host.os,
            status="online" if now - host.last_seen_at <= threshold else "offline",
            last_seen_at=host.last_seen_at,
        )
        for host in hosts
    ]


def latest_values(session: Session, host_name: str) -> dict[str, float]:
    """Último valor de cada métrica. Cinco consultas pequeñas, servidas por el índice."""
    host = session.exec(select(Host).where(Host.name == host_name)).first()
    if host is None:
        raise HostNotFoundError(host_name)

    values: dict[str, float] = {}
    for metric in METRICS:
        point = session.exec(
            select(MetricPoint)
            .where(MetricPoint.host_id == host.id, MetricPoint.metric == metric)
            .order_by(MetricPoint.ts.desc())
            .limit(1)
        ).first()
        if point is not None:
            values[metric] = point.value
    return values
