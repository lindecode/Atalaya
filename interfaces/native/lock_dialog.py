# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Native Windows dialog for inspecting and releasing file locks."""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from infrastructure.windows.file_locks import inspect_file_locks, terminate_lock_process
from shared.about import PROJECT_DIR


def _copy_to_clipboard(root: tk.Tk, text: str) -> None:
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


def show_lock_dialog(target_path: str | Path) -> None:
    """Opens a native, responsive Windows dialog showing which processes hold locks on `target_path`."""
    path = Path(target_path).resolve()

    root = tk.Tk()
    root.title(f"Atalaya · ¿Quién usa este archivo?")
    root.minsize(580, 420)
    root.resizable(True, True)

    ico = PROJECT_DIR / "assets" / "icon.ico"
    if ico.exists():
        try:
            root.iconbitmap(str(ico))
        except Exception:
            pass

    # Styling
    style = ttk.Style(root)
    style.theme_use("vista" if "vista" in style.theme_names() else "clam")

    # Header
    header_frame = ttk.Frame(root, padding=(16, 12, 16, 8))
    header_frame.pack(fill="x")

    lbl_title = ttk.Label(header_frame, text="🛡️ ¿Quién usa este archivo?", font=("Segoe UI", 12, "bold"))
    lbl_title.pack(anchor="w")

    lbl_sub = ttk.Label(header_frame, text="Inspección de procesos y bloqueos de Windows (Restart Manager)",
                        font=("Segoe UI", 9))
    lbl_sub.pack(anchor="w", pady=(2, 6))

    # Path display
    path_frame = ttk.Frame(header_frame)
    path_frame.pack(fill="x", pady=4)

    path_var = tk.StringVar(value=str(path))
    txt_path = ttk.Entry(path_frame, textvariable=path_var, state="readonly", font=("Consolas", 9))
    txt_path.pack(side="left", fill="x", expand=True, padx=(0, 6))

    btn_copy_path = ttk.Button(path_frame, text="Copiar ruta",
                               command=lambda: _copy_to_clipboard(root, str(path)))
    btn_copy_path.pack(side="right")

    ttk.Separator(root, orient="horizontal").pack(fill="x", padx=16, pady=4)

    # Content container
    content_frame = ttk.Frame(root, padding=(16, 8, 16, 8))
    content_frame.pack(fill="both", expand=True)

    status_var = tk.StringVar()
    lbl_status = ttk.Label(content_frame, textvariable=status_var, font=("Segoe UI", 10, "bold"), wraplength=540)
    lbl_status.pack(anchor="w", pady=(0, 8))

    # Scrollable processes list
    canvas = tk.Canvas(content_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
    scroll_frame = ttk.Frame(canvas)

    scroll_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

    def _on_canvas_configure(event):
        canvas.itemconfig(canvas_window, width=event.width)

    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Mouse wheel support
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def refresh_locks():
        for widget in scroll_frame.winfo_children():
            widget.destroy()

        if not path.exists():
            status_var.set(f"⚠️ El archivo o carpeta no existe en el disco:\n{path}")
            lbl_status.configure(foreground="#d97706")
            return

        try:
            locks = inspect_file_locks(path)
        except Exception as exc:
            status_var.set(f"❌ Error al consultar bloqueos: {exc}")
            lbl_status.configure(foreground="#dc2626")
            return

        if not locks:
            status_var.set("✅ Ningún proceso tiene bloqueado este archivo.\nEstá libre para modificar, mover o eliminar.")
            lbl_status.configure(foreground="#16a34a")
            info_lbl = ttk.Label(
                scroll_frame,
                text="Si Windows aún indica que no puede eliminarse, verifique:\n"
                     "• Permisos NTFS de su usuario.\n"
                     "• Atributos de solo lectura o archivo del sistema.\n"
                     "• Si es una carpeta, que no esté abierta en otra ventana o consola.",
                font=("Segoe UI", 9),
                foreground="#4b5563"
            )
            info_lbl.pack(anchor="w", padx=4, pady=8)
            return

        count = len(locks)
        status_var.set(f"🔴 {count} proceso{'s' if count > 1 else ''} tiene{'n' if count > 1 else ''} este archivo en uso:")
        lbl_status.configure(foreground="#dc2626")

        for proc in locks:
            card = ttk.LabelFrame(scroll_frame, text=f" {proc['name']}  (PID: {proc['pid']}) ", padding=(10, 8))
            card.pack(fill="x", expand=True, pady=4, padx=2)

            # Details
            details_text = f"• Tipo: {proc['app_type']}"
            if proc.get("service"):
                details_text += f"  (Servicio: {proc['service']})"
            if proc.get("user"):
                details_text += f"\n• Usuario: {proc['user']}"
            if proc.get("path"):
                details_text += f"\n• Ruta ejecutable: {proc['path']}"
            if proc.get("command") and proc["command"] != proc.get("path"):
                cmd = proc["command"]
                if len(cmd) > 120:
                    cmd = cmd[:117] + "…"
                details_text += f"\n• Comando: {cmd}"

            lbl_details = ttk.Label(card, text=details_text, font=("Segoe UI", 9))
            lbl_details.pack(anchor="w", pady=(0, 6))

            btn_box = ttk.Frame(card)
            btn_box.pack(fill="x", anchor="e")

            pid = proc["pid"]
            name = proc["name"]
            ps_cmd = f"Stop-Process -Id {pid}"

            btn_copy_cmd = ttk.Button(
                btn_box,
                text="Copiar comando PowerShell",
                command=lambda cmd=ps_cmd: _copy_to_clipboard(root, cmd)
            )
            btn_copy_cmd.pack(side="left", padx=(0, 6))

            def _kill(p_pid=pid, p_name=name):
                confirm = messagebox.askyesno(
                    "Confirmar finalización",
                    f"¿Está seguro de que desea forzar la detención de:\n\n{p_name} (PID: {p_pid})?\n\n"
                    "Los cambios no guardados en ese programa podrían perderse.",
                    icon="warning",
                    parent=root
                )
                if confirm:
                    ok, msg = terminate_lock_process(p_pid, force=True)
                    if ok:
                        messagebox.showinfo("Proceso finalizado", msg, parent=root)
                        refresh_locks()
                    else:
                        messagebox.showerror("Error al finalizar", msg, parent=root)

            btn_kill = ttk.Button(btn_box, text="Finalizar proceso", command=_kill)
            btn_kill.pack(side="right")

    # Bottom action bar
    bottom_frame = ttk.Frame(root, padding=(16, 8, 16, 12))
    bottom_frame.pack(fill="x", side="bottom")

    btn_refresh = ttk.Button(bottom_frame, text="🔄 Actualizar / Reintentar", command=refresh_locks)
    btn_refresh.pack(side="left")

    btn_close = ttk.Button(bottom_frame, text="Cerrar", command=root.destroy)
    btn_close.pack(side="right")

    root.bind("<Escape>", lambda e: root.destroy())

    # Center window
    root.update_idletasks()
    width = 620
    height = 460
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    refresh_locks()
    root.mainloop()
