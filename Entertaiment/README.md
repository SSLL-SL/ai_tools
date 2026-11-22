# Entretenimiento — aplicación web

Centro multimedia web adaptable para la pantalla del coche. No necesita compilación ni dependencias instaladas.

## Ejecutar

Desde esta carpeta, inicia un servidor estático:

```sh
python3 -m http.server 8000
```

Abre `http://localhost:8000` en el navegador.

## Funciones incluidas

- Navegación entre inicio, IPTV, plataformas, mapas, radio, precio de la luz y videojuegos.
- Importación de listas IPTV M3U desde un enlace, archivo o credenciales Xtream; búsqueda, categorías, favoritos, EPG XMLTV y reproducción HLS.
- Accesos directos a plataformas de streaming.
- Enlaces a mapas de navegación y localizadores de cargadores para vehículos eléctricos.
- Búsqueda de emisoras españolas, reproducción en segundo plano y favoritos mediante Radio Browser.
- Gráfico horario PVPC y cálculo de la franja consecutiva más económica con datos de Red Eléctrica.
- Biblioteca de ROMs local con IndexedDB y carga del emulador al abrir un juego.
- Tema claro/oscuro, pantalla completa y datos locales del navegador.

Las listas remotas y las emisoras deben permitir conexiones desde el navegador (CORS). Si el proveedor IPTV las bloquea, importa un archivo M3U o consulta con el proveedor. Las plataformas externas, el directorio de radio, los datos de energía y el emulador necesitan conexión a Internet.
