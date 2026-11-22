# Contexto del proyecto

## Objetivo

Cliente BitTorrent de consola y biblioteca Python, implementado sin dependencias de ejecución externas. El usuario eligió Python y pidió implementar el protocolo en el proyecto.

## Estado actual

- CLI: `main.py` (`python3 main.py ...`) y comando instalado `bittorrent-cli`.
- Paquete importable: `btclient`; instalación editable para desarrollo con `python3 -m pip install -e /ruta/a/bittorrent`.
- Admite archivos `.torrent` y magnets BitTorrent v1 (BTIH hexadecimal o Base32).
- Descubre peers por trackers HTTP/HTTPS y UDP, DHT IPv4 (BEP 5) y PEX (BEP 11).
- Obtiene metadata de magnets mediante BEP 9, valida el info-hash SHA-1 y luego descarga piezas.
- Verifica cada pieza con SHA-1 y guarda/reanuda estado entre ejecuciones en `<destino>/.btclient/`.
- Soporta torrents de uno o varios archivos.
- Última verificación: 14 pruebas de `unittest` pasan; incluyen tests locales simulados de trackers, peers, DHT, PEX, magnet y reanudación.

## Uso

```bash
python3 main.py archivo.torrent -o ./descargas
python3 main.py 'magnet:?xt=urn:btih:<hash>&dn=nombre' -o ./descargas
python3 main.py archivo.torrent --list
python3 -m unittest discover -s tests -v
```

Uso como API:

```python
import asyncio
from btclient.client import BitTorrentClient

async def main():
    client = BitTorrentClient(save_path="./descargas")
    task = asyncio.create_task(client.download("archivo.torrent"))  # También acepta magnet URI.
    while not task.done():
        print(client.get_progress())
        await asyncio.sleep(1)
    await task  # Propaga errores.

asyncio.run(main())
```

## Estructura principal

- `btclient/bencode.py`: parser/codificador bencode; conserva el `info` original para el hash.
- `btclient/torrent.py`: parseo y validación de metadatos, hashes y rutas.
- `btclient/magnet.py`: parseo de magnet BTIH.
- `btclient/tracker.py`: announce HTTP(S)/UDP.
- `btclient/dht.py`: KRPC, lookup y announce_peer.
- `btclient/peer.py`: conexión TCP, handshake BitTorrent y extensiones BEP 10.
- `btclient/pex.py`: compact peers BEP 11.
- `btclient/client.py`: metadata exchange BEP 9, descubrimiento, piezas y coordinación.
- `btclient/storage.py`, `btclient/resume.py`: persistencia de archivos y checkpoints.
- `tests/`: pruebas locales de integración y unitarias.

## Límites conocidos

- No admite magnet BitTorrent v2 (`btmh`).
- DHT solo IPv4; no se persiste la tabla de nodos.
- Magnets requieren peers accesibles compatibles con BEP 9.
- No hay pruebas unitarias para toda la interoperabilidad contra implementaciones externas; trackers, NAT/firewall y disponibilidad de peers pueden afectar descargas reales.

## Instrucciones para continuar

Leer primero `README.md` y este archivo. Mantener las pruebas locales pasando (`python3 -m unittest discover -s tests -v`) al cambiar el protocolo. No eliminar ni modificar torrents/archivos de descarga del directorio sin autorización.
