"""Formato y envío de alertas a Discord.

El envío se recibe por parámetro (`post`) para que las pruebas no salgan a la red.
"""

from collections.abc import Callable

import httpx

from .alerts import Transition

LABELS = {
    "cpu.percent": "CPU",
    "mem.percent": "Memoria",
    "disk.percent": "Disco",
}


def format_message(transition: Transition) -> str:
    """Un mensaje que se entiende sin abrir el dashboard."""
    rule = transition.rule
    label = LABELS.get(rule.metric, rule.metric)
    if rule.for_seconds >= 60:
        duration = f"{rule.for_seconds // 60} min"
    else:
        duration = f"{rule.for_seconds} s"

    if transition.state == "firing":
        direction = "por encima de" if rule.operator == ">" else "por debajo de"
        return (
            f"🔴 **{rule.name}** en `{transition.host}`: "
            f"{label} {direction} {rule.threshold:g} % durante {duration} "
            f"(valor extremo {transition.value:g} %)"
        )
    return (
        f"🟢 **{rule.name}** resuelta en `{transition.host}` "
        f"(valor {transition.value:g} %)"
    )


def send_discord(webhook_url: str, text: str, *, post: Callable = httpx.post) -> None:
    """Publica el texto en el canal del webhook. Lanza si Discord no lo acepta."""
    post(webhook_url, json={"content": text}, timeout=5.0).raise_for_status()
