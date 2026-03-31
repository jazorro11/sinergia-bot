# Technical Brief — v4

---

## 1. Título de la tarea

Chatbot de Telegram para Captura Conversacional de Datos y Agendamiento vía Calendly – Estudio Sinergia

---

## 2. Contexto

El sistema actual **no existe**: Alejandro maneja manualmente todas las conversaciones con clientes potenciales vía Telegram, recibiendo entre 30 y 100 mensajes semanales de personas que solicitan información o exploran opciones de diseño residencial.

Esto genera problemas como **tiempo desperdiciado en atención inicial repetitiva, ausencia de un proceso sistemático de captura de datos del proyecto, y oportunidades perdidas cuando Alejandro está en obra o reunión y los mensajes se acumulan sin respuesta oportuna. Además, cuando una conversación se interrumpe inesperadamente (el usuario deja de responder, pierde señal, etc.), toda la información que ya había compartido se pierde porque no quedó registrada en ningún lado**.

El objetivo de esta tarea es **implementar un bot conversacional en Telegram que automatice la primera capa de atención, recopile de forma orgánica los datos clave del proyecto, los persista progresivamente, y cierre la conversación dirigiendo al cliente a un enlace de Calendly para agendar una videollamada** para mejorar **la eficiencia en la gestión de contactos, garantizar visibilidad en tiempo real del avance de cada conversación, y asegurar que ningún dato se pierda aunque la conversación se interrumpa**.

> **Regla fundamental del MVP:** La conversación debe sentirse completamente humana. El bot NO debe parecer bot. Esto aplica a tono, ritmo de respuesta, longitud de mensajes y manejo del contexto. El orden de captura de datos no es fijo: el bot extrae la información de forma orgánica según el flujo natural, nunca como formulario secuencial.

---

## 3. Requerimientos técnicos

### Lenguaje / Stack

- **Lenguaje:** Python 3.11+
- **Framework web:** FastAPI — expone un único endpoint POST `/webhook` que recibe eventos de Telegram
- **Librería del bot:** `python-telegram-bot` v20+
- **IA conversacional:** Cliente oficial `openai` de Python hacia la **API de OpenAI** (endpoint por defecto del SDK)
- **Modelo por defecto:** `gpt-4o` (configurable vía variable de entorno para usar otro modelo disponible en tu cuenta/plan sin modificar código)
- **Persistencia:** Google Sheets vía `gspread` + Google Service Account
- **Agendamiento:** Enlace externo de Calendly (sin integración API). El bot envía la URL al cierre de la conversación.
- **Logging:** `logging` de la stdlib de Python, con salida a stdout (capturado automáticamente por Railway/Render)
- **Despliegue:** Railway o Render (un único servicio, sin servicios adicionales)

---

### Arquitectura

Para el MVP se adopta una **arquitectura de capas simples**, priorizando la velocidad de desarrollo y la claridad sobre la complejidad estructural.

```
sinergia-bot/
├── bot/
│   ├── __init__.py      # Paquete Python (Fase 1 del plan de implementación v2)
│   ├── logger.py        # Logging centralizado (Fase 2)
│   ├── config.py        # Variables de entorno y clientes LLM
│   ├── prompts.py       # System prompt y prompt de extracción
│   ├── storage.py       # Google Sheets (historial + leads)
│   ├── extraction.py    # LeadRecord + llamada estructurada al LLM
│   ├── conversation.py  # Orquestación del flujo conversacional
│   └── webhook.py       # FastAPI: POST /webhook
├── tests/
│   └── __init__.py      # Paquete de tests (Fase 1)
├── main.py              # Punto de entrada (uvicorn)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

El **orden de implementación por fases** (qué archivo crear en cada paso) está detallado en `.cursor/docs/plan-implementacion-sinergia-bot-v2.md`. Las Fases 1 y 2 del plan cubren la infraestructura base (`requirements.txt`, `.env.example`, `.gitignore`, `bot/__init__.py`, `tests/__init__.py`) y `bot/logger.py`.

**Principios:**
- Las dependencias apuntan hacia adentro: `webhook.py` → `conversation.py` → `extraction.py` / `storage.py`. Nunca al revés.
- Las llamadas al LLM están aisladas: las conversacionales en `conversation.py`, las de extracción en `extraction.py`.
- `prompts.py` contiene los prompts como constantes de texto. Ningún otro módulo construye prompts inline.
- No existe estado en memoria entre peticiones. Todo el estado vive en Google Sheets.
- Cada módulo usa el logger configurado en `logger.py`. No se usa `print()` en ningún lugar.

**Gestión del estado conversacional:**

El historial de cada conversación se persiste en una hoja de Google Sheets llamada `conversaciones`. En cada mensaje entrante, el bot:

1. Lee el historial existente del `chat_id` desde la hoja `conversaciones`.
2. Añade el mensaje nuevo al historial.
3. Envía el historial completo al LLM (vía la API de OpenAI) para generar la respuesta.
4. Escribe el historial actualizado de vuelta en la hoja `conversaciones`.

**Extracción de datos del lead — frecuencia configurable:**

Después de la respuesta del LLM, el bot ejecuta una llamada al modelo de extracción usando `extraction.py`. La frecuencia de esta extracción es configurable mediante la variable de entorno `EXTRACTION_FREQUENCY` (valor por defecto: `1`, es decir, en cada mensaje).

El mecanismo es:

- `conversation.py` cuenta el total de mensajes con `role=user` en el historial leído de Sheets y calcula `total_mensajes_user % EXTRACTION_FREQUENCY`. Si el resultado es `0`, se ejecuta la extracción. Esto se deriva del historial que ya se leyó en el paso 1, sin estado adicional ni columnas extra en Sheets.
- Cuando el conteo alcanza el valor de `EXTRACTION_FREQUENCY`, se ejecuta la extracción.
- **Excepción:** la extracción también se ejecuta siempre al detectar el cierre de la conversación (9 campos completos, límite de 30 mensajes, o usuario no quiere agendar), sin importar el conteo.

La extracción recibe el historial completo de la conversación y devuelve un JSON estructurado con los campos del lead que el cliente haya mencionado.

La prioridad del MVP es que ningún dato se pierda. Con `EXTRACTION_FREQUENCY=1`, la hoja `leads` siempre refleja el estado más reciente. Si en producción el costo de tokens es alto, se puede cambiar a `2` o `3` sin tocar código.

La extracción usa un **modelo más económico** (`gpt-4o-mini` por defecto, configurable en `LLM_EXTRACTION_MODEL`) para minimizar costos, ya que esta tarea es más simple que la conversación.

Con `EXTRACTION_FREQUENCY=1` y una conversación de 30 mensajes, se generan 30 llamadas de extracción con historial creciente. El acumulado aproximado es ~150K tokens de entrada por conversación usando `gpt-4o-mini`. Los costos dependen de la [tabla de precios actual de la API de OpenAI](https://platform.openai.com/docs/pricing) (entrada/salida por modelo). Como referencia orientativa, en el volumen típico del MVP (30–100 conversaciones semanales, mensajes relativamente cortos) el gasto mensual del bot suele situarse en un rango bajo a moderado de USD, pero debe recalcularse con los precios vigentes y la longitud real de cada conversación.

El flujo por mensaje es:

```
Mensaje del usuario (message o edited_message)
    ↓
1. Leer historial de Sheets
2. Verificar restricciones (horario, límite, conversación cerrada)
3. Llamada al LLM → respuesta conversacional
4. ¿Conteo de mensajes desde última extracción >= EXTRACTION_FREQUENCY, o cierre detectado?
   ├─ SÍ → Llamada al LLM de extracción → LeadRecord parcial → Upsert en hoja 'leads'
   └─ NO → continuar sin extracción
5. Guardar turno en hoja 'conversaciones'
6. Enviar respuesta al usuario (con delay de 1000 ms)
```

**Lógica de upsert en la hoja `leads`:**

- Si no existe una fila con ese `chat_id`, se crea una nueva con los campos extraídos hasta el momento. Los campos no mencionados quedan vacíos.
- Si ya existe una fila, se actualizan **solo los campos que cambiaron de `None` a un valor**. Un campo que ya tiene valor nunca se sobrescribe con `None`. Esto garantiza que los datos solo se acumulan, nunca se pierden.
- El campo `updated_at` se actualiza en cada escritura.

**Detección de cierre y envío de Calendly:**

La conversación tiene una única fase principal: **captura de datos**. El cierre se detecta por **dos mecanismos complementarios**:

**Mecanismo 1 — Por campos completos en la hoja `leads` (marcado de estado):**

Después de cada extracción, `conversation.py` verifica si el `LeadRecord` en la hoja `leads` tiene los 9 campos no nulos. Si es así, marca el estado del lead como `calendly_enviado` en la hoja `leads`. Este mecanismo no controla la respuesta al usuario (la respuesta conversacional ya se generó en el paso 3 del flujo, antes de la extracción). Su función es asegurar que el estado en Sheets refleje que la conversación está completa.

**Mecanismo 2 — Por detección de URL de Calendly en la respuesta del LLM (mecanismo principal):**

Después de generar la respuesta conversacional (paso 3), `conversation.py` verifica si la respuesta del LLM contiene la URL de Calendly (la cadena configurada en `CALENDLY_URL`). Si el LLM decidió que es momento de cerrar y la incluyó en su respuesta, el bot ejecuta el cierre y marca el estado del lead como `calendly_enviado` en Sheets. Este es el mecanismo principal de cierre: el LLM tiene el historial completo y puede decidir orgánicamente cuándo enviar Calendly, sin depender de que la extracción haya corrido correctamente. El Mecanismo 1 actúa como respaldo para garantizar que el estado en Sheets se actualice incluso si el LLM no incluyó la URL explícitamente.

**Tabla de cierre:**

| Evento | Nuevo estado | Qué hace el bot |
|---|---|---|
| Los 9 campos del lead están completos (por extracción o por detección de URL) | `calendly_enviado` | El bot hace una transición natural ("Con esa info ya puedo preparar algo, agendemos una videollamada corta") y envía el enlace de Calendly. |
| El cliente solicita agendar antes de completar los 9 campos, pero tiene al menos los 3 mínimos (nombre, ciudad, área) | `calendly_enviado` | El bot no lo retiene: envía el enlace de Calendly con una transición natural. |
| Se alcanzó el límite de 30 mensajes sin completar los datos | `limite_alcanzado` | El bot se despide, envía el enlace de Calendly igualmente, e indica que Alejandro se pondrá en contacto si no agenda. |
| El usuario pide no agendar | `no_agendar` | El bot se despide amablemente. No envía Calendly. |

**Condiciones para enviar Calendly:**

- **Cierre ideal (9 campos):** todos los campos del lead están completos. El bot transiciona naturalmente.
- **Cierre por solicitud del cliente:** el cliente pide hablar o agendar antes de completar todos los datos. Se verifica que tenga **al menos 3 campos mínimos obligatorios: `nombre`, `ciudad` y `area_aprox`**. Si los tiene, se envía Calendly. Si no, el bot le pide amablemente los datos faltantes de esos 3 antes de enviar el enlace.
- **Cierre por límite de 30 mensajes:** se envía Calendly sin importar cuántos campos se hayan capturado.

En todos los casos de cierre:
1. Se ejecuta una extracción final (independiente del conteo de `EXTRACTION_FREQUENCY`).
2. Se marca la conversación como `cerrada` en la hoja `conversaciones`.
3. Se actualiza el `estado` del lead en la hoja `leads`.

**Comportamiento con conversaciones cerradas:**

Cuando un usuario con conversación cerrada (estado `calendly_enviado`, `limite_alcanzado` o `no_agendar`) envía un mensaje nuevo, el bot responde con un mensaje fijo sin llamar al LLM: *"Hola! Ya estamos al tanto de tu proyecto. Si necesitas algo adicional, escríbenos por acá: {calendly_url}"*. Para el estado `no_agendar`, el mensaje es: *"Hola! Ya estamos al tanto de tu proyecto. Alejandro se pondrá en contacto contigo pronto."*

Este comportamiento se verifica en el paso 2 del flujo (verificar restricciones), antes de cualquier llamada al LLM.

**Manejo de mensajes editados de Telegram:**

Telegram envía un webhook diferente cuando un usuario edita un mensaje (`edited_message` en lugar de `message`). El bot trata los mensajes editados como mensajes nuevos: extrae `chat_id`, `user_id`, `text` y `timestamp` del campo `edited_message` y los procesa con el mismo flujo que un mensaje normal. Esto permite al usuario corregir datos (por ejemplo, un nombre mal escrito) y que el bot capture la corrección.

`webhook.py` verifica primero si el update contiene `message`; si no, verifica si contiene `edited_message`. En ambos casos extrae los mismos campos y delega a `conversation.py`,  dado que los mensajes editados se procesan como mensajes nuevos, el usuario recibirá una segunda respuesta del bot al editar un mensaje anterior. Esto es intencional: permite capturar correcciones de datos. El usuario podría percibir dos respuestas al mismo mensaje; esto es una limitación aceptada del MVP.

**Google Sheets — estructura de hojas:**

| Hoja | Propósito |
|---|---|
| `leads` | Un registro por conversación con los datos del proyecto. Se actualiza según la frecuencia de extracción configurada. Alejandro lo consulta en tiempo real. |
| `conversaciones` | Historial de mensajes por `chat_id`. Uso técnico, no operativo. |

> **Nota:** para obtener un dashboard rápido del estado de las conversaciones, Alejandro puede agregar una hoja calculada en el mismo Google Sheet con fórmulas que cuenten los campos no vacíos de la hoja `leads` y filtren por estado. Esto no requiere código del bot.

---

### Modelo de procesamiento asíncrono del webhook

Telegram espera una respuesta HTTP rápida a cada webhook. Si el servidor no responde a tiempo, Telegram reintenta el envío, lo cual causa mensajes duplicados. Para evitar esto, el bot usa el siguiente patrón:

1. `webhook.py` recibe el POST de Telegram.
2. Retorna HTTP 200 **inmediatamente** (en menos de 1 segundo).
3. Lanza el procesamiento del mensaje como una **tarea en background** usando `asyncio.create_task()` o `BackgroundTasks` de FastAPI.
4. La tarea en background ejecuta todo el flujo: lectura de historial, llamada al LLM, extracción, escritura en Sheets, y envío de la respuesta al usuario vía la API de Telegram (`bot.send_message()`).

Este patrón garantiza que Telegram siempre recibe un 200 rápido y nunca reintenta. La respuesta al usuario se envía como una llamada separada a la API de Telegram, no como parte de la respuesta HTTP del webhook.

---

### Configuración del cliente LLM

Los clientes LLM se inicializan en `config.py` usando el SDK oficial de OpenAI contra el endpoint por defecto (`https://api.openai.com/v1`). No hace falta fijar `base_url` salvo que en el futuro se use un proxy o otro proveedor compatible.

```python
from openai import OpenAI

# Cliente para conversación (modelo principal)
llm = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
)

# Cliente para extracción (modelo económico)
llm_extraction = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
)
```

Las llamadas especifican el modelo como parámetro:

```python
# Ejemplo de llamada conversacional
response = llm.chat.completions.create(
    model=os.environ["LLM_MODEL"],  # ej: "gpt-4o"
    messages=messages,
    temperature=0.7,
)

# Ejemplo de llamada de extracción con structured output
response = llm_extraction.chat.completions.create(
    model=os.environ["LLM_EXTRACTION_MODEL"],  # ej: "gpt-4o-mini"
    messages=extraction_messages,
    temperature=0.0,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "lead_record",
            "strict": True,
            "schema": LeadRecord.model_json_schema()
        }
    }
)
```

Para cambiar de modelo, se modifica la variable de entorno `LLM_MODEL` o `LLM_EXTRACTION_MODEL`. El código no cambia.

---

### Extracción estructurada de datos del lead

La extracción se implementa en `extraction.py` usando el parámetro `response_format` del cliente `openai`, que permite definir un JSON schema y recibir la respuesta ya estructurada.

**Schema del lead:**

```python
from pydantic import BaseModel

class LeadRecord(BaseModel):
    nombre: str | None = None
    ciudad: str | None = None
    tipo_espacio: str | None = None
    tipo_intervencion: str | None = None
    area_aprox: str | None = None
    situacion_actual: str | None = None
    fecha_deseada: str | None = None
    presupuesto: str | None = None
    alcance: str | None = None
```

**Flujo de extracción:**

1. `extraction.py` recibe el historial completo de la conversación.
2. Construye los mensajes para el LLM de extracción: el prompt de extracción (de `prompts.py`) + el historial como contexto.
3. Llama al LLM con `response_format` usando el JSON schema de `LeadRecord`.
4. Parsea la respuesta JSON como un `LeadRecord` de Pydantic.
5. Retorna el objeto al llamador (`conversation.py`).

Si la llamada falla (timeout, error de formato), se loguea el error y se continúa sin actualizar el lead. El usuario no se ve afectado.

> **Deuda técnica aceptada para el MVP:** la extracción analiza el historial completo desde cero en cada ejecución. Si el usuario mencionó su nombre en el mensaje 2, la extracción lo re-extrae en los mensajes siguientes. Esto no es un problema funcional (la lógica de upsert lo maneja), pero sí un consumo innecesario de tokens. Para una iteración futura se podría enviar solo los mensajes nuevos desde la última extracción exitosa, o enviar el `LeadRecord` parcial actual como contexto para que el LLM solo complete los campos faltantes.

---

### System Prompt

Este es el system prompt que se pasa al LLM en cada llamada conversacional. Es el componente más crítico del MVP: define la personalidad, las reglas de captura de datos y el comportamiento de cierre. Se almacena como constante de texto en `prompts.py`.

```
Eres Alejandro, del Estudio Sinergia. Estudio de diseño de interiores y construcción residencial en Colombia.

Tu objetivo en esta conversación es conocer el proyecto de la persona, recopilar la información clave de forma natural, y cuando tengas lo necesario, invitarla a agendar una videollamada contigo.

QUIÉN ERES
Eres cercano, directo y profesional. Escribes como alguien ocupado pero atento: mensajes cortos, a veces dos seguidos en lugar de uno largo, sin emojis en exceso. Tuteas siempre. No suenas a bot ni a formulario. Nunca reveles que eres un asistente automático o una IA, bajo ninguna circunstancia.

QUÉ HACE ESTUDIO SINERGIA
Diseño de interiores y construcción residencial. Trabajamos con apartamentos y casas. Manejamos tres líneas de servicio:
- Línea modular: solo construcción (acabados, iluminación, carpintería). Sin diseño personalizado ni renders. Materiales estándar de una tendencia definida. Ideal para proyectos con presupuesto más ajustado.
- Línea plus: diseño + construcción. Incluye renders y diseño personalizado.
- Línea onpremium: diseño + construcción de mayor alcance y personalización.
También ofrecemos servicios separados de solo diseño o solo asesoría.

CÓMO DEBES CONVERSAR
- Responde siempre de forma breve. Máximo 3 oraciones por mensaje, idealmente menos.
- No hagas más de una pregunta por mensaje.
- No sigas un orden fijo de preguntas. Aprovecha lo que la persona menciona para obtener la información de forma orgánica.
- Si la persona da información voluntariamente, no la vuelvas a preguntar.
- Si la persona pregunta por precios, dile que eso depende del alcance y del proyecto, y que por eso es importante la llamada. No des cifras.
- Si pregunta algo que no puedes responder bien por chat, redirige amablemente hacia la llamada.

INFORMACIÓN QUE NECESITAS RECOPILAR
Durante la conversación debes obtener, sin seguir este orden:
1. Nombre de la persona
2. Ciudad o municipio del proyecto
3. Tipo de espacio (apartamento o casa)
4. Tipo de intervención (obra gris o renovación)
5. Área aproximada en m2
6. Fecha estimada de entrega o inicio del proyecto
7. Presupuesto aproximado (o si no lo tiene claro, cuál es su situación)
8. Situación actual del proyecto (ya entregado, en construcción, mirando opciones)
9. Alcance deseado (solo diseño, diseño + obra, solo obra, o asesoría)

CUÁNDO INVITAR A AGENDAR
Cuando hayas obtenido esos 9 datos, haz una transición natural hacia el agendamiento. Dile que con esa info ya puedes preparar algo y que te gustaría mostrarle todo en una videollamada corta. Luego invítalo a agendar con un mensaje como: "Te dejo mi enlace para que agendes cuando te quede bien: {calendly_url}"

Si la persona pide hablar o agendar antes de que hayas recopilado todo, verifica que al menos tengas su nombre, la ciudad del proyecto y el área aproximada. Si los tienes, pasa al agendamiento sin retenerla. Si falta alguno de esos tres, pídelo de forma natural antes de enviar el enlace.

Si la persona dice que no quiere agendar, responde amablemente.

LO QUE NUNCA DEBES HACER
- Revelar que eres un bot o una IA
- Dar precios o presupuestos específicos
- Hacer más de una pregunta por mensaje
- Sonar como un formulario o un proceso de admisión
- Usar frases genéricas de atención al cliente como "con gusto te ayudo" o "claro que sí"
```

**Nota sobre `{calendly_url}`:** esta variable se reemplaza en `conversation.py` con el valor de la variable de entorno `CALENDLY_URL` antes de pasarle el prompt al LLM. El reemplazo se hace **siempre** (el LLM necesita conocer la URL para incluirla cuando decida que es momento de cerrar). El LLM decide cuándo mencionarla según las reglas del prompt.

---

### Prompt de extracción

Este prompt se usa en la llamada al LLM de extracción estructurada. Se almacena como constante de texto en `prompts.py`. Se usa junto con `response_format` del cliente `openai`.

```
Analiza el siguiente historial de conversación entre un asesor de diseño de interiores y un cliente potencial.

Extrae únicamente los datos que el cliente haya mencionado explícitamente. No inventes ni asumas información que no esté en la conversación.

Los campos a extraer son:
- nombre: nombre de la persona
- ciudad: ciudad o municipio donde está el proyecto
- tipo_espacio: "apartamento" o "casa"
- tipo_intervencion: "obra gris" o "renovación"
- area_aprox: área aproximada en metros cuadrados
- situacion_actual: estado del proyecto (entregado, en construcción, mirando opciones, etc.)
- fecha_deseada: fecha estimada de inicio o entrega
- presupuesto: presupuesto aproximado o indicación de su situación económica
- alcance: qué servicio busca (solo diseño, diseño + obra, solo obra, asesoría)

Si un dato no fue mencionado, devuelve null para ese campo.
```

---

### Manejo de errores

Cada llamada a un servicio externo (API de OpenAI, Google Sheets, Telegram API) debe estar envuelta en un bloque try/except. El patrón es:

| Servicio | Qué puede fallar | Qué hace el bot |
|---|---|---|
| **API OpenAI (conversacional)** | Timeout, error de cuota, modelo no disponible | Loguea el error. Envía al usuario: *"Disculpa, tuve un problema y no me muestra los últimos mensajes ¿Puedes repetir por favor?"*. |
| **API OpenAI (extracción)** | Timeout, JSON malformado, error de cuota | Loguea el error. **No afecta al usuario**: la respuesta conversacional ya se generó. El lead no se actualiza en este turno, pero se actualizará en el siguiente. |
| **Google Sheets (lectura)** | Timeout, error de red, límite de API | Loguea el error. Envía al usuario: *"Disculpa, tuve un problema de agenda ¿Puedes repetir por favor?"*. |
| **Google Sheets (escritura)** | Timeout, error de red, límite de API | Loguea el error. La respuesta conversacional ya se envió. Los datos se recuperarán en el siguiente turno porque el historial incluirá este mensaje. |
| Google Sheets (lectura de estado del lead) | Timeout, error de red, límite de API | Loguea el error. El bot asume que la conversación está en_curso y continúa con el flujo normal. En el peor caso, un usuario con conversación cerrada recibe una respuesta conversacional en lugar del mensaje fijo. |
| **Telegram API (envío)** | Timeout, bot bloqueado, chat no encontrado | Loguea el error. No se puede hacer nada más: el canal de comunicación falló. |

**Regla general:** el webhook **siempre** retorna HTTP 200 a Telegram inmediatamente (ver sección de procesamiento asíncrono). Los errores se manejan dentro de la tarea en background y se loguean. El usuario recibe un mensaje de fallback cuando es posible.

---

### Input esperado

Mensaje entrante desde Telegram vía webhook HTTP POST:

```python
TelegramMessage
- chat_id:    str   # ID único de la conversación (no nulo)
- user_id:    str   # ID del usuario en Telegram (no nulo)
- text:       str   # Contenido del mensaje; si es None o vacío → respuesta de tipo no soportado
- timestamp:  int   # Unix timestamp del mensaje (no nulo)
- is_edited:  bool  # True si proviene de edited_message, False si proviene de message. Usado por webhook.py para diferenciar el log ("Webhook recibido" vs "Mensaje editado recibido")
```

Estos datos provienen del objeto `Update` de la API de Telegram. `webhook.py` extrae los mismos campos tanto de `message` como de `edited_message`. FastAPI los recibe como JSON en el body del POST a `/webhook`.

---

### Output esperado

**Respuesta al usuario:**

```python
BotResponse
- message:   str   # Texto generado por el LLM, máximo ~200 caracteres idealmente
```

**Registro en Google Sheets (hoja `leads`):**

```python
LeadRecord  # Schema Pydantic para extracción estructurada
- nombre:               str | None
- ciudad:               str | None
- tipo_espacio:         str | None   # Apartamento / Casa
- tipo_intervencion:    str | None   # Obra gris / Renovación
- area_aprox:           str | None   # Rango en m2
- situacion_actual:     str | None   # Entregado / En construcción / Mirando opciones / Otro
- fecha_deseada:        str | None   # Fecha objetivo de entrega
- presupuesto:          str | None   # Presupuesto aproximado o "no definido"
- alcance:              str | None   # Solo diseño / Diseño + Obra / Solo obra / Asesoría
```

**Campos adicionales gestionados por `storage.py` (no por el LLM):**

```python
LeadRow  # Fila completa en la hoja 'leads'
- chat_id:              str          # Identificador de la conversación (clave primaria)
- nombre:               str | None   # ─┐
- ciudad:               str | None   #  │
- tipo_espacio:         str | None   #  │
- tipo_intervencion:    str | None   #  │  Campos extraídos por el LLM
- area_aprox:           str | None   #  │
- situacion_actual:     str | None   #  │
- fecha_deseada:        str | None   #  │
- presupuesto:          str | None   #  │
- alcance:              str | None   # ─┘
- estado:               str          # "en_curso" | "calendly_enviado" | "limite_alcanzado" | "no_agendar"
- created_at:           datetime     # Fecha de creación de la fila
- updated_at:           datetime     # Fecha de última actualización
```

**Campos mínimos para enviar Calendly:**

El bot envía el enlace de Calendly cuando se cumple **cualquiera** de estas condiciones:

1. **Los 9 campos están completos** → cierre ideal (detectado por extracción o por URL en respuesta del LLM).
2. **El cliente solicita agendar** y tiene al menos `nombre`, `ciudad` y `area_aprox` → cierre por solicitud.
3. **Se alcanzó el límite de 30 mensajes** → cierre forzado (se envía Calendly sin importar campos).

Si el cliente solicita agendar pero **no tiene los 3 campos mínimos** (`nombre`, `ciudad`, `area_aprox`), el bot le pide los faltantes de forma natural antes de enviar el enlace.

---

## 4. Constraints (Restricciones)

- Librerías permitidas: `fastapi`, `uvicorn`, `python-telegram-bot`, `openai`, `gspread`, `google-auth`, `httpx`, `pydantic`, y stdlib de Python. Dependencias de desarrollo: `pytest` y `ruff`. No añadir dependencias fuera de esta lista sin justificación explícita.
- Todas las llamadas al LLM pasan a través del cliente `openai` hacia la **API de OpenAI** (endpoint por defecto del SDK).
- Type hints en todas las funciones públicas de los módulos principales.
- Convenciones PEP 8. Linter: `ruff`.
- Las credenciales (token de Telegram, OpenAI API key, Google Service Account JSON, URL de Calendly) deben estar exclusivamente en variables de entorno. Prohibido hardcodear.
- La hoja `leads` se actualiza (upsert) según la frecuencia configurada en `EXTRACTION_FREQUENCY` (por defecto: cada mensaje). La lógica de upsert nunca sobrescribe un campo que ya tiene valor con `None`.
- Antes de enviar cada respuesta al usuario, el bot aplica un retraso fijo de 1000 ms para simular tiempo de escritura humano.
- El historial en la hoja `conversaciones` se actualiza en cada mensaje (lectura + escritura por turno).
- Todos los campos del `LeadRecord` son opcionales. Los campos `chat_id`, `estado`, `created_at` y `updated_at` son gestionados por `storage.py` y siempre están presentes.
- El bot no responde entre las 10 PM y las 7 AM hora Colombia (UTC-5). En esa franja responde con el siguiente mensaje de ausencia y no llama al LLM: *"Hola! En este momento no estoy disponible, pero mañana en la mañana te respondo 😌"*
- El bot solo procesa mensajes de texto (incluyendo mensajes editados). Ante imágenes, audio, stickers u otros tipos responde con un mensaje gentil indicando que solo puede leer texto por ahora.
- Límite de conversación: 30 mensajes por sesión. Al alcanzarlo, el bot cierra el flujo, actualiza el estado del lead a `limite_alcanzado`, envía el enlace de Calendly, e indica que Alejandro se pondrá en contacto si no agenda.
- El webhook retorna HTTP 200 a Telegram inmediatamente (< 1 segundo). Todo el procesamiento ocurre en background.
- El MVP no incluye panel web ni rutas que sirvan HTML al usuario final.
- El modelo conversacional y el modelo de extracción son configurables por separado vía variables de entorno (`LLM_MODEL` y `LLM_EXTRACTION_MODEL`).
- **Logging obligatorio** en todos los módulos (ver sección 6).
- Cada llamada a un servicio externo debe tener manejo de errores explícito (ver sección de Manejo de errores en la arquitectura).

---

## 5. Definition of Done (DoD)

El trabajo se considera terminado cuando:

- [ ] El código pasa `ruff` sin errores.
- [ ] Type hints implementados en todas las funciones públicas de `conversation.py`, `extraction.py`, `storage.py` y `webhook.py`.
- [ ] Los siguientes casos críticos tienen test unitario:
  - (1) Bot no llama al LLM en franja de silencio.
  - (2) Bot cierra flujo y actualiza estado del lead a `limite_alcanzado` al alcanzar 30 mensajes.
  - (3) Bot envía enlace de Calendly al capturar los 9 campos.
  - (6) La extracción respeta la frecuencia configurada en `EXTRACTION_FREQUENCY` y actualiza la hoja `leads` sin sobrescribir campos existentes con `None`.
  - (8) Los errores de la API de OpenAI (LLM conversacional) no dejan al usuario sin respuesta (se envía mensaje de fallback).
  - (10) El webhook retorna HTTP 200 inmediatamente y procesa en background.
- [ ] Existe al menos un test de integración que simula una conversación completa: saludo → captura progresiva de los 9 campos → detección de datos completos → envío de enlace de Calendly → cierre.
- [ ] El bot responde con el tono definido en el system prompt (cercano, breve, sin parecer bot).
- [ ] La hoja `leads` refleja los datos capturados según la frecuencia de extracción configurada.
- [ ] El bot no responde en la franja 10 PM – 7 AM hora Colombia, y responde con mensaje de ausencia.
- [ ] El bot responde con mensaje gentil ante mensajes que no son texto.
- [ ] El servicio está desplegado en Railway o Render con URL pública y webhook de Telegram apuntando a esa URL.
- [ ] Variables de entorno configuradas en la plataforma de despliegue (incluyendo `LLM_MODEL`, `LLM_EXTRACTION_MODEL`, `OPENAI_API_KEY`, `CALENDLY_URL` y `EXTRACTION_FREQUENCY`).
- [ ] El Google Sheet tiene las hojas `leads` y `conversaciones` con los encabezados correctos, y el Service Account tiene permisos de edición sobre el Sheet.
- [ ] El README del repositorio incluye instrucciones de instalación local, configuración del webhook de Telegram, y tabla de variables de entorno con valores por defecto.
- [ ] No se introducen dependencias fuera de las listadas en los constraints.
- [ ] Logging implementado según la especificación de la sección 6 (todos los eventos críticos registrados, sin datos sensibles en los logs).
- [ ] Se realizó al menos una prueba manual de conversación completa antes del deploy a producción, siguiendo el procedimiento documentado a continuación.

### Procedimiento de prueba manual

Antes de desplegar a producción, es obligatorio probar el bot con una conversación real en Telegram. El procedimiento es:

1. **Instalar ngrok** (https://ngrok.com) o usar el túnel integrado de Railway/Render en modo preview.
2. **Levantar el servidor localmente:** `uvicorn main:app --port 8000`.
3. **Exponer el puerto local:** `ngrok http 8000`. Ngrok entrega una URL pública temporal (ej: `https://abc123.ngrok-free.app`).
4. **Registrar el webhook temporal en Telegram:** hacer un GET a `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url=https://abc123.ngrok-free.app/webhook`.
5. **Abrir Telegram** y buscar el bot por su nombre de usuario (el que se configuró en BotFather).
6. **Simular una conversación completa:** saludar, dar datos progresivamente, verificar que el bot responde con el tono correcto, verificar que la hoja `leads` se actualiza, y verificar que al completar los datos el bot envía el enlace de Calendly.
7. **Verificar en Google Sheets** que tanto la hoja `conversaciones` como `leads` reflejan los datos de la prueba.
8. **Al terminar**, registrar el webhook definitivo de producción con la URL de Railway/Render.

> **Nota:** ngrok tiene un plan gratuito suficiente para pruebas. La URL temporal cambia cada vez que se reinicia ngrok, por lo que hay que re-registrar el webhook en cada sesión de prueba.

---

## 6. Logging y Observabilidad

### Por qué es obligatorio

Sin logging, cuando algo falla en producción no hay forma de saber qué pasó. Un error no manejado en el bot significa un mensaje sin respuesta y un cliente potencial perdido. El logging es un requerimiento de primera clase, no un nice-to-have.

### Implementación

**Módulo `bot/logger.py`:**

Configura un logger centralizado usando `logging` de la stdlib de Python. Todos los demás módulos importan el logger desde aquí.

```python
import logging
import os
import sys

def _parse_log_level() -> int:
    raw = os.environ.get("LOG_LEVEL", "INFO")
    level = getattr(logging, raw.upper(), None)
    if isinstance(level, int):
        return level
    return logging.INFO

logging.basicConfig(
    level=_parse_log_level(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

Cada módulo crea su propio logger al inicio:

```python
from bot.logger import get_logger
logger = get_logger(__name__)
```

### Qué se loguea y en qué nivel

| Módulo | Evento | Nivel | Ejemplo |
|---|---|---|---|
| `webhook.py` | Webhook recibido | `INFO` | `Webhook recibido: chat_id=12345, tipo=text` |
| `webhook.py` | Mensaje editado recibido | `INFO` | `Mensaje editado: chat_id=12345` |
| `webhook.py` | Tipo de contenido no soportado | `INFO` | `Contenido no soportado: chat_id=12345, tipo=photo` |
| `webhook.py` | Error al enviar respuesta a Telegram | `ERROR` | `Error enviando a Telegram: chat_id=12345, error=...` |
| `conversation.py` | Franja de silencio activada | `INFO` | `Silencio nocturno: chat_id=12345` |
| `conversation.py` | Conversación cerrada (mensaje a usuario existente) | `INFO` | `Conversación cerrada, mensaje fijo: chat_id=12345` |
| `conversation.py` | Límite de 30 mensajes alcanzado | `WARNING` | `Límite alcanzado: chat_id=12345, mensajes=30` |
| `conversation.py` | Cierre con Calendly enviado (por 9 campos) | `INFO` | `Calendly enviado: chat_id=12345, campos_completos=9/9` |
| `conversation.py` | Cierre con Calendly enviado (por URL en respuesta) | `INFO` | `Calendly detectado en respuesta LLM: chat_id=12345` |
| `conversation.py` | Cierre por solicitud con mínimos | `INFO` | `Calendly por solicitud: chat_id=12345, campos_completos=5/9` |
| `conversation.py` | Cierre por no_agendar | `INFO` | `No agendar: chat_id=12345` |
| `conversation.py` | Llamada al LLM conversacional | `DEBUG` | `LLM request: chat_id=12345, historial_len=8` |
| `conversation.py` | Respuesta del LLM recibida | `DEBUG` | `LLM response: chat_id=12345, len=142` |
| `conversation.py` | Error en LLM conversacional (fallback enviado) | `ERROR` | `Error LLM conversacional: chat_id=12345, error=...` |
| `extraction.py` | Extracción ejecutada | `INFO` | `Extracción: chat_id=12345, campos_nuevos=[nombre, ciudad]` |
| `extraction.py` | Extracción omitida (frecuencia no alcanzada) | `DEBUG` | `Extracción omitida: chat_id=12345, conteo=1/3` |
| `extraction.py` | Error en extracción (no afecta al usuario) | `ERROR` | `Error extracción: chat_id=12345, error=...` |
| `storage.py` | Lectura de historial | `DEBUG` | `Historial leído: chat_id=12345, turnos=12` |
| `storage.py` | Upsert de lead | `INFO` | `Lead actualizado: chat_id=12345, campos_con_valor=5/9` |
| `storage.py` | Error de Google Sheets | `ERROR` | `Error Sheets: operación=upsert_lead, error=...` |
| `config.py` | Variables de entorno cargadas | `INFO` | `Config cargada: LLM_MODEL=gpt-4o, EXTRACTION_FREQUENCY=1` |
| `config.py` | Variable de entorno faltante | `CRITICAL` | `Variable faltante: TELEGRAM_BOT_TOKEN` |

### Reglas de logging

- **Nunca loguear contenido de mensajes del usuario ni respuestas del LLM** en nivel `INFO` o superior. Estos contienen datos personales. Solo en `DEBUG` y con el entendimiento de que `DEBUG` no se activa en producción.
- **Nunca loguear tokens, API keys ni credenciales** en ningún nivel.
- **Siempre incluir `chat_id`** en los logs para poder rastrear una conversación completa.
- **El nivel por defecto en producción es `INFO`.** Se cambia a `DEBUG` vía la variable de entorno `LOG_LEVEL` solo para diagnóstico temporal.
- **Los errores de servicios externos** (API de OpenAI, Google Sheets, Telegram) siempre se loguean como `ERROR` con el mensaje de error original (sin stack trace completo en producción, a menos que `LOG_LEVEL=DEBUG`).

---

## 7. Configuración externa requerida (fuera del código)

Antes de que el código funcione, hay que configurar cuatro servicios externos:

### Telegram
- Crear un bot nuevo con **BotFather** en Telegram.
- BotFather entrega el `TELEGRAM_BOT_TOKEN`.
- Una vez el servidor esté desplegado con URL pública, registrar esa URL como webhook con una llamada HTTP a la API de Telegram.

### OpenAI
- Crear o usar una cuenta en [platform.openai.com](https://platform.openai.com).
- Generar una **API key** en la sección de API keys.
- Configurar límites de facturación o crédito según tu uso y comprobar que los modelos elegidos (`LLM_MODEL`, `LLM_EXTRACTION_MODEL`) están disponibles para tu proyecto.

### Google Sheets
- Crear un Google Sheet con dos hojas: `leads` y `conversaciones`.
- En la hoja `leads`: crear encabezados en la primera fila con los nombres exactos de los campos del `LeadRow`.
- En la hoja `conversaciones`: crear encabezados: `chat_id`, `role`, `content`, `timestamp`, `estado`.
- Crear un **Service Account** en Google Cloud Console.
- Dar al Service Account permisos de edición sobre el Google Sheet.
- Descargar el JSON de credenciales del Service Account.

### Calendly
- Crear o usar una cuenta de Calendly existente.
- Configurar un tipo de evento de 45 minutos para videollamada.
- Obtener la URL pública del evento (ej: `https://calendly.com/estudio-sinergia/llamada-inicial`).
- Configurar esta URL en la variable de entorno `CALENDLY_URL`.

---

## 8. Variables de entorno

| Variable | Descripción | Ejemplo | Requerida |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram (BotFather) | `123456:ABC-DEF...` | Sí |
| `OPENAI_API_KEY` | API Key de OpenAI | `sk-...` | Sí |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | JSON del Service Account como string | `{"type":"service_account",...}` | Sí |
| `GOOGLE_SHEET_ID` | ID del Google Sheet | `1BxiMVs0XRA5nFMdKvBd...` | Sí |
| `CALENDLY_URL` | URL del evento de Calendly | `https://calendly.com/estudio-sinergia/llamada` | Sí |
| `LLM_MODEL` | Modelo OpenAI para conversación | `gpt-4o` | Sí |
| `LLM_EXTRACTION_MODEL` | Modelo OpenAI para extracción | `gpt-4o-mini` | Sí |
| `EXTRACTION_FREQUENCY` | Cada cuántos mensajes del usuario se ejecuta la extracción | `1` | No (default: `1`) |
| `LOG_LEVEL` | Nivel de logging | `INFO` | No (default: `INFO`) |
| `PORT` | Puerto del servidor (inyectado por Railway/Render) | `8080` | No (default: `8000`) |

---

## 9. Fuera del alcance del MVP

Las siguientes funcionalidades están explícitamente **fuera del alcance** de esta versión. Se documentan para evitar ambigüedades y para informar decisiones en iteraciones futuras.

| Funcionalidad | Por qué está fuera del MVP | Posible iteración futura |
|---|---|---|
| **Intervención manual de Alejandro en conversaciones activas** | Si Alejandro escribe directamente por Telegram a un usuario que el bot está atendiendo, esos mensajes no pasan por el webhook y no se registran en el historial. Esto rompe la continuidad de la conversación para el bot. Resolver esto requiere acceso a la API de Telegram como usuario (no como bot), lo cual es significativamente más complejo. | Implementar un comando `/takeover` que pause el bot para ese `chat_id` y permita a Alejandro responder directamente. Los mensajes de Alejandro se registrarían manualmente o a través de un panel web. |
| **Optimización de extracción incremental** | La extracción analiza el historial completo desde cero cada vez, lo cual consume tokens innecesariamente. Para el MVP el costo es aceptable porque el modelo de extracción es económico y las conversaciones son cortas (máximo 30 mensajes). | Enviar solo los mensajes nuevos desde la última extracción exitosa, o enviar el `LeadRecord` parcial actual como contexto para que el LLM solo complete campos faltantes. |
| **Panel web de administración** | Alejandro consulta directamente el Google Sheet. No hay panel web. | Dashboard web con filtros, métricas y acciones rápidas. |
| **Agendamiento directo por Google Calendar** | Se usa Calendly como solución externa. El usuario sale del chat para agendar. | Integración con Google Calendar API para proponer y confirmar horarios dentro del chat. |
| **Soporte multiidioma** | Todas las conversaciones son en español. | Detección de idioma y respuesta en el idioma del usuario. |

---

## 9b. Mejoras post-MVP (no incluir en el plan de implementación)

Las siguientes mejoras fueron identificadas durante la revisión del brief. Son relevantes para iteraciones futuras pero **no deben incluirse en el plan de implementación del MVP ni en su desarrollo**. Se documentan aquí exclusivamente como referencia.

| Mejora | Descripción | Impacto esperado |
|---|---|---|
| **Delay proporcional a longitud de respuesta** | Reemplazar el delay fijo de 1000 ms por un cálculo proporcional a la cantidad de caracteres de la respuesta (ej: `min(len(respuesta) * 30, 3000)` ms). Un "Sí, dale" debería tardar menos que una respuesta de 3 oraciones. | Conversación más natural. Reduce la sensación de bot. |
| **Mensajes de error con tono humano** | Los mensajes de fallback actuales ("Disculpa, tuve un problema y no me muestra los últimos mensajes") suenan a sistema. Reescribirlos con el tono del system prompt: "Perdón, se me cruzó algo, ¿qué me decías?" o similar. | Consistencia con la identidad de "Alejandro". |
| **TTL de conversaciones inactivas** | Definir un tiempo máximo de inactividad (ej: 7 días). Si el usuario vuelve después de ese período, tratar como conversación nueva o enviar un mensaje de reconexión en lugar de retomar con un historial viejo. | Evita contexto stale y reduce costo de tokens al no enviar historiales antiguos al LLM. |
| **Normalización de campos del LeadRecord** | Campos como `area_aprox` y `presupuesto` son strings libres. El LLM puede extraer "más o menos 80 metros", "entre 50 y 80m2", o "80" para el mismo dato. Agregar normalización post-extracción o guías más estrictas en el prompt de extracción. | Datos más consistentes en la hoja de leads. Menos interpretación manual por Alejandro. |
| **Manejo de mensajes simultáneos del mismo usuario** | Si un usuario envía 3 mensajes rápidos, las 3 tareas background leen el mismo historial y generan respuestas independientes, causando posibles condiciones de carrera en escritura. Implementar un lock por `chat_id` o una cola de procesamiento secuencial. | Evita respuestas duplicadas o inconsistentes y corrupción del historial. |
| **Límites de Google Sheets documentados** | La API tiene un límite de 60 solicitudes/minuto. Con 4 llamadas por mensaje, a ~15 mensajes concurrentes comienzan los errores 429. Documentar el umbral y planificar migración a base de datos si el volumen crece. | Visibilidad sobre el techo de escalabilidad del MVP. |
| **Tests unitarios adicionales** | Tests que quedaron fuera del MVP: (4) Calendly con 3 campos mínimos por solicitud del cliente, (5) bot pide campos mínimos faltantes, (7) cambio de modelo vía variable de entorno, (9) errores de Sheets no bloquean respuesta, (11) detección de cierre por URL de Calendly en respuesta, (12) mensaje fijo a conversaciones cerradas, (13) procesamiento de mensajes editados. | Mayor cobertura de tests para casos edge. |

---

## 10. Resumen de dependencias entre módulos

```
main.py
  └─ importa → bot/webhook.py
                  └─ importa → bot/conversation.py
                                  ├─ importa → bot/config.py
                                  ├─ importa → bot/extraction.py
                                  │               └─ importa → bot/config.py (llm_extraction)
                                  │               └─ importa → bot/prompts.py
                                  ├─ importa → bot/storage.py
                                  │               └─ importa → bot/config.py
                                  └─ importa → bot/prompts.py

bot/logger.py  ← importado por todos los módulos
```

`config.py` y `logger.py` no importan nada interno. Son el nivel más bajo de la jerarquía.

---

## Changelog v3 → v4

| # | Cambio | Motivo |
|---|---|---|
| 1 | Frecuencia de extracción configurable vía `EXTRACTION_FREQUENCY` (default: 1) | Permite ajustar el balance costo/frescura sin cambiar código. |
| 2 | Eliminada la hoja `estado_conversaciones` | Redundante con la hoja `leads`. El dashboard se resuelve con fórmulas de Sheets. |
| 3 | Delay de respuesta ajustado a 1000 ms (era 2000 ms en v3) | 2000 ms se sentía artificialmente lento para mensajes cortos. |
| 4 | Webhook retorna HTTP 200 inmediatamente, procesamiento en background | Evita timeouts y reintentos de Telegram. Patrón recomendado para bots con LLM. |
| 5 | Comportamiento explícito para conversaciones cerradas | Antes no se especificaba qué pasaba si un usuario con conversación cerrada escribía de nuevo. |
| 6 | Detección de cierre por URL de Calendly en respuesta del LLM | Mecanismo de respaldo: si la extracción falla, el cierre no se bloquea. |
| 7 | Estado unificado a `no_agendar` (era `no agendar` y `no contactar` en v3) | Consistencia entre la tabla de cierre y el schema de `LeadRow`. |
| 8 | Mensajes editados (`edited_message`) procesados como mensajes nuevos | Permite al usuario corregir datos. Antes se ignoraban silenciosamente. |
| 9 | Extracción desde cero y la intervención manual de Alejandro documentadas como fuera del alcance | Transparencia sobre limitaciones aceptadas del MVP. |
| 10 | Eliminada la sección de agentes de Cursor (QA y Code Reviewer) | Prematura para un MVP sin código. Los criterios de calidad están cubiertos por el DoD. |

### Actualización post v4 (proveedor LLM)

| # | Cambio | Motivo |
|---|---|---|
| 1 | OpenRouter → **API de OpenAI** (`OPENAI_API_KEY`, modelos `gpt-4o` / `gpt-4o-mini`, endpoint por defecto del SDK) | Alinear documentación y pruebas con la clave disponible en el proyecto; misma arquitectura y SDK `openai`. |
