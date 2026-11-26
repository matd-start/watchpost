"""Pruebas del evaluador de alertas, del mensaje y del worker.

Todo usa un `now` explícito: no hay `sleep`, así que una ventana de 5 minutos
se prueba en milisegundos.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from server import worker
from server.app.models import Host, MetricPoint
from server.app.services.alerts import (
    Rule,
    RuleConfigError,
    Transition,
    evaluate,
    load_rules,
)
from server.app.services.notifier import format_message, send_discord

BASE = datetime(2026, 1, 1, tzinfo=UTC)
WEBHOOK = "https://discord.test/webhook"


def make_rule(**overrides) -> Rule:
    data = {
        "name": "CPU alta",
        "metric": "cpu.percent",
        "operator": ">",
        "threshold": 85.0,
        "recover": 80.0,
        "for_seconds": 120,
    }
    data.update(overrides)
    return Rule(**data)


def seed_points(
    session: Session,
    values: list[float],
    *,
    start: datetime = BASE,
    metric: str = "cpu.percent",
    host_name: str = "laptop-01",
) -> Host:
    host = session.exec(select(Host).where(Host.name == host_name)).first()
    if host is None:
        host = Host(name=host_name)
        session.add(host)
        session.commit()
        session.refresh(host)
    for index, value in enumerate(values):
        session.add(
            MetricPoint(
                host_id=host.id,
                metric=metric,
                value=value,
                ts=start + timedelta(seconds=10 * index),
            )
        )
    session.commit()
    return host


def test_fires_when_the_whole_window_is_above_the_threshold(
    client: TestClient, session: Session
) -> None:
    now = BASE + timedelta(seconds=140)
    seed_points(session, [86.0] * 13)

    transitions = evaluate(session, [make_rule()], now)

    assert [transition.state for transition in transitions] == ["firing"]
    assert transitions[0].value == 86.0
    assert transitions[0].host == "laptop-01"


def test_a_single_spike_does_not_fire(client: TestClient, session: Session) -> None:
    """Un punto al 100 % entre valores normales no es un problema sostenido."""
    seed_points(session, [20.0] * 12 + [100.0])

    assert evaluate(session, [make_rule()], BASE + timedelta(seconds=140)) == []


def test_does_not_fire_before_the_window_is_covered(client: TestClient, session: Session) -> None:
    """La condición se cumple, pero solo hay 50 s de datos para una ventana de 120 s."""
    seed_points(session, [100.0] * 6, start=BASE + timedelta(seconds=90))

    assert evaluate(session, [make_rule()], BASE + timedelta(seconds=140)) == []


def test_evaluating_twice_notifies_once(client: TestClient, session: Session) -> None:
    seed_points(session, [86.0] * 20)

    first = evaluate(session, [make_rule()], BASE + timedelta(seconds=140))
    second = evaluate(session, [make_rule()], BASE + timedelta(seconds=150))

    assert len(first) == 1
    assert second == []


def test_hysteresis_keeps_the_alert_between_the_two_thresholds(
    client: TestClient, session: Session
) -> None:
    """82 % está por debajo del umbral pero por encima de `recover`: no hay mensaje."""
    seed_points(session, [86.0] * 13)
    assert evaluate(session, [make_rule()], BASE + timedelta(seconds=140))

    later = BASE + timedelta(seconds=400)
    seed_points(session, [82.0] * 13, start=later - timedelta(seconds=120))

    assert evaluate(session, [make_rule()], later) == []


def test_resolves_below_recover_and_only_once(client: TestClient, session: Session) -> None:
    seed_points(session, [86.0] * 13)
    evaluate(session, [make_rule()], BASE + timedelta(seconds=140))

    later = BASE + timedelta(seconds=400)
    seed_points(session, [78.0] * 13, start=later - timedelta(seconds=120))

    resolved = evaluate(session, [make_rule()], later)
    again = evaluate(session, [make_rule()], later + timedelta(seconds=10))

    assert [transition.state for transition in resolved] == ["ok"]
    assert resolved[0].value == 78.0
    assert again == []


def test_flapping_between_79_and_81_never_notifies(client: TestClient, session: Session) -> None:
    """El caso que rompe los sistemas de alerta ingenuos: 360 mensajes por hora."""
    seed_points(session, [79.0, 81.0] * 10)

    transitions = evaluate(session, [make_rule()], BASE + timedelta(seconds=210))

    assert transitions == []


def test_rule_can_target_a_single_host(client: TestClient, session: Session) -> None:
    seed_points(session, [90.0] * 13, host_name="laptop-01")
    seed_points(session, [90.0] * 13, host_name="servidor-02")

    transitions = evaluate(session, [make_rule(host="servidor-02")], BASE + timedelta(seconds=140))

    assert [transition.host for transition in transitions] == ["servidor-02"]


def test_load_rules_reads_toml(tmp_path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(
        '[[rule]]\n'
        'name = "CPU alta"\n'
        'metric = "cpu.percent"\n'
        'operator = ">"\n'
        "threshold = 90\n"
        "recover = 85\n"
        "for_seconds = 60\n",
        encoding="utf-8",
    )

    rules = load_rules(path)

    assert len(rules) == 1
    assert rules[0].threshold == 90
    assert rules[0].recover == 85
    assert rules[0].for_seconds == 60
    assert rules[0].host is None


def test_recover_on_the_wrong_side_is_rejected(tmp_path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(
        '[[rule]]\n'
        'name = "Mala"\n'
        'metric = "cpu.percent"\n'
        'operator = ">"\n'
        "threshold = 90\n"
        "recover = 95\n",
        encoding="utf-8",
    )

    with pytest.raises(RuleConfigError, match="histéresis"):
        load_rules(path)


def test_message_explains_itself() -> None:
    transition = Transition(
        rule=make_rule(), host="laptop-01", state="firing", value=89.4, since=BASE
    )

    text = format_message(transition)

    assert "laptop-01" in text
    assert "85" in text
    assert "2 min" in text
    assert "89.4" in text


def test_resolved_message_says_resuelta() -> None:
    transition = Transition(rule=make_rule(), host="laptop-01", state="ok", value=78.0, since=BASE)

    assert "resuelta" in format_message(transition)


def test_send_discord_posts_the_content() -> None:
    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, **kwargs) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse()

    send_discord(WEBHOOK, "hola", post=fake_post)

    assert calls == [(WEBHOOK, {"json": {"content": "hola"}, "timeout": 5.0})]


def test_worker_sends_only_on_transitions(
    client: TestClient, session: Session, monkeypatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(worker, "send_discord", lambda url, text: sent.append(text))
    seed_points(session, [86.0] * 20)

    worker.run_once(session, [make_rule()], WEBHOOK, BASE + timedelta(seconds=140))
    worker.run_once(session, [make_rule()], WEBHOOK, BASE + timedelta(seconds=150))

    assert len(sent) == 1
    assert "laptop-01" in sent[0]
