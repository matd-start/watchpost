"""Worker de alertas: el `while` que el evaluador no es.

Se arranca aparte de la API, como el agente: `python -m server.worker`.
Evalúa las reglas cada `WATCHPOST_ALERT_INTERVAL_SECONDS` y solo habla cuando
hay una transición (firing o resuelta).
"""

import logging
import time
from datetime import datetime

import httpx
from sqlmodel import Session

from .app.config import get_settings
from .app.db import engine, init_db
from .app.services.alerts import Rule, Transition, evaluate, load_rules
from .app.services.notifier import format_message, send_discord, send_ntfy

logger = logging.getLogger("watchpost.worker")

# Canales intercambiables: misma firma `(url, texto)`, distinto destino.
SENDERS = {"discord": send_discord, "ntfy": send_ntfy}


def notify(transitions: list[Transition], channel: str, url: str) -> None:
    if not url:
        for transition in transitions:
            logger.info(format_message(transition))
        logger.warning("Sin WATCHPOST_ALERT_URL: las alertas solo quedan en el log")
        return

    send = SENDERS[channel]
    for transition in transitions:
        text = format_message(transition)
        logger.info(text)
        try:
            send(url, text)
        except httpx.HTTPStatusError as exc:
            # El mensaje de httpx incluye la URL, que en ntfy es el secreto:
            # se registra el código, no la excepción completa.
            logger.error(
                "El canal %s respondió %s; la alerta no se envió",
                channel,
                exc.response.status_code,
            )
        except httpx.RequestError as exc:
            logger.error("No pude conectar con el canal %s (%s)", channel, type(exc).__name__)
        except Exception:  # noqa: BLE001
            # El canal caído no puede tumbar el worker: el estado ya está guardado,
            # así que la próxima transición seguirá funcionando.
            logger.exception("Fallo inesperado al enviar la alerta por %s", channel)


def run_once(
    session: Session,
    rules: list[Rule],
    channel: str,
    url: str,
    now: datetime | None = None,
) -> list[Transition]:
    """Una pasada: evaluar y avisar. Es lo que el worker repite cada 30 s."""
    transitions = evaluate(session, rules, now)
    notify(transitions, channel, url)
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
    if not settings.alert_url:
        logger.warning("Falta WATCHPOST_ALERT_URL: las alertas solo se registrarán")

    try:
        while True:
            with Session(engine) as session:
                try:
                    run_once(session, rules, settings.alert_channel, settings.alert_url)
                except Exception:  # noqa: BLE001
                    logger.exception("Falló una evaluación de alertas")
            time.sleep(settings.alert_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Worker detenido")


if __name__ == "__main__":
    main()
