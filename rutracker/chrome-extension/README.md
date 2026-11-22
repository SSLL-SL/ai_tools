# Extensión de Chrome: extractor de magnet links

## Instalar

1. Abre `chrome://extensions` en Chrome.
2. Activa **Modo de desarrollador**.
3. Pulsa **Cargar descomprimida**.
4. Selecciona la carpeta `chrome-extension` de este proyecto.

## Usar

Para extraer magnets, abre la página, pulsa el icono de la extensión y copia un enlace individual o todos a la vez. **Actualizar** vuelve a escanear la pestaña.

## Descargar `.torrent` o el fichero completo

El helper usa `aria2c` para obtener solo los metadatos `.torrent`; **Descargar fichero** ejecuta la función `download_magnet` y descarga el contenido completo en `descargas/`. Durante la descarga, el popup muestra porcentaje, bytes, velocidad y peers.

1. En `chrome://extensions`, copia el **ID** que Chrome muestra para esta extensión.
2. Desde la carpeta raíz del proyecto, inicia el helper y déjalo ejecutándose:

   ```bash
   ./venv/bin/python torrent_helper.py --extension-id ID_DE_LA_EXTENSION
   ```

3. Vuelve a la pestaña, abre la extensión y pulsa **Descargar .torrent** o **Descargar fichero** junto al magnet deseado.

El fichero se guarda en `descargas/` dentro de la carpeta desde la que ejecutaste el helper. El helper solo escucha en `127.0.0.1` y acepta solicitudes del origen de esta extensión. Si Chrome pregunta si puede acceder a la red local, permite el acceso. Si cierras el popup mientras descarga, el helper sigue trabajando.
