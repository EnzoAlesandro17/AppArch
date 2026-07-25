"""Pestaña de generación de backups: listas de paquetes + copia de configuraciones."""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from apparch.db import Database

RESTORE_SCRIPT_TEMPLATE = """#!/usr/bin/env bash
# Script de restauración generado por AppArch el {timestamp}
# Revisá el contenido antes de ejecutarlo.
set -euo pipefail

echo "== Instalando paquetes oficiales =="
sudo pacman -S --needed - < pkglist-official.txt

if [ -s pkglist-aur.txt ]; then
    echo "== Instalando paquetes AUR (requiere un helper como yay/paru) =="
    if command -v yay >/dev/null 2>&1; then
        yay -S --needed - < pkglist-aur.txt
    elif command -v paru >/dev/null 2>&1; then
        paru -S --needed - < pkglist-aur.txt
    else
        echo "No se encontró yay ni paru. Instalá los paquetes de pkglist-aur.txt manualmente."
    fi
fi

if [ -s pkglist-flatpak.txt ]; then
    echo "== Instalando apps Flatpak (asume el remoto Flathub) =="
    if command -v flatpak >/dev/null 2>&1; then
        xargs -a pkglist-flatpak.txt -n1 flatpak install -y flathub
    else
        echo "No se encontró flatpak. Instalá los IDs de pkglist-flatpak.txt manualmente."
    fi
fi

echo "== Las configuraciones respaldadas están en la carpeta 'configs/' =="
echo "Copialas manualmente a su ubicación original (revisá las rutas antes de sobrescribir)."
"""


class BackupTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, db: Database):
        super().__init__(parent, padding=10)
        self.db = db
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="Genera una carpeta de backup con las listas de paquetes instalados\n"
                 "y una copia de las configuraciones rastreadas.",
            justify="left",
        ).pack(anchor="w")

        dest_row = ttk.Frame(self)
        dest_row.pack(fill="x", pady=(10, 0))
        ttk.Label(dest_row, text="Destino:").pack(side="left")
        default_dest = str(Path.home() / "apparch-backups")
        self.dest_var = tk.StringVar(value=default_dest)
        ttk.Entry(dest_row, textvariable=self.dest_var).pack(
            side="left", fill="x", expand=True, padx=(6, 6)
        )
        ttk.Button(dest_row, text="Elegir...", command=self._choose_dest).pack(side="left")

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", pady=(10, 0))
        self.run_btn = ttk.Button(btn_row, text="Generar backup", command=self._start_backup)
        self.run_btn.pack(side="left")
        self.open_btn = ttk.Button(
            btn_row, text="Abrir última carpeta", command=self._open_last, state="disabled"
        )
        self.open_btn.pack(side="left", padx=(6, 0))

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 4))

        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._last_backup_dir: Path | None = None

    def _choose_dest(self) -> None:
        path = filedialog.askdirectory(title="Carpeta base para los backups")
        if path:
            self.dest_var.set(path)

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start_backup(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        base_dest = Path(self.dest_var.get()).expanduser()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = base_dest / f"backup-{timestamp}"

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        self.run_btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.progress.start(12)

        packages = self.db.list_packages()
        configs = self.db.list_configs()

        self._worker = threading.Thread(
            target=self._run_backup, args=(backup_dir, packages, configs), daemon=True
        )
        self._worker.start()
        self.after(100, self._poll_queue)

    def _run_backup(self, backup_dir: Path, packages, configs) -> None:
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            self._queue.put(f"Carpeta de backup: {backup_dir}")

            official = sorted(p["name"] for p in packages if p["status"] == "installed" and p["source"] == "official")
            aur = sorted(p["name"] for p in packages if p["status"] == "installed" and p["source"] == "aur")
            flatpak_apps = sorted(p["name"] for p in packages if p["status"] == "installed" and p["source"] == "flatpak")

            (backup_dir / "pkglist-official.txt").write_text("\n".join(official) + ("\n" if official else ""))
            self._queue.put(f"Guardado pkglist-official.txt ({len(official)} paquetes)")

            (backup_dir / "pkglist-aur.txt").write_text("\n".join(aur) + ("\n" if aur else ""))
            self._queue.put(f"Guardado pkglist-aur.txt ({len(aur)} paquetes)")

            (backup_dir / "pkglist-flatpak.txt").write_text(
                "\n".join(flatpak_apps) + ("\n" if flatpak_apps else "")
            )
            self._queue.put(f"Guardado pkglist-flatpak.txt ({len(flatpak_apps)} apps)")

            configs_dir = backup_dir / "configs"
            configs_dir.mkdir(exist_ok=True)
            copied = skipped = 0
            for row in configs:
                src = Path(row["path"]).expanduser()
                if not src.exists():
                    self._queue.put(f"  [omitido] no existe: {src}")
                    skipped += 1
                    continue
                dest = configs_dir / str(src).lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if src.is_dir():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dest)
                    self._queue.put(f"  [ok] {src}")
                    copied += 1
                except (OSError, shutil.Error) as exc:
                    self._queue.put(f"  [error] {src}: {exc}")
                    skipped += 1

            self._queue.put(f"Configuraciones copiadas: {copied}, omitidas: {skipped}")

            script_path = backup_dir / "restore.sh"
            script_path.write_text(
                RESTORE_SCRIPT_TEMPLATE.format(timestamp=datetime.now().isoformat(timespec="seconds"))
            )
            script_path.chmod(0o755)
            self._queue.put("Generado restore.sh")

            self._queue.put(f"__DONE__{backup_dir}")
        except Exception as exc:  # noqa: BLE001 - se reporta al usuario, no se puede prever cada fallo de IO
            self._queue.put(f"__ERROR__{exc}")

    def _poll_queue(self) -> None:
        try:
            while True:
                message = self._queue.get_nowait()
                if message.startswith("__DONE__"):
                    backup_dir = Path(message[len("__DONE__"):])
                    self._last_backup_dir = backup_dir
                    self._finish(success=True, backup_dir=backup_dir)
                    return
                if message.startswith("__ERROR__"):
                    self._finish(success=False, error=message[len("__ERROR__"):])
                    return
                self._log(message)
        except queue.Empty:
            pass

        if self._worker and self._worker.is_alive():
            self.after(100, self._poll_queue)

    def _finish(self, success: bool, backup_dir: Path | None = None, error: str | None = None) -> None:
        self.progress.stop()
        self.run_btn.config(state="normal")
        if success:
            self._log("Backup completado.")
            self.open_btn.config(state="normal")
            messagebox.showinfo("Backup completo", f"Backup generado en:\n{backup_dir}")
        else:
            self._log(f"Error: {error}")
            messagebox.showerror("Error en el backup", str(error))

    def _open_last(self) -> None:
        if not self._last_backup_dir:
            return
        try:
            subprocess.run(["xdg-open", str(self._last_backup_dir)], check=False)
        except FileNotFoundError:
            messagebox.showinfo("Ruta del backup", str(self._last_backup_dir))
