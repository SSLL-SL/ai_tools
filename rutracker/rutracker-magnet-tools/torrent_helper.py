#!/usr/bin/env python3
"""Puente local para que la extensión obtenga .torrent desde enlaces magnet."""

import argparse
import asyncio
import json
import re
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4

from magnet_to_torrent import convert_magnet, download_magnet, validate_magnet


MAX_REQUEST_SIZE = 32 * 1024
MAX_TORRENT_SIZE = 16 * 1024 * 1024
DOWNLOAD_JOBS = {}
DOWNLOAD_JOBS_LOCK = Lock()


def run_download_job(job_id: str, magnet: str) -> None:
    def update_progress(progress: dict) -> None:
        with DOWNLOAD_JOBS_LOCK:
            job = DOWNLOAD_JOBS.get(job_id)
            if job is not None:
                job.update(
                    progress=progress.get("progress", 0.0),
                    downloaded=progress.get("downloaded", 0),
                    total=progress.get("total", 0),
                    peers=progress.get("peers", 0),
                    speed=progress.get("speed", 0.0),
                    phase="metadata" if not progress.get("total") else "download",
                    updated=time.time(),
                )

    try:
        asyncio.run(download_magnet(magnet, progress_callback=update_progress))
    except Exception as error:
        with DOWNLOAD_JOBS_LOCK:
            DOWNLOAD_JOBS[job_id].update(status="failed", error=str(error), updated=time.time())
        print(f"Descarga {job_id} fallida: {error}", flush=True)
    else:
        destination = str(Path("descargas").resolve())
        with DOWNLOAD_JOBS_LOCK:
            DOWNLOAD_JOBS[job_id].update(status="completed", destination=destination, updated=time.time())
        print(f"Descarga {job_id} completada en {destination}", flush=True)


class TorrentRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        pass

    def _is_allowed_extension(self) -> bool:
        return self.headers.get("Origin") == self.server.extension_origin

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.server.extension_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self._is_allowed_extension():
            self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not self._is_allowed_extension():
            self.send_response(403)
            self.end_headers()
            return
        if self.path not in ("/convert", "/download", "/download/status"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        self._send_json(405, {"error": "Usa POST /download/status para consultar la descarga."})

    def do_POST(self) -> None:
        if not self._is_allowed_extension():
            self.send_response(403)
            self.end_headers()
            return
        if self.path not in ("/convert", "/download", "/download/status"):
            self._send_json(404, {"error": "Ruta no encontrada."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Longitud de solicitud no válida."})
            return
        if length <= 0 or length > MAX_REQUEST_SIZE:
            self._send_json(413, {"error": "La solicitud está vacía o es demasiado grande."})
            return

        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Envía un objeto JSON.")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "Envía una solicitud JSON válida."})
            return
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return

        if self.path == "/download/status":
            job_id = payload.get("job_id")
            if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
                self._send_json(400, {"error": "ID de descarga no válido."})
                return
            with DOWNLOAD_JOBS_LOCK:
                job = DOWNLOAD_JOBS.get(job_id)
                result = dict(job) if job else None
            if result is None:
                self._send_json(404, {"error": "Descarga no encontrada."})
                return
            self._send_json(200, result)
            return

        try:
            magnet = payload.get("magnet")
            if not isinstance(magnet, str):
                raise ValueError("Falta el enlace magnet.")
            magnet = validate_magnet(magnet)
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return

        if self.path == "/download":
            now = time.time()
            with DOWNLOAD_JOBS_LOCK:
                expired = [
                    job_id
                    for job_id, job in DOWNLOAD_JOBS.items()
                    if job["status"] in ("completed", "failed") and now - job["updated"] > 3600
                ]
                for job_id in expired:
                    DOWNLOAD_JOBS.pop(job_id, None)

                job_id = uuid4().hex
                DOWNLOAD_JOBS[job_id] = {
                    "status": "downloading",
                    "phase": "metadata",
                    "progress": 0.0,
                    "downloaded": 0,
                    "total": 0,
                    "peers": 0,
                    "speed": 0.0,
                    "updated": now,
                }

            Thread(target=run_download_job, args=(job_id, magnet), daemon=True).start()
            self._send_json(202, {"job_id": job_id, "status": "downloading"})
            return

        try:
            with tempfile.TemporaryDirectory(prefix="magnet-extension-") as temp_dir:
                destination = Path(temp_dir) / "metadata.torrent"
                torrent_path = convert_magnet(magnet, str(destination), timeout=300)
                torrent_data = torrent_path.read_bytes()

            if not torrent_data or len(torrent_data) > MAX_TORRENT_SIZE:
                raise ValueError("El archivo .torrent está vacío o supera el límite de tamaño.")
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        except RuntimeError as error:
            self._send_json(502, {"error": str(error)})
            return
        except OSError as error:
            self._send_json(500, {"error": str(error)})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-bittorrent")
        self.send_header("Content-Length", str(len(torrent_data)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(torrent_data)


class TorrentHelperServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, extension_id: str):
        self.extension_origin = f"chrome-extension://{extension_id}"
        super().__init__(address, handler)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inicia el servicio local requerido por la extensión para descargar desde magnets."
    )
    parser.add_argument(
        "--extension-id",
        required=True,
        help="ID de la extensión mostrado en chrome://extensions",
    )
    parser.add_argument("--port", type=int, default=8765, help="puerto local (por defecto: 8765)")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-p]{32}", args.extension_id):
        parser.error("--extension-id debe ser el ID de 32 letras mostrado por Chrome")
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535")

    server = TorrentHelperServer(("127.0.0.1", args.port), TorrentRequestHandler, args.extension_id)
    print(f"Helper listo en http://127.0.0.1:{args.port} (Ctrl+C para salir)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nHelper detenido.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
