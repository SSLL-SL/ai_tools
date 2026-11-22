import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

DATA_PATH = os.environ.get(
    "GAMES_JSON_PATH",
    "/Users/ricardogarcia/Downloads/GAMES.json",
)
CONFIG_PATH = os.environ.get("CONFIG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
QUEUE_PATH = os.environ.get("QUEUE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue.json"))

def load_config():
    default = {"download_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
            default.update(cfg)
    return default

def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

config = load_config()
DOWNLOAD_DIR = config["download_dir"]
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def safe_filename(name):
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe + ".pkg"

def get_downloaded_files():
    if not os.path.isdir(DOWNLOAD_DIR):
        return {}
    result = {}
    for f in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(path):
            result[f] = os.path.getsize(path)
    return result

def format_size(size):
    if not size:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.log(size, 1024)) if size > 0 else 0
    i = min(i, len(units) - 1)
    s = size / (1024 ** i)
    return f"{s:.2f} {units[i]}"


def load_games():
    with open(DATA_PATH) as f:
        data = json.load(f)
    games = []
    for url, meta in data.get("DATA", {}).items():
        games.append({
            "url": url,
            "name": meta.get("name", ""),
            "title_id": meta.get("title_id", ""),
            "region": meta.get("region", ""),
            "version": meta.get("version", ""),
            "release": meta.get("release", ""),
            "size": meta.get("size", 0),
            "size_str": format_size(meta.get("size", 0)),
            "min_fw": meta.get("min_fw", ""),
            "cover_url": meta.get("cover_url", ""),
        })
    return games


GAMES = load_games()


class DownloadManager:
    def __init__(self, download_dir):
        self.download_dir = download_dir
        self._queue = []
        self._lock = threading.Lock()
        self._thread = None
        self._stop_events = {}
        self._load_queue()

    def _queue_path(self):
        return QUEUE_PATH

    def _save_queue(self):
        path = self._queue_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self._lock:
                to_save = []
                for e in self._queue:
                    to_save.append({k: v for k, v in e.items() if k not in ("_local_path", "_response")})
            with open(path, "w") as f:
                json.dump(to_save, f, indent=2)
        except Exception:
            pass

    def _load_queue(self):
        path = self._queue_path()
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                saved = json.load(f)
            for entry in saved:
                entry["_local_path"] = os.path.join(self.download_dir, entry.get("filename", ""))
                if entry.get("status") == "waiting":
                    pass
                elif entry.get("status") == "downloading":
                    entry["status"] = "paused"
                # Recalculate progress based on actual file size
                lp = entry.get("_local_path", "")
                if os.path.exists(lp):
                    actual = os.path.getsize(lp)
                    entry["downloaded_bytes"] = actual
                    if entry.get("total_bytes"):
                        entry["progress"] = int(actual * 100 / entry["total_bytes"])
                self._queue.append(entry)
        except Exception:
            pass

    def _stop_signal(self, entry_id):
        if entry_id not in self._stop_events:
            self._stop_events[entry_id] = threading.Event()
        return self._stop_events[entry_id]

    def add(self, url, name):
        entry_id = str(uuid.uuid4())[:8]
        entry = {
            "id": entry_id,
            "url": url,
            "name": name,
            "status": "waiting",
            "progress": 0,
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "error": None,
            "filename": self._safe_filename(name),
            "_local_path": os.path.join(self.download_dir, self._safe_filename(name)),
        }
        with self._lock:
            self._queue.append(entry)
            self._stop_events[entry_id] = threading.Event()
        self._save_queue()
        self._ensure_running()
        return entry

    def _safe_filename(self, name):
        return safe_filename(name)

    def _ensure_running(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._process, daemon=True)
            self._thread.start()

    def _process(self):
        while True:
            with self._lock:
                pending = [e for e in self._queue if e["status"] == "waiting"]
                if not pending:
                    break
                entry = pending[0]
                entry["status"] = "downloading"
            try:
                self._do_download(entry)
            except Exception as e:
                with self._lock:
                    if entry["status"] == "downloading":
                        entry["status"] = "failed"
                        entry["error"] = str(e)
                self._save_queue()
            time.sleep(1)

    def _do_download(self, entry):
        eid = entry["id"]
        local_path = os.path.join(self.download_dir, entry["filename"])
        entry["_local_path"] = local_path

        stop = self._stop_signal(eid)
        if stop.is_set():
            stop.clear()
            return

        resume_bytes = 0
        mode = "wb"
        headers = {}
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            resume_bytes = os.path.getsize(local_path)
            mode = "ab"
            headers["Range"] = f"bytes={resume_bytes}-"

        resp = requests.get(entry["url"], stream=True, timeout=(5, 30), headers=headers)
        entry["_response"] = resp

        if stop.is_set():
            resp.close()
            stop.clear()
            return

        if resp.status_code == 206:
            total = int(resp.headers.get("content-length", 0)) + resume_bytes
        else:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            if mode == "ab":
                mode = "wb"
                resume_bytes = 0

        entry["total_bytes"] = total
        downloaded = resume_bytes

        with open(local_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if stop.is_set():
                    resp.close()
                    stop.clear()
                    self._save_queue()
                    return
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    with self._lock:
                        entry["downloaded_bytes"] = downloaded
                        if total:
                            entry["progress"] = int(downloaded * 100 / total)
                    if downloaded % (8192 * 100) == 0:
                        self._save_queue()

        with self._lock:
            if entry["status"] == "downloading":
                entry["status"] = "completed"
                entry["progress"] = 100
                entry["downloaded_bytes"] = total
        self._save_queue()

    def pause(self, entry_id):
        with self._lock:
            entry = next((e for e in self._queue if e["id"] == entry_id), None)
            if entry and entry["status"] == "downloading":
                entry["status"] = "paused"
                self._stop_signal(entry_id).set()
        if entry and entry["status"] == "paused":
            self._save_queue()
            return True
        return False

    def resume(self, entry_id):
        with self._lock:
            entry = next((e for e in self._queue if e["id"] == entry_id), None)
            if entry and entry["status"] == "paused":
                entry["status"] = "waiting"
                ev = self._stop_events.get(entry_id)
                if ev:
                    ev.clear()
        if entry and entry["status"] == "waiting":
            self._save_queue()
            self._ensure_running()
            return True
        return False

    def cancel(self, entry_id):
        local_path = None
        resp_to_close = None
        with self._lock:
            entry = next((e for e in self._queue if e["id"] == entry_id), None)
            if entry:
                local_path = entry.get("_local_path")
                resp_to_close = entry.get("_response")
                ev = self._stop_events.get(entry_id)
                if ev is None:
                    ev = threading.Event()
                    self._stop_events[entry_id] = ev
                ev.set()
                self._queue = [e for e in self._queue if e["id"] != entry_id]
                self._stop_events.pop(entry_id, None)
        if resp_to_close:
            try:
                resp_to_close.close()
            except Exception:
                pass
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        self._save_queue()
        return True

    def retry(self, entry_id):
        local_path = None
        with self._lock:
            entry = next((e for e in self._queue if e["id"] == entry_id), None)
            if entry and entry["status"] in ("failed", "completed", "paused"):
                local_path = entry.get("_local_path")
                entry["status"] = "waiting"
                entry["progress"] = 0
                entry["downloaded_bytes"] = 0
                entry["error"] = None
                self._ensure_running()
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        self._save_queue()
        return True

    def get_queue(self):
        with self._lock:
            # Strip internal fields for API responses
            result = []
            for e in self._queue:
                entry = {k: v for k, v in e.items() if k not in ("_local_path", "_response")}
                result.append(entry)
            return result

    def clear_completed(self):
        with self._lock:
            kept = []
            for e in self._queue:
                if e["status"] in ("waiting", "downloading", "paused"):
                    kept.append(e)
                else:
                    self._stop_events.pop(e["id"], None)
            self._queue = kept
        self._save_queue()

    def update_dir(self, new_dir):
        self.download_dir = new_dir


dl_manager = DownloadManager(DOWNLOAD_DIR)


@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip().lower()
    sort_by = request.args.get("sort_by", "name")
    sort_order = request.args.get("sort_order", "asc")
    per_page = 50

    filtered = GAMES
    if search:
        filtered = [
            g for g in GAMES
            if search in g["name"].lower()
            or search in g["title_id"].lower()
            or search in g["region"].lower()
        ]

    reverse = sort_order == "desc"
    if sort_by == "size":
        filtered.sort(key=lambda g: g["size"], reverse=reverse)
    else:
        filtered.sort(key=lambda g: g["name"].lower(), reverse=reverse)

    local_files = get_downloaded_files()
    downloaded_names = set()
    partial_names = set()
    for g in filtered:
        fn = safe_filename(g["name"])
        actual_size = local_files.get(fn)
        if actual_size is not None:
            expected = g.get("size", 0)
            if expected and actual_size >= expected:
                downloaded_names.add(g["name"])
            elif not expected:
                downloaded_names.add(g["name"])
            else:
                partial_names.add(g["name"])

    total = len(filtered)
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_games = filtered[start:end]

    return render_template(
        "index.html",
        games=page_games,
        page=page,
        total_pages=total_pages,
        total=total,
        search=request.args.get("search", ""),
        sort_by=sort_by,
        sort_order=sort_order,
        downloaded_names=downloaded_names,
        partial_names=partial_names,
    )


@app.route("/api/queue/add", methods=["POST"])
def queue_add():
    data = request.get_json()
    url = data.get("url")
    name = data.get("name")
    if not url or not name:
        return jsonify({"error": "url and name required"}), 400
    entry = dl_manager.add(url, name)
    return jsonify(entry)


@app.route("/api/queue")
def queue_status():
    queue = dl_manager.get_queue()
    return jsonify(queue)


@app.route("/api/queue/clear", methods=["POST"])
def queue_clear():
    dl_manager.clear_completed()
    return jsonify({"ok": True})

@app.route("/api/queue/pause", methods=["POST"])
def queue_pause():
    data = request.get_json()
    ok = dl_manager.pause(data.get("id"))
    return jsonify({"ok": ok})

@app.route("/api/queue/resume", methods=["POST"])
def queue_resume():
    data = request.get_json()
    ok = dl_manager.resume(data.get("id"))
    return jsonify({"ok": ok})

@app.route("/api/queue/cancel", methods=["POST"])
def queue_cancel():
    data = request.get_json()
    ok = dl_manager.cancel(data.get("id"))
    return jsonify({"ok": ok})

@app.route("/api/queue/retry", methods=["POST"])
def queue_retry():
    data = request.get_json()
    ok = dl_manager.retry(data.get("id"))
    return jsonify({"ok": ok})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    global config, DOWNLOAD_DIR, dl_manager
    if request.method == "POST":
        data = request.get_json()
        if "download_dir" in data:
            new_dir = data["download_dir"]
            os.makedirs(new_dir, exist_ok=True)
            config["download_dir"] = new_dir
            DOWNLOAD_DIR = new_dir
            dl_manager.update_dir(new_dir)
            save_config(config)
    return jsonify({"download_dir": config["download_dir"]})


@app.route("/api/select-directory")
def select_directory():
    if os.environ.get("DISPLAY") is None and os.environ.get("WAYLAND_DISPLAY") is None and sys.platform != "darwin":
        return jsonify({"path": None, "error": "No display available (headless/Docker)"}), 400
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", 'set folderPath to POSIX path of (choose folder with prompt "Selecciona carpeta de descarga")'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                return jsonify({"path": path})
            return jsonify({"path": None, "error": "No folder selected"}), 400
        elif sys.platform == "linux":
            result = subprocess.run(["zenity", "--file-selection", "--directory"], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return jsonify({"path": result.stdout.strip()})
            return jsonify({"path": None, "error": "No folder selected"}), 400
        else:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askdirectory(title="Selecciona carpeta de descarga")
            root.destroy()
            if path:
                return jsonify({"path": path})
            return jsonify({"path": None, "error": "No folder selected"}), 400
    except Exception as e:
        return jsonify({"path": None, "error": str(e)}), 500


def start_server(host="0.0.0.0", port=5050, debug=None):
    if debug is None:
        debug = os.environ.get("FLASK_DEBUG", "1").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    start_server()
