# Rutracker Magnet Tools

Paquete para Chrome y Python 3.10 o posterior. No requiere instalar paquetes con `pip`.

## 1. Instalar la extensión

1. Descomprime el ZIP en una carpeta permanente.
2. En Chrome, abre `chrome://extensions` y activa **Modo de desarrollador**.
3. Pulsa **Cargar descomprimida** y selecciona la carpeta `chrome-extension`.
4. Copia el ID que Chrome muestra para la extensión.

## 2. Iniciar el helper

El helper permite que la extensión descargue el contenido con `download_magnet` y obtenga el `.torrent`. Inicia el helper y deja abierta su ventana:

- **macOS:** abre `start_helper_mac.command` y pega el ID de la extensión.
- **Windows:** abre `start_helper_windows.bat` y pega el ID.
- **Linux:** ejecuta `python3 torrent_helper.py --extension-id ID_DE_LA_EXTENSION`.

Si Chrome pregunta si la extensión puede acceder a la red local, permite el acceso.

## 3. Usar

Abre la página que contiene los magnet links y pulsa el icono de la extensión. Cada enlace permite copiar el magnet, descargar su `.torrent` o descargar el contenido completo. El contenido se guarda en `descargas/` junto a este README. El popup muestra porcentaje, bytes, velocidad y peers durante la descarga.

## Requisitos

- **Python 3.10+** para el helper.
- **aria2c**, solo para el botón **Descargar .torrent**. En macOS se instala con `brew install aria2`.
- La descarga del contenido usa el cliente BitTorrent incluido en el paquete y requiere conectividad con peers.

El helper escucha únicamente en `127.0.0.1` y acepta solicitudes del ID de esta extensión. No incluye el entorno virtual ni archivos descargados del equipo donde se creó el paquete.
