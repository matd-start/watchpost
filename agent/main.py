"""Bucle principal del agente: mide, envía, espera.

Sin asyncio a propósito: un bucle bloqueante es más fácil de leer y de depurar.
"""

import logging
import time
from datetime import UTC, datetime

import psutil

from .collector import collect, system_name
from .config import AgentConfig
from .sender import Point, Sender

logger = logging.getLogger("watchpost.agent")


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(config: AgentConfig) -> None:
    psutil.cpu_percent(interval=None)  # primera lectura: solo calienta el contador
    sender = Sender(config.server_url, config.api_key, config.host, system_name())
    logger.info(
        "Agente %s -> %s cada %ss", config.host, config.server_url, config.interval_seconds
    )
    try:
        while True:
            ts = iso_now()
            sample = collect(config.disk_path)
            points = [Point(metric, value, ts) for metric, value in sample.items()]
            if not sender.send(points):
                logger.info(
                    "Reintento en %ss (%s puntos pendientes)",
                    config.interval_seconds,
                    sender.pending,
                )
            time.sleep(config.interval_seconds)
    except KeyboardInterrupt:
        logger.info("Agente detenido")
    finally:
        sender.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run(AgentConfig())


if __name__ == "__main__":
    main()
