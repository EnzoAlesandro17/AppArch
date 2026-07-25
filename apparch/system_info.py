"""Utilidades para consultar estado del sistema: servicios systemd habilitados,
grupos del usuario y redes guardadas (vía NetworkManager). Esto complementa el
registro de paquetes con las cosas que no son "una app instalada" pero que
igual hay que reconfigurar a mano después de una reinstalación limpia."""

from __future__ import annotations

import shutil
import subprocess


class SystemInfoError(RuntimeError):
    """Se lanza cuando falla una consulta de estado del sistema."""


def get_enabled_services(scope: str) -> dict[str, str]:
    """Servicios systemd habilitados. scope: 'system' o 'user'.

    Devuelve {nombre_unidad: estado} (p. ej. {'bluetooth.service': 'enabled'}).
    """
    cmd = ["systemctl"]
    if scope == "user":
        cmd.append("--user")
    cmd += [
        "list-unit-files", "--type=service", "--state=enabled",
        "--no-legend", "--no-pager", "--plain",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError as exc:
        raise SystemInfoError("No se encontró el comando 'systemctl'.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemInfoError(f"La consulta a systemctl ({scope}) superó el tiempo de espera.") from exc

    if result.returncode != 0:
        raise SystemInfoError(f"systemctl ({scope}) devolvió un error: {result.stderr.strip()}")

    services: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            services[parts[0]] = parts[1]
    return services


def get_user_groups() -> list[str]:
    """Grupos a los que pertenece el usuario actual (p. ej. docker, wheel)."""
    try:
        result = subprocess.run(["id", "-nG"], capture_output=True, text=True, timeout=10, check=False)
    except FileNotFoundError as exc:
        raise SystemInfoError("No se encontró el comando 'id'.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemInfoError("La consulta de grupos superó el tiempo de espera.") from exc

    if result.returncode != 0:
        raise SystemInfoError(f"'id' devolvió un error: {result.stderr.strip()}")

    return result.stdout.split()


def get_saved_wifi_networks() -> list[str]:
    """Nombres de perfiles de conexión WiFi guardados, vía NetworkManager.

    Solo devuelve los nombres (SSID/perfil), nunca las contraseñas: los
    archivos reales de NetworkManager solo son legibles por root, así que
    esto es puramente informativo (qué redes tenías, no cómo conectarte).
    Si nmcli no está instalado, devuelve una lista vacía en silencio.
    """
    if not shutil.which("nmcli"):
        return []
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired as exc:
        raise SystemInfoError("La consulta a nmcli superó el tiempo de espera.") from exc

    if result.returncode != 0:
        raise SystemInfoError(f"nmcli devolvió un error: {result.stderr.strip()}")

    networks = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, _, conn_type = line.rpartition(":")
        if conn_type == "802-11-wireless" and name:
            networks.append(name)
    return networks
