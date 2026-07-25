"""Utilidades para consultar las apps instaladas vía Flatpak."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime

_RELEVANT_CHANGES = {"deploy install", "deploy update"}


class FlatpakError(RuntimeError):
    """Se lanza cuando flatpak no está disponible o falla una consulta."""


def is_available() -> bool:
    return shutil.which("flatpak") is not None


def _list(flag: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["flatpak", "list", flag, "--columns=application,version"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except FileNotFoundError as exc:
        raise FlatpakError("No se encontró el comando 'flatpak' en el sistema.") from exc
    except subprocess.TimeoutExpired as exc:
        raise FlatpakError("La consulta a flatpak superó el tiempo de espera.") from exc

    if result.returncode != 0:
        raise FlatpakError(f"flatpak devolvió un error: {result.stderr.strip()}")

    items: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        app_id = parts[0].strip()
        version = parts[1].strip() if len(parts) > 1 else ""
        if app_id:
            items[app_id] = version
    return items


def get_installed_apps() -> dict[str, str]:
    """Devuelve {application_id: version} de las apps flatpak instaladas (sin runtimes)."""
    return _list("--app")


def get_installed_runtimes() -> dict[str, str]:
    """Devuelve {runtime_id: version} de los runtimes compartidos instalados.

    Son las plataformas/bibliotecas base que las apps flatpak usan por
    debajo (p. ej. org.freedesktop.Platform, org.kde.Platform): no son apps
    en sí, pero ocupan espacio y también conviene tenerlas registradas.
    """
    return _list("--runtime")


def parse_history() -> dict[str, dict[str, str]]:
    """Extrae fecha de instalación y de última actualización de 'flatpak history'.

    Devuelve {application_id: {"installed": "YYYY-MM-DD HH:MM:SS", "updated": "..."}}.
    'flatpak history' tiene una ventana de retención limitada, así que para apps
    instaladas hace mucho tiempo puede faltar el evento original: en ese caso
    "installed" queda como el evento más antiguo disponible (mejor aproximación
    posible). Si el comando no existe o falla, devuelve un diccionario vacío.
    """
    if not is_available():
        return {}
    try:
        result = subprocess.run(
            ["flatpak", "history", "--columns=time,change,application", "-j"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    if result.returncode != 0:
        return {}

    try:
        events = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    now = datetime.now()
    history: dict[str, dict[str, str]] = {}
    for event in events:
        if event.get("change") not in _RELEVANT_CHANGES:
            continue
        app_id = event.get("application") or ""
        time_str = event.get("time") or ""
        if not app_id or not time_str:
            continue
        try:
            dt = datetime.strptime(f"{now.year} {time_str}", "%Y %b %d %H:%M:%S")
        except ValueError:
            continue
        if dt > now:
            dt = dt.replace(year=now.year - 1)
        iso = dt.strftime("%Y-%m-%d %H:%M:%S")
        if app_id not in history:
            history[app_id] = {"installed": iso, "updated": iso}
        else:
            history[app_id]["updated"] = iso
    return history


def get_outdated_apps() -> dict[str, dict[str, str]]:
    """Apps Y runtimes instalados con actualización disponible, revisando cada
    instalación (sistema/usuario) y cada remoto configurado en ellas.

    Devuelve {application_id: {"current": version_actual, "new": version_nueva}}.
    Si flatpak no está disponible, o falla la consulta de red, devuelve un
    diccionario vacío en silencio: no es una operación crítica del escaneo.
    """
    if not is_available():
        return {}

    installed = {**get_installed_apps(), **get_installed_runtimes()}
    outdated: dict[str, dict[str, str]] = {}

    for scope in ("--system", "--user"):
        try:
            remotes_result = subprocess.run(
                ["flatpak", "remotes", scope, "--columns=name"],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if remotes_result.returncode != 0:
            continue

        remotes = [line.strip() for line in remotes_result.stdout.splitlines() if line.strip()]
        for remote in remotes:
            try:
                result = subprocess.run(
                    ["flatpak", "remote-ls", "--updates", scope,
                     "--columns=application,version", remote],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                parts = line.strip().split("\t")
                if not parts or not parts[0]:
                    continue
                app_id = parts[0].strip()
                new_version = parts[1].strip() if len(parts) > 1 else ""
                if app_id in installed:
                    outdated[app_id] = {"current": installed[app_id], "new": new_version}

    return outdated
