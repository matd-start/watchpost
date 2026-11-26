"""Consulta de hosts."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from ..db import SessionDep
from ..schemas import HostOut, LatestOut, MetricName, SeriesOut
from ..services import metrics

router = APIRouter(prefix="/api/v1/hosts", tags=["hosts"])


@router.get("", response_model=list[HostOut])
def list_hosts(session: SessionDep) -> list[HostOut]:
    return metrics.list_hosts(session)


@router.get("/{host_name}/latest", response_model=LatestOut)
def latest(host_name: str, session: SessionDep) -> LatestOut:
    try:
        values = metrics.latest_values(session, host_name)
    except metrics.HostNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No existe el host {host_name}") from exc
    return LatestOut(host=host_name, values=values)


@router.get("/{host_name}/metrics", response_model=SeriesOut)
def metric_series(
    host_name: str,
    session: SessionDep,
    metric: MetricName,
    from_: Annotated[datetime, Query(alias="from", description="Inicio del rango (ISO 8601)")],
    to: Annotated[datetime, Query(description="Fin del rango, exclusivo (ISO 8601)")],
) -> SeriesOut:
    """Serie de una métrica en cubos. El tamaño del cubo lo decide el servidor."""
    try:
        return metrics.series(session, host_name, metric, from_, to)
    except metrics.HostNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No existe el host {host_name}") from exc
    except metrics.InvalidRangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
