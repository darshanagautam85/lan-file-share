import socket
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import time
import queue

PORT       = 5001
PING_PORT  = 5002
CONN_TIMEOUT = 8

selected_file = ""
cancel_event  = threading.Event()
ui_queue: queue.Queue = queue.Queue()

DEFAULT_ALLOWED_IPS = []

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "Unknown"
    finally:
        s.close()

def allowed_ips() -> list[str]:
    return []

def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds > 86400:
        return "--"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"

# ── Thread-safe UI helpers ────────────────────────────────────────────────────

def log(msg: str) -> None:
    ui_queue.put(("log", msg))

def set_status(msg: str, color: str = "black") -> None:
    ui_queue.put(("status", msg, color))

def set_progress(pct: float) -> None:
    ui_queue.put(("progress", pct))

def set_speed(speed: float, eta: float) -> None:
    ui_queue.put(("speed", speed, eta))

def set_sender_conn(state: str, peer_ip: str = "") -> None:
    ui_queue.put(("sender_conn", state, peer_ip))

def set_receiver_conn(state: str, peer_ip: str = "") -> None:
    ui_queue.put(("receiver_conn", state, peer_ip))

# ── Ping handshake ────────────────────────────────────────────────────────────

_last_ping_time: float = 0.0

def ping_receiver(ip: str) -> None:
    set_sender_conn("checking", ip)
    my_ip = get_local_ip()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((ip, PING_PORT))
        s.sendall(f"HELLO|{my_ip}".encode())
        reply = s.recv(16)
        s.close()
        if reply == b"ACK":
            set_sender_conn("connected", ip)
            log(f"Connected to receiver {ip}")
        else:
            set_sender_conn("disconnected", "")
    except Exception:
        set_sender_conn("disconnected", "")
        log(f"Could not reach {ip}")

def _ping_server_loop() -> None:
    global _last_ping_time
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", PING_PORT))
        srv.listen(10)
    except Exception as e:
        log(f"Ping server error: {e}")
        return
    while True:
        try:
            conn, addr = srv.accept()
        except OSError:
            break
        try:
            data = conn.recv(64).decode(errors="ignore")
            if data.startswith("HELLO"):
                parts   = data.split("|")
                peer_ip = parts[1].strip() if len(parts) > 1 else addr[0]
                conn.sendall(b"ACK")
                _last_ping_time = time.time()
                set_receiver_conn("connected", peer_ip)
                log(f"Sender {peer_ip} connected to us")
            conn.close()
        except Exception:
            pass

def _receiver_timeout_watcher() -> None:
    global _last_ping_time
    while True:
        time.sleep(1)
        if _last_ping_time > 0 and (time.time() - _last_ping_time) > CONN_TIMEOUT:
            set_receiver_conn("disconnected", "")
            _last_ping_time = 0

# ── Incoming request banner ───────────────────────────────────────────────────

class IncomingBanner(tk.Frame):
    """
    Inline accept/decline panel shown inside the main window
    when a file transfer request arrives. No popup needed.
    """
    def __init__(self, master, **kw):
        super().__init__(master, bg="#1a1a2e", relief="flat", **kw)
        self._answer_q: queue.Queue | None = None

        # top row — icon + title
        top = tk.Frame(self, bg="#1a1a2e")
        top.pack(fill="x", padx=14, pady=(10, 4))

        tk.Label(top, text="📥", font=("Arial", 22), bg="#1a1a2e").pack(side="left", padx=(0, 8))

        title_col = tk.Frame(top, bg="#1a1a2e")
        title_col.pack(side="left", fill="x", expand=True)

        self._title_lbl = tk.Label(
            title_col, text="", font=("Arial", 11, "bold"),
            bg="#1a1a2e", fg="#ffffff", anchor="w", wraplength=440,
        )
        self._title_lbl.pack(anchor="w")

        self._meta_lbl = tk.Label(
            title_col, text="", font=("Arial", 9),
            bg="#1a1a2e", fg="#aaaacc", anchor="w",
        )
        self._meta_lbl.pack(anchor="w")

        # save path row
        path_row = tk.Frame(self, bg="#1a1a2e")
        path_row.pack(fill="x", padx=14, pady=(4, 6))

        tk.Label(
            path_row, text="Save to:", font=("Arial", 9),
            bg="#1a1a2e", fg="#aaaacc", width=8, anchor="w",
        ).pack(side="left")

        self._path_var = tk.StringVar(value="")
        self._path_entry = tk.Entry(
            path_row, textvariable=self._path_var,
            font=("Courier", 9), width=42, state="readonly",
        )
        self._path_entry.pack(side="left", padx=(0, 6))

        tk.Button(
            path_row, text="Browse…", command=self._browse,
            font=("Arial", 9),
        ).pack(side="left")

        # button row
        btn_row = tk.Frame(self, bg="#1a1a2e")
        btn_row.pack(pady=(0, 10))

        tk.Button(
            btn_row, text="✔  Accept", width=14,
            bg="#1db954", fg="white", font=("Arial", 10, "bold"),
            activebackground="#17a045", relief="flat",
            command=self._accept,
        ).pack(side="left", padx=8)

        tk.Button(
            btn_row, text="✘  Decline", width=14,
            bg="#e05c5c", fg="white", font=("Arial", 10, "bold"),
            activebackground="#b03030", relief="flat",
            command=self._decline,
        ).pack(side="left", padx=8)

        # separator below
        tk.Frame(self, height=2, bg="#333355").pack(fill="x")

    # ── internal ──────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        path = filedialog.asksaveasfilename(
            initialfile=self._suggested_name,
            title="Choose where to save the file",
        )
        if path:
            self._path_var.set(path)

    def _accept(self) -> None:
        save_path = self._path_var.get().strip()
        if not save_path:
            # auto-pick Downloads folder if user didn't browse
            save_path = os.path.join(
                os.path.expanduser("~"), "Downloads", self._suggested_name
            )
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
        self.pack_forget()
        if self._answer_q:
            self._answer_q.put((True, save_path))
        log(f"Accepted: saving to {save_path}")

    def _decline(self) -> None:
        self.pack_forget()
        if self._answer_q:
            self._answer_q.put((False, ""))
        log("Declined incoming file request")

    # ── public ────────────────────────────────────────────────────────────────

    def show_request(self, sender_ip: str, filename: str,
                     filesize: int, answer_q: queue.Queue) -> None:
        self._answer_q      = answer_q
        self._suggested_name = filename

        self._title_lbl.config(
            text=f"{sender_ip}  wants to send you a file"
        )
        self._meta_lbl.config(
            text=f"📄  {filename}     💾  {fmt_size(filesize)}"
        )
        # pre-fill save path with Downloads/filename
        default_path = os.path.join(
            os.path.expanduser("~"), "Downloads", filename
        )
        self._path_var.set(default_path)

        # show banner at top of window and bring window forward
        self.pack(fill="x", before=status_label)

        # force window to front + flash taskbar
        root.lift()
        root.attributes("-topmost", True)
        root.after(3000, lambda: root.attributes("-topmost", False))
        root.bell()
        root.focus_force()


# ── Receiver (file transfer) ──────────────────────────────────────────────────

def _handle_client(conn: socket.socket, addr: tuple) -> None:
    try:
        raw_len = b""
        while len(raw_len) < 4:
            chunk = conn.recv(4 - len(raw_len))
            if not chunk:
                return
            raw_len += chunk
        meta_len = int.from_bytes(raw_len, "big")

        raw_meta = b""
        while len(raw_meta) < meta_len:
            chunk = conn.recv(meta_len - len(raw_meta))
            if not chunk:
                return
            raw_meta += chunk

        parts = raw_meta.decode().split("|")
        if len(parts) != 2:
            return
        filename, filesize_str = parts
        filesize = int(filesize_str)

        answer_q: queue.Queue = queue.Queue()
        # Ask via inline banner (not a popup)
        ui_queue.put(("ask_receive", addr[0], filename, filesize, answer_q))
        accepted, save_path = answer_q.get()   # blocks until user clicks

        if not accepted or not save_path:
            conn.send(b"NO")
            return
        conn.send(b"OK")

        received   = 0
        start_time = time.time()
        cancel_event.clear()
        set_status(f"Receiving {filename}…", "blue")
        set_progress(0)

        with open(save_path, "wb") as f:
            while received < filesize:
                if cancel_event.is_set():
                    log(f"CANCELLED receive of {filename}")
                    set_status("Receive cancelled", "red")
                    return
                conn.settimeout(10)
                try:
                    data = conn.recv(65536)
                except socket.timeout:
                    log(f"Timeout receiving {filename}")
                    set_status("Receive timed out", "red")
                    return
                if not data:
                    break
                f.write(data)
                received += len(data)
                pct       = received / filesize * 100
                elapsed   = max(time.time() - start_time, 0.001)
                speed_mbs = received / elapsed / 1024 / 1024
                remaining = (filesize - received) / max(received / elapsed, 1)
                set_progress(pct)
                set_speed(speed_mbs, remaining)

        if received < filesize:
            log(f"INCOMPLETE: {filename} ({fmt_size(received)} / {fmt_size(filesize)})")
            set_status("Transfer incomplete", "red")
        else:
            log(f"Received '{filename}' from {addr[0]} ({fmt_size(filesize)})")
            set_progress(100)
            set_speed(0, 0)
            set_status(f"✔ Received: {filename}", "green")
            ui_queue.put(("info", "File Received", f"'{filename}' saved to:\n{save_path}"))

    except Exception as e:
        log(f"Receive error: {e}")
        set_status("Receive error", "red")
    finally:
        conn.close()


def receive_loop() -> None:
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", PORT))
        server.listen(10)
        set_status("Listening for connections…", "green")
        while True:
            try:
                conn, addr = server.accept()
            except OSError:
                break
            threading.Thread(target=_handle_client, args=(conn, addr), daemon=True).start()
    except Exception as e:
        log(f"Server error: {e}")
        set_status("Server error — restart app", "red")


# ── Sender ────────────────────────────────────────────────────────────────────

def choose_file() -> None:
    global selected_file
    path = filedialog.askopenfilename()
    if path:
        selected_file = path
        file_label.config(text=os.path.basename(path))

def send_file() -> None:
    if not ip_entry.is_valid():
        messagebox.showerror("Error", "Enter a valid IP address (each part must be 0–255).")
        return
    if not selected_file:
        messagebox.showerror("Error", "Choose a file to send.")
        return
    threading.Thread(target=_send_worker, args=(ip_entry.get(), selected_file), daemon=True).start()

def _send_worker(ip: str, filepath: str) -> None:
    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    client   = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(10)
    try:
        client.connect((ip, PORT))
        meta = f"{filename}|{filesize}".encode()
        client.sendall(len(meta).to_bytes(4, "big") + meta)
        response = client.recv(2)
        if response != b"OK":
            ui_queue.put(("error", "Rejected", "The receiver declined the file."))
            return
        set_status(f"Sending {filename}…", "blue")
        set_progress(0)
        cancel_event.clear()
        sent       = 0
        start_time = time.time()
        with open(filepath, "rb") as f:
            while True:
                if cancel_event.is_set():
                    log(f"CANCELLED send of {filename}")
                    set_status("Send cancelled", "red")
                    return
                data = f.read(65536)
                if not data:
                    break
                client.sendall(data)
                sent += len(data)
                pct       = sent / filesize * 100
                elapsed   = max(time.time() - start_time, 0.001)
                speed_mbs = sent / elapsed / 1024 / 1024
                remaining = (filesize - sent) / max(sent / elapsed, 1)
                set_progress(pct)
                set_speed(speed_mbs, remaining)
        log(f"Sent '{filename}' → {ip} ({fmt_size(filesize)})")
        set_progress(100)
        set_speed(0, 0)
        set_status(f"✔ Sent: {filename}", "green")
        ui_queue.put(("info", "File Sent", f"'{filename}' sent successfully."))
    except socket.timeout:
        ui_queue.put(("error", "Timeout", f"Could not connect to {ip}."))
        set_status("Connection timed out", "red")
    except ConnectionRefusedError:
        ui_queue.put(("error", "Connection Refused", f"{ip} is not reachable on port {PORT}."))
        set_status("Connection refused", "red")
    except Exception as e:
        ui_queue.put(("error", "Send Error", str(e)))
        set_status("Send error", "red")
    finally:
        client.close()

def cancel_transfer() -> None:
    cancel_event.set()


# ── Segmented IP Entry ────────────────────────────────────────────────────────

class IPEntry(tk.Frame):
    def __init__(self, master, on_complete=None, **kw):
        super().__init__(master, **kw)
        self._octets: list[tk.Entry]     = []
        self._vars:   list[tk.StringVar] = []
        self._on_complete = on_complete

        for i in range(4):
            var = tk.StringVar()
            var.trace_add("write", lambda *_, idx=i: self._on_change(idx))
            e = tk.Entry(
                self, textvariable=var, width=3,
                font=("Courier", 12, "bold"), justify="center",
                relief="solid", bd=1,
            )
            e.grid(row=0, column=i * 2)
            e.bind("<KeyPress>", lambda ev, idx=i: self._on_key(ev, idx))
            e.bind("<FocusIn>",  lambda ev: ev.widget.select_range(0, tk.END))
            e.bind("<FocusOut>", lambda ev: self._check_complete())
            self._octets.append(e)
            self._vars.append(var)
            if i < 3:
                tk.Label(self, text=".", font=("Courier", 14, "bold"), padx=0).grid(
                    row=0, column=i * 2 + 1
                )

    def _on_change(self, idx: int) -> None:
        raw    = self._vars[idx].get()
        digits = "".join(c for c in raw if c.isdigit())
        if digits:
            digits = str(min(int(digits), 255))
        if digits != raw:
            self._vars[idx].set(digits)
            self._octets[idx].icursor(tk.END)
        if len(digits) == 3 and idx < 3:
            self._octets[idx + 1].focus_set()

    def _on_key(self, event: tk.Event, idx: int) -> str | None:
        key = event.keysym
        if key in ("period", "Tab") and idx < 3:
            self._octets[idx + 1].focus_set()
            return "break"
        if key == "BackSpace" and not self._vars[idx].get() and idx > 0:
            prev = self._octets[idx - 1]
            prev.focus_set()
            prev.icursor(tk.END)
            return "break"
        if len(key) == 1 and not key.isdigit():
            return "break"
        return None

    def _check_complete(self) -> None:
        if self.is_valid() and self._on_complete:
            self._on_complete(self.get())

    def get(self) -> str:
        return ".".join(v.get() for v in self._vars)

    def set(self, ip: str) -> None:
        parts = ip.split(".")
        for i, var in enumerate(self._vars):
            var.set(parts[i] if i < len(parts) else "")

    def is_valid(self) -> bool:
        parts = self.get().split(".")
        return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


# ── Connection card ───────────────────────────────────────────────────────────

class ConnCard(tk.Frame):
    _PALETTE = {
        "disconnected": {"dot": "#888888", "bg": "#f0f0f0", "text": "Not Connected", "fg": "#555555"},
        "checking":     {"dot": "#e8a000", "bg": "#fff8e6", "text": "Checking…",     "fg": "#b07000"},
        "connected":    {"dot": "#1db954", "bg": "#eafff1", "text": "Connected",      "fg": "#0a7a30"},
    }

    def __init__(self, master, role: str, **kw):
        super().__init__(master, relief="groove", bd=2, padx=12, pady=10, **kw)
        tk.Label(self, text=role.upper(), font=("Arial", 8, "bold"), fg="#999").pack(anchor="w")
        row = tk.Frame(self)
        row.pack(anchor="w", pady=(4, 0))
        self._dot = tk.Label(row, text="●", font=("Arial", 20))
        self._dot.pack(side="left", padx=(0, 8))
        col = tk.Frame(row)
        col.pack(side="left")
        self._state_lbl = tk.Label(col, font=("Arial", 12, "bold"))
        self._state_lbl.pack(anchor="w")
        self._peer_lbl  = tk.Label(col, font=("Courier", 10), fg="#555")
        self._peer_lbl.pack(anchor="w")
        self.set_state("disconnected")

    def _recolor(self, widget, bg: str) -> None:
        try:
            widget.config(bg=bg)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._recolor(child, bg)

    def set_state(self, state: str, peer_ip: str = "") -> None:
        p = self._PALETTE.get(state, self._PALETTE["disconnected"])
        self._recolor(self, p["bg"])
        self._dot.config(fg=p["dot"])
        self._state_lbl.config(text=p["text"], fg=p["fg"])
        self._peer_lbl.config(text=f"Peer: {peer_ip}" if peer_ip else "", fg=p["fg"])


# ── UI queue poll ─────────────────────────────────────────────────────────────

def poll_ui_queue() -> None:
    while not ui_queue.empty():
        item = ui_queue.get_nowait()
        cmd  = item[0]

        if cmd == "log":
            ts = time.strftime("%H:%M:%S")
            history_text.config(state="normal")
            history_text.insert(tk.END, f"[{ts}] {item[1]}\n")
            history_text.see(tk.END)
            history_text.config(state="disabled")

        elif cmd == "status":
            status_label.config(text=item[1], fg=item[2])

        elif cmd == "progress":
            progress["value"] = item[1]

        elif cmd == "speed":
            speed_label.config(text=f"Speed: {item[1]:.2f} MB/s  ETA: {fmt_eta(item[2])}")

        elif cmd == "sender_conn":
            _, state, peer_ip = item
            sender_card.set_state(state, peer_ip)

        elif cmd == "receiver_conn":
            _, state, peer_ip = item
            receiver_card.set_state(state, peer_ip)

        elif cmd == "info":
            messagebox.showinfo(item[1], item[2])

        elif cmd == "error":
            messagebox.showerror(item[1], item[2])

        elif cmd == "ask_receive":
            # Show inline banner — no popup
            _, sender_ip, filename, filesize, answer_q = item
            incoming_banner.show_request(sender_ip, filename, filesize, answer_q)

    root.after(50, poll_ui_queue)


# ── GUI ───────────────────────────────────────────────────────────────────────

root = tk.Tk()
root.title("LAN File Share")
root.geometry("630x860")
root.resizable(False, False)

tk.Label(root, text="LAN File Sharing", font=("Arial", 18, "bold")).pack(pady=(14, 2))
tk.Label(root, text=f"Your IP: {get_local_ip()}", font=("Arial", 11), fg="#555").pack()

status_label = tk.Label(root, text="Starting…", fg="gray", font=("Arial", 10, "italic"))
status_label.pack(pady=(4, 0))

# ── Incoming request banner (hidden until needed) ─────────────────────────────
incoming_banner = IncomingBanner(root)
# Not packed yet — shown dynamically by show_request()

# ── Connection status cards ───────────────────────────────────────────────────
conn_outer = tk.LabelFrame(
    root, text=" Connection Status ", font=("Arial", 10, "bold"), padx=10, pady=8
)
conn_outer.pack(fill="x", padx=16, pady=(10, 4))

cards_row = tk.Frame(conn_outer)
cards_row.pack(fill="x")

sender_card   = ConnCard(cards_row, role="Outgoing  (you → them)")
sender_card.pack(side="left", fill="both", expand=True, padx=(0, 6))

receiver_card = ConnCard(cards_row, role="Incoming  (them → you)")
receiver_card.pack(side="left", fill="both", expand=True)

# ── Send frame ────────────────────────────────────────────────────────────────
send_frame = tk.LabelFrame(root, text=" Send ", font=("Arial", 11, "bold"), padx=10, pady=8)
send_frame.pack(fill="x", padx=16, pady=(6, 4))

ip_row = tk.Frame(send_frame)
ip_row.pack(fill="x")
tk.Label(ip_row, text="Receiver IP:", width=12, anchor="w").pack(side="left")

def _on_ip_complete(ip: str) -> None:
    set_sender_conn("disconnected", "")
    threading.Thread(target=ping_receiver, args=(ip,), daemon=True).start()

ip_entry = IPEntry(ip_row, on_complete=_on_ip_complete)
ip_entry.pack(side="left", padx=(0, 6))

tk.Button(
    ip_row, text="⟳ Ping",
    command=lambda: (
        threading.Thread(target=ping_receiver, args=(ip_entry.get(),), daemon=True).start()
        if ip_entry.is_valid() else
        messagebox.showerror("Error", "Enter a valid IP first.")
    ),
).pack(side="left")

btn_row = tk.Frame(send_frame)
btn_row.pack(pady=(8, 0))

tk.Button(btn_row, text="Choose File", width=16, command=choose_file).pack(side="left", padx=4)
tk.Button(
    btn_row, text="Send File", width=16, bg="#4a9eff", fg="white",
    font=("Arial", 10, "bold"), command=send_file,
).pack(side="left", padx=4)
tk.Button(
    btn_row, text="Cancel", width=10, bg="#e05c5c", fg="white", command=cancel_transfer,
).pack(side="left", padx=4)

file_label = tk.Label(send_frame, text="No file selected", fg="#666", wraplength=520, anchor="w")
file_label.pack(pady=(6, 0), fill="x")

# ── Progress ──────────────────────────────────────────────────────────────────
prog_frame = tk.Frame(root)
prog_frame.pack(fill="x", padx=16, pady=(6, 0))

progress = ttk.Progressbar(prog_frame, orient="horizontal", length=598, mode="determinate")
progress.pack()

speed_label = tk.Label(root, text="Speed: 0.00 MB/s  ETA: --", font=("Courier", 10))
speed_label.pack(pady=(2, 0))

# ── Allowed IPs ───────────────────────────────────────────────────────────────
ip_frame = tk.LabelFrame(
    root, text=" Allowed Sender IPs (one per line) ",
    font=("Arial", 10, "bold"), padx=8, pady=6,
)
ip_frame.pack(fill="x", padx=16, pady=(10, 4))

ip_list_text = tk.Text(ip_frame, height=3, width=60, font=("Courier", 10))
ip_list_text.pack()
for _ip in DEFAULT_ALLOWED_IPS:
    ip_list_text.insert(tk.END, _ip + "\n")

# ── History log ───────────────────────────────────────────────────────────────
log_frame = tk.LabelFrame(root, text=" Transfer History ", font=("Arial", 10, "bold"), padx=8, pady=6)
log_frame.pack(fill="both", expand=True, padx=16, pady=(4, 12))

history_text = tk.Text(
    log_frame, state="disabled", height=6, font=("Courier", 9),
    bg="#1e1e1e", fg="#c8ffc8",
)
history_sb = tk.Scrollbar(log_frame, command=history_text.yview)
history_text.configure(yscrollcommand=history_sb.set)
history_sb.pack(side="right", fill="y")
history_text.pack(fill="both", expand=True)

# ── Start ─────────────────────────────────────────────────────────────────────
threading.Thread(target=receive_loop,              daemon=True).start()
threading.Thread(target=_ping_server_loop,         daemon=True).start()
threading.Thread(target=_receiver_timeout_watcher, daemon=True).start()
root.after(50, poll_ui_queue)
root.mainloop()