# Google Sheets en Sinergia (orquestación)

**Skill principal.** Antes de leer o escribir en Google Sheets en este proyecto, el agente debe usar **este documento** para decidir el flujo y luego abrir el skill técnico que corresponda.

**No** sustituye la referencia de herramientas MCP: los detalles de parámetros, rangos y ejemplos viven en:

- **Lectura / inspección:** [inspect-database.md](./inspect-database.md)
- **Escritura:** [write-database.md](./write-database.md)

---

## 1. Regla de decisión

| Tipo de necesidad | Qué hacer |
|-------------------|-----------|
| **Solo leer** datos (estructura, filas, búsqueda por `chat_id`, etc.) | Seguir **únicamente** [inspect-database.md](./inspect-database.md). |
| **Solo escribir** (altas de filas, append) | Seguir **únicamente** [write-database.md](./write-database.md). |
| **Combinar** lectura y escritura (ej. localizar filas por `chat_id` y luego actualizar `estado`) | **Primero** [inspect-database.md](./inspect-database.md) **completo** para la parte de lectura; **después** [write-database.md](./write-database.md) para la parte de escritura, **en ese orden**, sin asumir índices de fila sin haber leído. |

Si dudas entre “¿solo miro?” y “¿también modifico?”: en cuanto haya **cualquier** mutación (append o update), la fase de escritura está gobernada por **write-database.md**; la lectura previa sigue las reglas de **inspect-database.md**.

---

## 2. Operaciones del bot y qué skill aplica

| Operación del bot | Skill(s) |
|-------------------|----------|
| Leer historial de conversación de un `chat_id` | **Inspección** → [inspect-database.md](./inspect-database.md) (leer `conversaciones`, filtrar por columna A). |
| Contar mensajes de un `chat_id` | **Inspección** → mismo criterio: leer datos necesarios y contar filas que coincidan con el `chat_id` en A. |
| Verificar si una conversación está cerrada | **Inspección** → leer filas de ese `chat_id` y revisar columna **E** (`estado`); ver reglas de interpretación en la sección de errores si no hay filas. |
| Guardar un turno de conversación (mensaje usuario + respuesta del bot) | **Escritura** → [write-database.md](./write-database.md) (dos appends a `conversaciones` según el diseño del turno, o el patrón que defina el código). |
| Guardar un `LeadRecord` al cierre | **Escritura** → [write-database.md](./write-database.md) (append a `leads`). |
| Marcar conversación como cerrada | **Inspección + escritura en secuencia** → primero [inspect-database.md](./inspect-database.md) para localizar **todas** las filas del `chat_id`; luego [write-database.md](./write-database.md) (actualizar columna E en cada una). |

---

## 3. Reglas de integridad

1. **Encabezados:** Nunca sobrescribir la **fila 1** (cabeceras). Los appends deben añadir filas **debajo** de los datos; las actualizaciones de estado deben apuntar solo a filas de datos identificadas tras la lectura, no a `1:1` como datos de negocio.

2. **Append:** Siempre usar **`INSERT_ROWS`** en appends (ver [write-database.md](./write-database.md)) para no pisar celdas existentes ni depender del modo por defecto que puede sobrescribir.

3. **Lead por conversación:** El `LeadRecord` en `leads` se escribe **una sola vez** por conversación (al cierre acordado en el producto). No duplicar leads del mismo cierre salvo que el negocio defina explícitamente otra política.

4. **Cierre en `conversaciones`:** Al marcar como cerrada, actualizar **`estado` en la columna E en todas las filas** que compartan ese `chat_id`, no solo la primera. Detalle operativo en [write-database.md](./write-database.md).

5. **Valores nulos en lead:** Los campos `None` del `LeadRecord` se envían como **`""`** (cadena vacía), manteniendo las 12 columnas alineadas.

---

## 4. Manejo de errores

| Situación | Comportamiento esperado |
|-----------|-------------------------|
| `sheets_get_values` **sin filas** de datos para un `chat_id` (o resultado vacío / solo cabecera) | Tratar como **conversación nueva**: devolver **lista vacía** (o equivalente en la capa de código), sin asumir error de red. |
| **`sheets_append_values` falla** | **Lanzar excepción** con mensaje **claro** (incluye contexto: hoja, operación, causa si la API la expone). **No** reintentar en silencio ni tragar el error. |
| **`sheets_update_values` falla** al cerrar conversación | **Lanzar excepción** con mensaje claro. El **estado en Sheet puede quedar inconsistente** (algunas filas actualizadas y otras no); documentar o propagar que puede requerir **revisión manual** o un flujo de recuperación explícito, no asumir cierre completo. |

---

## 5. Contexto del proyecto

| Concepto | Valor |
|----------|--------|
| **Spreadsheet ID** | `1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s` |
| **Hoja `leads`** | Columnas **A:L** (12 columnas) |
| **Hoja `conversaciones`** | Columnas **A:E** (5 columnas) |
| **`estado` (conversaciones)** | Columna **E** |
| **`chat_id`** | Columna **A** en **ambas** hojas |

---

## Uso rápido para el agente

1. Abrir **este** skill.
2. Clasificar la tarea: ¿solo lectura, solo escritura, o ambas?
3. Abrir **inspect-database.md** y/o **write-database.md** según la tabla de la sección 2.
4. Aplicar reglas de integridad (sección 3) y manejo de errores (sección 4) junto con los detalles técnicos del skill secundario.
