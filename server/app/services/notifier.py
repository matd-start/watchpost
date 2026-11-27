"""Formato y envío de alertas.

Dos canales con la misma firma `(url, texto)`; el worker elige uno según
`WATCHPOST_ALERT_CHANNEL`. Añadir otro canal no toca el evaluador: solo se
registra en el diccionario `SENDERS` del worker.

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


def _plain(text: str) -> str:
    """Quita el énfasis de Markdown: ntfy lo mostraría con asteriscos literales."""
    return text.replace("**", "").replace("`", "")


def send_ntfy(topic_url: str, text: str, *, post: Callable = httpx.post) -> None:
    """Publica en un tema de ntfy: sin cuenta, sin token y con app opcional.

    El tema de ntfy.sh es público: cualquiera que lo conozca puede leer y publicar,
    así que se usa un nombre difícil de adivinar y se trata como un secreto. El
    título fijo evita que la app muestre la URL del tema en la pantalla de bloqueo.
    """
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": "Watchpost",
    }
    post(topic_url, content=_plain(text).encode(), headers=headers, timeout=5.0).raise_for_status()
