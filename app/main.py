"""Painel de controle do pipeline de drone.

Estado do pipeline via SSE, start/stop com exibição do endereço RTMP, vídeo ao
vivo em MJPEG com a inferência aplicada, coleta de quadros com split temporal ao
salvar, tela de datasets com galeria e edição, e upload ao Roboflow preservando
a partição. A tela de modelo e a pasta `train/` ficam para as fatias seguintes.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import collect as collect_mod
from . import datasets as datasets_mod
from . import pipeline
from . import roboflow_upload
from .collect import collect
from .roboflow_upload import uploader
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
    # A coleta primeiro: encerra a amostragem e escoa a fila de escrita antes do
    # leitor sumir, para não deixar uma sessão pela metade em disco.
    collect.shutdown()
    video.stop()
    monitor.stop()


app = FastAPI(title="Painel do pipeline", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class StartRequest(BaseModel):
    stream_path: str | None = None


class CollectRequest(BaseModel):
    interval: float = collect_mod.DEFAULT_INTERVAL
    limit: int | None = collect_mod.DEFAULT_LIMIT
    dedup: bool = collect_mod.DEFAULT_DEDUP


class DeleteImagesRequest(BaseModel):
    split: str
    filenames: list[str]


class DeleteDatasetRequest(BaseModel):
    confirm: str = ""


class ResplitRequest(BaseModel):
    margin: int | None = None


class UploadRequest(BaseModel):
    version: str
    workspace: str
    project: str
    # Nunca é gravada, logada nem devolvida: só atravessa para o SDK.
    api_key: str | None = None
    batch_name: str | None = None
    tags: list[str] | None = None


async def _state() -> dict:
    """snapshot() do pipeline usa subprocess — fora do event loop."""
    return {
        "pipeline": await run_in_threadpool(pipeline.snapshot),
        "stream": monitor.snapshot(),
        "video": video.stats(),
        # poll() pode carregar os pesos — vai para o threadpool junto.
        "model": await run_in_threadpool(detector.poll),
        "collect": collect.status(),
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        {"stream_path": pipeline.DEFAULT_STREAM_PATH, "current": "home"},
    )


@app.get("/datasets", response_class=HTMLResponse)
async def datasets_page(request: Request):
    return templates.TemplateResponse(request, "datasets.html", {"current": "datasets"})


@app.get("/datasets/{version}", response_class=HTMLResponse)
async def dataset_page(request: Request, version: str):
    return templates.TemplateResponse(
        request, "dataset.html", {"current": "datasets", "version": version}
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
        "collect": collect.status(),
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


# --- coleta -----------------------------------------------------------------


@app.get("/api/collect/preflight")
async def collect_preflight():
    """Pré-condições da coleta.

    O cliente já sabe pelo SSE se pode ou não coletar; esta rota existe para o
    modal de erro mostrar a mesma lista que o servidor usaria para recusar, com
    o texto do que fazer. `pipeline.snapshot()` usa subprocess — threadpool.
    """
    return await run_in_threadpool(collect_mod.preflight)


@app.post("/api/collect/start")
async def collect_start(body: CollectRequest | None = None):
    """Inicia a gravação. Revalida as pré-condições — o cliente pode estar
    olhando um estado de dois segundos atrás."""
    params = body or CollectRequest()
    return await run_in_threadpool(
        collect.start, params.interval, params.limit, params.dedup
    )


@app.post("/api/collect/pause")
async def collect_pause():
    return collect.pause()


@app.post("/api/collect/resume")
async def collect_resume():
    return await run_in_threadpool(collect.resume)


@app.post("/api/collect/save")
async def collect_save():
    """Encerra a sessão e dispara o split.

    Retorna assim que o estado vira `salvando`: a barreira da fila de escrita e
    a cópia dos arquivos rodam na thread de finalização, nunca no event loop.
    """
    return collect.save()


@app.post("/api/collect/dismiss")
async def collect_dismiss():
    """Fecha o resumo de `salvo` e volta a `ocioso`."""
    return collect.dismiss()


@app.get("/api/collect/status")
async def collect_status():
    """Só o bloco `collect`, em memória.

    O painel de gravação consulta esta rota a cada segundo enquanto há sessão
    aberta. O SSE continua a 2 s: acelerá-lo dobraria a frequência dos
    `docker inspect` do `pipeline.snapshot()` durante o voo.
    """
    return collect.status()


# --- datasets ---------------------------------------------------------------


def _dataset_guard(exc: datasets_mod.DatasetError) -> HTTPException:
    """`DatasetError` cobre nome inválido e ausência; ambos são 404 para o cliente.

    Distinguir "versão malformada" de "versão inexistente" com códigos
    diferentes só ajudaria quem estivesse sondando o disco de fora.
    """
    return HTTPException(status_code=404, detail=str(exc))


@app.get("/api/datasets")
async def api_datasets():
    """Lista, da versão mais recente para a mais antiga.

    Percorre diretórios e soma tamanhos — vai para o threadpool.
    """
    return {"datasets": await run_in_threadpool(datasets_mod.list_datasets)}


@app.get("/api/datasets/{version}")
async def api_dataset(version: str):
    try:
        return await run_in_threadpool(datasets_mod.detail, version)
    except datasets_mod.DatasetError as exc:
        raise _dataset_guard(exc) from exc


@app.get("/api/datasets/{version}/images/{split}")
async def api_dataset_images(version: str, split: str):
    def read() -> dict:
        base = datasets_mod.require_version(version)
        datasets_mod.require_split(split)
        uploaded = datasets_mod.uploaded_map(datasets_mod.read_upload_record(base))
        files = datasets_mod.split_files(base, split)
        return {
            "version": version,
            "split": split,
            "count": len(files),
            "images": [{"file": n, "uploaded": n in uploaded} for n in files],
        }

    try:
        return await run_in_threadpool(read)
    except datasets_mod.DatasetError as exc:
        raise _dataset_guard(exc) from exc


@app.get("/api/datasets/{version}/image/{split}/{filename}")
async def api_dataset_image(version: str, split: str, filename: str):
    try:
        path = await run_in_threadpool(datasets_mod.image_path, version, split, filename)
    except datasets_mod.DatasetError as exc:
        raise _dataset_guard(exc) from exc
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/datasets/{version}/thumb/{split}/{filename}")
async def api_dataset_thumb(version: str, split: str, filename: str):
    """Miniatura, gerada sob demanda e cacheada em disco (decodifica — threadpool)."""
    try:
        path = await run_in_threadpool(datasets_mod.thumb_path, version, split, filename)
    except datasets_mod.DatasetError as exc:
        raise _dataset_guard(exc) from exc
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "max-age=60"}
    )


@app.post("/api/datasets/{version}/images/preview-delete")
async def api_preview_delete(version: str, body: DeleteImagesRequest):
    """O que a exclusão faria, incluindo quantas já subiram ao Roboflow.

    O modal chama isto antes de mostrar o botão de excluir: a contagem de
    imagens já enviadas precisa vir do servidor, que é quem lê o roboflow.json.
    """
    try:
        return await run_in_threadpool(
            datasets_mod.preview_delete, version, body.split, body.filenames
        )
    except datasets_mod.DatasetError as exc:
        raise _dataset_guard(exc) from exc


@app.delete("/api/datasets/{version}/images")
async def api_delete_images(version: str, body: DeleteImagesRequest):
    """Exclui da partição **e** de `raw/`. Ver `datasets.delete_images`."""
    try:
        return await run_in_threadpool(
            datasets_mod.delete_images, version, body.split, body.filenames
        )
    except datasets_mod.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/datasets/{version}")
async def api_delete_dataset(version: str, body: DeleteDatasetRequest | None = None):
    confirm = body.confirm if body else ""
    try:
        return await run_in_threadpool(datasets_mod.delete_dataset, version, confirm)
    except datasets_mod.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/datasets/{version}/resplit")
async def api_resplit(version: str, body: ResplitRequest | None = None):
    """Refaz o split a partir de `raw/`. Mesmo `split.run()` da fatia 3."""
    margin = body.margin if body else None
    try:
        return await run_in_threadpool(datasets_mod.resplit, version, margin)
    except datasets_mod.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # SplitError e I/O
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- roboflow ---------------------------------------------------------------


@app.get("/api/roboflow/config")
async def api_roboflow_config():
    """Se há SDK e se há chave — nunca a chave."""
    return roboflow_upload.config()


@app.post("/api/roboflow/upload")
async def api_roboflow_upload(body: UploadRequest):
    """Inicia o envio em thread separada e responde na hora.

    `api_key` entra por aqui e não sai: não é gravada no `roboflow.json`, não
    volta em nenhuma resposta e não aparece em log.
    """
    return await run_in_threadpool(
        uploader.start, body.version, body.api_key, body.workspace,
        body.project, body.batch_name, body.tags,
    )


@app.post("/api/roboflow/cancel")
async def api_roboflow_cancel():
    return uploader.cancel()


@app.get("/api/roboflow/status")
async def api_roboflow_status():
    return uploader.status()
