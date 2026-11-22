# Contexto del proyecto Clemsa Mutancode FAP

## Estado actual

- Proyecto: `clemsa_keeloq_fap`, fuente principal `clemsa_keeloq.c`.
- Destino conectado: Flipper Zero con Unleashed `unlshd-093e`, firmware API `88.9`.
- SDK de ufbt configurado desde `https://up.unleashedflip.com/directory.json`, versión `unlshd-093`, API `88.9`.
- La versión estable más reciente se compiló con `ufbt` y se instaló/lanzó con `ufbt launch` el 2026-09-19.
- La interfaz está restaurada al menú único; la reestructuración con vistas personalizadas, pantallas RF separadas, gráfico y captura en hilo se retiró después de causar crashes.

## Funciones conservadas

- Edición de Serial, Disc, Cnt y Btn.
- Generación de trama Clemsa/KeeLoq.
- Guardado de perfiles en `/ext/apps_data/clemsa_profiles/`.
- Guardado de `.sub` (protocolo y RAW).
- Captura RF básica por HAL, 433.920 MHz, preset OOK 650 kHz, ventana de 5 segundos; intenta detectar preámbulo y 64 bits.
- Envío RF por HAL con OOK 650 kHz.

## Decisiones y observaciones importantes

- La primera versión se compiló contra API 87.1 y el dispositivo API 88.9, lo que provocó el aviso de aplicación antigua. El SDK se cambió al índice Unleashed y API 88.9.
- Se corrigió un buffer overflow en `text_input`: los tamaños de entrada ahora son específicos por campo.
- Se corrigió el arranque de la interfaz anterior seleccionando explícitamente el menú antes de `view_dispatcher_run()`.
- La versión con vistas propias se instalaba, pero causaba otro crash en el Flipper. El usuario pidió volver a la versión previa; se retiraron las vistas/hilo y se reinstaló el menú único.
- No modificar la interfaz con callbacks de dibujo/vistas personalizadas sin volver a probarla incrementalmente en el dispositivo.
- La captura RF todavía no detectaba el mando («No Clemsa remote found»). La lógica de decodificación es tentativa y puede no coincidir con el formato/timing real del mando. La UI gráfica de captura no está en la versión restaurada.

## Compilar e instalar

Desde `clemsa/clemsa_keeloq_fap`:

```sh
ufbt
ufbt launch
```

El Flipper aparece normalmente como `/dev/cu.usbmodemflip_Uiraiser1`. Si ufbt no lo detecta, verificar el puerto USB y que el dispositivo esté despierto/desbloqueado.

## Siguiente trabajo sugerido

Diagnosticar la captura RF por separado antes de cambiar la interfaz: capturar y mostrar/registrar pulsos crudos en un flujo estable, comparar una trama conocida con el RAW generado y ajustar niveles, preámbulo, tolerancias y longitud según evidencia del mando. Mantener el menú estable durante este trabajo.
