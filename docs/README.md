# Caudalit — Pipeline de datos eléctricos en AWS · Documentación

Construcción en abierto de un pipeline de datos end-to-end en AWS.
Diez fases, una por publicación. Este directorio es la prueba permanente del proyecto:
cuando al terminar se ejecute `terraform destroy` y la infraestructura desaparezca,
lo que queda es esto.

**Pregunta de negocio:** ¿cuánto sube la demanda eléctrica peninsular por cada grado
de temperatura, y a qué horas se paga más cara esa energía?

## Estructura

Cada fase tiene su carpeta con el mismo contenido:

```
docs/fase-N-nombre/
├── fase-N-nombre.pdf      documento completo de la fase
├── decisiones.md          decisiones técnicas y su razón
├── post-linkedin.txt      texto del post, listo para copiar
├── diagrama-linkedin.png  imagen para la publicación (opcional)
└── *.html                 fuentes, para regenerar el PDF
```

## Estado

| Fase | Título | Estado |
|---|---|---|
| 0 | Caso y dataset | Cerrada |
| 1 | Arquitectura | Cerrada — [`fase-1-arquitectura/`](fase-1-arquitectura/) |
| 2 | Repo, estructura y `.gitignore` | Cerrada — [`fase-2-repositorio/`](fase-2-repositorio/) |
| 3 | Terraform: backend, S3, IAM, Glue DB, Athena | Cerrada — [`fase-3-terraform/`](fase-3-terraform/) |
| 4 | Ingesta: Lambdas con reintentos | Pendiente |
| 5 | Transformación: Glue + PySpark | Pendiente |
| 6 | Consulta: Athena | Pendiente |
| 7 | Orquestación: Step Functions | Pendiente |
| 8 | CI/CD: GitHub Actions | Pendiente |
| 9 | Documentación final | Pendiente |
| 10 | Teardown | Pendiente |

## Regenerar un PDF

Los PDF se generan desde el HTML de la fase con Chrome en modo headless.
Hace falta servir el archivo por HTTP (no `file://`) para que carguen las tipografías:

```bash
cd docs/fase-1-arquitectura
python3 -m http.server 8901 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --hide-scrollbars --virtual-time-budget=25000 \
  --print-to-pdf=fase-1-arquitectura.pdf --no-pdf-header-footer \
  http://localhost:8901/arquitectura.html
```

Para las imágenes, cambiar `--print-to-pdf` por `--screenshot` y añadir
`--window-size=1200,630 --force-device-scale-factor=2`.
