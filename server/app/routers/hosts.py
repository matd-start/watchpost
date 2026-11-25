"""Consulta de hosts."""

from fastapi import APIRouter, HTTPException

from ..db import SessionDep
from ..schemas import HostOut, LatestOut
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
