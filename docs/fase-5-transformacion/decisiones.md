# Fase 5 — Transformación · Decisiones técnicas

## Contexto
Un job de Glue con PySpark que lee los tres JSON crudos de un día, los aplana,
los cruza por hora y escribe parquet particionado en `curated`. Es la fase donde
el dato deja de ser tres respuestas de API y pasa a ser una tabla que responde
la pregunta del proyecto.

## Qué se creó

| Recurso | Detalle |
|---|---|
| `caudalit-esios-dev-curated` | Glue 5.0, 2 workers G.1X, timeout 15 min, sin reintentos |
| `caudalit-esios-dev-artefactos` | Bucket para el script y los módulos del job |
| Tabla `demanda_precio_temperatura` | Declarada en Terraform, con proyección de particiones |
| Grupo de logs propio | Retención de 14 días |

## Decisiones

### 1. El desfase horario que devuelve Open-Meteo es incorrecto
Es el hallazgo de la fase y el que justifica la mitad del código.

Open-Meteo devuelve las horas en local sin desfase (`2024-03-01T00:00`) y, en otro
campo, un `utc_offset_seconds`. Para el 1 de marzo de 2024 ese campo vale **7200**,
es decir UTC+2. Pero el 1 de marzo Madrid está en horario de invierno, UTC+1: el
cambio de hora no llega hasta el 31 de marzo.

La API está reportando el desfase vigente el día en que se hace la petición, no el
del día de los datos.

Usar ese campo desplaza una hora todas las temperaturas de invierno. Nada falla, nada
avisa: el job termina en verde y el parquet queda escrito. Simplemente cada temperatura
queda emparejada con la demanda de la hora siguiente, y como el proyecto existe para
medir cuánto sube la demanda por cada grado, el error contamina exactamente la respuesta
que se busca.

La solución es ignorar el campo y resolver la hora local con las reglas horarias de
`Europe/Madrid` (`zoneinfo`), que sí conocen cuándo empieza y acaba el horario de verano.

### 2. REE sí entrega el desfase correcto, y eso decide cuál es la clave del cruce
REE devuelve `2024-03-01T00:00:00.000+01:00`: la hora local y su desfase real, correcto
para la fecha. Con eso, el instante es inequívoco.

Como una fuente es inequívoca y la otra no, la clave del cruce es el **instante UTC**,
no la hora local. Cruzar por hora local parece más natural y funciona 363 días al año;
el domingo que atrasa, la hora local se repite y el cruce produce filas duplicadas.

### 3. Las reglas horarias van en una tabla, no en `to_utc_timestamp`
Spark tiene `to_utc_timestamp`, que hace exactamente esta conversión. No se usa.

En su lugar, `tiempo.calendario(dia)` construye con `zoneinfo` la lista de pares
(hora local, instante UTC) del día, y el job la difunde como tabla pequeña y cruza
por la cadena local.

El motivo es poder probarlo. La lógica horaria queda en Python puro, cubierta por
tests que se ejecutan en milisegundos sin levantar Spark, y el comportamiento no
depende de la versión de Glue ni de la configuración de sesión. Difundir 24 filas
no cuesta nada.

### 4. Un día que dura 23 o 25 horas no es un día incompleto
La validación no compara contra 24 fijo. `tiempo.horas_esperadas(dia)` calcula las
horas reales que tiene ese día en Madrid: 23 el domingo que adelanta, 25 el que
atrasa, 24 el resto.

Validar contra 24 marcaría como sospechosos dos días al año que están perfectos, y
al revés, daría por bueno un 27 de octubre al que le falta una hora de verdad.

### 5. El cruce conserva los huecos
Un `full outer` entre las tres fuentes, no un `inner`. Si una hora falta en una
fuente, la fila sigue apareciendo con un nulo en esa columna.

Un `inner` habría dado una tabla más limpia y una mentira: las horas incompletas
desaparecerían sin dejar rastro, y nadie se enteraría de que la ingesta tiene un
agujero.

### 6. Qué tumba el job y qué solo se anota
No todo fallo de calidad merece parar.

- **Errores** (el job falla y no escribe): sin filas, instantes duplicados, demanda
  completamente vacía, valores fuera de rango plausible.
- **Avisos** (se escribe y queda en el log): número de filas distinto del esperado,
  nulos en columnas que no son la demanda.

La demanda es la columna que responde la pregunta de negocio; sin ella el día no
sirve. Una temperatura ausente deja el día cojo pero no inútil.

Los rangos (10.000–50.000 MW, −25 a 50 °C) son de plausibilidad, no límites físicos.
Sirven para detectar una unidad cambiada o un valor centinela, no para juzgar la red.

### 7. Proyección de particiones en vez de crawler o MSCK REPAIR
Athena necesita saber qué particiones existen. Las dos formas habituales son un
crawler de Glue o ejecutar `MSCK REPAIR TABLE` tras cada escritura.

Un crawler programado factura DPU cada vez que se ejecuta, mire alguien el resultado
o no. `MSCK REPAIR` es gratis pero hay que acordarse de lanzarlo, y si se olvida, la
partición existe en S3 y no en el catálogo.

La proyección de particiones elimina las dos: Athena deduce las particiones del patrón
de la ruta, declarado en las propiedades de la tabla. Coste cero y nada que mantener.

Obliga a que las rutas sean estrictamente predecibles, por eso el job escribe
`mes=03` y no `mes=3`, igual que la capa raw.

### 8. Reprocesar un día no toca el resto
`spark.sql.sources.partitionOverwriteMode = dynamic` con `mode("overwrite")`: se
reemplaza solo la partición del día procesado.

Con el modo estático por defecto, `overwrite` borra la tabla entera antes de escribir.
Reprocesar un día de marzo se llevaría por delante el histórico.

### 9. Sin reintentos en el job
`max_retries = 0`. Un reintento automático de Glue vuelve a arrancar el cluster y
vuelve a facturar, normalmente para fallar igual: si el JSON de origen está mal, lo
seguirá estando.

La orquestación de la Fase 7 decidirá qué merece reintento, con criterio y con alerta.

### 10. Tope de 15 minutos
Glue factura por DPU-hora y no tiene capa gratuita. El `timeout` no está para que el
job quepa, está para que un cuelgue no se convierta en una factura.

### 11. `collect()` no devuelve la zona horaria que crees
Encontrado al montar Spark en local para probar el job, y es la segunda trampa
horaria de la fase.

Con `spark.sql.session.timeZone = UTC`, un `.show()` de la marca de REE imprime
`2024-02-29 23:00:00`, que es correcto. Pero al recoger esa misma fila con
`collect()`, Python recibe `datetime(2024, 3, 1, 0, 0)`: **sin `tzinfo` y
convertida a la zona horaria del driver**, no a la de sesión.

El dato dentro de Spark está bien y el parquet se escribe bien. Lo que engaña es
el viaje de vuelta al driver. Un test que compare el objeto recogido contra UTC
falla por una hora sin que haya ningún error en la transformación, que es
exactamente lo que me pasó.

La forma fiable de comprobarlo es formatear la marca **dentro de Spark**
(`date_format`) y comparar cadenas. Así la conversión del driver no entra en la
ecuación.

## Lo que se probó

**La transformación completa, en Spark de verdad.** Se montó Java 17 y PySpark
3.5.3 en local para no dejar la capa de Spark sin ejecutar. La suite compara,
fila a fila, lo que produce Spark contra la implementación de referencia en
Python puro sobre los ficheros reales del 1 de marzo de 2024:

| Comprobación | Resultado |
|---|---|
| Las 24 filas de Spark coinciden con la referencia | correcto |
| `to_timestamp` con `SSSXXX` aplica el desfase de REE | correcto |
| `arrays_zip` alinea `time` y `temperature_2m` de Open-Meteo | correcto |
| La medianoche local del 1 de marzo cae en 23:00 UTC | correcto |
| Día completo: 24 filas, cero nulos, cero errores, cero avisos | correcto |
| El parquet se escribe en `anio=2024/mes=03/dia=01` | correcto |
| Al releerlo salen 24 filas con `momento_local` | correcto |

Son 28 tests en total. Los 24 de reglas horarias, aplanado y calidad no
necesitan Spark y corren en milisegundos; los 4 de Spark se saltan solos si
PySpark no está instalado, para que la suite no dependa de tener un Spark en la
máquina.

Además, la comprobación que más tranquiliza no es un test: es mirar la tabla. La
temperatura mínima cae a las 07:00-08:00 y la máxima a las 17:00, que es lo que
hace la temperatura. Si el desfase estuviera mal, la curva saldría corrida y se
vería a simple vista.

## Lo que sigue sin probarse
El job **no se ha ejecutado en Glue**. Lo verificado es la transformación, que es
donde estaba el riesgo. Queda por confirmar en la primera ejecución real lo que
solo existe en el entorno de AWS:

1. Que el envoltorio de `awsglue` arranca y `getResolvedOptions` recibe los
   parámetros esperados.
2. Que el rol lee de `raw` y escribe en `curated` con los permisos definidos.
3. Que Athena encuentra las particiones por proyección.

Esa ejecución cuesta unos cuatro céntimos.

## Cómo se ejecutan las pruebas

```bash
# Rapido, sin Spark: 24 tests en milisegundos
python3 -m unittest discover -s tests

# Completo, con Spark local
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export PYSPARK_PYTHON=/ruta/al/venv/bin/python
export PYSPARK_DRIVER_PYTHON=$PYSPARK_PYTHON
venv/bin/python -m unittest tests.test_transformacion tests.test_spark_local
```

PySpark necesita Python 3.11 o 3.12 y Java 17. Si el worker y el driver usan
versiones distintas de Python, Spark falla con `PYTHON_VERSION_MISMATCH`: de ahí
que haya que fijar `PYSPARK_PYTHON` explícitamente.

## Observación que queda para más adelante
Cada `terraform plan` marca las dos Lambdas como modificadas aunque su código no haya
cambiado: `archive_file` regenera el zip con un hash distinto. Es inofensivo —
redesplegar una Lambda es gratis— pero ensucia el plan y hace que nunca esté limpio.

Se ha dejado como está a propósito: es una rugosidad de la Fase 4 y arreglarla desde
la Fase 5 significaría tocar la ingesta, que funciona, por un motivo cosmético.

## Coste
El primer gasto real del proyecto que no es calderilla.

| Concepto | Coste |
|---|---|
| Ejecución del job (2 DPU, ~3 min) | ~0,04 USD |
| Una ejecución diaria durante un mes | ~1,20 USD |
| Almacenamiento del parquet | despreciable |
| Catálogo de Glue | gratis hasta 1 millón de objetos |

Glue no tiene capa gratuita: se factura por DPU-hora con mínimo por ejecución. Con dos
workers y un job de tres minutos son céntimos, pero un crawler programado cada hora o
un job en bucle es exactamente lo que dispara una factura de AWS.

## Siguiente
Fase 6 — consulta: las queries de Athena que responden por fin la pregunta del
proyecto, y el argumento del particionado medido en terabytes escaneados.
