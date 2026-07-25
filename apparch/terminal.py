"""Lanza una terminal interactiva para ejecutar comandos que requieren
confirmación del usuario (contraseña de sudo, revisión de paquetes a
actualizar, etc.). AppArch nunca ejecuta actualizaciones del sistema en
silencio: siempre las delega a una terminal visible."""

from __future__ import annotations

import shlex
import shutil
import subprocess

_TERMINAL_BUILDERS = [
    ("konsole", lambda cmd: ["konsole", "-e", "bash", "-c", cmd]),
    ("gnome-terminal", lambda cmd: ["gnome-terminal", "--", "bash", "-c", cmd]),
    ("xfce4-terminal", lambda cmd: ["xfce4-terminal", "-e", f"bash -c {shlex.quote(cmd)}"]),
    ("alacritty", lambda cmd: ["alacritty", "-e", "bash", "-c", cmd]),
    ("kitty", lambda cmd: ["kitty", "bash", "-c", cmd]),
    ("x-terminal-emulator", lambda cmd: ["x-terminal-emulator", "-e", "bash", "-c", cmd]),
    ("xterm", lambda cmd: ["xterm", "-hold", "-e", "bash", "-c", cmd]),
]


def is_available() -> bool:
    return any(shutil.which(binary) for binary, _ in _TERMINAL_BUILDERS)


def run_in_terminal(shell_command: str) -> bool:
    """Abre una terminal y ejecuta shell_command de forma interactiva.

    La terminal queda abierta después de que el comando termina, para que se
    pueda revisar la salida. Devuelve False si no se encontró ninguna
    terminal conocida instalada.
    """
    full_command = f"{shell_command}; echo; read -p 'Presioná Enter para cerrar...'"
    for binary, build_args in _TERMINAL_BUILDERS:
        if not shutil.which(binary):
            continue
        try:
            subprocess.Popen(build_args(full_command))
            return True
        except OSError:
            continue
    return False
