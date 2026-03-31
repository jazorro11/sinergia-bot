# sinergia-bot

Bot de conversación para Estudio Sinergia: webhook en FastAPI, integración con OpenAI y Google Sheets.

## Requisitos

- Python 3.11+
- Cuentas y credenciales: Telegram (BotFather), OpenAI, Google Cloud (Service Account + Sheet), Calendly

## Instalación local

1. Clonar el repositorio y entrar al directorio del proyecto.
2. Crear y activar un entorno virtual (`python -m venv .venv`).
3. Instalar dependencias: `pip install -r requirements.txt`
4. Copiar `.env.example` a `.env` y completar los valores.

La aplicación lee **solo** `os.environ`. El archivo `.env` se carga automáticamente al arrancar vía `load_dotenv()` en `main.py` (antes de importar la app). Si en PowerShell ves `$env:TELEGRAM_BOT_TOKEN.Length` en 0 **antes** de arrancar, es normal: la shell no lee `.env` sola; al ejecutar Uvicorn, el proceso de Python sí carga `.env` gracias a `main.py`.

## Ejecutar el servidor

Desde la raíz del repo (donde está `main.py` y `.env`):

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Al importar el módulo `main`, se aplica el `.env` de esa carpeta antes de cargar la app FastAPI.

Alternativa equivalente (por si ejecutas Uvicorn de forma que no pase por el import de `main` como primer paso):

```bash
python -m dotenv run -- uvicorn main:app --host 0.0.0.0 --port 8000
```

O directamente:

```bash
python main.py
```

(usa el puerto definido en `PORT`, por defecto 8000).

## Variables de entorno

Ver la tabla en `.cursor/docs/technical-brief-sinergia-bot-v4.md` (sección 8) o `.env.example`.

## Webhook de Telegram y despliegue

Para pruebas locales con túnel (ngrok) y registro del webhook, y para Railway/Render, sigue el procedimiento del brief (sección 5) y el plan de implementación (Fase 12–13).
