"""Utilidades para consultar el estado de paquetes instalados vía pacman."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime

LOG_PATH = "/var/log/pacman.log"

_LOG_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] \[ALPM\] (?P<action>installed|upgraded|reinstalled) (?P<name>\S+) "
)

_UPDATE_LINE_RE = re.compile(r"^(?P<name>\S+)\s+(?P<old>\S+)\s+->\s+(?P<new>\S+)")


class PacmanError(RuntimeError):
    """Se lanza cuando pacman no está disponible o falla una consulta."""


def is_available() -> bool:
    return shutil.which("pacman") is not None


def _run_query(args: list[str]) -> dict[str, str]:
    """Ejecuta un comando pacman -Q* y devuelve {nombre: version}."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=30, check=False
        )
    except FileNotFoundError as exc:
        raise PacmanError("No se encontró el comando 'pacman' en el sistema.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PacmanError("La consulta a pacman superó el tiempo de espera.") from exc

    # pacman -Qe / -Qm devuelven código 1 cuando la lista está vacía, sin ser un error real.
    if result.returncode not in (0, 1):
        raise PacmanError(f"pacman devolvió un error: {result.stderr.strip()}")

    packages: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            name, version = parts
            packages[name] = version
    return packages


def get_explicit_official_packages() -> dict[str, str]:
    """Paquetes instalados explícitamente que provienen de los repos oficiales."""
    explicit = _run_query(["pacman", "-Qe"])
    foreign = set(_run_query(["pacman", "-Qm"]).keys())
    return {name: v for name, v in explicit.items() if name not in foreign}


def get_foreign_packages() -> dict[str, str]:
    """Paquetes 'foráneos' (no están en los repos oficiales): típicamente AUR."""
    return _run_query(["pacman", "-Qm"])


def get_dependency_packages() -> dict[str, str]:
    """Paquetes oficiales instalados como dependencia de otra cosa, no a pedido.

    Es solo a modo informativo/didáctico: pacman los resuelve e instala solo
    a partir de los paquetes explícitos, así que no hace falta guardarlos
    para poder reinstalar (por eso no entran al backup). Se excluyen los
    foráneos (AUR) para no duplicarlos con esa categoría.
    """
    dependency = _run_query(["pacman", "-Qd"])
    foreign = set(_run_query(["pacman", "-Qm"]).keys())
    return {name: v for name, v in dependency.items() if name not in foreign}


def parse_install_history(log_path: str = LOG_PATH) -> dict[str, dict[str, str]]:
    """Extrae fecha de instalación y de última actualización de /var/log/pacman.log.

    Devuelve {nombre: {"installed": "YYYY-MM-DD HH:MM:SS", "updated": "..."}}.
    Si el log no cubre la instalación original de un paquete (por rotación de
    logs), "installed" queda como la fecha del evento más antiguo disponible,
    que es la mejor aproximación posible con los datos a mano.
    Si el log no existe o no se puede leer, devuelve un diccionario vacío.
    """
    history: dict[str, dict[str, str]] = {}
    try:
        with open(log_path, "r", errors="replace") as f:
            for line in f:
                match = _LOG_LINE_RE.match(line)
                if not match:
                    continue
                try:
                    dt = datetime.strptime(match.group("ts"), "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    continue
                iso = dt.strftime("%Y-%m-%d %H:%M:%S")
                name = match.group("name")
                if name not in history:
                    history[name] = {"installed": iso, "updated": iso}
                else:
                    history[name]["updated"] = iso
    except OSError:
        return {}
    return history


def get_outdated_packages() -> dict[str, dict[str, str]]:
    """Paquetes oficiales con actualización disponible según la última sync db local.

    Nota: refleja el estado de la última vez que se sincronizó la base de datos
    de pacman (p. ej. con 'pacman -Sy' o '-Syu'), no hace una consulta en vivo.
    Devuelve {nombre: {"current": version_actual, "new": version_nueva}}.
    """
    try:
        result = subprocess.run(
            ["pacman", "-Qu"], capture_output=True, text=True, timeout=30, check=False
        )
    except FileNotFoundError as exc:
        raise PacmanError("No se encontró el comando 'pacman' en el sistema.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PacmanError("La consulta a pacman superó el tiempo de espera.") from exc

    if result.returncode not in (0, 1):
        raise PacmanError(f"pacman devolvió un error: {result.stderr.strip()}")

    outdated: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        match = _UPDATE_LINE_RE.match(line.strip())
        if match:
            outdated[match.group("name")] = {
                "current": match.group("old"),
                "new": match.group("new"),
            }
    return outdated
