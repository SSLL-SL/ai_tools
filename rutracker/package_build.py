#!/usr/bin/env python3
"""Build a curated, portable ZIP without including local data or virtualenvs."""

from importlib.util import find_spec
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "rutracker-magnet-tools.zip"
PACKAGE_NAME = "rutracker-magnet-tools"


def add_file(archive: ZipFile, source: Path, archive_path: str, executable: bool = False) -> None:
    info = ZipInfo(f"{PACKAGE_NAME}/{archive_path}")
    info.compress_type = ZIP_DEFLATED
    info.external_attr = ((0o100755 if executable else 0o100644) << 16)
    archive.writestr(info, source.read_bytes())


def main() -> None:
    spec = find_spec("btclient")
    if spec is None or spec.origin is None:
        raise SystemExit(
            "No encuentro btclient. Ejecuta este empaquetador con el Python donde está instalado el cliente."
        )
    btclient_dir = Path(spec.origin).resolve().parent
    required_client_file = btclient_dir / "client.py"
    if not required_client_file.is_file():
        raise SystemExit(f"No encuentro el código de btclient en {btclient_dir}")

    with ZipFile(ARCHIVE, "w", compression=ZIP_DEFLATED) as archive:
        add_file(archive, ROOT / "PACKAGE_README.md", "README.md")
        add_file(archive, ROOT / "extract_magnets.py", "extract_magnets.py")
        add_file(archive, ROOT / "magnet_to_torrent.py", "magnet_to_torrent.py")
        add_file(archive, ROOT / "torrent_helper.py", "torrent_helper.py")
        add_file(archive, ROOT / "start_helper_mac.command", "start_helper_mac.command", executable=True)
        add_file(archive, ROOT / "start_helper_windows.bat", "start_helper_windows.bat")

        for source in sorted((ROOT / "chrome-extension").iterdir()):
            if source.is_file():
                add_file(archive, source, f"chrome-extension/{source.name}")

        for source in sorted(btclient_dir.glob("*.py")):
            add_file(archive, source, f"btclient/{source.name}")

    with ZipFile(ARCHIVE) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise SystemExit(f"El ZIP no pasó la verificación: {bad_member}")

    print(f"Paquete creado: {ARCHIVE}")
    print(f"Tamaño: {ARCHIVE.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
