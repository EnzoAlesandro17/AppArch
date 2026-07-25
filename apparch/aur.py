"""Utilidades para consultar actualizaciones de AUR vía un helper (yay o paru)."""

from __future__ import annotations

import re
import shutil
import subprocess

_UPDATE_LINE_RE = re.compile(r"^(?P<name>\S+)\s+(?P<old>\S+)\s+->\s+(?P<new>\S+)")


class AurHelperError(RuntimeError):
    """Se lanza cuando el helper de AUR falla al consultar actualizaciones."""


def find_helper() -> str | None:
    """Devuelve el primer helper de AUR disponible (yay o paru), o None."""
    for helper in ("yay", "paru"):
        if shutil.which(helper):
            return helper
    return None


def get_outdated_packages() -> dict[str, dict[str, str]]:
    """Paquetes AUR con actualización disponible (consulta la AUR RPC vía el helper).

    Si no hay yay ni paru instalados, devuelve un diccionario vacío en silencio
    (no todos los sistemas tienen un helper de AUR configurado).
    Devuelve {nombre: {"current": version_actual, "new": version_nueva}}.
    """
    helper = find_helper()
    if helper is None:
        return {}

    try:
        result = subprocess.run(
            [helper, "-Qua"], capture_output=True, text=True, timeout=60, check=False
        )
    except FileNotFoundError as exc:
        raise AurHelperError(f"No se encontró el comando '{helper}'.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AurHelperError(f"La consulta a {helper} superó el tiempo de espera.") from exc

    if result.returncode not in (0, 1):
        raise AurHelperError(f"{helper} devolvió un error: {result.stderr.strip()}")

    outdated: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        match = _UPDATE_LINE_RE.match(line.strip())
        if match:
            outdated[match.group("name")] = {
                "current": match.group("old"),
                "new": match.group("new"),
            }
    return outdated
