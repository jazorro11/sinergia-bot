# sinergia-bot

Bot de conversación en Telegram para **Estudio Sinergia**. Recibe actualizaciones vía webhook (`POST /webhook`), procesa el mensaje en segundo plano con FastAPI, usa OpenAI para la conversación y la extracción de datos, persiste historial y leads en **Google Sheets**, y puede cerrar la conversación enviando la URL de **Calendly**.

Flujo resumido: Telegram → tu servidor público en `/webhook` → orquestación → Sheets y respuesta al usuario (delay post-LLM, typing y acumulación de mensajes opcionales vía `.env`; ver tabla).

## Requisitos previos

- **Python 3.11+**
- **Telegram**: bot creado con [BotFather](https://t.me/BotFather) y su token
- **OpenAI**: API key y acceso a los modelos que configures en variables de entorno
- **Google Cloud**: proyecto con API de Google Sheets habilitada, cuenta de servicio con JSON, y el spreadsheet compartido con el **correo** de esa cuenta de servicio
- **Calendly**: URL pública del tipo de evento que el bot debe compartir al cerrar

## Instalación y ejecución local

Trabaja siempre en la **raíz del proyecto** (carpeta donde están `main.py` y `.env`).

1. Clonar el repositorio y entrar a esa carpeta.
2. Crear un entorno virtual:
   - Windows (PowerShell): `python -m venv .venv` luego `.\.venv\Scripts\Activate.ps1`
   - macOS/Linux: `python -m venv .venv` luego `source .venv/bin/activate`
3. Instalar dependencias: `pip install -r requirements.txt`
4. Copiar `.env.example` a `.env` y completar los valores (ver tabla más abajo).

La aplicación lee **solo** `os.environ`. El archivo `.env` se carga al arrancar con `load_dotenv()` en `main.py` (antes de importar la app). Si en PowerShell `TELEGRAM_BOT_TOKEN` aparece vacío **antes** de ejecutar el servidor, es normal: la shell no lee `.env`; el proceso de Python sí lo hace al importar `main`.

### Arrancar el servidor

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Al importar `main`, se aplica el `.env` de esa carpeta antes de cargar la app FastAPI.

Si necesitas forzar la carga explícita de `.env` con Uvicorn:

```bash
python -m dotenv run -- uvicorn main:app --host 0.0.0.0 --port 8000
```

O usando el punto de entrada que respeta `PORT` del entorno:

```bash
python main.py
```

(por defecto `PORT=8000` si no está definido).

## Variables de entorno

| Variable | ¿Requerida? | Descripción | Ejemplo / default |
|----------|-------------|-------------|-------------------|
| `TELEGRAM_BOT_TOKEN` | Sí | Token del bot (BotFather) | — |
| `OPENAI_API_KEY` | Sí | API key de OpenAI | — |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Sí | JSON de la cuenta de servicio en **una sola línea** (string válido) | — |
| `GOOGLE_SHEET_ID` | Sí | ID del spreadsheet (de la URL del documento) | — |
| `CALENDLY_URL` | Sí | URL pública del evento Calendly | `https://calendly.com/...` |
| `LLM_MODEL` | Sí | Modelo para la conversación | `gpt-4o` |
| `LLM_EXTRACTION_MODEL` | Sí | Modelo para extracción estructurada | `gpt-4o-mini` |
| `EXTRACTION_FREQUENCY` | No | Cada cuántos mensajes del usuario se ejecuta la extracción (entero ≥ 1) | `2` |
| `CONVERSATION_HISTORY_MAX_MESSAGES` | No | Máx. turnos enviados al LLM; `0` = sin límite | `0` |
| `LOG_LEVEL` | No | Nivel de logging (`DEBUG`, `INFO`, etc.) | `INFO` |
| `PORT` | No | Puerto HTTP del servidor | `8000` |
| `TELEGRAM_TYPING_ENABLED` | No | `true`/`false`: indicador «escribiendo…» durante el LLM y hasta enviar | `false` |
| `TYPING_RENEW_INTERVAL_SECONDS` | No | Renovar `sendChatAction(typing)` cada N s (≥ 1) | `4` |
| `MESSAGE_DEBOUNCE_SECONDS` | No | Segundos de silencio antes del LLM; `0` = un mensaje = un turno | `0` |
| `MESSAGE_DEBOUNCE_JOIN` | No | Separador al fusionar textos (puedes usar `\n\n` en el valor) | salto doble |
| `POST_LLM_DELAY_MS` | No | Espera tras la respuesta del LLM antes de `send_message` (ms) | `1000` |

Una plantilla comentada está en `.env.example`.

**Análisis de ráfagas (intervalos user→user):** con el entorno configurado, `python scripts/analyze_message_intervals.py` imprime métricas útiles para decidir `MESSAGE_DEBOUNCE_SECONDS`.

### Constantes de negocio (solo en código)

No se configuran por `.env`; están en `bot/config.py` por si necesitas revisarlas o cambiarlas en despliegue:

- **Zona horaria del negocio**: Colombia (UTC−5, sin DST).
- **Horario de silencio**: 22:00–07:00 (hora Colombia): en esa ventana el bot puede responder con el mensaje de ausencia en lugar de la conversación normal.
- **Límite de mensajes del usuario por conversación**: 30.
- **Delay antes de enviar la respuesta por Telegram**: por defecto 1000 ms (`POST_LLM_DELAY_MS` en `.env`). `RESPONSE_DELAY_MS` en código es alias del mismo valor.

## Webhook de Telegram

El endpoint expuesto es **`POST /webhook`** (sin prefijos adicionales). La URL que registres en Telegram debe ser HTTPS y terminar en `/webhook`, por ejemplo `https://tu-dominio.com/webhook`.

### Registrar el webhook

Con el bot en marcha y una URL pública que apunte a tu servidor:

```text
GET https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<HOST_PUBLICO>/webhook
```

Sustituye `<TELEGRAM_BOT_TOKEN>` y `<HOST_PUBLICO>` por tus valores. No compartas el token en documentación pública.

### Pruebas locales con ngrok

1. Arranca la app en un puerto local (p. ej. 8000).
2. En otra terminal: `ngrok http 8000` (u otra herramienta de túnel similar).
3. Copia la URL HTTPS que te da el túnel y úsala en `setWebhook` como `https://<subdominio>.ngrok-free.app/webhook` (o la que corresponda).

**Importante:** la URL de ngrok **cambia** cuando reinicias ngrok; debes volver a llamar a `setWebhook` en cada sesión de prueba.

### Comprobar el webhook (opcional)

```text
GET https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo
```

Revisa `url` y `last_error_message` si algo falla.

## Estructura del Google Sheet

El spreadsheet indicado en `GOOGLE_SHEET_ID` debe tener **dos hojas** con los nombres exactos **`conversaciones`** y **`leads`**. La primera fila de cada hoja son los encabezados.

### Hoja `conversaciones`

Columnas obligatorias (fila 1):

| Columna | Uso |
|---------|-----|
| `chat_id` | ID del chat en Telegram (texto) |
| `role` | `user` o `assistant` |
| `content` | Texto del mensaje |
| `timestamp` | Unix en segundos (Telegram), como texto, para ordenar el historial |
| `estado` | Estado del turno / conversación (p. ej. al cerrar se puede marcar `cerrada` en filas del chat) |

### Hoja `leads`

La fila 1 debe incluir **todas** estas columnas (orden recomendado, alineado con el código):

`chat_id`, `nombre`, `ciudad`, `tipo_espacio`, `tipo_intervencion`, `area_aprox`, `situacion_actual`, `fecha_deseada`, `presupuesto`, `alcance`, `estado`, `created_at`, `updated_at`

El upsert de leads **rellena solo celdas vacías** de los nueve campos de datos del lead; no borra valores ya escritos.

## Despliegue (Railway o Render)

Pasos generales (el detalle operativo del primer deploy corresponde a la Fase 12 del plan de implementación):

1. Conecta el repositorio y usa un entorno **Python** estándar.
2. **Comando de arranque** sugerido (la plataforma suele definir `PORT`):

   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

   En Windows en algunas plataformas se usa la variable equivalente; alternativamente puedes configurar el servicio para ejecutar `python main.py`, que lee `PORT` desde el entorno.

3. Define **todas** las variables de la tabla de entorno en el panel de la plataforma. Para `GOOGLE_SERVICE_ACCOUNT_JSON`, pega el JSON completo como valor de una sola línea (o sigue el método que permita tu proveedor para secretos multilínea).
4. Tras el deploy, obtén la URL pública HTTPS y registra el webhook: `https://<tu-servicio>/webhook`.
5. Revisa los **logs** del servicio para confirmar que arranca sin errores de configuración.

## Prueba manual (pre-producción)

Antes de dar el MVP por cerrado, conviene ejecutar el procedimiento de **Fase 13** del plan en [`.cursor/docs/plan-implementacion-sinergia-bot-v2.md`](.cursor/docs/plan-implementacion-sinergia-bot-v2.md): túnel local (ngrok) o preview del proveedor, conversación completa de punta a punta y revisión de ambas hojas en Sheets.

**Checklist breve:**

- Tono de la conversación acorde al producto (no rígido ni genérico).
- Hoja `leads` se actualiza según la frecuencia de extracción configurada.
- Cierre por los tres criterios previstos (9 campos completos, solicitud con mínimos del cliente, límite de mensajes).
- Mensaje de ausencia en horario de silencio.
- Respuesta amable a contenido no texto (foto, audio, etc.).
- Mensajes editados generan nueva respuesta.
- Conversaciones ya cerradas reciben el mensaje fijo correspondiente.
