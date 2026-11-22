#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys

from btclient.client import BitTorrentClient
from btclient.torrent import parse_torrent_file


def format_size(size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def print_progress(progress):
    pct = progress['progress'] * 100
    bar_length = 30
    filled = int(bar_length * pct / 100)
    bar = "=" * filled + (">" if filled < bar_length else "") + " " * max(0, bar_length - filled - 1)

    downloaded = format_size(progress['downloaded'])
    total = format_size(progress['total'])
    peers = progress['peers']

    speed = format_size(progress["speed"]) + "/s"
    print(f"\r[{bar}] {pct:.1f}% | {downloaded} / {total} | {speed} | Peers: {peers}", end="", flush=True)


def list_contents(torrent_path):
    info = parse_torrent_file(torrent_path)
    print(f"Nombre: {info.name}")
    print(f"Tamaño total: {format_size(info.total_size)}")
    print(f"Piezas: {info.num_pieces} ({format_size(info.piece_length)} c/u)")
    print(f"Trackers: {', '.join(info.trackers) if info.trackers else 'Ninguno'}")
    print(f"Archivos ({len(info.files)}):")
    for f in info.files:
        print(f"  {f.path} ({format_size(f.length)})")


async def download(torrent_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    client = BitTorrentClient(save_path=output_dir)

    print(f"Descargando: {'magnet link' if torrent_path.lower().startswith('magnet:') else torrent_path}")
    print(f"Destino: {output_dir}")
    print("Presiona Ctrl+C para detener\n")

    download_task = asyncio.create_task(client.download(torrent_path))

    try:
        while not download_task.done():
            print_progress(client.get_progress())
            await asyncio.sleep(1)

        await download_task
        print_progress(client.get_progress())
        print("\n\nDescarga completada!")
    except KeyboardInterrupt:
        print("\n\nDeteniendo descarga...")
        client.running = False
        download_task.cancel()
        try:
            await download_task
        except asyncio.CancelledError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Cliente BitTorrent de consola",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="Ruta al archivo .torrent o un enlace magnet")
    parser.add_argument(
        "-o", "--output", default=".", help="Directorio de destino (default: actual)"
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="Listar contenido sin descargar"
    )
    parser.add_argument("--port", type=int, default=6881, help="Puerto anunciado a los peers (default: 6881)")
    parser.add_argument("--verbose", action="store_true", help="Mostrar mensajes de diagnóstico")

    args = parser.parse_args()

    is_magnet = args.source.lower().startswith("magnet:")
    if args.list and is_magnet:
        print("Error: --list solo funciona con archivos .torrent", file=sys.stderr)
        sys.exit(1)
    if not is_magnet and not os.path.isfile(args.source):
        print(f"Error: No se encuentra el archivo '{args.source}'", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        if args.list:
            list_contents(args.source)
        else:
            asyncio.run(download(args.source, args.output))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
