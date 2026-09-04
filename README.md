<p align="right"><a href="README.en.md">English</a></p>

<h1 align="center">Grados y Megavatios</h1>

<p align="center">
  <strong>Un pipeline de datos end-to-end en AWS, construido en abierto.</strong><br>
  Cruza la demanda eléctrica española con la temperatura, hora a hora, para responder una pregunta concreta.
</p>

<p align="center">
  <img alt="Terraform" src="https://img.shields.io/badge/IaC-Terraform-7B42BC?style=flat-square&logo=terraform&logoColor=white">
  <img alt="AWS" src="https://img.shields.io/badge/Cloud-AWS-232F3E?style=flat-square&logo=amazonwebservices&logoColor=white">
  <img alt="PySpark" src="https://img.shields.io/badge/Proceso-PySpark-E25A1C?style=flat-square&logo=apachespark&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Fase" src="https://img.shields.io/badge/fase-4%20de%2010-2FD6C6?style=flat-square">
</p>

---

> ### ¿Cuánto sube la demanda eléctrica peninsular por cada grado de temperatura, y a qué horas se paga más cara esa energía?

Todo el proyecto existe para responder eso. Cada decisión técnica se justifica por si acerca o no a la respuesta.

![Arquitectura del pipeline](docs/fase-1-arquitectura/diagrama-linkedin.png)

---

## Qué es esto

Un proyecto de ingeniería de datos construido **en público**, fase a fase, con el mismo criterio con el que se construye en producción: infraestructura como código, calidad del dato en origen, orquestación con reintentos, observabilidad y coste bajo control.

No es un tutorial ni un *notebook*. Es una plataforma pequeña pero completa, y la documentación de por qué está hecha así.

Al terminar se ejecuta `terraform destroy` y la infraestructura desaparece. **Lo que queda como prueba es este repositorio**: el código, los diagramas y las decisiones.

## Arquitectura

| Etapa | Servicio | Qué resuelve |
|---|---|---|
| Ingesta | **Lambda** (Python) | Una función por fuente. Reintentos con *backoff*: la API de REE falla de forma intermitente. |
| Aterrizaje | **S3 · raw** | JSON tal cual llegó. Permite reprocesar sin volver a consultar la API. |
| Transformación | **Glue + PySpark** | Aplanado, validación, normalización horaria y *join* de las tres series por hora. |
| Almacén | **S3 · curated** | Parquet particionado por `anio/mes/dia`. |
| Catálogo | **Glue Data Catalog** | Registro del esquema. |
| Consulta | **Athena** | SQL sobre el dato curado. |
| Orquestación | **Step Functions** | Orden, reintentos y alertas. |
| Observabilidad | **CloudWatch** | Logs, métricas y alarmas. |
| Infraestructura | **Terraform** | Todo como código, con estado remoto y bloqueo. |
| CI/CD | **GitHub Actions** | `fmt` / `validate` / `plan` en cada PR. |

Región: `eu-west-1` (Irlanda).

## Fuentes de datos

Ambas **públicas y sin token**. Verificadas antes de diseñar nada.

| Fuente | Endpoint | Datos |
|---|---|---|
| Red Eléctrica | `apidatos.ree.es/es/datos/demanda/evolucion` | Demanda peninsular horaria |
| Red Eléctrica | `apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real` | Precio PVPC y mercado spot |
| Open-Meteo | `archive-api.open-meteo.com/v1/archive` | Temperatura horaria (Madrid) |

> [!IMPORTANT]
> El endpoint de demanda **exige** `geo_trunc=electric_system&geo_limit=peninsular&geo_ids=8741`.
> Sin esos parámetros devuelve `400`.
>
> Y devuelve `400 "Error Interno"` de forma **intermitente** incluso con peticiones correctas.
> Por eso la ingesta lleva reintentos desde el diseño, no como parche posterior.

Se descartó **ESIOS** deliberadamente: ofrece los mismos datos pero exige un token que tarda días en llegar. Una fuente que bloquea el arranque tiene un coste real aunque sea gratuita.

## Estado

| # | Fase | Estado |
|:--:|---|:--:|
| 0 | Caso y dataset | Cerrada |
| 1 | [Arquitectura](docs/fase-1-arquitectura/) | Cerrada |
| 2 | [Repositorio y estructura](docs/fase-2-repositorio/) | Cerrada |
| 3 | [Terraform: backend, S3, IAM, Glue DB, Athena](docs/fase-3-terraform/) | Cerrada |
| 4 | [Ingesta: Lambdas con reintentos](docs/fase-4-ingesta/) | Cerrada |
| 5 | [Transformación: Glue + PySpark](docs/fase-5-transformacion/) | En curso |
| 6 | Consulta: Athena | Pendiente |
| 7 | Orquestación: Step Functions | Pendiente |
| 8 | CI/CD: GitHub Actions | Pendiente |
| 9 | Documentación final | Pendiente |
| 10 | Teardown | Pendiente |

Cada fase cerrada deja su carpeta en [`docs/`](docs/) con el diagrama, el PDF y las decisiones razonadas.

Estado en vivo: **[caudalit.com/proyecto](https://caudalit.com/proyecto/)**

## Estructura

```
.
├── terraform/
│   └── bootstrap/     bucket de estado remoto (se ejecuta una sola vez)
├── src/
│   ├── lambdas/       ingesta REE y Open-Meteo
│   └── glue/          jobs PySpark raw → curated
├── tests/             69 pruebas; 18 levantan una sesión local de Spark
├── herramientas/      diagnóstico sin Spark y sin AWS
├── athena/            consultas que responden la pregunta de negocio
└── docs/              una carpeta por fase: diagrama, PDF y decisiones
```

## Cómo ejecutarlo

Requisitos: Terraform ≥ 1.10, AWS CLI configurada, Python 3.11 o 3.12.

```bash
# 1. Crear el bucket de estado remoto (una sola vez)
cd terraform/bootstrap && terraform init && terraform apply

# 2. Desplegar el resto
cd .. && terraform init -backend-config=backend.hcl && terraform plan
```

## Pruebas

La lógica de transformación y la de ingesta se prueban **sin AWS y sin red**. Las de
Spark se saltan solas si PySpark no está instalado, para que la suite no dependa de
tener un Spark en la máquina.

```bash
# 51 pruebas en milisegundos, sin dependencias
python3 -m unittest discover -s tests

# Las 18 restantes, con una sesión local de Spark
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export PYSPARK_PYTHON=$PWD/tests/venv/bin/python
export PYSPARK_DRIVER_PYTHON=$PYSPARK_PYTHON
tests/venv/bin/python -m unittest discover -s tests
```

Dos herramientas de diagnóstico, ninguna necesita AWS:

```bash
# Cruza y valida un día de datos crudos, con su informe de calidad
python3 herramientas/revisar_dia.py tests/datos 2024-10-27

# Comprueba contra Open-Meteo que la alineación horaria sigue siendo correcta
python3 herramientas/comprobar_desfase.py
```

## Coste

El proyecto está diseñado para caber en capa gratuita, con una excepción que conviene conocer:

> [!WARNING]
> **AWS Glue no tiene capa gratuita.** Se factura por DPU-hora con un mínimo por ejecución.
> El riesgo real es un *crawler* programado o un job en bucle.
>
> Mitigación: mínimo de DPUs, crawlers **bajo demanda y nunca en `schedule`**, presupuesto
> con alerta configurado *antes* de crear recursos, y `terraform destroy` al cerrar cada
> sesión de pruebas.

S3, Lambda, Step Functions y Athena entran holgadamente en capa gratuita con este volumen (kilobytes al día).

## Decisiones técnicas

Cada fase documenta lo que se decidió y por qué en su `decisiones.md`. Un resumen de las que condicionan todo lo demás:

- **Estado de Terraform en S3 con bloqueo**, nunca en local. Es parte de lo que el proyecto demuestra.
- **Step Functions en vez de MWAA.** Airflow tiene coste fijo de cientos de euros al mes; con tres pasos no se justifica.
- **Raw y curated separados.** El dato crudo intacto es el seguro contra un fallo en la lógica de transformación.
- **Parquet particionado por fecha.** Athena factura por TB escaneado; particionar convierte un escaneo completo en leer solo lo consultado.
- **Dos fuentes en lugar de una.** El *join* por hora es lo que separa un pipeline de un copiador de ficheros.

---

<p align="center">
  <sub>
    <strong>Caudalit</strong> · Ingeniería de datos en AWS · Madrid<br>
    <a href="https://caudalit.com">caudalit.com</a> ·
    <a href="https://www.linkedin.com/in/georgebogdandinu/">LinkedIn</a>
  </sub>
</p>
