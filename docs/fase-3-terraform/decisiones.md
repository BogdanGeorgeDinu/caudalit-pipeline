# Fase 3 — Infraestructura base · Decisiones técnicas

## Contexto
Crear con Terraform la infraestructura sobre la que se apoyan las fases siguientes,
con el presupuesto y las barreras de coste puestas **antes** que ningún recurso.

## Qué se creó

| Recurso | Cantidad | Coste mensual |
|---|---|---|
| Presupuesto con tres alertas | 1 | 0 (los dos primeros son gratis) |
| Bucket de estado de Terraform | 1 | ~0 (kilobytes) |
| Buckets de datos: raw, curated, resultados | 3 | ~0 (vacíos) |
| Roles IAM con políticas inline | 2 | 0 |
| Base de datos del catálogo de Glue | 1 | 0 (solo metadatos) |
| Workgroup de Athena | 1 | 0 (se paga por consulta) |
| Grupo de logs con retención | 1 | ~0 |

Ningún recurso factura por hora. La cuenta puede quedarse encendida indefinidamente.

## Decisiones

### 1. El presupuesto va antes que la infraestructura
Se crea en el módulo de bootstrap, antes que ningún recurso que pueda generar coste.
5 USD al mes con tres avisos: 50% real, 100% real y 100% previsto.

El aviso de **previsión** es el importante: proyecta el ritmo de gasto y avisa antes
de alcanzar el límite, que es cuando aún hay margen de reacción.

Va en USD y no en euros porque la cuenta factura en dólares; en otra moneda las
cifras no cuadrarían con la factura.

### 2. Dos módulos por el problema del huevo y la gallina
`bootstrap/` mantiene el estado **en local** porque es el módulo que crea el bucket
donde vivirá el estado de todo lo demás. No puede guardarse en un bucket que aún
no existe.

Lleva `prevent_destroy = true`: es el único recurso que sobrevive al `terraform destroy`
final. Sin el estado, los recursos quedan huérfanos y ya no se pueden gestionar.

### 3. Bloqueo de estado nativo, sin DynamoDB
Terraform 1.10 introdujo `use_lockfile` para el backend de S3. Hasta entonces hacía
falta una tabla de DynamoDB dedicada únicamente al bloqueo. Un recurso menos que
crear, documentar y pagar.

### 4. El nombre del bucket de estado lleva un sufijo aleatorio
Lo habitual es usar el ID de cuenta para garantizar unicidad global, pero eso lo
dejaría escrito en un repositorio público. El sufijo aleatorio consigue lo mismo
sin exponer nada.

En el módulo principal, donde sí se usa el ID de cuenta para nombrar buckets, se
obtiene con `data.aws_caller_identity` en tiempo de ejecución. Nunca escrito a mano.

### 5. El nombre real del bucket de estado no se versiona
Los bloques `backend` no admiten variables. Se usa configuración parcial: el bloque
declara solo `encrypt` y `use_lockfile`, y el resto vive en `backend.hcl`, excluido
del repositorio. Se inicializa con `terraform init -backend-config=backend.hcl`.
Se versiona `backend.hcl.example` con valores de muestra.

### 6. Versionado solo en `raw`
El dato crudo es el seguro ante un fallo en la lógica de transformación: permite
reprocesar sin volver a consultar una API que ya se sabe inestable.

`curated` se regenera desde `raw`, así que versionarlo solo ocuparía espacio.

### 7. IAM sin políticas gestionadas de AWS
Ni un solo `AmazonS3FullAccess`. Políticas inline acotadas a los recursos concretos:

- La Lambda de ingesta solo puede `s3:PutObject` en `raw`. No puede leer, ni borrar,
  ni tocar `curated`.
- El job de Glue lee `raw`, escribe en `curated` y opera sobre **su** base de datos
  del catálogo, no sobre todo el catálogo.

`DeleteObject` sí se concede sobre `curated`: es necesario para reescribir una
partición al reprocesar un día.

### 8. Sin crawler de Glue
Lo habitual sería crear un crawler que descubra el esquema. No se hace: un crawler
en `schedule` es la forma más común de gastar en Glue sin darse cuenta, porque
factura DPU cada vez que se ejecuta aunque no haya nada nuevo.

La tabla la registrará el propio job de PySpark al escribir en `curated` (Fase 5).

### 9. Límite de bytes escaneados en el workgroup de Athena
Athena factura por terabyte escaneado. El riesgo no es el uso normal —los datos son
kilobytes— sino una consulta mal escrita sobre una tabla sin particionar.

El workgroup impone un tope de 1 GiB por consulta y aborta la que lo supere. Es un
freno de mano, no una optimización. `enforce_workgroup_configuration` impide además
que alguien redirija los resultados fuera del bucket cifrado.

### 10. Los grupos de logs se declaran en Terraform
Si se deja que Lambda o Glue creen sus grupos de logs automáticamente, se crean
**sin retención**: se guardan indefinidamente y se pagan indefinidamente.
Declarados aquí, tienen 14 días.

## Incidencias

### Las etiquetas de S3 no admiten comas
`CreateBucket` devolvió `InvalidTag: The TagValue you have provided is invalid` en
los buckets `raw` y `curated`, pero no en `athena`. La diferencia era una coma en el
valor de la etiqueta `Proposito`.

Los valores de etiqueta de un bucket S3 aceptan un juego de caracteres más
restringido que el del resto de servicios: **la misma etiqueta funciona en un rol IAM
y falla en un bucket de S3**. El mensaje de error no indica cuál es el carácter
problemático ni qué etiqueta lo contiene.

El `apply` quedó a medias: el bucket de resultados de Athena, los roles, el workgroup
y el grupo de logs sí se crearon. Al corregir y volver a planificar, Terraform pasó de
23 recursos a 18 porque el estado ya registraba lo creado. Es exactamente para lo que
sirve el estado.

### Formato de salida de la CLI
`aws configure` acepta `JSON` en mayúsculas sin quejarse, pero después la CLI falla
con `Unknown output type: JSON`. Debe escribirse en minúsculas.

## Verificación posterior
Comprobado con la CLI sobre los recursos reales, no sobre el estado local:

- Cifrado `AES256` activo en los tres buckets de datos
- Bloqueo de acceso público activo en los tres
- Política de denegación de tráfico sin TLS presente en los tres
- Límite de escaneo de Athena: 1024 MiB
- Retención de logs: 14 días

## Siguiente
Fase 4 — Lambdas de ingesta con reintentos y backoff, escribiendo el JSON crudo
en `raw` particionado por fecha.
