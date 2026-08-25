# Fase 1 — Arquitectura · Decisiones técnicas

## Contexto
Definir la arquitectura del pipeline antes de escribir infraestructura, y verificar
que las fuentes de datos elegidas funcionan de verdad.

## Pregunta de negocio
> ¿Cuánto sube la demanda eléctrica peninsular por cada grado de temperatura,
> y a qué horas se paga más cara esa energía?

## Fuentes verificadas

| Fuente | Endpoint | Auth | Resultado |
|---|---|---|---|
| REE · demanda | `apidatos.ree.es/es/datos/demanda/evolucion` | ninguna | 200 · 24 puntos/día |
| REE · precio | `apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real` | ninguna | 200 · series PVPC y spot |
| Open-Meteo | `archive-api.open-meteo.com/v1/archive` | ninguna | 200 · 24 puntos/día |

Parámetros comunes de REE: `start_date`, `end_date` (ISO, `2024-03-01T00:00`), `time_trunc=hour`.

**`demanda/evolucion` requiere además** `geo_trunc=electric_system&geo_limit=peninsular&geo_ids=8741`.
Sin esos parámetros devuelve `400`.

## Decisiones

### 1. `apidatos.ree.es` en lugar de ESIOS
ESIOS ofrece los mismos datos pero exige un token que se solicita por correo a Red Eléctrica,
con espera de días. `apidatos` es pública y devuelve lo mismo de inmediato.
Una fuente que bloquea el arranque del proyecto tiene un coste real aunque sea gratuita.

### 2. Dos fuentes en lugar de una
Con solo los datos de REE el proyecto sería un copiador de ficheros. Añadir la temperatura
obliga a resolver esquemas distintos, normalización de zonas horarias y un *join* por clave,
que es el trabajo real de un pipeline de datos.

### 3. Reintentos con backoff en la ingesta, desde el diseño
La API de REE devuelve `400 "Error Interno / Inténtelo de nuevo más tarde"` de forma
intermitente incluso con peticiones correctas. Se observó durante la verificación de esta
fase. La ingesta se diseña asumiendo que la fuente falla, no se parchea después.

### 4. Step Functions en lugar de MWAA (Airflow)
MWAA tiene coste fijo mensual de cientos de euros aunque no se ejecute nada.
Step Functions se factura por transición de estado. Con tres pasos, Airflow no se justifica.

### 5. Separación raw / curated
El dato crudo se guarda intacto en S3 antes de transformarlo. Permite reprocesar ante un
fallo en la lógica sin volver a consultar una API que ya se sabe inestable.

### 6. Parquet particionado por año/mes/día
Athena factura por terabyte escaneado. El particionado convierte un escaneo completo
en la lectura únicamente de las particiones consultadas.

## Riesgo de coste identificado
**AWS Glue no tiene capa gratuita.** Se factura por DPU-hora con un mínimo por ejecución.
El riesgo principal es un *crawler* programado o un job en bucle. Mitigación: mínimo de DPUs,
crawlers bajo demanda y nunca en *schedule*, presupuesto con alerta configurado antes de
crear recursos, y `terraform destroy` al cerrar cada sesión de pruebas.

El resto del stack (S3, Lambda, Step Functions, Athena) entra holgadamente en capa gratuita
con este volumen de datos.

## Entregables
- `fase-1-arquitectura.pdf` — documento completo de la fase
- `diagrama-linkedin.png` — diagrama para publicación (2400×1260)
- `post-linkedin.txt` — texto del post
- `arquitectura.html` / `diagrama-linkedin.html` — fuentes regenerables

## Siguiente
Fase 2 — repositorio, estructura de carpetas, `.gitignore` y README esqueleto.
