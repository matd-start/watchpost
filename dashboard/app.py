"""Dashboard mínimo de Watchpost.

Consulta la API, nunca la base de datos: la API es la única dueña de los datos.
"""

import os
from datetime import UTC, datetime, timedelta

import altair as alt
import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("WATCHPOST_SERVER_URL", "http://127.0.0.1:8000")
TIMEOUT = 5.0
LABELS = {
    "cpu.percent": "CPU",
    "mem.percent": "Memoria",
    "disk.percent": "Disco",
}
# Los botones solo calculan `from` y `to`: el tamaño de cubo lo decide el servidor.
RANGES = {
    "15 min": timedelta(minutes=15),
    "1 h": timedelta(hours=1),
    "24 h": timedelta(days=1),
    "7 d": timedelta(days=7),
}
STEP_LABELS = {10: "10 s", 60: "1 min", 300: "5 min", 3600: "1 h"}
LOCAL_TZ = datetime.now().astimezone().tzinfo

st.set_page_config(page_title="Watchpost", page_icon="🛰️", layout="wide")


def get_json(path: str, params: dict[str, str] | None = None):
    response = httpx.get(f"{API_URL}{path}", params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=5)
def get_hosts() -> list[dict]:
    """Cacheado unos segundos: el dashboard y el fragmento piden lo mismo."""
    return get_json("/api/v1/hosts")


@st.cache_data(ttl=5)
def get_series(host: str, metric: str, start: str, end: str) -> dict:
    """Streamlit reejecuta el script en cada clic; sin caché sería una petición por widget."""
    params = {"metric": metric, "from": start, "to": end}
    return get_json(f"/api/v1/hosts/{host}/metrics", params)


@st.fragment(run_every="5s")
def render_hosts() -> None:
    try:
        hosts = get_hosts()
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


def render_history(hosts: list[dict]) -> None:
    """Línea de medias con banda mínimo–máximo, agregada por el servidor."""
    st.divider()
    st.subheader("Histórico")
    if not hosts:
        return

    names = [host["name"] for host in hosts]
    col_host, col_metric, col_range = st.columns([2, 2, 4])
    host_name = col_host.selectbox("Host", names)
    metric = col_metric.selectbox("Métrica", list(LABELS), format_func=LABELS.get)
    range_label = col_range.radio("Rango", list(RANGES), horizontal=True)

    end = datetime.now(UTC)
    start = end - RANGES[range_label]
    try:
        data = get_series(host_name, metric, start.isoformat(), end.isoformat())
    except httpx.HTTPError as exc:
        st.error(f"No puedo leer el histórico: {exc}")
        return

    if not data["points"]:
        st.info("Sin datos en este rango. Si acabas de arrancar el agente, espera unas muestras.")
        return

    frame = pd.DataFrame(data["points"])
    frame["bucket_start"] = (
        pd.to_datetime(frame["bucket_start"], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    )
    # Un cubo con muchas menos muestras que la mediana está incompleto (suele ser el último:
    # la ventana termina a mitad de cubo). Dibujarlo tal cual inventa una caída al final.
    frame["complete"] = frame["count"] >= frame["count"].median() * 0.9
    complete = frame[frame["complete"]]

    step = STEP_LABELS.get(data["step_seconds"], f"{data['step_seconds']} s")
    x = alt.X("bucket_start:T", title=None)
    tooltip = [
        alt.Tooltip("bucket_start:T", title="Cubo"),
        alt.Tooltip("avg:Q", title="Media", format=".1f"),
        alt.Tooltip("min:Q", title="Mínimo", format=".1f"),
        alt.Tooltip("max:Q", title="Máximo", format=".1f"),
        alt.Tooltip("count:Q", title="Muestras"),
    ]
    band = (
        alt.Chart(complete)
        .mark_area(opacity=0.18)
        .encode(x=x, y=alt.Y("min:Q", title="%", scale=alt.Scale(domain=[0, 100])), y2="max:Q")
    )
    line = alt.Chart(complete).mark_line(strokeWidth=2).encode(x=x, y="avg:Q", tooltip=tooltip)
    partial = (
        alt.Chart(frame[~frame["complete"]])
        .mark_point(size=70, filled=False, strokeWidth=2)
        .encode(x=x, y="avg:Q", tooltip=tooltip)
    )

    chart = (band + line + partial).properties(
        title=f"{LABELS[metric]} de {host_name} · cubos de {step}",
        height=320,
    )
    st.altair_chart(chart, width="stretch")

    notes = [f"Horas en tu zona local ({LOCAL_TZ})."]
    if not frame["complete"].all():
        notes.append("Los puntos huecos tienen pocas muestras y quedan fuera de la línea.")
    st.caption(" ".join(notes))


st.title("Watchpost")
render_hosts()
try:
    _hosts = get_hosts()
except httpx.HTTPError:
    _hosts = []
render_history(_hosts)
