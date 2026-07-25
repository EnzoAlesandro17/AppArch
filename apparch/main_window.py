"""Ventana principal de AppArch."""

from __future__ import annotations

import re
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk

from apparch.db import Database
from apparch.tabs.backup_tab import BackupTab
from apparch.tabs.configs_tab import ConfigsTab
from apparch.tabs.packages_tab import PackagesTab
from apparch.tabs.system_tab import SystemTab

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 600

_XRANDR_PRIMARY_RE = re.compile(r"connected primary (\d+)x(\d+)\+(\d+)\+(\d+)")


def _primary_monitor_geometry() -> tuple[int, int, int, int] | None:
    """Devuelve (ancho, alto, x, y) del monitor marcado como primario.

    Con más de un monitor, winfo_screenwidth()/height() de tkinter devuelve
    el escritorio virtual combinado, no un monitor individual: centrar con
    eso deja la ventana mal ubicada (o repartida entre pantallas). Se usa
    xrandr para encontrar el monitor primario real. Si no está disponible
    (p. ej. sesión Wayland), se vuelve al tamaño de pantalla combinado.
    """
    if not shutil.which("xrandr"):
        return None
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = _XRANDR_PRIMARY_RE.search(result.stdout)
    if not match:
        return None
    width, height, x, y = (int(v) for v in match.groups())
    return width, height, x, y


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AppArch — Registro de Arch Linux")
        self.minsize(800, 500)

        self.db = Database()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._apply_style()
        self._build_layout()

        # Se centra recién acá, después de armar todo el contenido: si se
        # hace antes, el packing de los widgets recalcula el tamaño natural
        # del contenido y pisa la geometría explícita que pedimos.
        self._center_window(WINDOW_WIDTH, WINDOW_HEIGHT)

    def _center_window(self, width: int, height: int) -> None:
        self.update_idletasks()
        monitor = _primary_monitor_geometry()
        if monitor:
            screen_width, screen_height, offset_x, offset_y = monitor
        else:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            offset_x = offset_y = 0
        x = offset_x + (screen_width - width) // 2
        y = offset_y + (screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_style(self) -> None:
        style = ttk.Style(self)
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")

    def _build_layout(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        packages_tab = PackagesTab(notebook, self.db)
        system_tab = SystemTab(notebook, self.db)
        configs_tab = ConfigsTab(notebook, self.db)
        backup_tab = BackupTab(notebook, self.db)

        notebook.add(packages_tab, text="Paquetes")
        notebook.add(system_tab, text="Sistema")
        notebook.add(configs_tab, text="Configuraciones")
        notebook.add(backup_tab, text="Backup")

    def _on_close(self) -> None:
        self.db.close()
        self.destroy()


def run() -> None:
    app = MainWindow()
    app.mainloop()
