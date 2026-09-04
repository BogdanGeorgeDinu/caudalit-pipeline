# Fase 4 — Ingesta · Decisiones técnicas

## Contexto
Dos funciones Lambda que consultan las APIs y depositan el JSON crudo en `raw`,
diseñadas asumiendo que la fuente falla.

## Qué se creó

| Recurso | Detalle |
|---|---|
| `caudalit-esios-dev-ingesta-ree` | Python 3.13, 256 MB, timeout 300 s |
| `caudalit-esios-dev-ingesta-clima` | Python 3.13, 256 MB, timeout 300 s |
| 2 grupos de logs | Retención de 14 días |

## Decisiones

### 1. Sin dependencias externas
La biblioteca `requests` no viene incluida en el runtime de Lambda, y empaquetarla
obliga a construir el zip con `pip install -t`, lo que añade un paso de build y,
en algunos casos, un contenedor para compilar dependencias nativas.

`urllib.request` de la biblioteca estándar hace exactamente lo mismo para este caso.
El resultado es que Terraform empaqueta la función con `archive_file` y no hay ningún
paso de build: un `terraform apply` y ya está desplegado.

### 2. Un solo artefacto para las dos funciones
Ambas comparten `comun.py` (cliente HTTP con reintentos, escritura a S3, logging).
Las alternativas eran duplicar ese módulo en dos carpetas o crear una Lambda Layer.

Se optó por empaquetar `src/lambdas/` completo en un único zip y desplegar dos
funciones apuntando al mismo artefacto con distinto `handler`: `ree.handler` y
`openmeteo.handler`. Sin duplicación y sin mantener una capa para 80 líneas.

### 3. Se reintenta ante error 400
Un `400 Bad Request` significa normalmente que la petición está mal formada y
reintentarla es un antipatrón: va a fallar igual.

`apidatos.ree.es` devuelve `400 "Error Interno"` de forma intermitente para peticiones
correctas, y a la siguiente responde `200` con exactamente los mismos parámetros.
Verificado en la Fase 1 y de nuevo al probar la premisa del proyecto.

Está comentado explícitamente en el código porque cualquiera que lo lea pensará que
es un error.

### 4. Espera exponencial con jitter
Los tiempos de espera crecen 1,5 s → 3 s → 6 s → 12 s → 24 s, más un componente
aleatorio de hasta 1 segundo.

El jitter no es cosmético: sin él, varias ejecuciones que fallan simultáneamente
reintentarían sincronizadas y golpearían el origen en el mismo instante, agravando
justo el problema que se intenta sortear.

Comprobado contra un `400` real: 1,3 s → 2,5 s → 4,55 s, y falla con una excepción
explícita en lugar de colgarse.

### 5. Logs estructurados en JSON
Cada evento se emite como una línea JSON con `evento` y campos propios
(`http_ok`, `http_reintento`, `http_agotado`, `s3_escrito`).

Permite filtrar en CloudWatch por `{ $.evento = "http_reintento" }` y medir con qué
frecuencia falla realmente la fuente en producción, en lugar de suponerlo.

### 6. Clave determinista en S3
```
fuente={fuente}/anio={AAAA}/mes={MM}/dia={DD}/datos.json
```

Particionado en formato Hive, que Glue y Athena reconocen automáticamente.

La clave depende solo de la fuente y la fecha del dato, no del momento de ejecución:
reprocesar un día **sobrescribe** su archivo en lugar de duplicarlo. La ingesta es
idempotente y se puede repetir sin ensuciar el bucket.

### 7. Por defecto, el día anterior
Sin parámetro `fecha`, se ingiere el día anterior: el actual todavía está incompleto
y REE publica con retraso. El parámetro permite reprocesar cualquier fecha histórica.

### 8. Timeout de 600 segundos, calculado y no estimado
Estaba en 300 s con el argumento de que «el peor caso se acerca a los minutos». Se hizo
la cuenta durante la Fase 5 y no salía:

- 6 intentos × 25 s de timeout HTTP = 150 s
- esperas de 1,5 + 3 + 6 + 12 + 24 = 46,5 s, más hasta 5 s de jitter
- **peor caso de una petición: 201,5 s**

La Lambda de clima hace una petición y cabe. **La de REE hace dos: 403 s.** Con 300 s
moría antes de agotar los reintentos de la segunda, y precisamente contra la API que se
sabe que falla sola. Con la primera petición en su peor caso, a la segunda solo le
quedaban 3 de sus 6 intentos.

Lambda factura por milisegundo consumido, no por el timeout configurado, así que subirlo
a 600 s no cuesta nada. La lección es la de siempre en esta fase: la cuenta, no la
intuición.

### 9. Cada respuesta se guarda en cuanto llega
La Lambda de REE pedía las dos series y solo después escribía las dos en S3. Si la
segunda agotaba los reintentos, se perdía también la primera, que ya había llegado bien.

Ahora cada respuesta se guarda nada más obtenerla. Reintentar el día solo tiene que
recuperar la fuente que falta, y como la clave en S3 es determinista, repetir la que ya
está simplemente la sobrescribe con lo mismo.

## Pruebas
La ingesta se quedó sin pruebas en su momento: toda la suite miraba la transformación,
justo la parte que no habla con una API que se sabe que falla sola. Se cubrió al
revisarla en la Fase 5, con **14 tests** sin red y sin AWS —`boto3` se sustituye por un
doble antes de importar el módulo, y `urlopen` y `sleep` también—:

- el reintento ante 400 hasta que la API responde 200;
- que la espera crece 1,5 · 3 · 6 y que el jitter desincroniza dos ejecuciones;
- que al agotar los intentos falla en alto y deja el motivo del último fallo;
- que un JSON inválido también se reintenta;
- que la clave en S3 es determinista y lleva los ceros delante;
- que la Lambda de REE guarda la demanda **antes** de pedir el precio;
- que la de clima pide en UTC y cubre también la víspera.

## Prueba realizada
Invocación real de ambas funciones sobre el 1 de marzo de 2024:

| Fuente | Puntos | Tamaño | Resultado |
|---|---|---|---|
| `ree_demanda` | 24 horarios | 2.545 B | Pico 33,8 GW |
| `ree_precio` | 24 horarios | 5.207 B | Media 2,1 EUR/MWh |
| `clima_temperatura` | 24 horarios | 910 B | Media 6,8 °C |

Los tres objetos aterrizaron en `raw` con el particionado correcto. Cero reintentos en
esta ejecución: REE respondió al primer intento en ambas llamadas.

**Observación sobre los datos:** un día frío (6,8 °C) con demanda alta (33,8 GW) y
precio casi nulo (2,1 EUR/MWh). Marzo de 2024 fue un mes de viento récord en España.
Es un ejemplo concreto de que las renovables rompen la correlación entre demanda y
precio, y anticipa que el análisis de la Fase 6 no dará una relación lineal simple.

## Coste
El millón de invocaciones mensuales de Lambda es gratuito de forma permanente, no solo
durante el primer año. Con dos ejecuciones diarias no se roza ese límite. El gasto real
son los logs de CloudWatch, del orden de kilobytes.

## Siguiente
Fase 5 — transformación con Glue y PySpark: aplanar los tres JSON, normalizar las
zonas horarias, unirlos por hora y escribir parquet particionado en `curated`.
