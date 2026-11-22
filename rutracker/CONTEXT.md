# Contexto del proyecto

## Proyecto

Herramienta local para extraer magnet links de páginas web y usarlos desde una extensión Chrome. Carpeta de trabajo:
`/Users/ricardogarcia/Documents/rutracker`

El proyecto actual **no es Rust**: la extensión está en JavaScript (Chrome Manifest V3) y el helper en Python. Si el usuario decide migrarlo a Rust, habría que reescribir el helper.

## Archivos principales

- `extract_magnets.py`: extrae magnets de una URL, admite cookies Netscape o HTML guardado con `--html-file`.
- `magnet_to_torrent.py`: valida magnets, obtiene `.torrent` con aria2c, y tiene `async download_magnet(...)` que llama a `btclient.BitTorrentClient`.
- `torrent_helper.py`: servicio local HTTP escuchando en `127.0.0.1:8765`, restringido al origen de la extensión. Endpoints:
  - `POST /convert`: devuelve datos `.torrent`.
  - `POST /download`: inicia tarea asíncrona de descarga completa.
  - `POST /download/status`: devuelve estado/progreso.
- `chrome-extension/`: extensión que inspecciona el DOM de la pestaña activa, copia magnets, guarda `.torrent`, descarga el fichero y muestra porcentaje, bytes, velocidad y peers.
- `PACKAGE_README.md`, `start_helper_mac.command`, `start_helper_windows.bat`: instrucciones y launchers.
- `package_build.py`: genera `rutracker-magnet-tools.zip`, empaquetando también las fuentes del paquete `btclient`.
- `rutracker-magnet-tools.zip`: paquete portable ya generado.

## Uso local

Instalar/cargar `chrome-extension/` desde `chrome://extensions` con modo desarrollador, copiar el ID de extensión y arrancar desde la raíz:

```bash
./venv/bin/python torrent_helper.py --extension-id ID_DE_LA_EXTENSION
```

Recargar extensión después de cambios en JavaScript/manifiesto. Reiniciar helper después de cambios Python. La descarga completa se guarda en `descargas/` relativo al directorio desde el que corre el helper. `aria2c` es requisito solo para descargar `.torrent`.

Para regenerar ZIP:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python package_build.py
```

El empaquetador busca `btclient` en el entorno activo; el venv del proyecto tiene una instalación editable que apunta a `/Users/ricardogarcia/Documents/bittorrent/btclient`. El ZIP incluye el código fuente de `btclient`, no el venv.

## Implementación/problemas relevantes

- RuTracker responde HTTP 403 a peticiones de servidor; extracción funciona guardando la página como HTML y pasando `--html-file`, o desde la extensión Chrome sobre la pestaña ya abierta.
- Se solucionó el 403 al consultar estado usando `POST /download/status` en lugar de GET, porque se valida el `Origin` de Chrome.
- `download_magnet` configura `BitTorrentClient(..., port=0)` para pedir puerto efímero y evitar conflictos en 6881.
- En el popup, `readJsonResponse` convierte respuestas vacías/no JSON en errores legibles con HTTP status.
- El progreso se obtiene pasando `progress_callback` a `download_magnet`; llama `get_progress()` aproximadamente cada segundo.
- Se hicieron pruebas de sintaxis, cliente/helper simulado, CORS/flujo de progreso y ZIP.

## Privacidad / cuidado

No incluir ni revelar `cookies.txt`; contiene credenciales de sesión. No incluir en distribuciones HTML guardados, `.torrent`, `descargas/`, `.DS_Store`, `venv/` o `__pycache__`. El ZIP existente se validó como 22 archivos y libre de esos datos locales.

## Último intercambio

El usuario preguntó cómo compilar Rust; se respondió con comandos Cargo (`cargo check`, `cargo build`, `cargo run`, `cargo build --release`) y se aclaró que el proyecto actual no es Rust. Después pidió “guarda el contexto”; este archivo se creó para facilitar la continuación.
