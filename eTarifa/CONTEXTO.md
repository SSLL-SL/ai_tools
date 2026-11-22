# Contexto del proyecto — eTarifa

## Objetivo

Aplicación web en español para comparar tarifas eléctricas usando el consumo mensual y la potencia contratada de una vivienda. La interfaz se presenta como **Clara**.

## Estado actual

- Proyecto estático, sin framework, dependencias ni proceso de compilación.
- Para probarlo, abrir `index.html` en un navegador.
- `index.html`: estructura y formulario de alta/edición.
- `styles.css`: estilos adaptables a móvil y escritorio.
- `app.js`: datos de tarifas, cálculos, ordenación y acciones.
- `node --check app.js` pasó tras los últimos cambios.

## Funcionalidad implementada

- El usuario introduce consumo mensual en punta, llano y valle (kWh), y potencia contratada punta y valle (kW).
- Compara tarifas planas 24h, de 2 periodos, de 3 periodos y de mercado.
- Las tarjetas muestran el coste estimado mensual/anual y un desglose de energía y potencia.
- Cada tarifa se puede **editar** o **borrar**, incluidas las cuatro tarifas iniciales de ejemplo.
- Se pueden añadir ofertas, con precios de energía, potencia y cuota mensual opcional.
- El resultado se recalcula y ordena al modificar los datos o las tarifas.

## Reglas de cálculo y supuestos

- Tarifa plana: todo el consumo se multiplica por un único precio de energía.
- Dos periodos: punta usa su precio; el consumo llano y valle se agrupa al precio valle.
- Tres periodos y mercado: se aplican precios independientes a punta, llano y valle.
- Potencia: `(kW punta × precio punta + kW valle × precio valle) × 30 días`.
- Coste mensual = energía + potencia + cuota mensual opcional; estimación anual = mensual × 12.
- Importes antes de impuestos, alquiler del contador y otros conceptos de factura.
- La diferencia anual destacada es entre la opción más barata y la segunda más barata; no compara con una tarifa actual del usuario.
- Los precios iniciales son ficticios y están etiquetados como tarifas de demostración.
- Los datos se mantienen solo en memoria; al recargar la página vuelven los valores y tarifas iniciales.

## Posibles siguientes mejoras

- Guardar tarifas y datos del usuario entre visitas (por ejemplo, con `localStorage`).
- Permitir comparar el resultado con la tarifa actual del usuario.
- Añadir impuestos y otros conceptos de factura como opciones configurables.
- Permitir importar o exportar tarifas.
