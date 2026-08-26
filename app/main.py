"""Painel de controle do pipeline de drone.

Estado do pipeline via SSE, start/stop com exibição do endereço RTMP e vídeo ao
vivo em MJPEG com a inferência aplicada. Coleta, split e Roboflow ficam para as
fatias seguintes.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import pipeline
from .inference import detector
from .monitor import monitor
from .video import BOUNDARY, video

BASE_DIR = Path(__file__).resolve().parent
SSE_INTERVAL_S = 2.0


@asynccontextmanager
async def lifespan(_: FastAPI):
    monitor.start()
    video.start()
    yield
    video.stop()
    monitor.stop()


app = FastAPI(title="Painel do pipeline", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class StartRequest(BaseModel):
    stream_path: str | None = None


async def _state() -> dict:
    """snapshot() do pipeline usa subprocess — fora do event loop."""
    return {
        "pipeline": await run_in_threadpool(pipeline.snapshot),
        "stream": monitor.snapshot(),
        "video": video.stats(),
        # poll() pode carregar os pesos — vai para o threadpool junto.
        "model": await run_in_threadpool(detector.poll),
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"stream_path": pipeline.DEFAULT_STREAM_PATH}
    )


@app.get("/events")
async def events(request: Request):
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            payload = json.dumps(await _state())
            yield f"data: {payload}\n\n"
            await asyncio.sleep(SSE_INTERVAL_S)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/pipeline/status")
async def pipeline_status():
    return await _state()


def _envelope(result: dict) -> dict:
    """Mesma forma de /events, para o JS ter um só renderizador."""
    ok = result.pop("ok")
    return {
        "ok": ok,
        "pipeline": result,
        "stream": monitor.snapshot(),
        "video": video.stats(),
        "model": detector.status(),
    }


@app.post("/api/pipeline/start")
async def pipeline_start(body: StartRequest | None = None):
    stream_path = body.stream_path if body else None
    return _envelope(await run_in_threadpool(pipeline.start, stream_path))


@app.post("/api/pipeline/stop")
async def pipeline_stop():
    return _envelope(await run_in_threadpool(pipeline.stop))


@app.get("/stream")
async def stream():
    """MJPEG do quadro já inferido.

    Enquanto o gerador vive, ele conta como consumidor: é o que mantém o RTSP
    aberto. Fechar a aba encerra o gerador e, dez segundos depois sem nenhum
    outro consumidor, o leitor solta a conexão.
    """
    return StreamingResponse(
        video.mjpeg(),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/stream/stats")
async def stream_stats():
    return video.stats()


@app.get("/api/model")
async def model_status():
    return await run_in_threadpool(detector.poll)


@app.post("/api/model/reload")
async def model_reload():
    """Recarrega os pesos sem reiniciar o processo."""
    return await run_in_threadpool(detector.reload)
