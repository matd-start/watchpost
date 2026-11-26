"""Reglas de alerta: ventana sostenida, histéresis y máquina de estados.

El evaluador es una función pura de (datos, reglas, estado): recibe `now` y no
duerme ni envía nada. Así se prueba en milisegundos lo que en producción tarda
minutos, y el worker queda reducido a un `while` con `sleep`.

La alerta se calcula sobre los puntos crudos de la ventana, nunca sobre un cubo:
una media de 5 minutos puede esconder 40 segundos al 100 %.
"""

import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import func
from sqlmodel import Session, select

from ..models import AlertState, Host, MetricPoint, utcnow
from ..schemas import METRICS, MetricName
from .metrics import to_utc

Operator = Literal[">", "<"]
State = Literal["ok", "firing"]


class RuleConfigError(ValueError):
    """`rules.toml` tiene una regla que no se puede evaluar."""


@dataclass(frozen=True)
class Rule:
    """Una condición que, sostenida `for_seconds`, genera una alerta."""

    name: str
    metric: MetricName
    operator: Operator
    threshold: float
    for_seconds: int
    recover: float | None = None
    host: str | None = None


@dataclass(frozen=True)
class Transition:
    """Un cambio de estado. Es lo único que merece un mensaje."""

    rule: Rule
    host: str
    state: State
    value: float
    since: datetime


def _build_rule(raw: dict, seen: set[str]) -> Rule:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise RuleConfigError("Cada regla necesita un nombre")
    if name in seen:
        raise RuleConfigError(f"Regla duplicada: {name}")

    metric = raw.get("metric")
    if metric not in METRICS:
        raise RuleConfigError(f"{name}: métrica desconocida {metric!r} (válidas: {METRICS})")

    operator = raw.get("operator")
    if operator not in (">", "<"):
        raise RuleConfigError(f"{name}: `operator` debe ser \">\" o \"<\"")

    try:
        threshold = float(raw["threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuleConfigError(f"{name}: `threshold` debe ser un número") from exc

    recover = raw.get("recover")
    recover = float(recover) if recover is not None else None
    if recover is not None:
        wrong_side = recover >= threshold if operator == ">" else recover <= threshold
        if wrong_side:
            raise RuleConfigError(
                f"{name}: `recover` debe quedar del lado contrario al umbral "
                f"({operator} {threshold}), o la histéresis no existe"
            )

    try:
        for_seconds = int(raw.get("for_seconds", 120))
    except (TypeError, ValueError) as exc:
        raise RuleConfigError(f"{name}: `for_seconds` debe ser un entero") from exc
    if for_seconds <= 0:
        raise RuleConfigError(f"{name}: `for_seconds` debe ser positivo")

    host = raw.get("host")
    return Rule(
        name=name,
        metric=metric,
        operator=operator,
        threshold=threshold,
        recover=recover,
        for_seconds=for_seconds,
        host=str(host) if host else None,
    )


def load_rules(path: str | Path) -> list[Rule]:
    """Lee `rules.toml`. Falla al arrancar, no a mitad de una alerta."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuleConfigError(f"No puedo leer {path}: {exc}") from exc

    rules: list[Rule] = []
    seen: set[str] = set()
    for raw in data.get("rule", []):
        rule = _build_rule(raw, seen)
        rules.append(rule)
        seen.add(rule.name)
    return rules


def _target_hosts(session: Session, rule: Rule) -> list[Host]:
    statement = select(Host)
    if rule.host:
        statement = statement.where(Host.name == rule.host)
    return list(session.exec(statement).all())


def _window(session: Session, host: Host, rule: Rule, start: datetime, end: datetime):
    """Una consulta por regla y host: cuántas muestras, el mínimo y el máximo."""
    return session.execute(
        select(
            func.count(MetricPoint.id),
            func.min(MetricPoint.value),
            func.max(MetricPoint.value),
        ).where(
            MetricPoint.host_id == host.id,
            MetricPoint.metric == rule.metric,
            MetricPoint.ts >= start,
            MetricPoint.ts <= end,
        )
    ).one()


def _history_start(session: Session, host: Host, rule: Rule) -> datetime | None:
    """Primera muestra de (host, métrica): dice si la ventana está cubierta."""
    return session.exec(
        select(func.min(MetricPoint.ts)).where(
            MetricPoint.host_id == host.id,
            MetricPoint.metric == rule.metric,
        )
    ).one()


def _state_of(session: Session, rule: Rule, host: Host) -> AlertState | None:
    return session.exec(
        select(AlertState).where(AlertState.rule_name == rule.name, AlertState.host_id == host.id)
    ).first()


def _evaluate_one(session: Session, rule: Rule, host: Host, now: datetime) -> Transition | None:
    start = now - timedelta(seconds=rule.for_seconds)
    count, lowest, highest = _window(session, host, rule, start, now)
    if count == 0:
        # Sin datos no se puede juzgar. La alerta activa se queda como está:
        # el "host sin reportar" es otra regla (v1.1).
        return None

    # La ventana solo vale si hay historial anterior a su inicio: si el host
    # empezó a reportar hace 50 s, no se puede afirmar nada de 120 s.
    first_sample = _history_start(session, host, rule)
    covered = first_sample is not None and to_utc(first_sample) <= start
    recover = rule.recover if rule.recover is not None else rule.threshold

    if rule.operator == ">":
        breaching, recovered = lowest > rule.threshold, highest < recover
        trigger_value, recover_value = lowest, highest
    else:
        breaching, recovered = highest < rule.threshold, lowest > recover
        trigger_value, recover_value = highest, lowest

    current: State = "ok"
    state = _state_of(session, rule, host)
    if state is not None:
        current = state.state  # type: ignore[assignment]

    if current == "ok" and covered and breaching:
        new_state, value = "firing", trigger_value
    elif current == "firing" and recovered:
        new_state, value = "ok", recover_value
    else:
        return None

    if state is None:
        state = AlertState(rule_name=rule.name, host_id=host.id)
        session.add(state)
    state.state = new_state
    state.since = now
    state.last_notified_at = now

    return Transition(
        rule=rule,
        host=host.name,
        state=new_state,
        value=round(float(value), 2),
        since=now,
    )


def evaluate(session: Session, rules: list[Rule], now: datetime | None = None) -> list[Transition]:
    """Evalúa todas las reglas y devuelve solo las transiciones (0, 1 o varias)."""
    moment = to_utc(now or utcnow())
    transitions = [
        transition
        for rule in rules
        for host in _target_hosts(session, rule)
        if (transition := _evaluate_one(session, rule, host, moment)) is not None
    ]
    session.commit()
    return transitions
