# Contexto de la sesión

## Proyecto

Aplicación web estática de entretenimiento para la pantalla de un Tesla, implementada sin framework ni dependencias de compilación.

## Identidad y decisiones de interfaz

- Nombre visible: **Entretenimiento**.
- Estilo inspirado en Tesla: actualmente claro por defecto, con alternancia a tema oscuro.
- La interfaz se ha hecho más colorida: cada categoría de la portada tiene su propio acento y fondo pastel.
- Los controles táctiles tienen un objetivo mínimo de 56 × 56 px; los mosaicos y las filas de opciones son mayores.
- Se quitaron el hero inicial, el banner de comunidad/Telegram, la sección Guías y el minijuego/tema de Halloween.
- Se añadió una sección **Mapas** con búsqueda y filtros para navegación y carga eléctrica.
- Se quitó el enlace de Telegram del pie de página.

## Archivos principales

- ` e3.html`: HTML de la aplicación. **El nombre del archivo tiene un espacio inicial**.
- `app.js`: navegación por hash, renderizado de mapas y plataformas, IPTV, radio, precios, ROMs y preferencias.
- `styles.css`: tema Tesla/colorido, estilos responsive y reglas de objetivos táctiles.
- `README.md`: instrucciones y resumen de funcionalidades.

No se detectó un repositorio Git en la carpeta.

## Funcionalidad actual

- IPTV: listas M3U por URL/archivo y credenciales Xtream; categorías, búsqueda, favoritos, XMLTV y reproducción HLS.
- Streaming: accesos directos externos.
- Mapas: Google Maps, Apple Maps, Waze, OpenStreetMap, HERE WeGo, Bing Maps, Tesla Superchargers, A Better Routeplanner, PlugShare y ChargeFinder.
- Radio: búsqueda/favoritos con Radio Browser y reproducción directa.
- Precio de la luz: PVPC horario consultado desde Red Eléctrica; cálculo de la ventana más barata.
- Videojuegos: ROMs locales en IndexedDB y emulador cargado desde EmulatorJS.
- Preferencias y listas se almacenan localmente en el navegador.

## Servicios externos

Google Fonts y Google Favicon; servicios de streaming y mapas; Radio Browser y las URL de audio de las emisoras; API de Red Eléctrica; TDTChannels; jsDelivr para HLS.js; EmulatorJS CDN; y los proveedores IPTV/EPG elegidos por el usuario.

## Consideraciones para continuar

- La importación IPTV por URL es una petición directa del navegador y puede fallar si el proveedor no permite CORS. El intento de añadir un servidor proxy local se revirtió a petición del usuario; no volver a añadirlo sin consultarlo.
- `README.md` indica `python3 -m http.server 8000` y abrir la raíz, pero actualmente no hay `index.html`: el archivo de entrada se llama `e3.html`. Para probarlo con ese nombre, se puede abrir `http://localhost:8000/e3.html`. Conviene confirmar antes de renombrarlo.
- La carga PVPC usa `https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real` (la fuente anterior de Energy-Charts fallaba por CORS).

## Verificaciones recientes

- `node --check app.js` pasa.
- Se comprobaron las referencias de IDs del DOM contra `e3.html`.
- Las llaves de `styles.css` están equilibradas.
