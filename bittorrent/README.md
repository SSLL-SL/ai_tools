# BitTorrent CLI

Cliente BitTorrent de consola en Python, implementado sin bibliotecas de terceros. Descarga desde archivos `.torrent`, descubre peers mediante trackers HTTP/HTTPS o UDP y DHT (BEP 5), e intercambia peers mediante PEX (BEP 11).

## Requisitos

- Python 3.10 o posterior
- Conexión a Internet y un `.torrent` o enlace magnet; usa trackers o DHT para hallar peers

No hay que instalar paquetes con `pip`.

## Uso

```bash
python3 main.py archivo.torrent -o ./descargas
```

También acepta enlaces magnet BTIH (hash hexadecimal o Base32) y obtiene los metadatos de peers compatibles con BEP 9:

```bash
python3 main.py 'magnet:?xt=urn:btih:<info-hash>&dn=nombre&tr=<tracker-url>' -o ./descargas
```

Ver el contenido del torrent sin descargar:

```bash
python3 main.py archivo.torrent --list
```

## Usarlo desde otro proyecto Python

Instálalo en el entorno virtual del otro proyecto en modo editable:

```bash
python3 -m pip install -e /ruta/a/bittorrent
```

Después puedes importar el cliente y pasarle la ruta `.torrent` o el enlace magnet:

```python
import asyncio
from btclient.client import BitTorrentClient

async def main():
    client = BitTorrentClient(save_path="./descargas")
    task = asyncio.create_task(client.download("magnet:?xt=urn:btih:<hash>"))
    while not task.done():
        print(client.get_progress())
        await asyncio.sleep(1)
    await task  # Propaga errores de la descarga.

asyncio.run(main())
```

Opciones útiles: `--port 6881` selecciona el puerto de escucha/anuncio y `--verbose` muestra información de trackers y peers. Si ese puerto ya está ocupado, el cliente selecciona uno libre. DHT requiere conectividad UDP; PEX empieza a aportar peers después de conectarse a un peer compatible.

La descarga se reanuda automáticamente al ejecutar otra vez el mismo `.torrent` con el mismo directorio de destino. El estado queda en `./descargas/.btclient/`; antes de reanudar, el cliente verifica las piezas guardadas con SHA-1 y vuelve a descargar las que estén incompletas o dañadas.

Ejecutar las pruebas locales, incluido un intercambio completo con un peer simulado:

```bash
python3 -m unittest discover -s tests -v
```

## Límites actuales

- La DHT implementa nodos IPv4; no implementa DHT sobre IPv6 ni persistencia de la tabla de nodos.
- Magnet requiere un peer que soporte el protocolo de extensiones y metadata exchange (BEP 9).
