#!/usr/bin/env python3
"""Obtiene el archivo .torrent asociado a un magnet usando aria2c."""

import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from btclient.client import BitTorrentClient


def validate_magnet(value: str) -> str:
    magnet = value.strip()
    parsed = urlsplit(magnet)
    if parsed.scheme.lower() != "magnet" or not parse_qs(parsed.query).get("xt"):
        raise ValueError("Indica un magnet válido que incluya el parámetro xt.")
    return magnet

async def download_magnet(magnet: str, timeout: float = 300, progress_callback=None):
    magnet = validate_magnet(magnet)
    client = BitTorrentClient(save_path="./descargas", port=0)
    task = asyncio.create_task(client.download(magnet))
    try:
        while not task.done():
            if progress_callback:
                progress_callback(client.get_progress())
            await asyncio.wait({task}, timeout=1)
        await task
    finally:
        if progress_callback:
            progress_callback(client.get_progress())

def convert_magnet(magnet: str, output: str | None = None, timeout: float = 300) -> Path:
    magnet = validate_magnet(magnet)
    aria2c = shutil.which("aria2c")
    if not aria2c:
        raise RuntimeError(
            "No se encontró aria2c. Instálalo, por ejemplo con «brew install aria2», y vuelve a intentarlo."
        )

    destination = None
    if output:
        destination = Path(output).expanduser()
        if destination.suffix.lower() != ".torrent":
            destination = destination.with_name(destination.name + ".torrent")
        if not destination.is_absolute():
            destination = Path.cwd() / destination
        if not destination.parent.is_dir():
            raise ValueError(f"No existe la carpeta de destino: {destination.parent}")
        if destination.exists():
            raise ValueError(f"El archivo ya existe: {destination}")

    with tempfile.TemporaryDirectory(prefix="magnet-to-torrent-") as temp_dir:
        command = [
            aria2c,
            "--bt-metadata-only=true",
            "--bt-save-metadata=true",
            "--seed-time=0",
            "--summary-interval=0",
            "--console-log-level=warn",
            "--bt-tracker-connect-timeout=10",
            "--bt-tracker-timeout=15",
            f"--dir={temp_dir}",
            magnet,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Se agotó el tiempo de espera ({timeout:g} s).") from error

        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            if details:
                details = "\n" + "\n".join(details.splitlines()[-8:])
            raise RuntimeError(f"aria2c no pudo obtener los metadatos.{details}")

        torrent_files = list(Path(temp_dir).glob("*.torrent"))
        if not torrent_files:
            raise RuntimeError("aria2c terminó, pero no generó ningún archivo .torrent.")

        source = torrent_files[0]
        if destination is None:
            destination = Path.cwd() / source.name
        if destination.exists():
            raise ValueError(f"El archivo ya existe: {destination}")

        shutil.copy2(source, destination)

    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Obtiene el .torrent desde un magnet sin descargar los archivos del torrent."
    )
    parser.add_argument("magnet", help="enlace magnet")
    parser.add_argument(
        "-o", "--output", help="ruta del archivo .torrent (por defecto, el nombre generado por aria2c)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="tiempo máximo para obtener los metadatos en segundos (por defecto: 300)",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout debe ser mayor que cero")

    try:
        output = convert_magnet(args.magnet, args.output, args.timeout)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Guardado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
