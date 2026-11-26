"""Worker de alertas: el `while` que el evaluador no es.

Se arranca aparte de la API, como el agente: `python -m server.worker`.
Evalúa las reglas cada `WATCHPOST_ALERT_INTERVAL_SECONDS` y solo habla cuando
hay una transición (firing o resuelta).
"""

import logging
import time
from datetime import datetime

from sqlmodel import Session

from .app.config import get_settings
from .app.db import engine, init_db
from .app.services.alerts import Rule, Transition, evaluate, load_rules
from .app.services.notifier import format_message, send_discord

logger = logging.getLogger("watchpost.worker")


def notify(transitions: list[Transition], webhook_url: str) -> None:
    for transition in transitions:
        text = format_message(transition)
        logger.info(text)
        if not webhook_url:
            logger.warning("Sin WATCHPOST_DISCORD_WEBHOOK_URL: la alerta solo queda en el log")
            continue
        try:
            send_discord(webhook_url, text)
        except Exception:  # noqa: BLE001
            # Discord caído no puede tumbar el worker: el estado ya está guardado,
            # así que la próxima transición seguirá funcionando.
            logger.exception("No pude enviar la alerta a Discord")


def run_once(
    session: Session,
    rules: list[Rule],
    webhook_url: str,
    now: datetime | None = None,
) -> list[Transition]:
    """Una pasada: evaluar y avisar. Es lo que el worker repite cada 30 s."""
    transitions = evaluate(session, rules, now)
    notify(transitions, webhook_url)
    return transitions


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    init_db()
    rules = load_rules(settings.rules_path)
    logger.info(
        "%s reglas desde %s, evaluación cada %ss",
        len(rules),
        settings.rules_path,
        settings.alert_interval_seconds,
    )
    if not settings.discord_webhook_url:
        logger.warning("Falta WATCHPOST_DISCORD_WEBHOOK_URL: las alertas solo se registrarán")

    try:
        while True:
            with Session(engine) as session:
                try:
                    run_once(session, rules, settings.discord_webhook_url)
                except Exception:  # noqa: BLE001
                    logger.exception("Falló una evaluación de alertas")
            time.sleep(settings.alert_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Worker detenido")


if __name__ == "__main__":
    main()
