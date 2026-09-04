# Fase 5 — Transformación · Decisiones técnicas

## Contexto
Un job de Glue con PySpark que lee los tres JSON crudos de un día, los aplana,
los cruza por hora y escribe parquet particionado en `curated`. Es la fase donde
el dato deja de ser tres respuestas de API y pasa a ser una tabla que responde
la pregunta del proyecto.

También es la fase en la que el arreglo de un fallo silencioso resultó ser el
fallo. Queda documentado abajo, porque es lo más útil que ha dado el proyecto
hasta ahora.

## Qué se creó

| Recurso | Detalle |
|---|---|
| `caudalit-esios-dev-curated` | Glue 5.0, 2 workers G.1X, timeout 15 min, sin reintentos |
| `caudalit-esios-dev-artefactos` | Bucket para el script y los módulos del job |
| Tabla `demanda_precio_temperatura` | Declarada en Terraform, con proyección de particiones |
| Grupo de logs continuo | Retención de 14 días |
| `/aws-glue/jobs/output` y `/error` | Salida del driver y los ejecutores, con retención |

## Decisiones

### 1. A Open-Meteo se le piden los datos en UTC
Es la decisión que ordena toda la fase, y se llegó a ella por el camino largo.

Open-Meteo devuelve las horas sin desfase (`2024-03-01T00:00`) y, en otro campo,
un `utc_offset_seconds`. Consultada en septiembre, para el 1 de marzo ese campo
vale **7200**: UTC+2, cuando Madrid el 1 de marzo está en UTC+1.

La primera lectura fue que la API se equivoca y que el campo hay que ignorarlo,
resolviendo la hora local con las reglas de `Europe/Madrid` (`zoneinfo`). **Esa
lectura es falsa, y el arreglo introdujo justo el error que pretendía evitar.**

La API no se equivoca: es coherente consigo misma. Construye la serie aplicando
el desfase que declara. Que ese desfase sea el vigente el día de la petición y no
el del día de los datos hace que las etiquetas no sean hora de Madrid — pero
`etiqueta − utc_offset_seconds` sigue dando el UTC correcto siempre.

Reinterpretar esas etiquetas como hora local de Madrid es lo que desplaza el dato
una hora en invierno. Comprobado pidiendo el mismo día dos veces, en
`Europe/Madrid` y en `UTC`, y comparando contra la segunda:

| Día | `utc_offset_seconds` | Reinterpretando como hora de Madrid | Restando el campo declarado |
|---|---|---|---|
| 2024-03-01 | 7200 | 21 horas mal de 24 | 0 de 24 |
| 2024-01-15 | 7200 | 19 horas mal de 24 | 0 de 24 |
| 2024-07-15 | 7200 | 0 de 24 | 0 de 24 |

En julio coincide porque Madrid sí está en UTC+2. El error solo aparece en
invierno, que es la mitad del año en la que la temperatura más explica la demanda.

La solución no es corregir el desfase aguas abajo, es no tenerlo: la ingesta pide
`timezone=UTC` y la marca ya es un instante. Como el día local de Madrid empieza
a las 22:00 o 23:00 UTC de la víspera, la petición cubre dos días UTC y la
transformación recorta la ventana.

### 2. El parseo rechaza un payload que no venga en UTC
`parseo.temperatura` comprueba que `utc_offset_seconds` sea cero y revienta si no.

Es la lección de lo anterior convertida en código. El problema no fue equivocarse
de huso: fue que equivocarse no producía ningún síntoma. Si algún día la ingesta
vuelve a pedir en hora local, ahora el job falla en alto en vez de escribir un
parquet corrido una hora.

### 3. La ventana del día local es la única traducción entre husos
`tiempo.ventana_utc(dia)` devuelve el intervalo semiabierto en UTC del día local
de Madrid. Todo lo demás del pipeline trabaja en UTC.

El proyecto piensa en días locales —es lo que particiona la tabla y lo que
entiende quien mira el consumo— pero cruza las fuentes por instante. Concentrar
esa traducción en una función, probada y en Python puro, evita que la lógica de
husos se reparta por el código, que es como apareció el error de la primera
versión.

De paso, la ventana explica sola el día de 23 y 25 horas: `horas_esperadas` es su
longitud, no una tabla de casos especiales.

### 4. La marca se parsea con desfase explícito, no con la zona de sesión
En Spark, la marca de Open-Meteo se convierte concatenándole una `Z` y parseando
con un formato que lleva desfase (`yyyy-MM-dd'T'HH:mmXXX`), igual que la de REE.

`to_timestamp` sobre una marca sin desfase la interpreta en
`spark.sql.session.timeZone`. Funciona mientras esa configuración sea UTC, y falla
en silencio el día que alguien la cambie. Es exactamente la clase de dependencia
invisible que ya costó un desfase de una hora en esta misma fase.

Esto sustituye al mecanismo anterior, que difundía un calendario de pares
(hora local, instante UTC) y cruzaba por la cadena local. Ese calendario hacía dos
cosas a la vez —convertir y acotar el día— y ambas dependían de la premisa
equivocada. Con las marcas ya en UTC, convertir es un parseo y acotar es un filtro.

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

Conviene ser honesto sobre su alcance: ninguna de estas reglas habría detectado el
desfase de una hora. Un dato corrido sigue estando dentro de rango.

**Las reglas viven en un solo sitio.** `calidad.veredicto` recibe los números ya
contados y emite el juicio; la transformación en Spark los cuenta con agregados y la
referencia en Python recorriendo listas, pero ninguna de las dos redacta su propia
versión. Estaban duplicadas y ya habían empezado a separarse: Spark decía
`instantes duplicados` sin el número y `demanda: N valores fuera de rango` con otro
nombre de columna, y en un día vacío emitía un aviso de más. Nada de eso corrompía
datos, pero hacía que el log del job dijera cosas distintas de las que decía la
herramienta local para el mismo día.

De paso se arregló una regla documentada que no estaba implementada: los nulos en
columnas que no son la demanda ahora sí generan aviso, en vez de solo contarse.

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

### 10. Los grupos de logs de Glue se declaran, no se dejan nacer solos
Glue escribe el continuo en su grupo propio, pero la salida del driver y de los
ejecutores va a `/aws-glue/jobs/output` y `/aws-glue/jobs/error`. No existían, y el rol
no tiene `logs:CreateLogGroup` a propósito.

Sin declararlos, el primer job habría corrido sin dejar salida del driver — justo lo que
se mira cuando algo falla. Declarados en Terraform nacen además con retención; los que
crea AWS por su cuenta no caducan nunca y se pagan para siempre.

### 11. Tope de 15 minutos
Glue factura por DPU-hora y no tiene capa gratuita. El `timeout` no está para que el
job quepa, está para que un cuelgue no se convierta en una factura.

### 12. `collect()` no devuelve la zona horaria que crees
La otra trampa horaria de la fase, esta al montar Spark en local para probar el job.

Con `spark.sql.session.timeZone = UTC`, un `.show()` de la marca de REE imprime
`2024-02-29 23:00:00`, que es correcto. Pero al recoger esa misma fila con
`collect()`, Python recibe `datetime(2024, 3, 1, 0, 0)`: **sin `tzinfo` y
convertida a la zona horaria del driver**, no a la de sesión.

El dato dentro de Spark está bien y el parquet se escribe bien. Lo que engaña es
el viaje de vuelta al driver. La forma fiable de comprobarlo es formatear la marca
**dentro de Spark** (`date_format`) y comparar cadenas.

## Cómo se coló el error, y qué lo habría evitado
Los 28 tests de la primera versión pasaban con el dato desplazado una hora. No es
mala suerte: la suite estaba construida de forma que no podía verlo.

- `parseo.py` (referencia en Python) y `transformacion.py` (Spark) implementaban
  la **misma** regla. Compararlas entre sí solo demuestra que coinciden, no que
  acierten. Si la regla es falsa, las dos fallan igual y el test sale verde.
- Había un test llamado `test_temperatura_usa_las_reglas_horarias_y_no_el_desfase_declarado`.
  Codificaba la premisa equivocada y la protegía.
- Ninguna comprobación contrastaba la salida contra la **fuente**.

Lo que lo destapó no fue un test: fue mirar la tabla. La temperatura mínima salía a
las 09:00 locales, más de una hora después del amanecer del 1 de marzo. Con el
arreglo cae a las 08:00, que es donde tiene que estar.

El test que faltaba y ahora existe es `test_la_temperatura_no_va_corrida_respecto_a_la_fuente`:
lee el JSON crudo y comprueba, hora a hora, que la temperatura que acaba en curated
es la que la fuente pone en ese instante. Se ha verificado que **falla** si se
reintroduce la conversión anterior.

Regla que queda para el resto del proyecto: al menos una comprobación por fuente
tiene que atarse al dato de origen, no a otra implementación propia.

## Lo que se probó

**La transformación completa, en Spark de verdad.** La suite compara, fila a fila,
lo que produce Spark contra la implementación de referencia en Python puro sobre
los ficheros reales del 1 de marzo de 2024, y además contra el JSON crudo.

| Comprobación | Resultado |
|---|---|
| Las 24 filas de Spark coinciden con la referencia | correcto |
| Cada temperatura coincide con la que la fuente pone en ese instante | correcto |
| `to_timestamp` con `SSSXXX` aplica el desfase de REE | correcto |
| `arrays_zip` alinea `time` y `temperature_2m` de Open-Meteo | correcto |
| La medianoche local del 1 de marzo cae en 23:00 UTC | correcto |
| El payload de dos días UTC se recorta a la ventana local | correcto |
| Un payload en hora local se rechaza en alto | correcto |
| Spark y la referencia emiten el mismo veredicto de calidad | correcto |
| Día completo: 24 filas, cero nulos, cero errores, cero avisos | correcto |
| El parquet se escribe en `anio=2024/mes=03/dia=01` | correcto |
| Al releerlo salen 24 filas con `momento_local` | correcto |

### Los dos días que no tienen 24 horas
Se probaron con datos reales, porque son el caso donde las tres fuentes pueden
descuadrar sin que nada falle:

| Día | Horas locales | Filas | Errores | Avisos | Nulos |
|---|---|---|---|---|---|
| 2024-03-31 (adelanta) | 23 | 23 | 0 | 0 | 0 |
| 2024-10-27 (atrasa) | 25 | 25 | 0 | 0 | 0 |

El 31 de marzo la hora local salta de 01:00 a 03:00 y las 02:00 no aparecen, que es
lo correcto: no llegan a ocurrir. El 27 de octubre las 02:00 locales aparecen **dos
veces**, con desfases `+02:00` y `+01:00`, separadas una hora en UTC y con temperaturas
distintas.

Esto último **la ingesta anterior no podía hacerlo**. Pidiendo la temperatura en
`Europe/Madrid`, Open-Meteo devuelve 24 etiquetas a desfase fijo para un día que tiene
25 horas: una de las dos 02:00 simplemente no existía. Verificado contra la API. Era un
segundo fallo silencioso, independiente del desfase de invierno, que el cambio a UTC
arregla de paso.

Son **55 tests**: 37 sin Spark, que corren en milisegundos, y 18 que levantan una
sesión local. Los de Spark se saltan solos si PySpark no está instalado.

## Lo que sigue sin probarse
El job **no se ha ejecutado en Glue**. Queda por confirmar en la primera ejecución
real lo que solo existe en el entorno de AWS:

1. Que el envoltorio de `awsglue` arranca y `getResolvedOptions` recibe los
   parámetros esperados.
2. Que el rol lee de `raw` y escribe en `curated` con los permisos definidos.
3. Que Athena encuentra las particiones por proyección.

Antes hay que **reingestar** el 1 de marzo: el JSON que hay en `raw` está en hora
local de Madrid, que es el formato que la nueva ingesta ya no produce y que el
parseo ahora rechaza. La clave en S3 es determinista, así que reingestar
sobrescribe el fichero en vez de duplicarlo.

Esa ejecución cuesta unos cuatro céntimos.

## Cómo se ejecutan las pruebas

```bash
# Rapido, sin Spark: 37 tests en milisegundos
python3 -m unittest discover -s tests

# Completo, con Spark local
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export PYSPARK_PYTHON=/ruta/al/venv/bin/python
export PYSPARK_DRIVER_PYTHON=$PYSPARK_PYTHON
venv/bin/python -m unittest tests.test_transformacion \
    tests.test_cambio_de_hora tests.test_spark_local
```

PySpark necesita Python 3.11 o 3.12 y Java 17. Si el worker y el driver usan
versiones distintas de Python, Spark falla con `PYTHON_VERSION_MISMATCH`: de ahí
que haya que fijar `PYSPARK_PYTHON` explícitamente.

## Herramientas de la fase
Dos scripts en `herramientas/`, los dos sin Spark y sin AWS:

- `revisar_dia.py <carpeta_raw> <fecha>` — cruza y valida un día de datos crudos y
  saca la tabla y el informe de calidad. Sirve para diagnosticar un día sospechoso
  sin gastar un DPU.
- `comprobar_desfase.py [fechas...]` — pide el mismo día a Open-Meteo en
  `Europe/Madrid` y en `UTC` y mide las dos lecturas posibles de la etiqueta contra
  la verdad de referencia. Es lo que destapó el fallo, y queda para poder repetir la
  medición si la API cambia de criterio.

## Una observación que resultó ser falsa
Estaba anotado que cada `terraform plan` marcaba las dos Lambdas como modificadas
aunque su código no hubiera cambiado, por culpa de `archive_file`, y que había que
convivir con un plan que nunca queda limpio.

Se comprobó y **no es cierto**. `output_base64sha256` es determinista sobre el
contenido: tres `plan` consecutivos borrando el zip entre medias dan el mismo hash, y
tocar el `mtime` de los tres ficheros sin cambiar una línea tampoco lo altera.

El cambio que el plan marca ahora es real: `openmeteo.py` pasó a pedir los datos en UTC.
Después del próximo `apply` el plan debería quedar limpio; conviene confirmarlo entonces
y no volver a dar por buena una rugosidad sin medirla.

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
