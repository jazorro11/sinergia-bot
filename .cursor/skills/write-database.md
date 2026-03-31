# Escribir en la base de datos (Google Sheet de Sinergia)

Skill de referencia para agentes: usar **solo** el MCP **google-sheets** (`mcp-gsheets`) y las herramientas indicadas para **escribir** en el spreadsheet de Sinergia.

Para **leer** estructura o datos antes de escribir, reutiliza `sheets_get_values` como en [inspect-database.md](./inspect-database.md).

## Constantes del proyecto

| Dato | Valor |
|------|--------|
| **spreadsheetId** | `1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s` |
| **Hoja leads** | `leads` |
| **Hoja conversaciones** | `conversaciones` |

---

## 1. Agregar una fila nueva a `leads`

**Herramienta:** `sheets_append_values`

### Parámetros relevantes

| Parámetro | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `spreadsheetId` | Sí | ID del documento. |
| `range` | Sí | Ubicación de la “tabla” en notación A1 (ej. `leads!A:L`). Debe cubrir el **ancho** de las columnas que vas a enviar. |
| `values` | Sí | Matriz 2D: cada fila interna es una fila del Sheet. Para un solo alta: `[ [ celda1, celda2, … ] ]`. |
| `insertDataOption` | **Sí para este proyecto** | Debe ser **`"INSERT_ROWS"`**. |
| `valueInputOption` | No | Por defecto `USER_ENTERED` (interpreta fechas/números como si los escribiera un usuario). Suele ser adecuado para `created_at` en ISO. |

### Orden exacto de las 12 columnas en `values`

La fila que envíes en `values` debe respetar **este orden** (índices 0–11):

| # | Campo | Notas |
|---|--------|--------|
| 1 | `chat_id` | Identificador del chat. |
| 2 | `nombre` | |
| 3 | `ciudad` | |
| 4 | `tipo_espacio` | |
| 5 | `tipo_intervencion` | |
| 6 | `area_aprox` | |
| 7 | `situacion_actual` | |
| 8 | `fecha_deseada` | |
| 9 | `presupuesto` | |
| 10 | `alcance` | |
| 11 | `enlace_calendly` | |
| 12 | `created_at` | Ver formato abajo. |

### Valores `None` / opcionales

Si en tu modelo un campo es **`None`** o no aplica, envía **cadena vacía** `""` en esa posición del array. Así la celda queda vacía y no rompes el alineamiento de columnas.

### Formato de `created_at`

Usar **ISO 8601** en string, por ejemplo:

`"2024-01-15T14:30:00"`

(Puedes incluir zona u offset si el bot lo define de forma consistente, p. ej. `2024-01-15T14:30:00-03:00`.)

### Por qué `INSERT_ROWS` y no el valor por defecto

El valor por defecto de `insertDataOption` es **`OVERWRITE`**: escribe sobre el destino calculado para el append y puede **pisar celdas ya existentes** en lugar de desplazar filas. Con **`INSERT_ROWS`** Google Sheets **inserta filas nuevas** y coloca ahí los valores, evitando sobreescribir datos previos por accidente. Para altas de leads siempre usa **`"INSERT_ROWS"`**.

### Ejemplo: fila completa

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "leads!A:L",
  "values": [
    [
      "5501234567",
      "Ana López",
      "Montevideo",
      "oficina",
      "diseño",
      "80",
      "espacio sin mobiliario",
      "2024-02-01",
      "USD 5000",
      "solo sala de reuniones",
      "https://calendly.com/ejemplo",
      "2024-01-15T14:30:00"
    ]
  ],
  "insertDataOption": "INSERT_ROWS"
}
```

### Ejemplo: campos opcionales vacíos

Misma columna 12 con fecha; columnas intermedias sin dato como `""`:

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "leads!A:L",
  "values": [
    [
      "5509876543",
      "Carlos",
      "",
      "local",
      "",
      "",
      "a definir",
      "",
      "",
      "",
      "",
      "2024-03-20T09:00:00"
    ]
  ],
  "insertDataOption": "INSERT_ROWS"
}
```

### Errores comunes

- **Olvidar `insertDataOption: "INSERT_ROWS"`** → riesgo de `OVERWRITE` y pérdida de datos.
- **`values` con menos de 12 elementos** → columnas finales vacías o desalineadas respecto a la cabecera.
- **`range` demasiado estrecho** (ej. `leads!A:F`) si mandas 12 celdas → truncamiento o comportamiento inesperado; mantén `A:L`.
- **Nombre de hoja incorrecto** → error de rango.

---

## 2. Agregar una fila nueva a `conversaciones`

**Herramienta:** `sheets_append_values` con **`insertDataOption`: `"INSERT_ROWS"`**

### Orden exacto de las 5 columnas

| # | Campo | Descripción |
|---|--------|-------------|
| 1 | `chat_id` | Misma columna A que en `leads` para ese usuario/conversación. |
| 2 | `role` | Solo valores válidos: **`user`** o **`assistant`**. |
| 3 | `content` | Texto del mensaje. |
| 4 | `timestamp` | **Unix timestamp como entero** (segundos desde epoch), no string ISO. |
| 5 | `estado` | Solo valores válidos: **`activa`** o **`cerrada`**. |

### `role`

- **`user`**: mensaje del usuario final.
- **`assistant`**: mensaje del bot / asistente.

### `estado`

- **`activa`**: conversación en curso.
- **`cerrada`**: conversación finalizada (debe alinearse con actualizaciones posteriores en columna E; ver sección 3).

### Formato de `timestamp`

Enviar **número entero** Unix (segundos), por ejemplo `1705327800` para representar un instante concreto. No mezclar con string ISO en esta columna si el esquema del Sheet espera enteros.

### Ejemplo: fila de usuario

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!A:E",
  "values": [
    [
      "5501234567",
      "user",
      "Hola, necesito cotizar una oficina en Montevideo",
      1705327800,
      "activa"
    ]
  ],
  "insertDataOption": "INSERT_ROWS"
}
```

### Ejemplo: fila de asistente

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!A:E",
  "values": [
    [
      "5501234567",
      "assistant",
      "Perfecto, te hago unas preguntas para afinar la cotización.",
      1705327815,
      "activa"
    ]
  ],
  "insertDataOption": "INSERT_ROWS"
}
```

### Errores comunes

- **`role` o `estado` con mayúsculas distintas o sinónimos** (`User`, `closed`) si el resto del sistema espera minúsculas fijas → inconsistencia al filtrar.
- **`timestamp` como string** → la hoja puede mostrar texto en lugar de número o romper informes.
- Misma advertencia que en leads: **siempre `INSERT_ROWS`** para no pisar filas.

---

## 3. Actualizar el campo `estado` en `conversaciones`

Combina **lectura** y **escritura** con las herramientas permitidas:

1. **`sheets_get_values`** — localizar filas del `chat_id`.
2. **`sheets_update_values`** — escribir el nuevo `estado` en la **columna E** de esas filas.

### Flujo paso a paso

1. **Leer** datos suficientes para ubicar filas, por ejemplo toda la hoja o solo la columna A más E si ya tienes un patrón establecido. Lo más robusto para alinear filas con los 5 campos:

   - `range`: `conversaciones!A:E`

2. **Identificar filas** (número de fila en el Sheet, base **1**):

   - La **primera fila** del rango suele ser **cabecera**; las filas de datos empiezan en la fila **2** del documento si la fila 1 es header.
   - Recorrer cada fila de la respuesta: si la columna A (índice 0 del array de la fila) coincide con el `chat_id` buscado, anota el **número de fila absoluto** en el spreadsheet (fila 1 = cabecera, etc.).

3. **Actualizar columna E** (`estado`) para **cada** fila anotada:

   - **Herramienta:** `sheets_update_values`
   - **Parámetros:** `spreadsheetId`, `range` con notación A1 **acotada a la celda o bloque E**, y `values` coherente con la forma del rango.

### Parámetros de `sheets_update_values`

| Parámetro | Descripción |
|-----------|-------------|
| `spreadsheetId` | ID del documento. |
| `range` | Ej. `conversaciones!E5` para **solo** la celda E de la fila 5, o `conversaciones!E5:E7` para tres filas **consecutivas**. |
| `values` | Matriz 2D: una fila por fila del Sheet afectada. Una celda: `[["cerrada"]]`. Tres celdas E consecutivas: `[["cerrada"],["cerrada"],["cerrada"]]`. |
| `valueInputOption` | Opcional: `USER_ENTERED` (defecto) o `RAW`. |

### Por qué actualizar TODAS las filas del `chat_id`

Cada mensaje puede ser una **fila distinta** con el mismo `chat_id` en A. Si solo cambias `estado` en la **primera** fila, el resto seguirá en `activa` y cualquier informe o lógica que lea la conversación quedará **incoherente**. El cierre debe reflejarse en **todas** las filas de ese `chat_id` en `conversaciones`.

### Formato del rango al actualizar

- **Una fila:** `conversaciones!E{n}` con `values`: `[["cerrada"]]`.
- **Varias filas seguidas** (ej. filas 5, 6, 7): un solo `sheets_update_values` con `range`: `conversaciones!E5:E7` y `values`: `[["cerrada"],["cerrada"],["cerrada"]]`.
- **Filas no consecutivas:** una llamada a `sheets_update_values` **por cada fila** (ej. `conversaciones!E5`, luego `conversaciones!E9`), cada una con `[["cerrada"]]`.

No uses un rango gigante tipo `E:E` para “solo cerrar un chat” sin cálculo previo: podrías pisar estados de otros chats.

### Ejemplo completo: marcar conversación como `cerrada`

**Paso A — Leer**

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!A:E"
}
```

Supón que la cabecera ocupa la fila 1 y el `chat_id` `"5501234567"` aparece en las **filas 5, 6 y 8** (datos reales; ajusta según el resultado).

**Paso B — Actualizar filas no consecutivas** (tres llamadas, una por fila):

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!E5",
  "values": [["cerrada"]]
}
```

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!E6",
  "values": [["cerrada"]]
}
```

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!E8",
  "values": [["cerrada"]]
}
```

**Variante** si las filas fueran **5, 6, 7** consecutivas: una sola llamada:

```json
{
  "spreadsheetId": "1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s",
  "range": "conversaciones!E5:E7",
  "values": [
    ["cerrada"],
    ["cerrada"],
    ["cerrada"]
  ]
}
```

### Errores comunes

- **Descontar mal la fila de cabecera** → actualizas la fila 1 (headers) o te desplazas una fila.
- **Actualizar solo la primera coincidencia** → estado inconsistente en el mismo `chat_id`.
- **`values` con dimensiones incorrectas** para el rango (ej. rango `E5:E7` pero solo `[["cerrada"]]`).
- **Confundir columnas**: `estado` es la **quinta** columna → **E**, no D.

---

## Resumen rápido

| Objetivo | Herramienta | Recuerda |
|----------|-------------|----------|
| Nuevo lead | `sheets_append_values` | `leads!A:L`, 12 campos en orden, `""` si null, `created_at` ISO, **`INSERT_ROWS`** |
| Nuevo mensaje | `sheets_append_values` | `conversaciones!A:E`, `role` user/assistant, `timestamp` int Unix, `estado` activa/cerrada, **`INSERT_ROWS`** |
| Cerrar / cambiar estado | `sheets_get_values` → `sheets_update_values` | Actualizar **E** en **todas** las filas de ese `chat_id` |

**IDs:** `spreadsheetId` = `1XPyxwgy474Fpn4rEH2HWP9Y3FegPB2WgS7labT_n-1s`.

Para este documento de escritura, las únicas herramientas MCP usadas son **`sheets_append_values`**, **`sheets_get_values`** (solo como paso previo en el flujo de estado) y **`sheets_update_values`**.
