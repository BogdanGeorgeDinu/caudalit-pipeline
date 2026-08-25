# Fase 2 — Repositorio · Decisiones técnicas

## Contexto
Crear la estructura del proyecto y publicarla, decidiendo antes del primer commit
qué entra en un repositorio público y qué no.

## Decisiones

### 1. Dos repositorios separados
| Repo | Visibilidad | Motivo |
|---|---|---|
| `caudalit-pipeline` | público | Es la pieza de portfolio. Cuando al final se ejecute `terraform destroy`, esto es lo que queda como prueba. |
| `caudalit-web` | privado | El código fuente de un sitio comercial no aporta al portfolio. Se conecta a Netlify para desplegar en cada push. |

Cambian a ritmos distintos y se despliegan distinto. En un monorepo, cada retoque
de la web ensuciaría el historial del proyecto técnico.

### 2. `.gitignore` escrito antes del primer commit
No es una formalidad: un archivo que entra en el historial sigue siendo accesible
aunque se borre en un commit posterior. Sacarlo obliga a reescribir la historia del
repositorio y forzar el push.

| Regla | Riesgo que evita |
|---|---|
| `*.tfstate`, `*.tfstate.*` | Terraform guarda el estado real de la infraestructura y **puede incluir valores sensibles en texto plano**. Filtración más habitual en repos de IaC. |
| `*.tfvars` (salvo `*.example.tfvars`) | Valores reales: IDs de cuenta, ARNs, nombres de bucket. |
| `.terraform/` | Providers descargados; cientos de MB regenerables con `terraform init`. |
| `.env`, `*.pem`, `*.key`, `credentials` | Credenciales y claves privadas. |
| `post-linkedin.txt` | Borradores de publicaciones: no son parte del proyecto técnico y desdibujan lo que enseña el repo. |
| `__pycache__/`, `*.zip`, `build/` | Artefactos de empaquetado de Lambdas. |
| `.DS_Store` | Ruido de Finder; además delata la estructura de carpetas local. |

### 3. Correo privado de GitHub en los commits
Se configuró `user.email` con la dirección `@users.noreply.github.com` en lugar del
correo personal. Sin esto, el correo real queda escrito en cada commit de un
repositorio público, expuesto a los bots que rastrean GitHub. Corregirlo después
exige reescribir todo el historial.

### 4. Un commit por fase
El historial de Git cuenta la misma progresión que las publicaciones. Permite leer
cómo evolucionó una decisión, no solo su resultado final.

### 5. Estructura completa desde el primer commit
Git no versiona carpetas vacías. Se añadió `.gitkeep` en `terraform/bootstrap/`,
`src/lambdas/`, `src/glue/` y `athena/` para que el repositorio comunique el alcance
del proyecto desde el principio.

### 6. HTTPS en lugar de SSH
Con `gh` instalado, HTTPS no requiere configuración adicional: `gh` actúa como gestor
de credenciales y el token queda en el llavero del sistema. Además HTTPS usa el puerto
443, que ninguna red bloquea, mientras que SSH (puerto 22) sí se bloquea con frecuencia
en redes corporativas y públicas. Reversible en cualquier momento con `git remote set-url`.

## Procedimiento de publicación
Regla fija del proyecto: **la revisión va antes del push, no después.**
Antes de subir se comprueba sobre el índice de Git que no entran `*.tfstate`, `*.tfvars`,
`.env`, claves ni borradores de publicaciones. La verificación se repite después contra
el árbol remoto real, no contra la copia local.

## Herramientas instaladas en esta fase
| Herramienta | Versión | Necesaria para |
|---|---|---|
| Homebrew | 6.0.19 | gestor de paquetes |
| `gh` | 2.98.0 | crear repos y autenticar Git |
| `terraform` | 1.15.8 | Fase 3 |
| `aws-cli` | 2.36.30 | Fase 3 |

`terraform` ya no está en homebrew-core; se instala desde `hashicorp/tap`.
La versión 1.15 admite bloqueo de estado nativo en S3 (`use_lockfile`), lo que evita
tener que crear una tabla de DynamoDB en la Fase 3.

## Entregables
- `fase-2-repositorio.pdf` — documento de la fase
- `diagrama-linkedin.png` — diagrama para publicación
- `repositorio.html` — fuente regenerable
- `post-linkedin.txt` — texto del post (**excluido del repositorio**)

## Siguiente
Fase 3 — Terraform: bootstrap del backend remoto, S3 (raw/curated), IAM con permisos
mínimos, base de datos de Glue, workgroup de Athena y **presupuesto con alerta antes
de crear ningún recurso**.
