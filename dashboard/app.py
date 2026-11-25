"""Dashboard mínimo de Vigía.

Consulta la API, nunca la base de datos: la API es la única dueña de los datos.
"""

import os

import httpx
import streamlit as st

API_URL = os.environ.get("VIGIA_SERVER_URL", "http://127.0.0.1:8000")
TIMEOUT = 5.0
LABELS = {
    "cpu.percent": "CPU",
    "mem.percent": "Memoria",
    "disk.percent": "Disco",
}

st.set_page_config(page_title="Vigía", page_icon="🛰️", layout="wide")


def get_json(path: str):
    response = httpx.get(f"{API_URL}{path}", timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.fragment(run_every="5s")
def render_hosts() -> None:
    try:
        hosts = get_json("/api/v1/hosts")
    except httpx.HTTPError as exc:
        st.error(f"No puedo hablar con la API en {API_URL}. ¿Está arrancada? ({exc})")
        return

    if not hosts:
        st.info("Todavía no hay hosts. Arranca el agente: `python -m agent.main`")
        return

    for host in hosts:
        online = host["status"] == "online"
        st.subheader(f"{host['name']} · {'🟢 en línea' if online else '🔴 desconectado'}")
        try:
            latest = get_json(f"/api/v1/hosts/{host['name']}/latest")
        except httpx.HTTPError as exc:
            st.warning(f"Sin datos de {host['name']}: {exc}")
            continue

        columns = st.columns(len(LABELS))
        for column, (metric, label) in zip(columns, LABELS.items(), strict=True):
            value = latest["values"].get(metric)
            column.metric(label, f"{value:.1f} %" if value is not None else "—")
        st.caption(f"Última vez visto: {host['last_seen_at']} (UTC)")


st.title("Vigía")
render_hosts()
