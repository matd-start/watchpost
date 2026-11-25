# Watchpost

Mini Datadog autohospedado en Python. Un agente mide CPU, memoria y disco de una
máquina, los envía por HTTP a una API, y un dashboard muestra el estado.

**Estado: v0.1.0 — esqueleto que camina.** El recorrido completo funciona
(agente → API → SQLite → dashboard). Las gráficas históricas, las reglas de
alerta y Docker llegan en las fases siguientes.

## Qué hace hoy

- El agente lee `cpu.percent`, `mem.percent` y `disk.percent` cada 10 segundos con `psutil`.
- Envía los puntos a `POST /api/v1/ingest` con una API key en la cabecera `X-API-Key`.
- Si el servidor no responde, guarda hasta 500 puntos en memoria y los reenvía en el ciclo siguiente.
- El servidor registra los hosts nuevos solos y guarda los puntos en SQLite.
- El dashboard muestra cada host, su estado (en línea / desconectado) y el último valor de cada métrica.

## Requisitos

Python 3.12 o superior (probado con 3.13) y Git.

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

## Limitaciones conocidas

- Las lecturas de la API no piden clave.
- No hay gráficas históricas todavía (fase 3) ni agregación por rangos.
- Si un host deja de reportar mientras tiene una alerta activa, esa alerta no se
  resuelve sola (fase 4).
- Solo probado en Windows 11; `psutil` es multiplataforma, falta la prueba en Linux.

## Hoja de ruta

- **v0.2** Histórico de métricas y gráficas por rango, con downsampling por cubos.
- **v0.3** Reglas de alerta, worker evaluador y notificación a Discord.
- **v0.4** Retención, Docker Compose y CI en GitHub Actions.
- **v1.0** README de portafolio, diagrama, GIF y release.
