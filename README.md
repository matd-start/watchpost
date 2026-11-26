# Watchpost

Mini Datadog autohospedado en Python. Un agente mide CPU, memoria y disco de una
máquina, los envía por HTTP a una API, y un dashboard muestra el estado.

**Estado: v0.2.0 — histórico con downsampling.** El recorrido completo funciona
(agente → API → SQLite → dashboard) y la gráfica histórica responde en milisegundos.
Las reglas de alerta y Docker llegan en las fases siguientes.

## Qué hace hoy

- El agente lee `cpu.percent`, `mem.percent` y `disk.percent` cada 10 segundos con `psutil`.
- Envía los puntos a `POST /api/v1/ingest` con una API key en la cabecera `X-API-Key`.
- Si el servidor no responde, guarda hasta 500 puntos en memoria y los reenvía en el ciclo siguiente.
- El servidor registra los hosts nuevos solos y guarda los puntos en SQLite.
- El dashboard muestra cada host, su estado (en línea / desconectado) y el último valor de cada métrica.
- La API devuelve el histórico agregado por cubos (`avg`, `min`, `max`, `count`) y el
  dashboard lo pinta con rangos de 15 min, 1 h, 24 h y 7 días.
- Un worker evalúa reglas de umbral sobre ventanas sostenidas y avisa a Discord
  (con histéresis, sin repetir el mensaje mientras el problema siga).

## Requisitos

Python 3.12 o superior (probado con 3.13 en Windows 11 y 3.12 en Ubuntu 22.04) y Git.

En Ubuntu 22.04 el Python del sistema es 3.10 y **no sirve**: falla con
`cannot import name 'UTC' from 'datetime'`. Sin privilegios de administrador:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv venv --python 3.12
uv pip install -r requirements-dev.txt
```

## Arranque rápido

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # y cambia WATCHPOST_API_KEY
```

Después, en tres terminales con el entorno activado:

```powershell
# 1. API
uvicorn server.app.main:app --reload

# 2. Dashboard  ->  http://localhost:8501
streamlit run dashboard/app.py

# 3. Agente
python -m agent.main
```

La documentación interactiva de la API está en `http://127.0.0.1:8000/docs`.

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| POST | `/api/v1/ingest` | Recibir un lote de métricas (requiere `X-API-Key`) |
| GET | `/api/v1/hosts` | Listar hosts y su estado |
| GET | `/api/v1/hosts/{host}/latest` | Último valor de cada métrica de un host |
| GET | `/api/v1/hosts/{host}/metrics` | Serie histórica por cubos entre `from` y `to` |
| GET | `/health` | Comprobar que la API está viva |

Ejemplo de ingesta:

```json
{
  "host": "laptop-01",
  "os": "Windows 11",
  "points": [
    {"metric": "cpu.percent", "value": 23.5},
    {"metric": "mem.percent", "value": 61.2}
  ]
}
```

## Alertas

Copia `rules.example.toml` a `rules.toml`, pon tu webhook en `.env` y arranca el worker
(en una cuarta terminal):

```powershell
copy rules.example.toml rules.toml
python -m server.worker
```

| Variable | Uso |
|---|---|
| `WATCHPOST_DISCORD_WEBHOOK_URL` | URL del webhook de Discord (si falta, solo se registra en el log) |
| `WATCHPOST_ALERT_INTERVAL_SECONDS` | Cada cuánto se evalúan las reglas (30 por defecto) |
| `WATCHPOST_RULES_PATH` | Ruta del fichero de reglas (`rules.toml` por defecto) |

Cada regla tiene un umbral (`threshold`), un umbral de salida (`recover`) y una
ventana (`for_seconds`). Se dispara solo si **toda** la ventana cruza el umbral, y se
resuelve solo si toda la ventana cruza `recover`: entre ambos hay una banda muerta
que evita los mensajes en hosts que oscilan. Además se notifica únicamente cuando
el estado cambia, así que un problema de 6 horas es un mensaje, no setecientos.

## Arquitectura

```
[agente] --POST /ingest--> [API FastAPI] --escribe--> [SQLite]
                                ^
                                | GET
                        [dashboard Streamlit]
```

- **Agente** (`agent/`): mide y envía. Sin asyncio: un bucle bloqueante se lee mejor.
- **API** (`server/app/`): routers finos, lógica en `services/`, datos en `models.py`.
- **Dashboard** (`dashboard/`): consulta la API, nunca la base de datos.

## Decisiones de diseño

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| SQLite con WAL | PostgreSQL | Cero configuración para el volumen previsto; migrar después es una mejora documentable |
| `INSERT ... ON CONFLICT DO NOTHING` | Insertar a ciegas | El agente reintenta lotes: sin esto, un reintento duplica filas |
| `deque(maxlen=500)` en el agente | Lista sin límite | Al llenarse descarta los puntos más viejos y el agente no se queda sin memoria |
| El estado del host se calcula | Columna `status` en la tabla | Un dato derivado guardado se queda obsoleto; se calcula con `last_seen_at` |
| Lecturas abiertas, escritura con API key | Todo autenticado | El dashboard es local; la ingesta es la superficie expuesta |
| Streamlit | React | Un solo lenguaje mientras se aprende |
| Sin asyncio en el agente | `asyncio` + `httpx.AsyncClient` | Un `while` con `sleep` es suficiente y se depura mejor |

## Pruebas

```powershell
pytest
ruff check .
```

Las pruebas de la API levantan una base de datos temporal y usan `TestClient`:
cubren ingesta válida, clave incorrecta, valor fuera de rango, fecha futura,
host nuevo, estado en línea/desconectado, idempotencia y consulta del último valor.
Las de la serie siembran fechas fijas y comprueban la agregación por cubos, el
borde exclusivo de `to`, los cubos parciales y los errores de rango.

## Limitaciones conocidas

- Las lecturas de la API no piden clave.
- Dos agentes con el mismo `hostname` (Windows y WSL2 en la misma máquina) escriben
  en el mismo host: el campo `os` oscila entre ambos y las series se mezclan.
- Si un host deja de reportar mientras tiene una alerta activa, esa alerta no se
  resuelve sola (fase 4).
- Probado en Windows 11 y en Ubuntu 22.04 (WSL2); el dashboard solo se ha abierto en local.

## Hoja de ruta

- **v0.2** Histórico de métricas y gráficas por rango, con downsampling por cubos. ✅
- **v0.3** Reglas de alerta, worker evaluador y notificación a Discord.
- **v0.4** Retención, Docker Compose y CI en GitHub Actions.
- **v1.0** README de portafolio, diagrama, GIF y release.
