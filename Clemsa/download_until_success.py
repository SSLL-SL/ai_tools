"""Download the files listed in a txt file, retrying every 10 minutes until each one succeeds."""

import argparse
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests


CHUNK_SIZE = 1024 * 1024
RETRY_INTERVAL_SECONDS = 10 * 60


def read_urls(list_file: Path) -> list[str]:
    urls = []
    seen = set()

    for line_number, line in enumerate(
        list_file.read_text(encoding="utf-8").splitlines(), start=1
    ):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if not entry.startswith(("http://", "https://")):
            print(f"Línea {line_number} ignorada, no es una URL: {entry}", flush=True)
            continue
        if entry in seen:
            print(f"Línea {line_number} ignorada, URL duplicada: {entry}", flush=True)
            continue
        seen.add(entry)
        urls.append(entry)

    return urls


def default_destination(url: str) -> str:
    return Path(unquote(urlparse(url).path)).name or "downloaded_file"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = destination.with_name(destination.name + ".part")

    try:
        with requests.get(url, stream=True, timeout=(20, 60)) as response:
            response.raise_for_status()
            with temporary_file.open("wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        file.write(chunk)

        temporary_file.replace(destination)
    except Exception:
        temporary_file.unlink(missing_ok=True)
        raise


def download_until_success(url: str, destination: Path) -> bool:
    attempt = 1
    while True:
        print(f"[{destination.name}] Intento {attempt}...", flush=True)
        try:
            download(url, destination)
            print(f"[{destination.name}] Descarga completada.", flush=True)
            return True
        except requests.RequestException as error:
            print(f"[{destination.name}] No se pudo descargar: {error}", flush=True)
        except OSError as error:
            print(f"[{destination.name}] Error al guardar el archivo: {error}", flush=True)

        print(f"[{destination.name}] Nuevo intento en 10 minutos.", flush=True)
        attempt += 1
        time.sleep(RETRY_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga los archivos de una lista txt (una URL por línea) y reintenta "
            "cada 10 minutos hasta conseguir cada uno."
        )
    )
    parser.add_argument("lista", type=Path, help="fichero txt con una URL por línea")
    parser.add_argument(
        "--destino",
        type=Path,
        default=Path("."),
        help="carpeta donde guardar los archivos (por defecto, la actual)",
    )
    args = parser.parse_args()

    if not args.lista.is_file():
        parser.error(f"no se encuentra el fichero de lista: {args.lista}")

    urls = read_urls(args.lista)
    if not urls:
        print("La lista no contiene ninguna URL.", flush=True)
        return

    print(f"{len(urls)} URL(s) en la lista. Destino: {args.destino}", flush=True)

    completed = 0
    for index, url in enumerate(urls, start=1):
        destination = args.destino / default_destination(url)

        if destination.is_file() and destination.stat().st_size > 0:
            print(
                f"({index}/{len(urls)}) {destination.name} ya existe, se omite.",
                flush=True,
            )
            completed += 1
            continue

        print(f"({index}/{len(urls)}) Descargando {url}", flush=True)
        download_until_success(url, destination)
        completed += 1

    print(f"Terminadas {completed}/{len(urls)} descargas.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.", flush=True)