# AppArch

App de escritorio (Tkinter) para llevar un registro de los paquetes, apps,
estado del sistema y configuraciones de Arch Linux, pensada para poder
responder "¿en qué se diferencia esta máquina de un Arch limpio?" y facilitar
un backup/reinstalación ordenada.

Ventana 1200x600, centrada en el monitor primario (detectado vía `xrandr`).

## Uso

```bash
cd AppArch
source venv/bin/activate
python main.py
```

Sin dependencias externas: solo librería estándar (`tkinter`, `sqlite3`).
Los datos viven en `~/.local/share/apparch/apparch.db`, aparte del código.

## Funcionalidad actual

### Pestaña Paquetes
Escanea y mantiene un historial (nunca borra filas, solo cambia el estado a
"Eliminado") de:

- **Oficial** — `pacman -Qe` menos foráneos (paquetes que vos pediste).
- **AUR** — `pacman -Qm` (paquetes foráneos, sin importar motivo de instalación).
- **Flatpak** — `flatpak list --app`.
- **Runtime** (subcategoría de Flatpak) — `flatpak list --runtime`, las
  plataformas compartidas que arrastran las apps.
- **Dependencia** (subcategoría de Oficial) — `pacman -Qd` menos foráneos,
  paquetes oficiales instalados como dependencia, no a pedido.

El filtro de Origen muestra solo Oficial/AUR/Flatpak; el tilde "Mostrar
dependencias" suma runtime + dependencia a la vista (ninguno de los dos entra
al backup: se reinstalan solos al pedir el paquete que los arrastra).

Por paquete se guarda versión, notas propias, y fecha real de instalación y
de última actualización (sacadas de `/var/log/pacman.log` y
`flatpak history`, no inventadas — con la limitación honesta de que si el log
rotó o el historial de flatpak no llega tan atrás, la fecha de "instalado" es
la mejor aproximación disponible, no necesariamente la original).

**Buscar actualizaciones** (separado de "Escanear sistema"): chequea
`pacman -Qu` (oficiales, incluye dependencias), `yay -Qua`/`paru -Qua` (AUR,
incluye dependencias) y `flatpak remote-ls --updates` (apps + runtimes) en
cada instalación/remoto configurado. Si hay algo, ofrece actualizar por
origen abriendo una terminal interactiva (nunca corre nada del sistema en
silencio). Los paquetes oficiales siempre se actualizan todos juntos con
`pacman -Syu` — nunca selección individual, porque en Arch las
actualizaciones parciales pueden romper dependencias.

### Pestaña Sistema
Mismo patrón de escaneo/historial que Paquetes, pero para estado que no es
"un paquete instalado": servicios systemd habilitados (sistema y usuario),
grupos del usuario, y nombres de redes WiFi guardadas (vía `nmcli`, sin leer
contraseñas — esos archivos son solo root).

### Pestaña Configuraciones
Registro manual de rutas (dotfiles, `/etc/...`) a respaldar, con
descripción propia y sugerencias de rutas comunes de Arch. Ver "Pendiente"
abajo — las sugerencias hoy son genéricas, no específicas del escritorio.

### Pestaña Backup
Genera una carpeta con `pkglist-official.txt`, `pkglist-aur.txt`,
`pkglist-flatpak.txt` (solo oficial/AUR/flatpak explícitos, nunca
dependencias ni runtimes), copia de las configuraciones rastreadas, y un
`restore.sh` para reinstalar todo en un sistema nuevo.

## Pendiente / para retomar

- **Sugerencias de Configuración específicas de este escritorio (KDE
  Plasma)**: hoy `SUGGESTED_PATHS` en `configs_tab.py` es genérico de Arch
  (pacman.conf, fstab, bashrc, etc.). Se detectaron y quedan por sumar:
  `~/.config/kwinrc` (compositor/transparencia), `~/.config/kwinoutputconfig.json`
  y `~/.local/share/kscreen/` (la resolución de pantalla forzada vive ahí,
  no en Xorg), `~/.config/plasma-org.kde.plasma.desktop-appletsrc` (fondo,
  paneles), `~/.config/kdeglobals` (tema), `/etc/localtime` (hora). Falta
  decidir si reemplazan la lista genérica o se suman.
- **Desinstalar paquetes AUR y Flatpak** desde la pestaña Paquetes (no para
  oficiales: muchos son fragmentos/dependencias de otra cosa y desinstalar
  el nombre equivocado puede romper algo sin que se vea la relación).
- **Separar explícito vs. dependencia dentro de "Oficiales"** en el diálogo
  de "Buscar actualizaciones" (hoy aparecen mezclados sin distinguir cuál es
  cuál).
- **Snapshot automático liviano**: auto-generar `pkglist-*.txt` (barato,
  milisegundos) cada vez que un escaneo detecta un cambio real, sin tocar la
  copia de configs (cara, puede ser carpetas grandes) que seguiría siendo
  manual o con límite de frecuencia + retención para no llenar el disco.
- **Pestaña "Archivos personales"** (todavía no arrancada): separar
  contenido a copiar de verdad (fotos, Descargas) de carpetas de proyectos
  git, donde alcanza con verificar que esté todo pusheado al remoto en vez
  de copiar el peso completo.
- **Paquetes globales de lenguaje** (`npm -g`, `pip --user`, `cargo`,
  `gem`): deliberadamente afuera de alcance por ahora — en este sistema hoy
  no hay ninguno instalado, así que sería construir para un problema que no
  existe. Retomar si en algún momento se acumulan varios.
- **Docker**: contenedores/imágenes son un mundo aparte, invisible para
  pacman/AUR/Flatpak. No evaluado todavía si vale la pena trackearlos.
