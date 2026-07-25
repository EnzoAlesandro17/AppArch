"""Pestaña de registro de paquetes instalados (oficiales y AUR)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from apparch import aur, flatpak, pacman, terminal
from apparch.db import Database

SOURCE_LABELS = {
    "official": "Oficial", "aur": "AUR", "flatpak": "Flatpak",
    "flatpak_runtime": "Runtime", "dependency": "Dependencia",
}
STATUS_LABELS = {"installed": "Instalado", "removed": "Eliminado"}

# Familia "real" de cada origen, para el filtro simplificado (Oficial/AUR/Flatpak):
# dependencia cuenta como Oficial, runtime cuenta como Flatpak.
SOURCE_FAMILY = {
    "official": "official", "dependency": "official",
    "flatpak": "flatpak", "flatpak_runtime": "flatpak",
    "aur": "aur",
}
# Orígenes que no se pidieron a propósito: se ocultan salvo que se tilde
# "Mostrar dependencias".
AUTOMATIC_SOURCES = {"dependency", "flatpak_runtime"}

# El ancho por defecto de un Entry de tkinter es 20 columnas; el doble para
# que el cuadro de notas entre más texto sin scrollear horizontalmente.
NOTES_ENTRY_WIDTH = 40


class _NotesDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, title: str, prompt: str, initial: str):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: str | None = None

        ttk.Label(self, text=prompt, padding=(10, 10, 10, 4)).pack(anchor="w")

        self._var = tk.StringVar(value=initial)
        entry = ttk.Entry(self, textvariable=self._var, width=NOTES_ENTRY_WIDTH)
        entry.pack(fill="x", padx=10, pady=(0, 10))
        entry.focus_set()
        entry.icursor("end")

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Guardar", command=self._on_save).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=self._on_cancel).pack(side="right", padx=(0, 6))

        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self._on_cancel())

    def _on_save(self) -> None:
        self.result = self._var.get()
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_notes(parent: tk.Widget, title: str, prompt: str, initial: str = "") -> str | None:
    dialog = _NotesDialog(parent, title, prompt, initial)
    parent.wait_window(dialog)
    return dialog.result


class PackagesTab(ttk.Frame):
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

        self.updates_btn = ttk.Button(bar, text="Buscar actualizaciones", command=self.check_updates)
        self.updates_btn.pack(side="left", padx=(6, 0))

        ttk.Label(bar, text="Origen:").pack(side="left", padx=(16, 4))
        self.source_filter = ttk.Combobox(
            bar, state="readonly", width=10,
            values=["Todos", "Oficial", "AUR", "Flatpak"],
        )
        self.source_filter.set("Todos")
        self.source_filter.pack(side="left")
        self.source_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())

        self.show_deps_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Mostrar dependencias", variable=self.show_deps_var,
            command=self.refresh_table,
        ).pack(side="left", padx=(12, 0))

        ttk.Label(bar, text="Estado:").pack(side="left", padx=(16, 4))
        self.status_filter = ttk.Combobox(
            bar, state="readonly", width=10,
            values=["Todos", "Instalado", "Eliminado"],
        )
        self.status_filter.set("Instalado")
        self.status_filter.pack(side="left")
        self.status_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())

        ttk.Label(bar, text="Buscar:").pack(side="left", padx=(16, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        ttk.Entry(bar, textvariable=self.search_var, width=20).pack(side="left")

    def _build_table(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        columns = ("installed", "updated", "name", "version", "source", "status", "notes")
        self.tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")
        headings = {
            "installed": "Instalado",
            "updated": "Actualizado",
            "name": "Nombre",
            "version": "Versión",
            "source": "Origen",
            "status": "Estado",
            "notes": "Notas",
        }
        widths = {
            "installed": 95, "updated": 95, "name": 170, "version": 90,
            "source": 65, "status": 75, "notes": 210,
        }
        anchors = {
            "installed": "center", "updated": "center", "name": "w", "version": "w",
            "source": "center", "status": "center", "notes": "w",
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
        sources: dict[str, dict[str, str]] = {}
        warnings: list[str] = []

        if pacman.is_available():
            try:
                sources["official"] = pacman.get_explicit_official_packages()
                sources["aur"] = pacman.get_foreign_packages()
                sources["dependency"] = pacman.get_dependency_packages()
            except pacman.PacmanError as exc:
                warnings.append(f"pacman: {exc}")
        else:
            warnings.append("pacman no está disponible en este sistema.")

        if flatpak.is_available():
            try:
                sources["flatpak"] = flatpak.get_installed_apps()
                sources["flatpak_runtime"] = flatpak.get_installed_runtimes()
            except flatpak.FlatpakError as exc:
                warnings.append(f"flatpak: {exc}")

        if not sources:
            messagebox.showerror(
                "No se pudo escanear",
                "\n".join(warnings) or "No hay gestores de paquetes disponibles.",
            )
            return

        self.scan_btn.config(state="disabled")
        try:
            summary = self.db.sync_packages(sources)
            pacman_history = pacman.parse_install_history() if "official" in sources or "aur" in sources else {}
            flatpak_history = (
                flatpak.parse_history() if "flatpak" in sources or "flatpak_runtime" in sources else {}
            )
            self.db.update_install_history(pacman_history, flatpak_history)
        finally:
            self.scan_btn.config(state="normal")

        self.status_filter.set("Todos")
        self.refresh_table()

        message = (
            f"Nuevos: {summary['added']}\n"
            f"Actualizados: {summary['updated']}\n"
            f"Marcados como eliminados: {summary['removed']}"
        )
        if warnings:
            message += "\n\nAvisos:\n" + "\n".join(warnings)
        messagebox.showinfo("Escaneo completo", message)

    def check_updates(self) -> None:
        warnings: list[str] = []
        outdated: dict[str, dict[str, dict[str, str]]] = {}

        self.updates_btn.config(state="disabled")
        try:
            if pacman.is_available():
                try:
                    official_outdated = pacman.get_outdated_packages()
                    if official_outdated:
                        outdated["official"] = official_outdated
                except pacman.PacmanError as exc:
                    warnings.append(f"pacman: {exc}")
            else:
                warnings.append("pacman no está disponible en este sistema.")

            if aur.find_helper():
                try:
                    aur_outdated = aur.get_outdated_packages()
                    if aur_outdated:
                        outdated["aur"] = aur_outdated
                except aur.AurHelperError as exc:
                    warnings.append(f"AUR: {exc}")

            if flatpak.is_available():
                flatpak_outdated = flatpak.get_outdated_apps()
                if flatpak_outdated:
                    outdated["flatpak"] = flatpak_outdated
        finally:
            self.updates_btn.config(state="normal")

        if not outdated:
            message = "Todo está actualizado."
            if warnings:
                message += "\n\nAvisos:\n" + "\n".join(warnings)
            messagebox.showinfo("Buscar actualizaciones", message)
            return

        if warnings:
            messagebox.showwarning("Avisos", "\n".join(warnings))

        UpdatesDialog(self, outdated)

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows_by_iid.clear()

        source_map = {"Todos": None, "Oficial": "official", "AUR": "aur", "Flatpak": "flatpak"}
        status_map = {"Todos": None, "Instalado": "installed", "Eliminado": "removed"}
        source_filter = source_map.get(self.source_filter.get())
        status_filter = status_map.get(self.status_filter.get())
        show_deps = self.show_deps_var.get()
        query = self.search_var.get().strip().lower()

        rows = self.db.list_packages()
        shown = 0
        for row in rows:
            if not show_deps and row["source"] in AUTOMATIC_SOURCES:
                continue
            if source_filter and SOURCE_FAMILY.get(row["source"]) != source_filter:
                continue
            if status_filter and row["status"] != status_filter:
                continue
            if query and query not in row["name"].lower():
                continue
            iid = self.tree.insert(
                "", "end",
                values=(
                    (row["installed_date"] or "")[:10] or "—",
                    (row["updated_date"] or "")[:10] or "—",
                    row["name"],
                    row["version"] or "",
                    SOURCE_LABELS.get(row["source"], row["source"]),
                    STATUS_LABELS.get(row["status"], row["status"]),
                    row["notes"] or "",
                ),
                tags=(row["status"],),
            )
            self._rows_by_iid[iid] = row["id"]
            shown += 1

        self.tree.tag_configure("removed", foreground="#999")

        counts = self.db.package_counts()
        self.status_var.set(
            f"Mostrando {shown} de {counts['installed'] + counts['removed']} — "
            f"Oficiales: {counts['official']}  |  AUR: {counts['aur']}  |  "
            f"Flatpak: {counts['flatpak']}  |  Runtimes: {counts['flatpak_runtime']}  |  "
            f"Dependencias: {counts['dependency']}  |  Eliminados: {counts['removed']}"
        )

    def edit_selected_notes(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        package_id = self._rows_by_iid.get(iid)
        if package_id is None:
            return
        current = self.tree.item(iid, "values")[6]
        new_notes = ask_notes(self, "Editar notas", "Notas para este paquete:", current)
        if new_notes is None:
            return
        self.db.update_package_notes(package_id, new_notes)
        self.refresh_table()


class UpdatesDialog(tk.Toplevel):
    """Muestra los paquetes desactualizados detectados en el escaneo y ofrece
    actualizarlos, un origen a la vez, en una terminal interactiva.

    Los paquetes oficiales siempre se actualizan todos juntos con
    'pacman -Syu': en Arch, actualizar solo algunos y dejar otros atrás
    (upgrade parcial) puede romper dependencias, así que no se ofrece
    selección individual para ese origen.
    """

    def __init__(self, parent: tk.Widget, outdated: dict[str, dict[str, dict[str, str]]]):
        super().__init__(parent)
        self.title("Actualizaciones disponibles")
        self.geometry("520x440")
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="Se encontraron paquetes desactualizados. Actualizar abre una\n"
                 "terminal para que confirmes los cambios (y la contraseña si hace falta).",
            justify="left", padding=(10, 10, 10, 0),
        ).pack(anchor="w")

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for source in ("official", "aur", "flatpak"):
            items = outdated.get(source)
            if items:
                self._build_section(inner, source, items)

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Cerrar", command=self.destroy).pack(side="right")

    def _build_section(self, parent: tk.Widget, source: str, items: dict[str, dict[str, str]]) -> None:
        label = SOURCE_LABELS.get(source, source)
        section = ttk.LabelFrame(parent, text=f"{label} — {len(items)} con actualización", padding=8)
        section.pack(fill="x", pady=(0, 10))

        for name, info in sorted(items.items()):
            ttk.Label(section, text=f"{name}:  {info['current']}  →  {info['new']}").pack(anchor="w")

        ttk.Button(
            section, text=f"Actualizar {label} ahora",
            command=lambda: self._update_source(source),
        ).pack(anchor="e", pady=(8, 0))

    def _update_source(self, source: str) -> None:
        if source == "official":
            command = "sudo pacman -Syu"
        elif source == "aur":
            helper = aur.find_helper()
            if helper is None:
                messagebox.showerror("Sin helper de AUR", "No se encontró yay ni paru instalado.")
                return
            command = f"{helper} -Sua"
        elif source == "flatpak":
            command = "flatpak update"
        else:
            return

        if not terminal.run_in_terminal(command):
            messagebox.showerror(
                "No se encontró una terminal",
                "No se pudo abrir ninguna terminal conocida. Ejecutá manualmente:\n\n" + command,
            )
