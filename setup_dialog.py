import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sys, os, json, shutil, subprocess, threading, time, glob
import winreg

# ── Project directory (from environment variable) ──────────────────────────────
ENV_VAR_NAME = "GoGreen_BE_DIR"

def get_project_dir():
    # 1. Environment variable of this process
    path = os.environ.get(ENV_VAR_NAME)

    # 2. Read directly from the user registry. A shortcut started from Explorer
    #    may not see a variable that was set after Explorer started.
    if not path:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                path, _ = winreg.QueryValueEx(key, ENV_VAR_NAME)
        except OSError:
            path = None

    if path:
        path = os.path.normpath(os.path.expandvars(path))
        if os.path.isdir(path):
            return path

    # 3. Fallback if the variable is missing or points to a deleted folder
    if getattr(sys, 'frozen', False):
        # .exe is inside dist\, so go up one level to reach the project folder
        return os.path.dirname(os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR          = get_project_dir()
ENV_FILE          = os.path.join(BASE_DIR, ".env")
METER_CONFIG_FILE = os.path.join(BASE_DIR, "local_folder", "meter_config.json")
SERVER_STATE_FILE = os.path.join(BASE_DIR, ".server_state.json")

BAUDRATES      = ["1200","2400","4800","9600","19200","38400","57600","115200"]
POLL_INTERVALS = ["0.5","1.0","2.0","5.0","10.0"]

BG        = "#f4f6f9"
CARD      = "#ffffff"
GREEN     = "#2e7d32"
GREEN_H   = "#1b5e20"
GREEN_L   = "#e8f5e9"
TEXT      = "#1a1a2e"
SUBTEXT   = "#6b7280"
BORDER    = "#e0e0e0"
DC_ACCENT = "#1565c0"
AC_ACCENT = "#6a1b9a"
RED       = "#c62828"
RED_H     = "#b71c1c"
AMBER     = "#e65100"
AMBER_BG  = "#fff3e0"
SLATE     = "#455a64"
SLATE_H   = "#37474f"

# ── data helpers ───────────────────────────────────────────────────────────────
def get_available_ports():
    try:
        import serial.tools.list_ports
        ports = [p.device for p in sorted(serial.tools.list_ports.comports(), key=lambda x: x.device)]
        if ports: return ports
    except Exception: pass
    return [f"COM{i}" for i in range(1, 21)]

def load_env():
    v = {"DC_COM_PORT": "", "DC_BAUDRATE": "19200", "DC_POLL": "1.0",
         "RUN_MODE": "both"}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, val = line.split("=", 1)
                    if k.strip() in v: v[k.strip()] = val.strip()
    return v

def load_meter_config():
    d = {"port": "", "baudrate": 9600, "poll_interval": 1.0}
    if not os.path.exists(METER_CONFIG_FILE): return d
    try:
        with open(METER_CONFIG_FILE) as f: cfg = json.load(f)
        d["port"] = str(cfg.get("port","")).strip()
        d["baudrate"] = int(cfg.get("baudrate", 9600))
        d["poll_interval"] = float(cfg.get("poll_interval", 1.0))
    except Exception: pass
    return d

def save_env(dc_port, dc_baudrate, run_mode,dc_poll_interval):
    with open(ENV_FILE, "w") as f:
        f.write(f"DC_COM_PORT={dc_port}\nDC_BAUDRATE={dc_baudrate}\nRUN_MODE={run_mode}\nDC_POLL={dc_poll_interval}")

def save_meter_config(ac_port, ac_baudrate, ac_poll):
    config = {}
    if os.path.exists(METER_CONFIG_FILE):
        try:
            with open(METER_CONFIG_FILE) as f: config = json.load(f)
        except Exception: pass
    config.update({"port": ac_port, "baudrate": int(ac_baudrate), "poll_interval": float(ac_poll)})
    tmp = METER_CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f: json.dump(config, f, indent=4)
    os.replace(tmp, METER_CONFIG_FILE)

def load_server_state():
    try:
        with open(SERVER_STATE_FILE) as f: return json.load(f)
    except Exception: return {"django": False, "fastapi": False}

def save_server_state(state):
    with open(SERVER_STATE_FILE, "w") as f: json.dump(state, f)

def find_db_path():
    for name in ("db.sqlite3", "database.sqlite3"):
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p): return p
    found = glob.glob(os.path.join(BASE_DIR, "**", "*.sqlite3"), recursive=True)
    return found[0] if found else None

# ── virtual environment helpers ────────────────────────────────────────────────
def find_venv():
    """Return the venv folder name (.venv or venv) if it has an activate script, else None."""
    for name in (".venv", "venv"):
        if os.path.exists(os.path.join(BASE_DIR, name, "Scripts", "activate.bat")):
            return name
    return None

def get_python():
    """Python inside the venv if available, otherwise system python."""
    name = find_venv()
    if name:
        py = os.path.join(BASE_DIR, name, "Scripts", "python.exe")
        if os.path.exists(py):
            return py
    return "python"

def launch_in_terminal(title, command):
    """Open a new cmd window in the project dir; activate the venv only if it exists."""
    name = find_venv()
    activate = f"call {name}\\Scripts\\activate.bat && " if name else ""
    subprocess.Popen(
        f'start "{title}" cmd /k "{activate}{command}"',
        shell=True, cwd=BASE_DIR
    )

# ── process control ────────────────────────────────────────────────────────────
def kill_server_on_port(port):
    try:
        r = subprocess.run(f'netstat -ano | findstr ":{port} "',
                           shell=True, capture_output=True, text=True)
        pids = set()
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and f":{port}" in parts[1]:
                pid = parts[-1]
                if pid.isdigit() and pid != "0": pids.add(pid)
        for pid in pids:
            subprocess.run(f'taskkill /F /T /PID {pid}', shell=True, capture_output=True)
        for title in ("Django Server", "FastAPI Server"):
            subprocess.run(f'taskkill /F /FI "WINDOWTITLE eq {title}*"',
                           shell=True, capture_output=True)
        time.sleep(1.5)
        v = subprocess.run(f'netstat -ano | findstr ":{port} "',
                           shell=True, capture_output=True, text=True)
        return not any(f":{port}" in ln and "LISTEN" in ln for ln in v.stdout.splitlines())
    except Exception: return False

def check_port_free(port):
    r = subprocess.run(f'netstat -ano | findstr ":{port} "',
                       shell=True, capture_output=True, text=True)
    return not any(f":{port}" in ln for ln in r.stdout.splitlines())

def run_migrate(callback):
    def _run():
        try:
            proc = subprocess.run([get_python(), "manage.py", "migrate"],
                                  cwd=BASE_DIR, capture_output=True, text=True, timeout=120)
            callback(True, proc.stdout + proc.stderr)
        except Exception as e: callback(False, str(e))
    threading.Thread(target=_run, daemon=True).start()

def launch_django():
    launch_in_terminal(
        "Django Server",
        "python -m uvicorn electricity_monitoring_be.application:application "
        "--lifespan=on --host 0.0.0.0 --port 8000 --reload")

def launch_fastapi():
    launch_in_terminal(
        "FastAPI Server",
        "python -m uvicorn local_folder.main:app --host 0.0.0.0 --port 8001 --reload")

def stop_server(name, port, server_state, refresh_cb, parent=None):
    if not messagebox.askyesno(
        "Stop server",
        f"Stop {name} (port {port})?\n\nThis will close its terminal window.",
        parent=parent
    ):
        return

    # ── Loading overlay ────────────────────────────────────────────────
    loading = tk.Toplevel(parent)
    loading.title("Stopping server")
    loading.configure(bg=CARD)
    loading.resizable(False, False)
    loading.transient(parent)
    loading.grab_set()

    sw = loading.winfo_screenwidth()
    sh = loading.winfo_screenheight()

    W, H = 360, 150
    loading.geometry(
        f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}"
    )

    tk.Label(
        loading,
        text="Stopping server…",
        bg=CARD,
        fg=TEXT,
        font=("Segoe UI", 12, "bold")
    ).pack(pady=(25, 5))

    tk.Label(
        loading,
        text=f"Stopping {name} on port {port}",
        bg=CARD,
        fg=SUBTEXT,
        font=("Segoe UI", 9)
    ).pack()

    progress = ttk.Progressbar(
        loading,
        mode="indeterminate",
        length=280
    )
    progress.pack(pady=(18, 0))
    progress.start(10)

    # Prevent closing the loading window manually
    loading.protocol("WM_DELETE_WINDOW", lambda: None)

    # Disable main window while stopping
    parent.attributes("-disabled", True)

    def do_stop():
        ok = kill_server_on_port(port)

        def finish_stop():
            progress.stop()

            try:
                parent.attributes("-disabled", False)
            except Exception:
                pass

            try:
                loading.grab_release()
                loading.destroy()
            except Exception:
                pass

            # Keep your existing server state logic
            server_state[name.lower()] = False
            save_server_state(server_state)
            refresh_cb()

            if ok:
                messagebox.showinfo(
                    "Stopped",
                    f"{name} server stopped.",
                    parent=parent
                )
            else:
                messagebox.showwarning(
                    "May still be running",
                    f"Kill sent to port {port}, but it may still be active.\n"
                    "Close the terminal window manually if needed.",
                    parent=parent
                )

        # Return to Tkinter's main thread
        parent.after(0, finish_stop)

    # Run the potentially slow operation in background
    threading.Thread(
        target=do_stop,
        daemon=True
    ).start()

def validate_and_launch(dc_port, dc_baudrate,dc_poll_interval,  ac_port, ac_baudrate, ac_poll,
                        want_django, want_fastapi, server_state, refresh_cb, parent=None):
    dc_port = dc_port.strip().upper(); ac_port = ac_port.strip().upper()
    dc_baudrate = dc_baudrate.strip(); ac_baudrate = ac_baudrate.strip(); 
    dc_poll_interval = dc_poll_interval.strip(); 
    ac_poll = ac_poll.strip()

    if not want_django and not want_fastapi:
        messagebox.showwarning("Nothing selected", "Check at least one server to launch.", parent=parent)
        return

    needs_dc = want_django and not server_state.get("django")
    needs_ac = want_fastapi and not server_state.get("fastapi")

    if needs_dc:
        if not dc_port:
            messagebox.showerror("Missing", "DC Meter COM port required.", parent=parent); return
        if not dc_baudrate:
            messagebox.showerror("Missing", "DC Meter baud rate required.", parent=parent); return
        try: int(dc_baudrate)
        except ValueError:
            messagebox.showerror("Invalid", "DC baud rate must be a number.", parent=parent); return

    if needs_ac:
        if not ac_port:
            messagebox.showerror("Missing", "AC Meter COM port required.", parent=parent); return
        if not ac_baudrate:
            messagebox.showerror("Missing", "AC Meter baud rate required.", parent=parent); return
        if not ac_poll:
            messagebox.showerror("Missing", "AC poll interval required.", parent=parent); return
        try: int(ac_baudrate); float(ac_poll)
        except ValueError:
            messagebox.showerror("Invalid", "AC baud rate / poll must be numbers.", parent=parent); return

    if needs_dc and needs_ac and dc_port == ac_port:
        messagebox.showerror("Port conflict", f"DC and AC meters can't share port {dc_port}.", parent=parent)
        return

    run_mode = "both" if (want_django and want_fastapi) else ("django" if want_django else "fastapi")
    save_env(dc_port, dc_baudrate, run_mode, dc_poll_interval)
    if needs_ac and ac_port:
        try: save_meter_config(ac_port, ac_baudrate, ac_poll)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save meter_config.json:\n{e}", parent=parent); return

    launched = []
    if needs_dc: launch_django(); server_state["django"] = True; launched.append("Django  →  http://localhost:8000")
    if needs_ac: launch_fastapi(); server_state["fastapi"] = True; launched.append("FastAPI →  http://localhost:8001")
    save_server_state(server_state)

    if launched:
        messagebox.showinfo("Servers started", "Started:\n" + "\n".join(f"  • {s}" for s in launched), parent=parent)
    else:
        messagebox.showinfo("Already running", "All selected servers are already running.", parent=parent)
    refresh_cb()

# ── custom checkbox widget ─────────────────────────────────────────────────────
def CustomCheckbox(parent, var, accent, locked=False):
    """Draw a pill-style checkbox on a canvas. Returns the canvas widget."""
    SIZE = 22
    c = tk.Canvas(parent, width=SIZE, height=SIZE, bg=CARD,
                  highlightthickness=0, cursor="arrow" if locked else "hand2")

    def redraw():
        c.delete("all")
        on = var.get()
        if locked:
            # greyed filled circle with checkmark
            c.create_oval(2, 2, SIZE-2, SIZE-2, fill="#c8e6c9", outline="#a5d6a7", width=1)
            c.create_text(SIZE//2, SIZE//2, text="✓", fill=GREEN, font=("Segoe UI", 10, "bold"))
        elif on:
            c.create_oval(2, 2, SIZE-2, SIZE-2, fill=accent, outline=accent, width=1)
            c.create_text(SIZE//2, SIZE//2, text="✓", fill="white", font=("Segoe UI", 10, "bold"))
        else:
            c.create_oval(2, 2, SIZE-2, SIZE-2, fill=CARD, outline="#9e9e9e", width=1.5)

    def toggle(e=None):
        if not locked:
            var.set(not var.get())
            redraw()

    c.bind("<Button-1>", toggle)
    var.trace_add("write", lambda *_: redraw())
    redraw()
    return c

# ── New Instance Wizard ────────────────────────────────────────────────────────
def open_new_instance_wizard(parent, server_state, refresh_cb):
    win = tk.Toplevel(parent)
    win.title("New Match — Reset Database")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.grab_set()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    W, H = 620, 640
    win.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

    wiz = {
        "backup_folder": [None],
        "skip_backup":   [False],
        "db_path":       [find_db_path()],
    }

    # 3 user-facing steps: Choose backup → Review → Done
    # Execution is triggered at "Review → Done" transition (no separate Executing step shown in indicator)
    STEP_LABELS = ["1  Choose backup", "2  Review & confirm", "3  Done"]
    current_step = [0]   # 0=backup, 1=review, 2=executing(hidden), 3=done

    # ── header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(win, bg=GREEN, pady=14)
    hdr.pack(fill="x")
    tk.Label(hdr, text="🏏  New Match Setup",
             bg=GREEN, fg="white", font=("Segoe UI", 13, "bold")).pack()
    tk.Label(hdr, text="Prepare the system for the next cricket match",
             bg=GREEN, fg="#c8e6c9", font=("Segoe UI", 9)).pack()

    # ── step indicator — full width spread ────────────────────────────────────
    step_bar_outer = tk.Frame(win, bg=BG)
    step_bar_outer.pack(fill="x", padx=0, pady=0)

    # Canvas-based step bar for full-width connector lines
    step_canvas = tk.Canvas(step_bar_outer, bg=BG, highlightthickness=0, height=64)
    step_canvas.pack(fill="x", padx=20, pady=(12, 4))

    def redraw_steps():
        step_canvas.delete("all")
        step_canvas.update_idletasks()
        W2 = step_canvas.winfo_width()
        if W2 < 10: W2 = 580
        n = len(STEP_LABELS)
        # indicator maps: step 0,1 = wizard steps 0,1; step 2 = done (step 3)
        indicator_step = current_step[0] if current_step[0] < 2 else 2

        positions = [int(W2 * (i + 0.5) / n) for i in range(n)]
        CY = 24  # circle center y

        # draw connector lines first (behind circles)
        for i in range(n - 1):
            x1 = positions[i] + 14
            x2 = positions[i+1] - 14
            color = GREEN if i < indicator_step else BORDER
            step_canvas.create_line(x1, CY, x2, CY, fill=color, width=2)

        # draw circles and labels
        for i, label in enumerate(STEP_LABELS):
            cx = positions[i]
            done   = i < indicator_step
            active = i == indicator_step

            if done:
                fill, outline, fg_text = GREEN, GREEN, "white"
                sym = "✓"
            elif active:
                fill, outline, fg_text = GREEN, GREEN, "white"
                sym = str(i + 1)
            else:
                fill, outline, fg_text = CARD, BORDER, SUBTEXT
                sym = str(i + 1)

            r = 14
            step_canvas.create_oval(cx-r, CY-r, cx+r, CY+r, fill=fill, outline=outline, width=2)
            step_canvas.create_text(cx, CY, text=sym, fill=fg_text,
                                    font=("Segoe UI", 9, "bold"))

            lbl_color = GREEN if (done or active) else SUBTEXT
            lbl_font  = ("Segoe UI", 8, "bold") if active else ("Segoe UI", 8)
            # strip leading "N  " for display
            display = label.split("  ", 1)[1] if "  " in label else label
            step_canvas.create_text(cx, CY + r + 10, text=display,
                                    fill=lbl_color, font=lbl_font,
                                    width=100, justify="center")

    step_canvas.bind("<Configure>", lambda e: redraw_steps())

    tk.Frame(win, bg=BORDER, height=1).pack(fill="x")

    # ── content ───────────────────────────────────────────────────────────────
    content = tk.Frame(win, bg=BG)
    content.pack(fill="both", expand=True, padx=22, pady=10)

    # ── nav bar ───────────────────────────────────────────────────────────────
    tk.Frame(win, bg=BORDER, height=1).pack(fill="x", side="bottom")
    nav = tk.Frame(win, bg=BG, pady=11, padx=20)
    nav.pack(fill="x", side="bottom")

    back_btn = tk.Button(nav, text="← Back", bg=BG, fg=SUBTEXT,
                         font=("Segoe UI", 10), relief="flat", bd=0,
                         padx=14, pady=8, cursor="hand2")
    back_btn.pack(side="left")

    cancel_btn = tk.Button(nav, text="Cancel", bg=BG, fg=SUBTEXT,
                           font=("Segoe UI", 10), relief="flat", bd=0,
                           padx=14, pady=8, cursor="hand2", command=win.destroy)
    cancel_btn.pack(side="left", padx=(4, 0))

    next_btn = tk.Button(nav, text="Next  →", bg=GREEN, fg="white",
                         font=("Segoe UI", 10, "bold"), relief="flat", bd=0,
                         padx=22, pady=8, cursor="hand2",
                         activebackground=GREEN_H, activeforeground="white")
    next_btn.pack(side="right")

    # ── helpers ───────────────────────────────────────────────────────────────
    def clear():
        for w in content.winfo_children(): w.destroy()

    def card(parent, title, subtitle=None, accent=GREEN):
        wrap = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill="x", pady=(0, 10))
        tk.Frame(wrap, bg=accent, width=5).pack(side="left", fill="y")
        inner = tk.Frame(wrap, bg=CARD, padx=16, pady=14)
        inner.pack(side="left", fill="both", expand=True)
        tk.Label(inner, text=title, bg=CARD, fg=accent,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(inner, text=subtitle, bg=CARD, fg=SUBTEXT,
                     font=("Segoe UI", 9), anchor="w",
                     wraplength=500, justify="left").pack(fill="x", pady=(3, 0))
        return inner

    def goto(step):
        current_step[0] = step
        redraw_steps()
        RENDERERS[step]()

    # ── Step 0: Choose backup ─────────────────────────────────────────────────
    def render_step_0():
        clear()
        back_btn.config(state="disabled", fg=BG)   # hidden on step 1
        cancel_btn.pack(side="left", padx=(4, 0))
        next_btn.config(text="Next  →", bg=GREEN, activebackground=GREEN_H, state="normal")

        inner = card(content, "Choose a backup location",
                     "Select where to save today's match data before resetting. "
                     "Nothing is deleted or stopped yet.", DC_ACCENT)

        db = wiz["db_path"][0]
        tk.Label(inner, text="Database file:", bg=CARD, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(10, 2))
        if db:
            tk.Label(inner, text=db, bg=CARD, fg=DC_ACCENT,
                     font=("Segoe UI", 9), wraplength=490,
                     justify="left").pack(anchor="w")
        else:
            tk.Label(inner,
                     text="⚠  No SQLite database found — migration will still run.",
                     bg=CARD, fg=AMBER, font=("Segoe UI", 9)).pack(anchor="w")

        tk.Label(inner, text="Backup destination:", bg=CARD, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(14, 2))

        pick_row = tk.Frame(inner, bg=CARD)
        pick_row.pack(fill="x")

        folder_var = tk.StringVar(value=wiz["backup_folder"][0] or "")
        folder_lbl = tk.Label(pick_row, textvariable=folder_var,
                              bg="#f0f4ff", fg=DC_ACCENT,
                              font=("Segoe UI", 9), anchor="w",
                              padx=10, pady=7,
                              highlightbackground=DC_ACCENT, highlightthickness=1)
        folder_lbl.pack(side="left", fill="x", expand=True)

        def browse():
            chosen = filedialog.askdirectory(title="Select backup destination", parent=win)
            if chosen:
                wiz["backup_folder"][0] = chosen
                folder_var.set(chosen)

        tk.Button(pick_row, text="Browse…", bg=DC_ACCENT, fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
                  padx=14, pady=7, cursor="hand2",
                  activebackground="#0d47a1",
                  command=browse).pack(side="left", padx=(8, 0))

        skip_var = tk.BooleanVar(value=wiz["skip_backup"][0])
        sk_row = tk.Frame(inner, bg=CARD)
        sk_row.pack(fill="x", pady=(14, 0))

        skip_canvas = CustomCheckbox(sk_row, skip_var, SLATE)
        skip_canvas.pack(side="left")
        tk.Label(sk_row, text="  Skip backup — I don't need to save this match's data",
                 bg=CARD, fg=SUBTEXT, font=("Segoe UI", 9),
                 cursor="hand2").pack(side="left")

        def on_next():
            if not skip_var.get() and not wiz["backup_folder"][0]:
                messagebox.showerror("No folder selected",
                    "Choose a backup folder, or tick 'Skip backup' to continue without one.",
                    parent=win)
                return
            wiz["skip_backup"][0] = skip_var.get()
            goto(1)

        next_btn.config(command=on_next)

    # ── Step 1: Review & confirm ──────────────────────────────────────────────
    def render_step_1():
        clear()
        back_btn.config(state="normal", fg=SUBTEXT)
        next_btn.config(text="Confirm & reset  →", bg=RED,
                        activebackground=RED_H, state="normal")

        card(content, "Review and confirm",
             "Nothing has happened yet. Check the plan below, then click 'Confirm & reset'.",
             RED)

        plan_inner = card(content, "Actions that will execute", accent=SLATE)

        db     = wiz["db_path"][0]
        skip   = wiz["skip_backup"][0]
        folder = wiz["backup_folder"][0]
        running = [k for k, v in server_state.items() if v]

        def action_row(icon, label, detail, col):
            r = tk.Frame(plan_inner, bg=CARD)
            r.pack(fill="x", pady=5)
            tk.Frame(r, bg=col, width=3).pack(side="left", fill="y")
            rr = tk.Frame(r, bg=CARD, padx=10)
            rr.pack(side="left", fill="both", expand=True)
            tk.Label(rr, text=f"{icon}  {label}", bg=CARD, fg=col,
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
            tk.Label(rr, text=detail, bg=CARD, fg=SUBTEXT,
                     font=("Segoe UI", 9), anchor="w",
                     wraplength=400, justify="left").pack(fill="x")

        if not skip and folder and db:
            action_row("📋", "Copy database",
                       f"{os.path.basename(db)}  →  {folder}", DC_ACCENT)
        else:
            action_row("⏭", "Skip backup", "Match data will NOT be saved.", AMBER)

        if running:
            action_row("⛔", "Stop servers",
                       " + ".join(s.title() for s in running), RED)
        else:
            action_row("✓", "No servers to stop", "Both servers are already stopped.", GREEN)

        action_row("🗑", "Delete database",
                   db if db else "No database file found — skipping.", RED if db else SUBTEXT)
        action_row("▶", "Run migrations",
                   "python manage.py migrate  (creates fresh database)", GREEN)

        warn = tk.Label(content,
                        text="⚠  Deletes the current database permanently. Ensure the backup is correct.",
                        bg=AMBER_BG, fg=AMBER, font=("Segoe UI", 9),
                        wraplength=560, justify="left", anchor="w", padx=12, pady=8)
        warn.pack(fill="x", pady=(0, 6))

        def on_confirm():
            goto(2)

        next_btn.config(command=on_confirm)
        back_btn.config(command=lambda: goto(0))

    # ── Step 2: Execute ───────────────────────────────────────────────────────
    def render_step_2():
        clear()
        back_btn.config(state="disabled", fg=BG)
        cancel_btn.pack_forget()
        next_btn.config(state="disabled", text="Working…", bg=SUBTEXT,
                        activebackground=SUBTEXT)

        exec_inner = card(content, "Resetting — please wait…",
                          "Each step below will update as it completes.", SLATE)

        prog_frame = tk.Frame(exec_inner, bg=CARD)
        prog_frame.pack(fill="x", pady=(12, 0))

        db      = wiz["db_path"][0]
        skip    = wiz["skip_backup"][0]
        folder  = wiz["backup_folder"][0]
        running = [k for k, v in server_state.items() if v]

        exec_steps = []
        if not skip and folder and db:
            exec_steps.append(("Copy database", "backup"))
        if running:
            exec_steps.append((f"Stop {' + '.join(s.title() for s in running)}", "stop"))
        if db:
            exec_steps.append(("Delete database file", "delete"))
        exec_steps.append(("Run migrations", "migrate"))

        row_refs = {}
        for label, key in exec_steps:
            r = tk.Frame(prog_frame, bg=CARD, pady=5)
            r.pack(fill="x")
            icon = tk.Label(r, text="⏳", bg=CARD, fg="#bbb", font=("Segoe UI", 12), width=2)
            icon.pack(side="left")
            lbl = tk.Label(r, text=label, bg=CARD, fg=SUBTEXT, font=("Segoe UI", 10))
            lbl.pack(side="left", padx=(8, 0))
            row_refs[key] = (icon, lbl)

        errors = []

        def mark(key, ok, detail=""):
            if key not in row_refs: return
            icon, lbl = row_refs[key]
            if ok:
                icon.config(text="✓", fg=GREEN)
                lbl.config(fg=GREEN)
            else:
                icon.config(text="✗", fg=RED)
                lbl.config(fg=RED, text=lbl.cget("text") + (f" — {detail}" if detail else " — failed"))
            win.update_idletasks()

        def run_all():
            if not skip and folder and db:
                try:
                    ts   = time.strftime("%Y%m%d_%H%M%S")
                    dest = os.path.join(folder, f"{ts}_{os.path.basename(db)}")
                    shutil.copy2(db, dest)
                    win.after(0, mark, "backup", True)
                except Exception as e:
                    win.after(0, mark, "backup", False, str(e))
                    errors.append(f"Backup failed: {e}")

            if running:
                failed_stop = []
                for srv in running:
                    port = 8000 if srv == "django" else 8001
                    if not kill_server_on_port(port):
                        failed_stop.append(srv)
                    server_state[srv] = False
                save_server_state(server_state)
                win.after(0, refresh_cb)
                if failed_stop:
                    win.after(0, mark, "stop", False, "close terminal manually")
                    errors.append(f"Could not fully stop: {', '.join(failed_stop)}")
                else:
                    win.after(0, mark, "stop", True)

            if db and os.path.exists(db):
                try:
                    os.remove(db)
                    win.after(0, mark, "delete", True)
                except Exception as e:
                    win.after(0, mark, "delete", False, str(e))
                    errors.append(f"Delete failed: {e}")
            elif "delete" in row_refs:
                win.after(0, mark, "delete", True)

            def migrate_done(success, output):
                if success:
                    win.after(0, mark, "migrate", True)
                else:
                    win.after(0, mark, "migrate", False, "see terminal")
                    errors.append(f"Migration failed:\n{output[:400]}")
                win.after(0, finish, errors[:])

            run_migrate(migrate_done)

        def finish(errs):
            if errs:
                ef = tk.Frame(exec_inner, bg="#fff3f3",
                              highlightbackground=RED, highlightthickness=1)
                ef.pack(fill="x", pady=(12, 0))
                tk.Label(ef, text="Some steps had issues:", bg="#fff3f3", fg=RED,
                         font=("Segoe UI", 9, "bold"),
                         padx=10, pady=6, anchor="w").pack(fill="x")
                for e in errs:
                    tk.Label(ef, text=f"  • {e}", bg="#fff3f3", fg=RED,
                             font=("Segoe UI", 9), anchor="w",
                             padx=10, wraplength=500, justify="left").pack(fill="x")
                next_btn.config(state="normal", text="Close", bg=SLATE,
                                activebackground=SLATE_H, command=win.destroy)
            else:
                win.after(600, lambda: goto(3))

        threading.Thread(target=run_all, daemon=True).start()

    # ── Step 3: Done ──────────────────────────────────────────────────────────
    def render_step_3():
        clear()
        back_btn.config(state="disabled", fg=BG)
        cancel_btn.pack_forget()
        next_btn.config(state="normal", text="Close wizard",
                        bg=SLATE, activebackground=SLATE_H,
                        command=win.destroy)

        inner = card(content, "All done — ready for the next match!", accent=GREEN)

        tk.Label(inner, text="✅  Database reset complete.",
                 bg=CARD, fg=GREEN, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(10, 6))
        tk.Label(inner,
                 text="The old database has been backed up and a fresh one created.\n\n"
                      "Click 'Launch servers' on the main screen to start the new match.",
                 bg=CARD, fg=SUBTEXT, font=("Segoe UI", 10),
                 wraplength=490, justify="left").pack(anchor="w")

        def launch_and_close():
            win.destroy()
            # Bring parent window to front
            parent.deiconify()
            parent.lift()
            parent.focus_force()

        tk.Button(inner, text="▶  Go to Launch screen",
                  bg=GREEN, fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", bd=0,
                  padx=18, pady=9, cursor="hand2",
                  activebackground=GREEN_H, activeforeground="white",
                  command=launch_and_close).pack(anchor="w", pady=(18, 0))

    RENDERERS = [render_step_0, render_step_1, render_step_2, render_step_3]

    redraw_steps()
    render_step_0()

# ── Main UI ────────────────────────────────────────────────────────────────────
def main():
    env          = load_env()
    mc           = load_meter_config()
    ports        = get_available_ports()
    server_state = load_server_state()

    root = tk.Tk()
    root.title("Go Green – Server Setup")
    root.resizable(True, True)
    root.configure(bg=BG)
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"560x780+{(sw-560)//2}+{(sh-780)//2}")
    root.minsize(480, 600)
    root.maxsize(740, 1000)

    style = ttk.Style(); style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                    foreground=TEXT, bordercolor=BORDER, arrowcolor=GREEN, padding=6)
    style.map("TCombobox", fieldbackground=[("readonly", CARD)])

    # ── header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=GREEN, pady=14)
    hdr.pack(fill="x")
    tk.Label(hdr, text="🌿  Go Green Energy Monitor",
             bg=GREEN, fg="white", font=("Segoe UI", 14, "bold")).pack()
    tk.Label(hdr, text="Configure and manage servers",
             bg=GREEN, fg="#c8e6c9", font=("Segoe UI", 9)).pack()

    # ── status bar ────────────────────────────────────────────────────────────
    sbar = tk.Frame(root, bg=CARD, pady=10, padx=16,
                    highlightbackground=BORDER, highlightthickness=1)
    sbar.pack(fill="x")
    tk.Label(sbar, text="LIVE SERVER STATUS", bg=CARD, fg=SUBTEXT,
             font=("Segoe UI", 7, "bold")).pack(anchor="w", pady=(0, 6))

    srow = tk.Frame(sbar, bg=CARD)
    srow.pack(fill="x")

    # Each server pill: dot + name + url + status badge + stop button
    dj_widgets  = {}
    fa_widgets  = {}

    def make_status_pill(parent, name, port, key, out):
        pill = tk.Frame(parent, bg=CARD, padx=0, pady=0,
                        highlightbackground=BORDER, highlightthickness=1)
        pill.pack(side="left", padx=(0, 12), ipadx=10, ipady=6)

        top_row = tk.Frame(pill, bg=CARD)
        top_row.pack(fill="x", padx=10, pady=(6, 2))

        dot = tk.Label(top_row, text="⬤", bg=CARD, font=("Segoe UI", 9))
        dot.pack(side="left")

        tk.Label(top_row, text=f"  {name}", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        badge = tk.Label(top_row, text="", bg=CARD,
                         font=("Segoe UI", 8, "bold"), padx=6, pady=1)
        badge.pack(side="left", padx=(8, 0))

        url_lbl = tk.Label(pill, text=f"localhost:{port}", bg=CARD, fg=SUBTEXT,
                           font=("Segoe UI", 8))
        url_lbl.pack(anchor="w", padx=10)

        stop = tk.Button(pill, text="⬛  Stop server",
                         bg="#ffebee", fg=RED,
                         font=("Segoe UI", 8, "bold"), relief="flat", bd=0,
                         padx=10, pady=4, cursor="hand2",
                         highlightbackground="#ef9a9a", highlightthickness=1)
        stop.pack(fill="x", padx=10, pady=(6, 8))

        out["dot"]   = dot
        out["badge"] = badge
        out["stop"]  = stop
        out["pill"]  = pill
        return pill

    make_status_pill(srow, "Django",  8000, "django",  dj_widgets)
    make_status_pill(srow, "FastAPI", 8001, "fastapi", fa_widgets)

    def refresh_status():
        dj = server_state.get("django",  False)
        fa = server_state.get("fastapi", False)

        for running, w in ((dj, dj_widgets), (fa, fa_widgets)):
            w["dot"].config(fg=GREEN if running else "#cccccc")
            if running:
                w["badge"].config(text=" ● Running", bg=GREEN_L, fg=GREEN)
                w["stop"].config(state="normal", bg="#ffebee", fg=RED,
                                 highlightbackground="#ef9a9a")
            else:
                w["badge"].config(text=" ○ Stopped", bg="#f5f5f5", fg=SUBTEXT)
                w["stop"].config(state="disabled", bg="#f5f5f5", fg="#bbb",
                                 highlightbackground=BORDER)

    dj_widgets["stop"].config(
        command=lambda: stop_server("Django",  8000, server_state, refresh_status, parent=root))
    fa_widgets["stop"].config(
        command=lambda: stop_server("FastAPI", 8001, server_state, refresh_status, parent=root))
    refresh_status()

    # ── scrollable area ───────────────────────────────────────────────────────
    outer  = tk.Frame(root, bg=BG)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
    sb2    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb2.set)
    sb2.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    sf = tk.Frame(canvas, bg=BG)
    cw = canvas.create_window((0, 0), window=sf, anchor="nw")
    sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
    canvas.bind_all("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def sec(parent, title, accent):
        o = tk.Frame(parent, bg=BG, padx=16, pady=6)
        o.pack(fill="x")
        tk.Frame(o, bg=accent, width=4).pack(side="left", fill="y")
        c = tk.Frame(o, bg=CARD, highlightbackground=BORDER, highlightthickness=1,
                     padx=16, pady=14)
        c.pack(side="left", fill="both", expand=True)
        tk.Label(c, text=title, bg=CARD, fg=accent,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", pady=(0, 10))
        return c

    def flabel(parent, text, hint=None):
        tk.Label(parent, text=text, bg=CARD, fg=TEXT,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        if hint:
            tk.Label(parent, text=hint, bg=CARD, fg=SUBTEXT,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0, 2))

    def combo(parent, var, vals):
        cb = ttk.Combobox(parent, textvariable=var, values=vals,
                          state="normal", font=("Segoe UI", 10))
        cb.pack(fill="x", pady=(0, 12))
        return cb

    # ── DC meter section ──────────────────────────────────────────────────────
    dc_c = sec(sf, "🔵  DC Meter  (Django — RS485)", DC_ACCENT)
    flabel(dc_c, "COM Port", "RS485 port connected to the DC energy meter")
    dc_port_var = tk.StringVar(value=env["DC_COM_PORT"])
    combo(dc_c, dc_port_var, ports)
    flabel(dc_c, "Baud Rate", "Must match the DC meter's configured baud rate")
    dc_baud_var = tk.StringVar(value=env["DC_BAUDRATE"])
    combo(dc_c, dc_baud_var, BAUDRATES)
    flabel(dc_c, "Poll Interval (seconds)", "How often Django reads from the DC meter")
    dc_poll_var = tk.StringVar(value=env.get("DC_POLL", "1.0"))
    combo(dc_c, dc_poll_var, POLL_INTERVALS)

    # ── AC meter section ──────────────────────────────────────────────────────
    ac_c = sec(sf, "🟣  AC Meter  (FastAPI — RS485)", AC_ACCENT)
    tk.Label(ac_c, text="Also editable from the frontend Settings page.",
             bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8),
             justify="left", anchor="w").pack(fill="x", pady=(0, 10))
    flabel(ac_c, "COM Port", "RS485 port connected to the AC energy meter")
    ac_port_var = tk.StringVar(value=mc["port"])
    combo(ac_c, ac_port_var, ports)
    flabel(ac_c, "Baud Rate", "Must match the AC meter's configured baud rate")
    ac_baud_var = tk.StringVar(value=str(mc["baudrate"]))
    combo(ac_c, ac_baud_var, BAUDRATES)
    flabel(ac_c, "Poll Interval (seconds)", "How often FastAPI reads from the AC meter")
    ac_poll_var = tk.StringVar(value=str(mc["poll_interval"]))
    combo(ac_c, ac_poll_var, POLL_INTERVALS)

    # ── Server selection ──────────────────────────────────────────────────────
    srv_c = sec(sf, "⚙️  Servers to Launch", GREEN)

    saved_mode = env.get("RUN_MODE", "both")
    want_django_var  = tk.BooleanVar(value=saved_mode in ("both", "django"))
    want_fastapi_var = tk.BooleanVar(value=saved_mode in ("both", "fastapi"))

    def server_card(parent, title, hint, port, var, accent, state_key):
        running = server_state.get(state_key, False)
        if running:
            var.set(True)

        row = tk.Frame(parent, bg=CARD, pady=2)
        row.pack(fill="x", pady=(0, 8))

        # checkbox (locked if running)
        cb_canvas = CustomCheckbox(row, var, accent, locked=running)
        cb_canvas.pack(side="left", padx=(0, 10))

        # text block
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left", fill="both", expand=True)

        title_color = GREEN if running else TEXT
        tk.Label(txt, text=title, bg=CARD, fg=title_color,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(txt, text=hint, bg=CARD, fg=SUBTEXT,
                 font=("Segoe UI", 8), anchor="w").pack(fill="x")
        if running:
            tk.Label(txt,
                     text="Currently running — use Stop button above to stop.",
                     bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8, "italic"),
                     anchor="w").pack(fill="x")

        # badge
        if running:
            tk.Label(row, text="  ● Running  ", bg=GREEN_L, fg=GREEN,
                     font=("Segoe UI", 8, "bold"), padx=4, pady=3).pack(side="right", padx=6)
        else:
            tk.Label(row, text="  ○ Stopped  ", bg="#f5f5f5", fg=SUBTEXT,
                     font=("Segoe UI", 8), padx=4, pady=3).pack(side="right", padx=6)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(0, 6))

    server_card(srv_c,
                "Django  (port 8000)",
                "Handles DC meter data. Required for the main energy dashboard.",
                8000, want_django_var, DC_ACCENT, "django")

    server_card(srv_c,
                "FastAPI  (port 8001)",
                "Handles AC meter polling. Required for live AC readings.",
                8001, want_fastapi_var, AC_ACCENT, "fastapi")

    tk.Label(srv_c, text="Running servers are pre-checked and will not be restarted.",
             bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8), anchor="w").pack(anchor="w")

    tk.Frame(sf, bg=BG, height=10).pack()

    # ── bottom buttons ────────────────────────────────────────────────────────
    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")
    bot  = tk.Frame(root, bg=BG, padx=16, pady=12)
    bot.pack(fill="x", side="bottom")
    brow = tk.Frame(bot, bg=BG)
    brow.pack(fill="x")

    new_btn = tk.Button(brow, text="🏏  New match",
                        bg=SLATE, fg="white",
                        font=("Segoe UI", 10, "bold"),
                        relief="flat", bd=0, padx=16, pady=11,
                        cursor="hand2",
                        activebackground=SLATE_H, activeforeground="white",
                        command=lambda: open_new_instance_wizard(
                            root, server_state, refresh_status))
    new_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
    new_btn.bind("<Enter>", lambda e: new_btn.config(bg=SLATE_H))
    new_btn.bind("<Leave>", lambda e: new_btn.config(bg=SLATE))

    launch_btn = tk.Button(brow, text="▶  Launch servers",
                           bg=GREEN, fg="white",
                           font=("Segoe UI", 10, "bold"),
                           relief="flat", bd=0, padx=16, pady=11,
                           cursor="hand2",
                           activebackground=GREEN_H, activeforeground="white",
                           command=lambda: validate_and_launch(
                               dc_port_var.get(), dc_baud_var.get(),dc_poll_var.get(),
                               ac_port_var.get(), ac_baud_var.get(), ac_poll_var.get(),
                               want_django_var.get(), want_fastapi_var.get(),
                               server_state, refresh_status, parent=root))
    launch_btn.pack(side="right", fill="x", expand=True)
    launch_btn.bind("<Enter>", lambda e: launch_btn.config(bg=GREEN_H))
    launch_btn.bind("<Leave>", lambda e: launch_btn.config(bg=GREEN))

    root.mainloop()

if __name__ == "__main__":
    main()