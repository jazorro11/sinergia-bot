"""Application entrypoint: re-exports the FastAPI app and runs uvicorn when executed."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from bot.webhook import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    from bot.config import PORT

    uvicorn.run(app, host="0.0.0.0", port=PORT)
