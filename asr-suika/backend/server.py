"""FastAPIとWebSocketでゲームへ音声命令を配信する。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.voice_service import VoiceRecognitionService

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def _optional_model_path() -> Path | None:
    configured = os.environ.get("VOSK_MODEL_PATH")
    return Path(configured).expanduser() if configured else None


def _optional_device() -> int | str | None:
    configured = os.environ.get("AUDIO_DEVICE")
    if configured is None:
        return None
    try:
        return int(configured)
    except ValueError:
        return configured


voice_service = VoiceRecognitionService(
    model_path=_optional_model_path(),
    device=_optional_device(),
)
app = FastAPI(title="声でスイカ割り", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prevent_stale_frontend(
    request: Request,
    call_next,
) -> Response:
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/voice")
async def voice_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    subscriber = await voice_service.subscribe()

    async def send_events() -> None:
        while True:
            try:
                event = await asyncio.wait_for(subscriber.get(), timeout=10)
            except TimeoutError:
                event = {"type": "ping"}
            await websocket.send_json(event)

    sender = asyncio.create_task(send_events())
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict) or message.get("type") != "configure":
                continue
            assignments = message.get("commands")
            if assignments is not None and not isinstance(assignments, dict):
                continue
            try:
                voice_service.configure_commands(assignments)
            except ValueError as error:
                logging.getLogger(__name__).warning(
                    "音声認識候補を変更できませんでした: %s",
                    error,
                )
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(
            asyncio.CancelledError,
            RuntimeError,
            WebSocketDisconnect,
        ):
            await sender
        await voice_service.unsubscribe(subscriber)


if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="game")
else:
    logging.getLogger(__name__).warning(
        "distがありません。開発時は別ターミナルで npm run dev を起動してください"
    )
