# Plan de Implementación v2 — Sinergia Bot

> Basado en el Technical Brief v4. Este documento describe el plan de implementación completo del chatbot de Telegram para Estudio Sinergia. No contiene código: define qué archivos se crean, para qué sirve cada uno, qué lógica implementan, y cómo se relacionan entre sí.

---

## Visión general del flujo

Antes de listar archivos, es importante entender el recorrido completo de un mensaje:

```
Usuario en Telegram
      ↓ (mensaje de texto o mensaje editado)
Telegram envía HTTP POST a /webhook
      ↓
webhook.py  →  retorna HTTP 200 inmediatamente
      ↓         lanza tarea en background ↓
      ↓
conversation.py  →  orquesta toda la lógica
      ↓              ├─ verifica restricciones (horario, conv. cerrada, límite)
      ↓              ├─ lee historial de Sheets
      ↓              ├─ llama al LLM conversacional vía la API de OpenAI
      ↓              ├─ detecta cierre por URL de Calendly en respuesta
      ↓              ├─ ejecuta extracción periódica (si toca)
      ↓              └─ detecta cierre por 9 campos completos
      ↓
extraction.py  →  llama al LLM de extracción → retorna LeadRecord
      ↓
storage.py  →  lee/escribe en Google Sheets (historial + leads)
      ↓
Telegram API  →  envía respuesta al usuario (con delay de 1000 ms)
```

---

## Estructura de archivos del proyecto

```
sinergia-bot/
│
├── bot/
│   ├── __init__.py
│   ├── logger.py
│   ├── config.py
│   ├── prompts.py
│   ├── storage.py
│   ├── extraction.py
│   ├── conversation.py
│   └── webhook.py
│
├── tests/
│   ├── __init__.py
│   ├── test_conversation.py
│   ├── test_extraction.py
│   └── test_integration.py
│
├── main.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

### Dependencias entre módulos

```
main.py
  └─ importa → bot/webhook.py
                  └─ importa → bot/conversation.py
                                  ├─ importa → bot/config.py
                                  ├─ importa → bot/extraction.py
                                  │               └─ importa → bot/config.py
                                  │               └─ importa → bot/prompts.py
                                  ├─ importa → bot/storage.py
                                  │               └─ importa → bot/config.py
                                  └─ importa → bot/prompts.py

bot/logger.py  ← importado por todos los módulos
```

`config.py` y `logger.py` no importan nada interno. Son el nivel más bajo de la jerarquía.

---

## Fase 1 — Infraestructura base

### Archivos a crear

---

### `requirements.txt`

**Por qué existe:** define exactamente qué librerías instalar y en qué versiones. Permite que cualquier persona (o servidor de despliegue) reproduzca el entorno idéntico con un solo comando (`pip install -r requirements.txt`).

**Qué contiene:**

Lista de dependencias fijadas:
- `fastapi` — framework web que recibe el webhook
- `uvicorn` — servidor ASGI que ejecuta FastAPI (FastAPI no se puede correr solo; sin `uvicorn`, la aplicación no arranca)
- `python-telegram-bot>=20` — librería para enviar mensajes a Telegram
- `openai` — cliente oficial de OpenAI (endpoint por defecto de la API de OpenAI)
- `gspread` — librería para leer y escribir Google Sheets
- `google-auth` — autenticación con Google Service Account
- `httpx` — cliente HTTP (dependencia interna de `python-telegram-bot` v20)
- `pydantic` — validación de datos y schema del LeadRecord
- `python-dotenv` — carga opcional del archivo `.env` en desarrollo local para poblar `os.environ` antes de importar `config.py`; en producción la plataforma inyecta variables y el archivo puede no existir

Dependencias de desarrollo (no van a producción):
- `pytest` — framework de tests
- `ruff` — linter de código

No se permite agregar dependencias fuera de esta lista sin justificación explícita (constraint del brief v4).

---

### `.env.example`

**Por qué existe:** es una plantilla que documenta qué variables de entorno necesita el proyecto. Se sube al repositorio para que cualquier desarrollador sepa qué configurar. El `.env` real con los valores secretos **nunca** se sube.

**Nota:** copiar a `.env` no basta por sí solo: la aplicación solo ve valores que estén en `os.environ` tras cargar el archivo (p. ej. `load_dotenv()` en `main.py`) o exportar variables en la shell / IDE / plataforma de despliegue.

**Variables que documenta (10 en total):**

Requeridas (el sistema falla al arrancar si faltan):
- `TELEGRAM_BOT_TOKEN` — token del bot de Telegram (lo da BotFather)
- `OPENAI_API_KEY` — clave de API de OpenAI
- `GOOGLE_SERVICE_ACCOUNT_JSON` — contenido del JSON de credenciales de Google como string
- `GOOGLE_SHEET_ID` — ID del Google Sheet con las hojas `leads` y `conversaciones`
- `CALENDLY_URL` — URL pública del evento de Calendly
- `LLM_MODEL` — modelo para conversación (ej: `gpt-4o`)
- `LLM_EXTRACTION_MODEL` — modelo para extracción (ej: `gpt-4o-mini`)

Opcionales (tienen valores por defecto):
- `EXTRACTION_FREQUENCY` — cada cuántos mensajes del usuario se ejecuta la extracción (default: `1`)
- `LOG_LEVEL` — nivel de logging (default: `INFO`)
- `PORT` — puerto del servidor, inyectado por Railway/Render (default: `8000`)

---

### `.gitignore`

**Por qué existe:** le indica a Git qué archivos ignorar. El más crítico es `.env` (con las claves reales). También ignora `__pycache__/`, `.venv/`, `*.pyc`, `.DS_Store`. Evita que secretos lleguen accidentalmente al repositorio.

---

### `bot/__init__.py`

**Por qué existe:** archivo vacío que convierte la carpeta `bot/` en un paquete Python. Sin él, los demás archivos no pueden importarse entre sí con la sintaxis `from bot.config import ...`.

---

### `tests/__init__.py`

**Por qué existe:** archivo vacío. Mismo propósito que el anterior, para la carpeta `tests/`.

---

## Fase 2 — Logger

### Archivo a crear: `bot/logger.py`

**Por qué existe:** configura el logging centralizado del proyecto. Todos los demás módulos lo importan. No importa nada interno del proyecto. Es, junto con `config.py`, el nivel más bajo de la jerarquía de dependencias.

**Por qué va primero:** es un requisito del brief v4 que todos los módulos usen logging. Si se implementa después, habría que volver a cada módulo a agregarlo.

**Lógica:**
- Lee la variable de entorno `LOG_LEVEL` directamente (es la única excepción a la regla de que solo `config.py` lee variables de entorno; el brief v4 lo especifica así porque `logger.py` debe funcionar antes de que `config.py` se importe).
- Configura `logging.basicConfig` con formato `"%(asctime)s | %(levelname)s | %(name)s | %(message)s"` y formato de fecha `"%Y-%m-%d %H:%M:%S"`.
- Expone una función `get_logger(name)` que retorna un logger con el nombre del módulo que lo llama.
- Cada módulo lo usa al inicio: `from bot.logger import get_logger` seguido de `logger = get_logger(__name__)`.

---

## Fase 3 — Configuración

### Archivo a crear: `bot/config.py`

**Por qué existe:** centraliza todas las variables de entorno y los clientes de servicios externos. Es el único módulo (además de `logger.py` para `LOG_LEVEL`) que toca `os.environ`. El resto de módulos importa desde aquí.

**Lógica:**

1. Lee las 10 variables de entorno. Las 7 requeridas deben existir al arrancar; si falta alguna, loguea `CRITICAL` y falla inmediatamente. Las 3 opcionales tienen defaults.

2. Parsea `GOOGLE_SERVICE_ACCOUNT_JSON` de string a dict (viene como string para poder pasarlo en Railway/Render sin subir archivos).

3. Inicializa dos clientes `openai.OpenAI` con `api_key=os.environ["OPENAI_API_KEY"]` y el endpoint por defecto del SDK (sin `base_url` salvo necesidad futura de proxy u otro host compatible):
   - `llm` — para llamadas conversacionales (usa `LLM_MODEL`)
   - `llm_extraction` — para llamadas de extracción (usa `LLM_EXTRACTION_MODEL`)
   - Son dos instancias separadas para claridad, aunque técnicamente podrían ser una sola.

4. Define constantes de negocio:
   - Horario de silencio: 22:00–07:00 UTC-5 (hora Colombia)
   - Límite de mensajes: 30
   - Delay de respuesta: 1000 ms
   - Mensaje de ausencia: `"Hola! En este momento no estoy disponible, pero mañana en la mañana te respondo 😌"`
   - Mensaje para contenido no soportado (texto gentil indicando que solo puede leer texto)
   - Mensajes fijos para conversaciones cerradas (uno para `calendly_enviado`/`limite_alcanzado` y otro para `no_agendar`)

5. Loguea al arrancar (`INFO`): modelo conversacional, modelo de extracción, frecuencia de extracción.

---

## Fase 4 — Prompts

### Archivo a crear: `bot/prompts.py`

**Por qué existe:** centraliza los prompts como constantes de texto. Ningún otro módulo construye prompts inline. Si hay que ajustar el tono del bot o las reglas de extracción, se edita un solo archivo.

**Lógica:**

No tiene funciones ni lógica. Solo define dos constantes de texto:

- `SYSTEM_PROMPT` — El system prompt completo del brief v4 (sección "System Prompt"). Contiene `{calendly_url}` como placeholder que `conversation.py` reemplaza con el valor de la variable de entorno `CALENDLY_URL` antes de pasarlo al LLM. Define la personalidad de "Alejandro", las reglas de conversación, los 9 campos a capturar, y las reglas de cierre.

- `EXTRACTION_PROMPT` — El prompt de extracción del brief v4 (sección "Prompt de extracción"). Instruye al LLM de extracción para que analice el historial y extraiga los 9 campos del lead, retornando `null` para los no mencionados.

---

## Fase 5 — Persistencia

### Archivo a crear: `bot/storage.py`

**Por qué existe:** es la única capa que habla con Google Sheets. Ningún otro módulo debe saber que la persistencia existe en Sheets — solo importan funciones de este archivo.

**Funciones que provee:**

**`get_conversation_history(chat_id)`**
- Abre la hoja `conversaciones` en Google Sheets.
- Busca todas las filas donde la columna `chat_id` coincida con el valor recibido.
- Reconstruye y retorna el historial como una lista de dicts con formato `{"role": "user"/"assistant", "content": "texto"}`. Este es el formato que espera el cliente de OpenAI.
- Si no existe ninguna fila para ese `chat_id`, retorna una lista vacía (primera vez que escribe el usuario).
- Loguea `DEBUG` con la cantidad de turnos leídos.

**`save_conversation_turn(chat_id, role, content, timestamp, estado)`**
- Agrega una fila a la hoja `conversaciones` con: `chat_id`, `role`, `content`, `timestamp`, `estado`.
- Se llama dos veces por mensaje procesado: una para el turno del usuario y otra para el turno del assistant.
- El campo `estado` permite marcar si la conversación sigue `en_curso` o está `cerrada`.

**`get_lead(chat_id)`**
- Busca y retorna la fila del lead en la hoja `leads` para ese `chat_id`.
- Retorna el lead como dict (o un objeto con los campos de `LeadRow`) si existe; `None` si no existe.
- Se usa para dos cosas: verificar si la conversación ya está cerrada (campo `estado`), y obtener los valores actuales del lead para la lógica de upsert.

**`upsert_lead(chat_id, lead_record, estado)`**
- Si no existe una fila con ese `chat_id` en la hoja `leads`: crea una nueva con `chat_id`, los campos del `LeadRecord`, `estado` (por defecto `"en_curso"`), `created_at` y `updated_at`.
- Si ya existe una fila: actualiza **solo los campos que pasaron de `None`/vacío a un valor**. Un campo que ya tiene valor **nunca** se sobrescribe con `None`. Actualiza `updated_at` y opcionalmente el `estado` si se recibe uno nuevo.
- Esta lógica es crítica para el MVP: garantiza que los datos del lead solo se acumulan, nunca se pierden.
- Loguea `INFO` con la cantidad de campos con valor después del upsert.

**`mark_conversation_closed(chat_id)`**
- Actualiza la columna `estado` de todas las filas de ese `chat_id` en la hoja `conversaciones` a `"cerrada"`.

**Manejo de errores:**
- Cada operación está envuelta en try/except.
- Las funciones de lectura (`get_conversation_history`, `get_lead`) loguean `ERROR` y propagan la excepción para que el llamador decida qué hacer.
- Las funciones de escritura (`save_conversation_turn`, `upsert_lead`, `mark_conversation_closed`) loguean `ERROR` y **no** propagan: la respuesta al usuario ya se generó/envió, así que una falla de escritura no debe bloquear al usuario.
- Nunca se loguean datos sensibles (contenido de mensajes) en nivel `INFO` o superior.

---

## Fase 6 — Extracción estructurada

### Archivo a crear: `bot/extraction.py`

**Por qué existe:** aísla la llamada al LLM de extracción en su propio módulo. Recibe un historial de conversación y retorna un objeto `LeadRecord` con los campos que el LLM pudo extraer. No conoce Sheets ni Telegram.

**Qué define:**

**Modelo `LeadRecord`** — Modelo Pydantic con los 9 campos opcionales del lead, todos `str | None = None`:
- `nombre`, `ciudad`, `tipo_espacio`, `tipo_intervencion`, `area_aprox`, `situacion_actual`, `fecha_deseada`, `presupuesto`, `alcance`

**Función `extract_lead_data(history, chat_id)`:**

1. Construye los mensajes para el LLM de extracción: el `EXTRACTION_PROMPT` (importado de `prompts.py`) como system message, más el historial completo de la conversación como contexto.

2. Llama a `llm_extraction` (importado de `config.py`) con:
   - `model` = valor de `LLM_EXTRACTION_MODEL` (default: `gpt-4o-mini`)
   - `temperature` = 0.0 (extracción determinista, no creativa)
   - `response_format` con `json_schema` usando `LeadRecord.model_json_schema()` para obtener structured output

3. Parsea la respuesta JSON como un `LeadRecord` de Pydantic.

4. Loguea `INFO` con los campos que tienen valor (sin loguear los valores mismos, solo los nombres de campo).

5. Retorna el `LeadRecord`.

**Manejo de errores:** si la llamada falla (timeout, JSON malformado, error de cuota), loguea `ERROR` y retorna `None`. El llamador (`conversation.py`) continúa sin actualizar el lead. El usuario no se ve afectado porque la respuesta conversacional ya se generó antes de la extracción.

---

## Fase 7 — Lógica conversacional

### Archivo a crear: `bot/conversation.py`

**Por qué existe:** es el cerebro del bot. Orquesta todo el flujo de procesamiento de un mensaje. Importa `config`, `prompts`, `storage` y `extraction`. Es el módulo más complejo del proyecto.

**Función principal: `process_message(chat_id, user_id, text, timestamp, is_edited)`**

Recibe los datos extraídos por `webhook.py` y retorna el texto de respuesta que se enviará al usuario. El flujo paso a paso es:

**Paso 1 — Verificar horario de silencio.**
Llama a la función auxiliar `is_silence_hours()`. Si la hora actual en UTC-5 está entre 22:00 y 07:00, retorna el mensaje de ausencia definido en `config.py`. No llama al LLM ni toca Sheets. Loguea `INFO`: `"Silencio nocturno: chat_id=..."`.

**Paso 2 — Verificar si la conversación ya está cerrada.**
Llama a `storage.get_lead(chat_id)`. Si el lead existe y su `estado` es `calendly_enviado`, `limite_alcanzado` o `no_agendar`, retorna el mensaje fijo correspondiente sin llamar al LLM:
- Para `calendly_enviado` y `limite_alcanzado`: `"Hola! Ya estamos al tanto de tu proyecto. Si necesitas algo adicional, escríbenos por acá: {calendly_url}"`.
- Para `no_agendar`: `"Hola! Ya estamos al tanto de tu proyecto. Alejandro se pondrá en contacto contigo pronto."`.
- Loguea `INFO`: `"Conversación cerrada, mensaje fijo: chat_id=..."`.
- Si la llamada a Sheets falla aquí, asume que la conversación está `en_curso` y continúa con el flujo normal (loguea `ERROR`).

**Paso 3 — Leer historial de la conversación.**
Llama a `storage.get_conversation_history(chat_id)`. Si falla, retorna un mensaje de fallback al usuario: `"Disculpa, tuve un problema de agenda ¿Puedes repetir por favor?"`. Loguea `ERROR`.

**Paso 4 — Verificar límite de 30 mensajes.**
Cuenta los mensajes con `role=user` en el historial leído (usando la función auxiliar `count_user_messages()`). Si el conteo es ≥ 30:
- Ejecuta extracción final llamando a `extraction.extract_lead_data()`.
- Hace `storage.upsert_lead()` con estado `limite_alcanzado`.
- Llama a `storage.mark_conversation_closed()`.
- Retorna una respuesta de despedida con el enlace de Calendly e indicación de que Alejandro se pondrá en contacto.
- Loguea `WARNING`: `"Límite alcanzado: chat_id=..., mensajes=30"`.

**Paso 5 — Construir mensajes para el LLM conversacional.**
Prepara la lista de mensajes en el formato de la API de OpenAI:
- Posición 0: `SYSTEM_PROMPT` (importado de `prompts.py`) con `{calendly_url}` reemplazado por el valor de `CALENDLY_URL` de `config.py`. El reemplazo se hace siempre para que el LLM conozca la URL y pueda incluirla cuando decida que es momento de cerrar.
- Luego: el historial completo leído de Sheets.
- Último: el mensaje nuevo del usuario.

**Paso 6 — Llamar al LLM conversacional.**
Usa el cliente `llm` de `config.py` con el modelo `LLM_MODEL` y `temperature=0.7`. Loguea `DEBUG` con la longitud del historial antes de la llamada. Si la llamada falla (timeout, error de cuota, modelo no disponible):
- Loguea `ERROR`.
- Retorna el mensaje de fallback: `"Disculpa, tuve un problema y no me muestra los últimos mensajes ¿Puedes repetir por favor?"`.

**Paso 7 — Detectar cierre por URL de Calendly en la respuesta (Mecanismo 2 — principal).**
Verifica si la respuesta del LLM contiene la cadena configurada en `CALENDLY_URL`. Si la contiene:
- Marca como cierre. Ejecuta extracción final (independiente del conteo de `EXTRACTION_FREQUENCY`).
- Hace `storage.upsert_lead()` con estado `calendly_enviado`.
- Llama a `storage.mark_conversation_closed()`.
- Loguea `INFO`: `"Calendly detectado en respuesta LLM: chat_id=..."`.
- La respuesta conversacional no se modifica (ya contiene la URL de Calendly porque el LLM la incluyó).

**Paso 8 — Evaluar si toca ejecutar extracción periódica.**
Solo si NO se detectó cierre en el paso 7 (para no duplicar la extracción):
- Cuenta los mensajes `role=user` en el historial completo (incluyendo el mensaje nuevo que aún no se guardó, sumándole 1 al conteo).
- Usa la función auxiliar `should_extract()`: si `total_mensajes_user % EXTRACTION_FREQUENCY == 0`, ejecuta la extracción.
- Si toca: llama a `extraction.extract_lead_data()` con el historial completo. Si retorna un `LeadRecord` (no `None`), hace `storage.upsert_lead()`.
- Si no toca: loguea `DEBUG` con el conteo actual vs la frecuencia.

**Paso 9 — Verificar cierre por campos completos (Mecanismo 1 — respaldo).**
Solo si se ejecutó extracción en el paso 8:
- Llama a `storage.get_lead(chat_id)` para obtener el lead actualizado.
- Verifica si los 9 campos del `LeadRecord` están no nulos.
- Si todos están completos y no se detectó cierre en el paso 7: marca estado como `calendly_enviado` en Sheets y marca conversación cerrada.
- Este mecanismo **no controla la respuesta al usuario** (ya se generó en el paso 6). Solo asegura que el estado en Sheets refleje que la conversación está completa.
- Loguea `INFO`: `"Calendly enviado: chat_id=..., campos_completos=9/9"`.

**Paso 10 — Guardar turnos en Sheets.**
Llama a `storage.save_conversation_turn()` dos veces:
- Una con `role=user`, el `text` del usuario, y `timestamp`.
- Otra con `role=assistant`, la respuesta del LLM, y timestamp actual.
- El campo `estado` de ambos turnos es `"cerrada"` si se detectó cierre, o `"en_curso"` si no.

**Paso 11 — Retornar la respuesta** del LLM para que `webhook.py` la envíe al usuario.

---

**Funciones auxiliares dentro del módulo:**

- `is_silence_hours()` — Obtiene la hora actual en UTC-5 usando `datetime` y `timezone` de la stdlib. Retorna `True` si está entre 22:00 y 07:00.

- `should_extract(user_message_count)` — Retorna `True` si `user_message_count % EXTRACTION_FREQUENCY == 0`.

- `count_user_messages(history)` — Recibe la lista de historial y cuenta los dicts con `role == "user"`. Retorna un entero.

---

## Fase 8 — Webhook

### Archivo a crear: `bot/webhook.py`

**Por qué existe:** es la puerta de entrada HTTP del sistema. Recibe el POST de Telegram, extrae los datos relevantes, retorna 200 inmediatamente, y lanza el procesamiento en background. No contiene lógica de negocio.

**Lógica:**

1. Define la app FastAPI con un único endpoint: `POST /webhook`.

2. Recibe el JSON del update de Telegram. Verifica primero si contiene `message`; si no, verifica si contiene `edited_message`. De cualquiera de los dos extrae: `chat_id`, `user_id`, `text`, `timestamp`. Marca `is_edited=True` si vino de `edited_message`. Loguea `INFO` con el tipo de webhook recibido.

3. Detecta el tipo de contenido. Si `text` es `None` o vacío (foto, audio, sticker, etc.):
   - Loguea `INFO` con el tipo de contenido no soportado.
   - Lanza tarea en background que envía el mensaje gentil de contenido no soportado (definido en `config.py`) vía `bot.send_message()`.
   - Retorna HTTP 200.

4. **Retorna HTTP 200 inmediatamente** (sin esperar procesamiento). Esto evita que Telegram reintente el envío por timeout.

5. **Lanza tarea en background** usando `asyncio.create_task()` o `BackgroundTasks` de FastAPI. La tarea async ejecuta:
   - Llama a `conversation.process_message()` con los datos extraídos.
   - Espera `asyncio.sleep(1.0)` (delay de 1000 ms para simular tiempo de escritura humana).
   - Envía la respuesta al usuario vía `bot.send_message()` usando `python-telegram-bot`.
   - Todo envuelto en try/except: si falla el envío a Telegram, loguea `ERROR` con `chat_id` y mensaje de error.

**Nota sobre `python-telegram-bot`:** se usa únicamente para enviar mensajes (`bot.send_message()`). No se usa su sistema de handlers ni su polling, porque el bot recibe webhooks crudos con FastAPI.

---

## Fase 9 — Punto de entrada

### Archivo a crear: `main.py`

**Por qué existe:** es el archivo que se ejecuta para arrancar el servidor. Es el punto de entrada único del sistema.

**Lógica:**
- **Antes de cualquier import interno** que arrastre `bot.config` o `bot.webhook`: llamar a `load_dotenv()` desde `dotenv`, con ruta explícita al archivo `.env` en el directorio raíz del proyecto (mismo nivel que `main.py`), resolviendo la ruta con `pathlib.Path(__file__).resolve().parent / ".env"`, y `override=False` para no pisar variables ya definidas en el entorno (p. ej. en Railway/Render).
- Importa la app FastAPI definida en `bot/webhook.py`.
- Arranca `uvicorn` escuchando en el puerto que define la variable de entorno `PORT` (default `8000`). Railway y Render inyectan este valor automáticamente.
- No contiene lógica de negocio. Solo inicialización y carga de entorno local.

---

## Fase 10 — Tests unitarios

### Archivos a crear

---

### `tests/test_conversation.py`

**Por qué existe:** contiene los tests unitarios de los casos críticos definidos en el DoD (sección 5 del brief v4). Cada test aísla una función específica usando mocks que reemplazan dependencias reales (API de OpenAI / LLM, Google Sheets, Telegram).

**Tests que contiene:**

**Test 1 — Horario de silencio (DoD #1):**
- Mockea la hora actual a 23:00 UTC-5.
- Llama a `process_message()`.
- Verifica que la respuesta es el mensaje de ausencia.
- Verifica que **no** se llamó al LLM ni a Sheets.

**Test 2 — Límite de 30 mensajes (DoD #2):**
- Mockea `storage.get_conversation_history()` para que retorne un historial con 30 mensajes de usuario.
- Llama a `process_message()`.
- Verifica que se ejecutó la extracción final.
- Verifica que se llamó a `storage.upsert_lead()` con `estado="limite_alcanzado"`.
- Verifica que se llamó a `storage.mark_conversation_closed()`.
- Verifica que la respuesta contiene la URL de Calendly.

**Test 3 — Cierre con 9 campos / Calendly enviado (DoD #3):**
- Mockea la respuesta del LLM conversacional para que contenga la URL de Calendly.
- Llama a `process_message()`.
- Verifica que se ejecutó la extracción final exactamente una vez.
- Verifica que se llamó a `storage.upsert_lead()` con `estado="calendly_enviado"`.
- Verifica que se llamó a `storage.mark_conversation_closed()`.

**Test 6 — Frecuencia de extracción y upsert sin sobrescribir (DoD #6):**
- Configura `EXTRACTION_FREQUENCY=2`.
- Simula 3 mensajes secuenciales con historiales crecientes.
- Verifica que la extracción se ejecutó en el mensaje 2 (conteo par) pero no en el 1 ni en el 3.
- Para el test de upsert: mockea un lead existente con `nombre="Carlos"`. Ejecuta un upsert con un `LeadRecord` donde `nombre=None` y `ciudad="Bogotá"`. Verifica que después del upsert, `nombre` sigue siendo `"Carlos"` y `ciudad` es `"Bogotá"`.

**Test 8 — Fallback ante error del LLM conversacional (DoD #8):**
- Mockea el cliente LLM conversacional para que lance una excepción (timeout o error de cuota).
- Llama a `process_message()`.
- Verifica que el usuario recibe el mensaje de fallback: `"Disculpa, tuve un problema y no me muestra los últimos mensajes ¿Puedes repetir por favor?"`.
- Verifica que el error se logueó como `ERROR`.

**Test 10 — Webhook retorna 200 inmediatamente (DoD #10):**
- Usa el test client de FastAPI (`TestClient`) para enviar un POST al endpoint `/webhook` con un payload válido de Telegram.
- Verifica que la respuesta HTTP es 200.
- Verifica que el procesamiento se lanzó en background (el test no espera la respuesta al usuario).

---

### `tests/test_extraction.py`

**Por qué existe:** tests específicos del módulo de extracción, separados de los de conversación para mayor claridad.

**Tests que contiene:**

**Test — Extracción parcial exitosa:**
- Mockea el LLM de extracción para que retorne un JSON con 3 campos con valor y 6 con `null`.
- Llama a `extract_lead_data()` con un historial de ejemplo.
- Verifica que el `LeadRecord` retornado tiene los 3 campos con valor y los 6 como `None`.

**Test — Fallo de extracción no propaga:**
- Mockea el LLM de extracción para que lance una excepción.
- Llama a `extract_lead_data()`.
- Verifica que retorna `None` sin lanzar excepción.
- Verifica que el error se logueó.

---

### `tests/test_integration.py`

**Por qué existe:** simula una conversación completa de principio a fin para verificar que todos los módulos funcionan juntos correctamente. Es un requisito explícito del DoD.

**Test que contiene:**

**Test — Conversación completa (saludo → 9 campos → cierre):**
- Simula una secuencia de turnos donde el usuario va dando, progresivamente, los 9 campos requeridos (nombre, ciudad, tipo de espacio, tipo de intervención, área, situación actual, fecha deseada, presupuesto, alcance).
- Mockea el LLM conversacional para que en el último turno incluya la URL de Calendly en su respuesta.
- Mockea el LLM de extracción para que retorne `LeadRecords` progresivamente más completos.
- Mockea Google Sheets con un almacenamiento en memoria.
- Verifica que en cada turno se llamó a `storage.save_conversation_turn()`.
- Verifica que la hoja `leads` (mockeada) acumula campos progresivamente sin perder los anteriores.
- Verifica que al final, el lead tiene los 9 campos con valores correctos, estado `calendly_enviado`, y la conversación está marcada como cerrada.

---

## Fase 11 — Documentación

### Archivo a crear: `README.md`

**Por qué existe:** es el documento que cualquier persona lee primero al abrir el repositorio. Es un requisito explícito del DoD.

**Qué incluye:**

1. Descripción breve del proyecto y su propósito.
2. Requisitos previos: Python 3.11+, cuentas en Telegram (BotFather), OpenAI (API key), Google Cloud (Service Account), y Calendly.
3. Instrucciones de instalación local paso a paso:
   - Clonar el repo.
   - Crear entorno virtual (`python -m venv .venv` y activarlo).
   - Instalar dependencias (`pip install -r requirements.txt`).
   - Copiar `.env.example` a `.env` y completar los valores.
   - Correr el servidor localmente: `uvicorn main:app --host 0.0.0.0 --port 8000` (o el puerto deseado). Al cargar el módulo `main`, se ejecuta `load_dotenv()` antes de importar la app, por lo que el `.env` en la raíz del repo se aplica automáticamente. Alternativa sin depender del orden de imports del módulo: `python -m dotenv run -- uvicorn main:app --host 0.0.0.0 --port 8000`.
4. Tabla de variables de entorno con descripciones, ejemplos y valores por defecto.
5. Instrucciones para configurar el webhook de Telegram (cómo registrar la URL del servidor con la API de Telegram, incluyendo ngrok para pruebas locales).
6. Estructura del Google Sheet: nombres de hojas (`leads` y `conversaciones`) y columnas esperadas en cada una.
7. Instrucciones de despliegue en Railway o Render.
8. Procedimiento de prueba manual (referencia a la Fase 13).

---

## Fase 12 — Deploy inicial

No genera archivos. Es una fase de ejecución.

**Pasos:**
1. Crear el servicio en Railway o Render.
2. Configurar todas las variables de entorno en la plataforma de despliegue.
3. Hacer deploy del repositorio.
4. Verificar que el servicio arranca sin errores (revisar logs).
5. Registrar el webhook de Telegram con la URL pública del servicio: hacer un GET a `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url=https://{URL_PUBLICA}/webhook`.

---

## Fase 13 — Prueba manual (pre-producción)

No genera archivos. Es una fase de ejecución obligatoria antes de considerar el MVP terminado (requisito explícito del DoD, sección 5 del brief v4).

**Procedimiento:**

1. Instalar ngrok localmente (https://ngrok.com) o usar el túnel integrado de Railway/Render en modo preview.

   Asegurarse de que las variables estén en el proceso que ejecuta Uvicorn (véase brief v4 sección 5, nota sobre `.env` vs `os.environ`, y sección 8).

2. Levantar el servidor localmente: `uvicorn main:app --host 0.0.0.0 --port 8000`.
3. Exponer el puerto local: `ngrok http 8000`. Ngrok entrega una URL pública temporal (ej: `https://abc123.ngrok-free.app`).
4. Registrar el webhook temporal en Telegram: hacer un GET a `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url=https://abc123.ngrok-free.app/webhook`.
5. Abrir Telegram y buscar el bot por su nombre de usuario (el que se configuró en BotFather).
6. Simular una conversación completa: saludar, dar datos progresivamente, verificar tono, verificar que la hoja `leads` se actualiza, verificar que al completar datos el bot envía el enlace de Calendly.
7. Verificar en Google Sheets que ambas hojas (`conversaciones` y `leads`) reflejan los datos de la prueba.
8. Al terminar, registrar el webhook definitivo de producción con la URL de Railway/Render.

**Qué se valida específicamente:**
- El tono se siente humano (no suena a bot, ni a formulario, ni a atención al cliente genérica).
- La hoja `leads` se actualiza progresivamente según `EXTRACTION_FREQUENCY`.
- El cierre funciona por sus tres vías: 9 campos completos, solicitud del cliente con mínimos, y límite de 30 mensajes.
- El mensaje de ausencia se envía en horario de silencio.
- Mensajes no-texto (enviar una foto, audio, sticker) reciben respuesta gentil.
- Mensajes editados generan una nueva respuesta del bot.
- Conversaciones cerradas reciben el mensaje fijo correspondiente.

**Nota:** la URL de ngrok cambia cada vez que se reinicia, por lo que hay que re-registrar el webhook en cada sesión de prueba.

---

## Orden de implementación y justificación

| Fase | Archivos | Depende de | Justificación |
|---|---|---|---|
| 1 | `requirements.txt`, `.env.example`, `.gitignore`, `bot/__init__.py`, `tests/__init__.py` | Nada | Infraestructura base sin lógica. |
| 2 | `bot/logger.py` | Fase 1 (paquete `bot/` existente) | Todos los módulos lo importan; sin dependencias de imports internos, pero el archivo vive bajo `bot/` creado en Fase 1. |
| 3 | `bot/config.py` | `logger.py` | Segundo en la jerarquía. Todo lo demás usa la configuración. |
| 4 | `bot/prompts.py` | Nada | Solo texto. Se necesita antes de `conversation.py` y `extraction.py`. |
| 5 | `bot/storage.py` | `config.py`, `logger.py` | La conversación y extracción dependen de leer/escribir datos. |
| 6 | `bot/extraction.py` | `config.py`, `prompts.py`, `logger.py` | La conversación depende de poder extraer datos del lead. |
| 7 | `bot/conversation.py` | Todos los anteriores | Orquesta todo. Es el último módulo de lógica. |
| 8 | `bot/webhook.py` | `conversation.py`, `config.py`, `logger.py` | Punto de entrada HTTP. Necesita que exista la lógica. |
| 9 | `main.py` | `webhook.py` | Solo arranca el servidor. |
| 10 | `tests/test_conversation.py`, `tests/test_extraction.py` | Módulos correspondientes | Verifican la lógica de cada módulo en aislamiento. |
| 11 | `tests/test_integration.py` | Todos los módulos | Solo tiene sentido cuando todo existe. |
| 12 | `README.md` | Todo | Al final, cuando se sabe exactamente qué necesita el proyecto. |
| 13 | Deploy inicial | `README.md`, servicios externos configurados | El código debe estar completo y documentado. |
| 14 | Prueba manual | Deploy o ngrok | Requiere un servidor corriendo y servicios externos listos. |

---

## Resumen de archivos

| Archivo | Tipo | Descripción |
|---|---|---|
| `bot/__init__.py` | Nuevo | Archivo vacío, convierte `bot/` en paquete Python. |
| `bot/logger.py` | Nuevo | Logging centralizado con `get_logger()`. |
| `bot/config.py` | Nuevo | Variables de entorno, clientes LLM, constantes de negocio. |
| `bot/prompts.py` | Nuevo | System prompt y prompt de extracción como constantes de texto. |
| `bot/storage.py` | Nuevo | Lectura/escritura en Google Sheets (historial y leads con upsert). |
| `bot/extraction.py` | Nuevo | Schema `LeadRecord` (Pydantic) y llamada al LLM de extracción. |
| `bot/conversation.py` | Nuevo | Flujo completo de procesamiento de un mensaje (el cerebro). |
| `bot/webhook.py` | Nuevo | FastAPI endpoint, retorna 200 inmediato, procesa en background. |
| `main.py` | Nuevo | Punto de entrada: `load_dotenv()` y arranque de uvicorn. |
| `requirements.txt` | Nuevo | Dependencias del proyecto. |
| `.env.example` | Nuevo | Plantilla de variables de entorno. |
| `.gitignore` | Nuevo | Archivos y carpetas ignorados por Git. |
| `README.md` | Nuevo | Documentación del proyecto. |
| `tests/__init__.py` | Nuevo | Archivo vacío, convierte `tests/` en paquete Python. |
| `tests/test_conversation.py` | Nuevo | Tests unitarios de los 6 casos del DoD. |
| `tests/test_extraction.py` | Nuevo | Tests del módulo de extracción. |
| `tests/test_integration.py` | Nuevo | Test de conversación completa de principio a fin. |
