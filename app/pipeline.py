"""Controle do MediaMTX e do túnel bore.

Mesma sequência de start.sh/stop.sh, porém em subprocess e reportando cada
passo para o painel. O estado nunca é confiado à memória: antes de responder,
reconcilia com a realidade (docker inspect, pgrep, /tmp/bore.log), para que o
painel enxergue um pipeline que já estava de pé antes dele subir.

O túnel é opcional
------------------
Ele existe só para dar um endereço alcançável a uma máquina sem IP público.
Quando `PUBLIC_HOST` está definida, o drone publica direto no IP da máquina: o
`rtmp_url` é montado com ela, nenhum bore é iniciado e o cartão do túnel fica
cinza. Sem `PUBLIC_HOST` o túnel é tentado, mas falhar nele não derruba o
pipeline — o MediaMTX no ar já basta para receber stream e gravar imagens.
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

# Host público da máquina. Definida => o drone alcança o RTMP direto e o túnel
# deixa de ser tentado. Aceita "ip", "ip:porta", "host" ou "rtmp://host".
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip()
RTMP_PORT = os.environ.get("RTMP_PORT", "1935").strip() or "1935"

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


def tunnel_expected() -> bool:
    """Só se espera túnel quando não há host público configurado."""
    return not PUBLIC_HOST


def public_endpoint() -> str | None:
    """`PUBLIC_HOST` normalizada para `host:porta`, ou None se não definida.

    Aceita o que a pessoa tiver em mãos — `203.0.113.10`, `203.0.113.10:1935`,
    `rtmp://drone.exemplo.br` — porque o valor costuma ser copiado do painel do
    provedor ou de um `curl ifconfig.me`, não digitado num formato canônico.
    """
    if not PUBLIC_HOST:
        return None
    host = PUBLIC_HOST.split("://", 1)[-1].strip("/")
    if not host:
        return None
    # Depois do `]` de um IPv6 literal; para os demais, o host inteiro. Sem esse
    # corte, `[::1]` pareceria já ter porta por causa dos dois-pontos internos.
    tail = host.rsplit("]", 1)[-1]
    return host if ":" in tail else f"{host}:{RTMP_PORT}"


def rtmp_host() -> str | None:
    """Endereço `host:porta` que o drone deve alcançar.

    `PUBLIC_HOST` ganha do túnel: se ela está definida é porque a máquina já é
    alcançável, e um bore que tenha sobrado de outra execução não deve mudar o
    endereço publicado no painel.
    """
    endpoint = public_endpoint()
    if endpoint:
        return endpoint
    addr = tunnel_address()
    return addr if addr and tunnel_running() else None


def rtmp_url(stream_path: str | None = None) -> str | None:
    host = rtmp_host()
    if not host:
        return None
    path = (stream_path or effective_stream_path()).lstrip("/")
    return f"rtmp://{host}/{path}"


def rtsp_url(stream_path: str | None = None) -> str:
    path = (stream_path or effective_stream_path()).lstrip("/")
    return f"rtsp://localhost:8554/{path}"


# --- passos -----------------------------------------------------------------

_lock = threading.Lock()
_steps: list[dict] = []
_busy = False
_last_error: str | None = None
# Separado do erro de propósito: o túnel indisponível é um aviso, não uma
# falha do pipeline. Pintá-lo de vermelho faria a pessoa parar de gravar por
# causa de um recurso que ela nem está usando.
_last_warning: str | None = None
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
        # Descarta as linhas em branco antes de cortar: o erro do bore vem em
        # bloco ("Error: ...", "", "Caused by:", "    ..."), e um corte cego nas
        # três últimas linhas jogaria fora justamente a que diz o quê e onde.
        lines = [ln.strip() for ln in BORE_LOG.read_text(errors="replace").splitlines()]
        tail = " | ".join([ln for ln in lines if ln][-3:])
    except OSError:
        pass
    raise StepError(f"túnel não subiu. {tail or 'veja /tmp/bore.log'}"[:400])


def start(stream_path: str | None = None, config_path: Path | None = None) -> dict:
    """Sobe o MediaMTX e, se for o caso, o túnel. Bloqueante — fora do event loop.

    O túnel é a última etapa e a única não essencial: quando `PUBLIC_HOST` está
    definida ele nem entra na lista de passos, e quando não está, falhar nele
    devolve `ok=True` com um aviso. O que decide se dá para gravar é o MediaMTX
    de pé recebendo stream, não o bore.
    """
    global _busy, _last_error, _last_warning, _stream_path

    with _lock:
        if _busy:
            # snapshot() também traz `error`; ele vem antes para não engolir esta
            # mensagem — era uma das correções pendentes do SPEC_ATUAL.
            return {"ok": False, **snapshot(), "error": "pipeline já está em operação"}
        _busy = True

    _stream_path = (stream_path or DEFAULT_STREAM_PATH).strip().lstrip("/")
    config = config_path or CONFIG_PATH
    _last_error = None
    _last_warning = None
    with_tunnel = tunnel_expected()
    _reset_steps(["MediaMTX", "API"] + (["Túnel", "Endereço"] if with_tunnel else []))

    ok = True
    try:
        _mark("MediaMTX", "running")
        _start_mediamtx(config)
        _mark("MediaMTX", "ok", f"container {CONTAINER} no ar")

        _mark("API", "running")
        _wait_api()
        _mark("API", "ok", "respondendo em :9997")
    except (StepError, OSError, subprocess.SubprocessError) as exc:
        ok = False
        _last_error = str(exc)
        _fail_running_steps(_last_error)
    else:
        if with_tunnel:
            try:
                _mark("Túnel", "running")
                _start_tunnel()
                _mark("Túnel", "ok", f"bore local 1935 --to {BORE_TO}")

                _mark("Endereço", "running")
                addr = _wait_address()
                _mark("Endereço", "ok", addr)
            except (StepError, OSError, subprocess.SubprocessError) as exc:
                # O MediaMTX ficou de pé: o pipeline serve. Vermelho no cartão
                # do túnel, aviso no painel, `ok` intacto.
                _last_warning = (
                    f"túnel indisponível (opcional): {exc} — o MediaMTX está no ar. "
                    "Publique no IP da máquina ou defina PUBLIC_HOST para montar "
                    "o endereço RTMP sem túnel."
                )
                _fail_running_steps(str(exc))
    finally:
        _busy = False

    return {"ok": ok, **snapshot()}


def stop() -> dict:
    """Encerra túnel e container. Não apaga dados.

    O pkill roda mesmo com `PUBLIC_HOST` definida: pode haver um bore de uma
    execução anterior, e parar o pipeline tem que parar tudo que ele subiu.
    """
    global _busy, _last_error, _last_warning

    with _lock:
        if _busy:
            # snapshot() também traz `error`; ele vem antes para não engolir esta
            # mensagem — era uma das correções pendentes do SPEC_ATUAL.
            return {"ok": False, **snapshot(), "error": "pipeline já está em operação"}
        _busy = True

    _last_error = None
    _last_warning = None
    _reset_steps(["Túnel", "MediaMTX"])
    ok = True
    try:
        _mark("Túnel", "running")
        killed = _run(["pkill", "-f", BORE_PATTERN], timeout=15).returncode == 0
        _mark("Túnel", "ok", "encerrado" if killed
               else ("não usado (IP direto)" if not tunnel_expected() else "já estava parado"))

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


def _tunnel_state() -> dict:
    """Estado do túnel para o cartão do painel.

    `status` carrega a intenção, não só o fato: `unused` é um túnel que não
    subiu porque ninguém pediu, e o painel o pinta de cinza. `down` é um túnel
    que era para estar de pé — só esse vira vermelho.
    """
    expected = tunnel_expected()
    running = tunnel_running()
    address = tunnel_address() if running else None

    if not expected:
        status, label = "unused", "não usado (IP direto)"
    elif running and address:
        status, label = "ok", address
    elif running:
        status, label = "starting", "subindo…"
    else:
        status, label = "down", "parado"

    return {
        "running": running,
        "address": address,
        "expected": expected,
        "status": status,
        "label": label,
    }


def snapshot() -> dict:
    """Estado atual, medido no sistema e não na memória do processo."""
    mtx_up = container_running()
    tunnel = _tunnel_state()
    endpoint = public_endpoint()
    host = endpoint or (tunnel["address"] if tunnel["running"] else None)
    path = effective_stream_path()
    url = f"rtmp://{host}/{path}" if host else None

    return {
        "busy": _busy,
        "error": _last_error,
        "warning": _last_warning,
        "steps": list(_steps),
        "stream_path": path,
        "configured_path": _stream_path,
        "path_detected": path != _stream_path,
        "mediamtx": {"running": mtx_up, "container": CONTAINER},
        "tunnel": tunnel,
        "public_host": endpoint,
        "rtmp_source": "public_host" if endpoint else ("tunnel" if host else None),
        "rtmp_url": url,
        "rtsp_url": f"rtsp://localhost:8554/{path}",
        "hls_url": f"http://localhost:8888/{path}",
    }
