"""Controle do MediaMTX e do túnel bore.

Mesma sequência de start.sh/stop.sh, porém em subprocess e reportando cada
passo para o painel. O estado nunca é confiado à memória: antes de responder,
reconcilia com a realidade (docker inspect, pgrep, /tmp/bore.log), para que o
painel enxergue um pipeline que já estava de pé antes dele subir.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "mediamtx.yml"
BORE_LOG = Path("/tmp/bore.log")

CONTAINER = "mtx"
IMAGE = "bluenviron/mediamtx:latest"
PORTS = ("1935:1935", "8554:8554", "8888:8888", "9997:9997")

API_BASE = os.environ.get("MEDIAMTX_API", "http://localhost:9997")
PATHS_LIST_URL = f"{API_BASE}/v3/paths/list"

BORE_PATTERN = "bore local"
BORE_TO = os.environ.get("BORE_TO", "bore.pub")
ADDR_RE = re.compile(r"listening at (\S+?):(\d+)")

API_TIMEOUT_S = 15
TUNNEL_TIMEOUT_S = 20

DEFAULT_STREAM_PATH = os.environ.get("STREAM_PATH", "live/m4td")


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


# --- leitura do estado real -------------------------------------------------


def container_running() -> bool:
    p = _run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], timeout=15)
    return p.returncode == 0 and p.stdout.strip() == "true"


def tunnel_running() -> bool:
    return _run(["pgrep", "-f", BORE_PATTERN], timeout=10).returncode == 0


def tunnel_address() -> str | None:
    """Último endereço anunciado pelo bore no log."""
    try:
        text = BORE_LOG.read_text(errors="replace")
    except OSError:
        return None
    matches = ADDR_RE.findall(text)
    if not matches:
        return None
    host, port = matches[-1]
    return f"{host}:{port}"


def api_ready() -> bool:
    try:
        r = httpx.get(PATHS_LIST_URL, timeout=1.5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def active_path_name() -> str | None:
    """Nome do path publicando agora, lido do monitor.

    Import local: `monitor` importa deste módulo, e no topo faria ciclo.
    """
    from .monitor import monitor

    paths = monitor.snapshot().get("paths") or []
    ready = [p for p in paths if p.get("ready")] or paths
    if not ready:
        return None
    # Se o path configurado estiver entre os ativos, ele ganha; senão, o que
    # está recebendo mais dados.
    for path in ready:
        if path.get("name") == _stream_path:
            return _stream_path
    return max(ready, key=lambda p: p.get("mbps") or 0).get("name")


def effective_stream_path() -> str:
    """O path que o painel deve exibir: o real, quando houver um.

    O sufixo do path é a única credencial do endpoint RTMP. Assumir o
    `STREAM_PATH` padrão quando há outro publicando faz o painel mostrar um
    endereço que não funciona — era uma das correções pendentes do SPEC_ATUAL.
    """
    return active_path_name() or _stream_path


def rtmp_url(stream_path: str | None = None) -> str | None:
    addr = tunnel_address()
    if not addr or not tunnel_running():
        return None
    path = (stream_path or effective_stream_path()).lstrip("/")
    return f"rtmp://{addr}/{path}"


def rtsp_url(stream_path: str | None = None) -> str:
    path = (stream_path or effective_stream_path()).lstrip("/")
    return f"rtsp://localhost:8554/{path}"


# --- passos -----------------------------------------------------------------

_lock = threading.Lock()
_steps: list[dict] = []
_busy = False
_last_error: str | None = None
_stream_path = DEFAULT_STREAM_PATH


def _reset_steps(names: list[str]) -> None:
    global _steps
    _steps = [{"name": n, "status": "pending", "detail": ""} for n in names]


def _mark(name: str, status: str, detail: str = "") -> None:
    for step in _steps:
        if step["name"] == name:
            step["status"] = status
            step["detail"] = detail
            return


def _fail_running_steps(message: str) -> None:
    for step in _steps:
        if step["status"] == "running":
            step["status"] = "error"
            step["detail"] = message
        elif step["status"] == "pending":
            step["status"] = "skipped"


class StepError(RuntimeError):
    pass


# --- start / stop -----------------------------------------------------------


def _start_mediamtx(config_path: Path) -> None:
    if not config_path.is_file():
        raise StepError(f"config não encontrado: {config_path}")
    _run(["docker", "rm", "-f", CONTAINER], timeout=60)
    args = [
        "docker", "run", "-d",
        "--name", CONTAINER,
        "--restart", "unless-stopped",
        "-v", f"{config_path}:/mediamtx.yml",
    ]
    for mapping in PORTS:
        args += ["-p", mapping]
    args.append(IMAGE)
    p = _run(args, timeout=180)
    if p.returncode != 0:
        raise StepError((p.stderr or p.stdout).strip()[:400] or "docker run falhou")


def _wait_api() -> None:
    deadline = time.monotonic() + API_TIMEOUT_S
    while time.monotonic() < deadline:
        if api_ready():
            return
        time.sleep(1)
    raise StepError(
        f"API não respondeu em {API_TIMEOUT_S}s. Veja: docker logs {CONTAINER}"
    )


def _start_tunnel() -> None:
    _run(["pkill", "-f", BORE_PATTERN], timeout=15)
    time.sleep(0.5)
    BORE_LOG.write_text("")  # zera para não reler um endereço antigo
    with BORE_LOG.open("ab") as log:
        subprocess.Popen(
            ["bore", "local", "1935", "--to", BORE_TO],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def _wait_address() -> str:
    deadline = time.monotonic() + TUNNEL_TIMEOUT_S
    while time.monotonic() < deadline:
        addr = tunnel_address()
        if addr:
            return addr
        if not tunnel_running():
            break
        time.sleep(0.5)
    tail = ""
    try:
        tail = BORE_LOG.read_text(errors="replace").strip().splitlines()[-3:]
        tail = " | ".join(tail)
    except (OSError, IndexError):
        pass
    raise StepError(f"túnel não subiu. {tail or 'veja /tmp/bore.log'}"[:400])


def start(stream_path: str | None = None, config_path: Path | None = None) -> dict:
    """Sobe MediaMTX + túnel. Bloqueante — chame fora do event loop."""
    global _busy, _last_error, _stream_path

    with _lock:
        if _busy:
            # snapshot() também traz `error`; ele vem antes para não engolir esta
            # mensagem — era uma das correções pendentes do SPEC_ATUAL.
            return {"ok": False, **snapshot(), "error": "pipeline já está em operação"}
        _busy = True

    _stream_path = (stream_path or DEFAULT_STREAM_PATH).strip().lstrip("/")
    config = config_path or CONFIG_PATH
    _last_error = None
    _reset_steps(["MediaMTX", "API", "Túnel", "Endereço"])

    ok = True
    try:
        _mark("MediaMTX", "running")
        _start_mediamtx(config)
        _mark("MediaMTX", "ok", f"container {CONTAINER} no ar")

        _mark("API", "running")
        _wait_api()
        _mark("API", "ok", "respondendo em :9997")

        _mark("Túnel", "running")
        _start_tunnel()
        _mark("Túnel", "ok", f"bore local 1935 --to {BORE_TO}")

        _mark("Endereço", "running")
        addr = _wait_address()
        _mark("Endereço", "ok", addr)
    except (StepError, OSError, subprocess.SubprocessError) as exc:
        ok = False
        _last_error = str(exc)
        _fail_running_steps(_last_error)
    finally:
        _busy = False

    return {"ok": ok, **snapshot()}


def stop() -> dict:
    """Encerra túnel e container. Não apaga dados."""
    global _busy, _last_error

    with _lock:
        if _busy:
            # snapshot() também traz `error`; ele vem antes para não engolir esta
            # mensagem — era uma das correções pendentes do SPEC_ATUAL.
            return {"ok": False, **snapshot(), "error": "pipeline já está em operação"}
        _busy = True

    _last_error = None
    _reset_steps(["Túnel", "MediaMTX"])
    ok = True
    try:
        _mark("Túnel", "running")
        killed = _run(["pkill", "-f", BORE_PATTERN], timeout=15).returncode == 0
        _mark("Túnel", "ok", "encerrado" if killed else "já estava parado")

        _mark("MediaMTX", "running")
        removed = _run(["docker", "rm", "-f", CONTAINER], timeout=60).returncode == 0
        _mark("MediaMTX", "ok", "encerrado" if removed else "já estava parado")
    except (OSError, subprocess.SubprocessError) as exc:
        ok = False
        _last_error = str(exc)
        _fail_running_steps(_last_error)
    finally:
        _busy = False

    return {"ok": ok, **snapshot()}


# --- snapshot ---------------------------------------------------------------


def snapshot() -> dict:
    """Estado atual, medido no sistema e não na memória do processo."""
    mtx_up = container_running()
    tun_up = tunnel_running()
    addr = tunnel_address() if tun_up else None
    path = effective_stream_path()
    url = f"rtmp://{addr}/{path}" if addr else None

    return {
        "busy": _busy,
        "error": _last_error,
        "steps": list(_steps),
        "stream_path": path,
        "configured_path": _stream_path,
        "path_detected": path != _stream_path,
        "mediamtx": {"running": mtx_up, "container": CONTAINER},
        "tunnel": {"running": tun_up, "address": addr},
        "rtmp_url": url,
        "rtsp_url": f"rtsp://localhost:8554/{path}",
        "hls_url": f"http://localhost:8888/{path}",
    }
