# bittorrent-cli

Port a **Rust** del paquete `rutracker-magnet-tools`: un cliente BitTorrent de
consola con DHT, PEX, reanudación, un helper HTTP local para la extensión de
Chrome y utilidades para convertir magnets y extraer enlaces magnet de páginas
web.

## Binarios

| Binario             | Original en Python     | Descripción                                                       |
| ------------------- | ---------------------- | ----------------------------------------------------------------- |
| `btclient`          | `main.py`              | Descarga un `.torrent` o un magnet, o lista su contenido.         |
| `magnet-to-torrent` | `magnet_to_torrent.py` | Obtiene el `.torrent` de un magnet usando `aria2c`.               |
| `torrent-helper`    | `torrent_helper.py`    | Servicio HTTP local (solo `127.0.0.1`) que usa la extensión.      |
| `extract-magnets`   | `extract_magnets.py`   | Extrae enlaces magnet de una URL o de un HTML guardado.           |

## Compilar

Se necesita el toolchain de Rust (`rustup`). En **Windows** hace falta además
**Visual Studio Build Tools** con la carga de trabajo *Desarrollo para el
escritorio con C++* (aportan `link.exe`, `ml64.exe`, etc.).

> **Nota sobre Smart App Control**: si Windows bloquea `rustc.exe` con
> `os error 4551` («Una directiva de Control de aplicaciones bloqueó este
> archivo»), desactiva *Smart App Control* en
> `Seguridad de Windows → Control de aplicaciones y navegador` y vuelve a
> compilar.

```powershell
cargo build --release
```

Los ejecutables quedan en `target\release\`:

```text
btclient.exe
magnet-to-torrent.exe
torrent-helper.exe
extract-magnets.exe
```

En Linux/macOS:

```bash
cargo build --release
```

## Uso

### btclient

```bash
# Descargar un .torrent
btclient archivo.torrent -o descargas --port 6881

# Descargar desde un magnet (los metadatos se piden por extensión ut_metadata)
btclient "magnet:?xt=urn:btih:..."

# Ver el contenido sin descargar
btclient archivo.torrent --list

# Mensajes de diagnóstico
btclient archivo.torrent --verbose
```

### magnet-to-torrent

Requiere `aria2c` en el `PATH` (en macOS: `brew install aria2`).

```bash
magnet-to-torrent "magnet:?xt=urn:btih:..." -o salida.torrent --timeout 300
```

### extract-magnets

```bash
extract-magnets https://pagina-con-magnets
extract-magnets https://pagina-con-magnets --cookies cookies.txt
extract-magnets --html-file pagina.html
```

## Helper + extensión de Chrome

1. Carga la carpeta `chrome-extension` del paquete original en
   `chrome://extensions` (Modo de desarrollador → *Cargar descomprimida*).
2. Copia el ID que muestra Chrome.
3. Inicia el helper:

   ```bash
   torrent-helper --extension-id <ID_DE_LA_EXTENSION> --port 8765
   ```

   o ejecuta `start_helper_windows.bat` en Windows.

El helper escucha únicamente en `127.0.0.1`, acepta solicitudes solo del origen
`chrome-extension://<ID>` (CORS con `Access-Control-Allow-Private-Network`) y
guarda las descargas completas en `./descargas`, relativo al directorio de
trabajo desde el que se inicia.

## Estructura

```text
src/
  lib.rs          Índice de módulos y reexportes.
  error.rs        Error y Result unificados.
  bencode.rs      Benencode escrito a mano (preserva los bytes de `info`).
  torrent.rs      Lectura de .torrent, info-hash y verificación SHA-1.
  storage.rs      Lectura/escritura de piezas en disco.
  resume.rs       Punto de control de reanudación en `.btclient/`.
  magnet.rs       Análisis de enlaces magnet.
  pex.rs          Codificación/decodificación de peer exchange (BEP 11).
  tracker.rs      Anuncio HTTP/UDP a trackers.
  peer.rs         Conexión con un peer: handshake y mensajes.
  dht.rs          Cliente DHT (BEP 5).
  client.rs       Motor de descarga (peers, trackers, DHT, PEX, metadatos).
  aria2.rs        Conversión de magnet a .torrent y descarga vía aria2c/cliente.
  extract.rs      Descarga de páginas y extracción de magnets.
  helper.rs       Servidor HTTP local para la extensión.
  bin/            Los cuatro ejecutables.
```
