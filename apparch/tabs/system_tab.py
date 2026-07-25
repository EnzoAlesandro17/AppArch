"""Pestaña de estado del sistema: servicios systemd habilitados, grupos del
usuario y redes guardadas. Es lo que falta para saber en qué se diferencia
esta máquina de un Arch limpio más allá de los paquetes instalados."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from apparch import system_info
from apparch.db import Database
from apparch.tabs.packages_tab import ask_notes

CATEGORY_LABELS = {"service": "Servicio", "group": "Grupo", "wifi": "Red WiFi"}
STATUS_LABELS = {"present": "Presente", "removed": "Eliminado"}
SCOPE_LABELS = {"system": "Sistema", "user": "Usuario"}


class SystemTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, db: Database):
        super().__init__(parent, padding=10)
        self.db = db
        self._rows_by_iid: dict[str, int] = {}

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

        self.refresh_table()

    # ---- construcción de UI --------------------------------------------

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))

        self.scan_btn = ttk.Button(bar, text="Escanear sistema", command=self.scan_system)
        self.scan_btn.pack(side="left")

        ttk.Label(bar, text="Categoría:").pack(side="left", padx=(16, 4))
        self.category_filter = ttk.Combobox(
            bar, state="readonly", width=12,
            values=["Todas", "Servicio", "Grupo", "Red WiFi"],
        )
        self.category_filter.set("Todas")
        self.category_filter.pack(side="left")
        self.category_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())

        ttk.Label(bar, text="Estado:").pack(side="left", padx=(16, 4))
        self.status_filter = ttk.Combobox(
            bar, state="readonly", width=10,
            values=["Todos", "Presente", "Eliminado"],
        )
        self.status_filter.set("Presente")
        self.status_filter.pack(side="left")
        self.status_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())

        ttk.Label(bar, text="Buscar:").pack(side="left", padx=(16, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        ttk.Entry(bar, textvariable=self.search_var, width=20).pack(side="left")

    def _build_table(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        columns = ("category", "scope", "name", "status", "notes")
        self.tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")
        headings = {
            "category": "Categoría", "scope": "Alcance", "name": "Nombre",
            "status": "Estado", "notes": "Notas",
        }
        widths = {"category": 100, "scope": 90, "name": 280, "status": 90, "notes": 300}
        anchors = {
            "category": "center", "scope": "center", "name": "w",
            "status": "center", "notes": "w",
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=anchors[col])

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.edit_selected_notes())

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#666").pack(
            fill="x", pady=(6, 0)
        )

    # ---- lógica ---------------------------------------------------------

    def scan_system(self) -> None:
        warnings: list[str] = []
        totals = {"added": 0, "updated": 0, "removed": 0}

        def _sync(category: str, items: dict[str, str], scope: str | None, label: str) -> None:
            try:
                summary = self.db.sync_system_items(category, items, scope=scope)
                for key in totals:
                    totals[key] += summary[key]
            except system_info.SystemInfoError as exc:
                warnings.append(f"{label}: {exc}")

        self.scan_btn.config(state="disabled")
        try:
            try:
                services_system = system_info.get_enabled_services("system")
                _sync("service", services_system, "system", "servicios (sistema)")
            except system_info.SystemInfoError as exc:
                warnings.append(f"servicios (sistema): {exc}")

            try:
                services_user = system_info.get_enabled_services("user")
                _sync("service", services_user, "user", "servicios (usuario)")
            except system_info.SystemInfoError as exc:
                warnings.append(f"servicios (usuario): {exc}")

            try:
                groups = system_info.get_user_groups()
                _sync("group", {g: "" for g in groups}, None, "grupos")
            except system_info.SystemInfoError as exc:
                warnings.append(f"grupos: {exc}")

            try:
                wifi = system_info.get_saved_wifi_networks()
                _sync("wifi", {n: "" for n in wifi}, None, "redes wifi")
            except system_info.SystemInfoError as exc:
                warnings.append(f"redes wifi: {exc}")
        finally:
            self.scan_btn.config(state="normal")

        self.status_filter.set("Todos")
        self.refresh_table()

        message = (
            f"Nuevos: {totals['added']}\n"
            f"Actualizados: {totals['updated']}\n"
            f"Marcados como eliminados: {totals['removed']}"
        )
        if warnings:
            message += "\n\nAvisos:\n" + "\n".join(warnings)
        messagebox.showinfo("Escaneo completo", message)

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows_by_iid.clear()

        category_map = {"Todas": None, "Servicio": "service", "Grupo": "group", "Red WiFi": "wifi"}
        status_map = {"Todos": None, "Presente": "present", "Eliminado": "removed"}
        category_filter = category_map.get(self.category_filter.get())
        status_filter = status_map.get(self.status_filter.get())
        query = self.search_var.get().strip().lower()

        rows = self.db.list_system_items()
        shown = 0
        for row in rows:
            if category_filter and row["category"] != category_filter:
                continue
            if status_filter and row["status"] != status_filter:
                continue
            if query and query not in row["name"].lower():
                continue
            iid = self.tree.insert(
                "", "end",
                values=(
                    CATEGORY_LABELS.get(row["category"], row["category"]),
                    SCOPE_LABELS.get(row["scope"], "—"),
                    row["name"],
                    STATUS_LABELS.get(row["status"], row["status"]),
                    row["notes"] or "",
                ),
                tags=(row["status"],),
            )
            self._rows_by_iid[iid] = row["id"]
            shown += 1

        self.tree.tag_configure("removed", foreground="#999")

        counts = self.db.system_item_counts()
        self.status_var.set(
            f"Mostrando {shown} de {counts['present'] + counts['removed']} — "
            f"Servicios: {counts['service']}  |  Grupos: {counts['group']}  |  "
            f"Redes WiFi: {counts['wifi']}  |  Eliminados: {counts['removed']}"
        )

    def edit_selected_notes(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        item_id = self._rows_by_iid.get(iid)
        if item_id is None:
            return
        current = self.tree.item(iid, "values")[4]
        new_notes = ask_notes(self, "Editar notas", "Notas para este elemento:", current)
        if new_notes is None:
            return
        self.db.update_system_item_notes(item_id, new_notes)
        self.refresh_table()
