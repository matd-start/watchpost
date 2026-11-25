"""Lectura de métricas del sistema.

Este módulo solo mide: no envía, no guarda, no decide. Una sola razón para cambiar.
"""

import os
import platform

import psutil


def system_name() -> str:
    return f"{platform.system()} {platform.release()}"


def default_disk_path() -> str:
    """La raíz del sistema: `C:\\` en Windows, `/` en Linux."""
    return os.path.abspath(os.sep)


def collect(disk_path: str | None = None) -> dict[str, float]:
    """Devuelve una muestra de cada métrica de porcentaje.

    `cpu_percent(interval=None)` compara con la llamada anterior, así que la
    primera lectura devuelve 0.0: el bucle principal lo calienta al arrancar.
    """
    path = disk_path or default_disk_path()
    return {
        "cpu.percent": psutil.cpu_percent(interval=None),
        "mem.percent": psutil.virtual_memory().percent,
        "disk.percent": psutil.disk_usage(path).percent,
    }
