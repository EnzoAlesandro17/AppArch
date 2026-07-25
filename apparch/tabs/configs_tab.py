"""Pestaña de configuraciones a rastrear para el backup (dotfiles, /etc, etc.)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from apparch.db import Database

# Rutas típicas de Arch Linux que suele valer la pena respaldar.
SUGGESTED_PATHS = [
    ("/etc/pacman.conf", "Configuración de pacman"),
    ("/etc/pacman.d/mirrorlist", "Lista de mirrors de pacman"),
    ("~/.config", "Configuraciones de aplicaciones (XDG_CONFIG_HOME)"),
    ("~/.bashrc", "Configuración de bash"),
    ("~/.zshrc", "Configuración de zsh"),
    ("~/.profile", "Variables de entorno de sesión"),
    ("~/.ssh/config", "Configuración de cliente SSH"),
    ("~/.gitconfig", "Configuración global de git"),
    ("/etc/fstab", "Tabla de sistemas de archivos"),
    ("/etc/hosts", "Resolución de hosts local"),
    ("/etc/environment", "Variables de entorno globales"),
]


class ConfigsTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, db: Database):
        super().__init__(parent, padding=10)
        self.db = db
        self._rows_by_iid: dict[str, int] = {}

        self._build_toolbar()
        self._build_table()

        self.refresh_table()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))

        ttk.Button(bar, text="Agregar archivo...", command=self.add_file).pack(side="left")
        ttk.Button(bar, text="Agregar carpeta...", command=self.add_folder).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(bar, text="Sugerencias...", command=self.show_suggestions).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(bar, text="Eliminar", command=self.remove_selected).pack(
            side="left", padx=(6, 0)
        )

    def _build_table(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        columns = ("path", "description", "added")
        self.tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")
        headings = {"path": "Ruta", "description": "Descripción", "added": "Agregado"}
        widths = {"path": 340, "description": 340, "added": 140}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.edit_selected_description())

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows_by_iid.clear()
        for row in self.db.list_configs():
            exists = Path(row["path"]).expanduser().exists()
            tag = "missing" if not exists else ""
            iid = self.tree.insert(
                "", "end",
                values=(row["path"], row["description"] or "", row["added_date"]),
                tags=(tag,),
            )
            self._rows_by_iid[iid] = row["id"]
        self.tree.tag_configure("missing", foreground="#c0392b")

    def _add_path(self, path: str) -> None:
        description = simpledialog.askstring(
            "Descripción", f"Descripción opcional para:\n{path}", parent=self
        ) or ""
        added = self.db.add_config(path, description)
        if not added:
            messagebox.showwarning("Ya existe", "Esa ruta ya está en el registro.")
        self.refresh_table()

    def add_file(self) -> None:
        path = filedialog.askopenfilename(title="Seleccionar archivo de configuración")
        if path:
            self._add_path(path)

    def add_folder(self) -> None:
        path = filedialog.askdirectory(title="Seleccionar carpeta de configuración")
        if path:
            self._add_path(path)

    def show_suggestions(self) -> None:
        tracked = {row["path"] for row in self.db.list_configs()}
        pending = [
            (p, desc) for p, desc in SUGGESTED_PATHS
            if p not in tracked and Path(p).expanduser().exists()
        ]
        if not pending:
            messagebox.showinfo(
                "Sugerencias", "No hay sugerencias nuevas: ya están agregadas o no existen."
            )
            return

        dialog = SuggestionsDialog(self, pending)
        self.wait_window(dialog)
        for path, description in dialog.selected:
            self.db.add_config(path, description)
        self.refresh_table()

    def edit_selected_description(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        config_id = self._rows_by_iid.get(iid)
        if config_id is None:
            return
        current = self.tree.item(iid, "values")[1]
        new_desc = simpledialog.askstring(
            "Editar descripción", "Descripción:", initialvalue=current, parent=self
        )
        if new_desc is None:
            return
        self.db.update_config_description(config_id, new_desc)
        self.refresh_table()

    def remove_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        config_id = self._rows_by_iid.get(iid)
        path = self.tree.item(iid, "values")[0]
        if config_id is None:
            return
        if messagebox.askyesno("Confirmar", f"¿Dejar de rastrear '{path}'?"):
            self.db.remove_config(config_id)
            self.refresh_table()


class SuggestionsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, pending: list[tuple[str, str]]):
        super().__init__(parent)
        self.title("Rutas sugeridas")
        self.geometry("480x360")
        self.transient(parent)
        self.grab_set()

        self.selected: list[tuple[str, str]] = []
        self._vars: list[tuple[tk.BooleanVar, str, str]] = []

        ttk.Label(
            self, text="Marcá las rutas que querés agregar al registro:", padding=(10, 10, 10, 0)
        ).pack(anchor="w")

        list_frame = ttk.Frame(self, padding=10)
        list_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for path, description in pending:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(inner, text=f"{path}  —  {description}", variable=var).pack(
                anchor="w", pady=2
            )
            self._vars.append((var, path, description))

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Agregar seleccionadas", command=self._confirm).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side="right", padx=(0, 6))

    def _confirm(self) -> None:
        self.selected = [(path, desc) for var, path, desc in self._vars if var.get()]
        self.destroy()
