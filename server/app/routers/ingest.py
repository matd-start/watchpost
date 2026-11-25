"""Ingesta de métricas."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from ..config import get_settings
from ..db import SessionDep
from ..schemas import IngestRequest, IngestResponse
from ..services import metrics

router = APIRouter(prefix="/api/v1", tags=["ingesta"])


def require_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    """RNF-04: sin la clave correcta no se escribe nada."""
    if x_api_key != get_settings().api_key:
        raise HTTPException(
            status_code=401,
            detail="Falta la cabecera X-API-Key o la clave no es válida",
        )


@router.post(
    "/ingest",
    status_code=202,
    response_model=IngestResponse,
    dependencies=[Depends(require_api_key)],
)
def ingest(payload: IngestRequest, session: SessionDep) -> IngestResponse:
    try:
        accepted = metrics.ingest(session, payload)
    except metrics.FutureTimestampError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return IngestResponse(host=payload.host, accepted=accepted)
