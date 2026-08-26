"""Upload de um dataset para o Roboflow, preservando a partição.

O parâmetro que importa
-----------------------
Cada imagem sobe com `split=` explícito. Sem ele, o Roboflow reparticiona por
conta própria — e o split dele é aleatório, o que desfaz inteiro o trabalho da
fatia 3: quadros vizinhos no tempo voltariam a cair em partições diferentes e o
vazamento de treino na validação estaria de volta, agora invisível porque
aconteceu do outro lado da rede.

Por isso, se o SDK instalado recusar o argumento `split`, a execução **aborta**
em vez de subir sem ele. Um dataset com a partição errada é pior que nenhum
dataset: parece pronto e mente na métrica.

`batch_name` e `tag_names` levam a versão do dataset. Meses depois, quando
alguém perguntar de qual voo veio determinada imagem, é a única resposta
possível.

A chave
-------
Nunca é gravada em disco, nunca volta numa resposta de API, nunca entra em log.
`config()` informa apenas se existe uma e de onde ela viria. A saída padrão do
SDK é capturada e descartada durante as chamadas, para que nada que ele imprima
acabe no log do painel.

`roboflow` é importado dentro da thread, nunca no topo do módulo: a aplicação
sobe sem o pacote instalado, e a tela explica como instalá-lo.
"""

from __future__ import annotations

import contextlib
import io
import os
import threading
import time
from pathlib import Path

from . import datasets

ROOT = Path(__file__).resolve().parent.parent
DOTENV = ROOT / ".env"

KEY_VAR = "ROBOFLOW_API_KEY"
DEFAULT_TAGS = ("drone",)

# Uma falha isolada é registrada e a execução continua; dez seguidas significam
# que o problema não é do arquivo, e insistir 500 vezes só demora mais.
MAX_CONSECUTIVE_FAILURES = 10
FLUSH_EVERY = 5  # gravações do roboflow.json durante a execução

IDLE, RUNNING = "ocioso", "enviando"
DONE, PARTIAL, CANCELLED, ERROR = "concluído", "parcial", "cancelado", "erro"


class UploadError(RuntimeError):
    pass


# --- chave -------------------------------------------------------------------


def _key_from_dotenv() -> str | None:
    """Lê só `ROBOFLOW_API_KEY` do `.env`, sem despejar o arquivo em os.environ.

    O painel deliberadamente não chama `load_dotenv()` — carregar o `.env`
    inteiro mudaria o valor de outras variáveis já lidas na importação dos
    módulos. Aqui se lê uma linha, e só.
    """
    try:
        for line in DOTENV.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == KEY_VAR:
                return value.strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


def resolve_key(explicit: str | None) -> tuple[str | None, str]:
    """Devolve `(chave, origem)`. A chave nunca sai deste módulo por outra via."""
    if explicit and explicit.strip():
        return explicit.strip(), "formulário"
    from_env = os.environ.get(KEY_VAR)
    if from_env:
        return from_env, "ambiente"
    from_file = _key_from_dotenv()
    if from_file:
        return from_file, ".env"
    return None, "ausente"


def sdk_available() -> tuple[bool, str | None]:
    try:
        import roboflow  # noqa: F401
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]
    return True, None


def config() -> dict:
    """Estado do que a tela precisa saber — sem nunca revelar a chave."""
    available, error = sdk_available()
    _, source = resolve_key(None)
    return {
        "sdk_available": available,
        "sdk_error": error,
        "install_hint": "pip install roboflow",
        "has_key": source != "ausente",
        "key_source": None if source == "ausente" else source,
        "key_var": KEY_VAR,
        "default_tags": list(DEFAULT_TAGS),
    }


# --- serviço -----------------------------------------------------------------


class Uploader:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = IDLE
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._progress: dict = {}
        self._version: str | None = None

    # -- estado --

    def status(self) -> dict:
        with self._lock:
            state = self._state
            version = self._version
            progress = dict(self._progress)
        return {
            "state": state,
            "active": state == RUNNING,
            "version": version,
            "progress": progress or None,
            "config": config(),
        }

    def _refuse(self, message: str) -> dict:
        return {"ok": False, "upload": self.status(), "error": message}

    # -- início --

    def start(self, version: str, api_key: str | None, workspace: str, project: str,
              batch_name: str | None = None, tags: list[str] | None = None) -> dict:
        with self._lock:
            if self._state == RUNNING:
                return self._refuse(f"já existe um upload em andamento ({self._version})")

            try:
                base = datasets.require_version(version)
            except datasets.DatasetError as exc:
                return self._refuse(str(exc))

            available, sdk_error = sdk_available()
            if not available:
                return self._refuse(
                    f"pacote roboflow não instalado ({sdk_error}). Instale com: pip install roboflow"
                )

            key, source = resolve_key(api_key)
            if not key:
                return self._refuse(
                    f"nenhuma chave disponível — informe no formulário ou defina {KEY_VAR}"
                )
            if not (workspace or "").strip() or not (project or "").strip():
                return self._refuse("workspace e projeto são obrigatórios")

            targets = self._targets(base)
            if not targets:
                return self._refuse(
                    "não há imagens em train/valid/test — rode o split antes de enviar"
                )

            record = datasets.read_upload_record(base) or {}
            uploaded = datasets.uploaded_map(record)
            pending = [t for t in targets if t[1] not in uploaded]

            batch = (batch_name or "").strip() or version
            tag_list = [t.strip() for t in (tags or []) if t and t.strip()]
            if not tag_list:
                # A versão é a etiqueta que liga a imagem ao voo de origem.
                tag_list = [version, *DEFAULT_TAGS]

            self._cancel.clear()
            self._state = RUNNING
            self._version = version
            self._progress = {
                "version": version,
                "total": len(targets),
                "pending": len(pending),
                "skipped": len(targets) - len(pending),
                "done": 0,
                "failed": 0,
                "current": None,
                "current_split": None,
                "started_at": time.time(),
                "elapsed_s": 0.0,
                "eta_s": None,
                "message": "conectando ao Roboflow…",
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(base, version, key, workspace.strip(), project.strip(),
                      batch, tag_list, targets, uploaded, record),
                name="roboflow-upload",
                daemon=True,
            )
            self._thread.start()

        return {"ok": True, "upload": self.status()}

    def cancel(self) -> dict:
        with self._lock:
            if self._state != RUNNING:
                return self._refuse(f"nenhum upload em andamento ({self._state})")
            self._cancel.set()
            self._progress["message"] = "cancelando após a imagem atual…"
        return {"ok": True, "upload": self.status()}

    @staticmethod
    def _targets(base: Path) -> list[tuple[str, str]]:
        """`[(split, arquivo), …]` na ordem train, valid, test."""
        out = []
        for split in datasets.SPLITS:
            for name in datasets.split_files(base, split):
                out.append((split, name))
        return out

    # -- execução --

    def _run(self, base, version, key, workspace, project_name, batch, tags,
             targets, uploaded, record) -> None:
        record = self._init_record(record, version, workspace, project_name, batch, tags, targets)
        failures = list(record.get("failures") or [])
        consecutive = 0
        final_state, error = DONE, None

        try:
            project = self._connect(key, workspace, project_name)
        except Exception as exc:
            # A mensagem do SDK pode conter a URL da requisição; a chave nunca
            # viaja na URL, mas o texto é truncado por precaução.
            error = f"não foi possível abrir o projeto ({type(exc).__name__}: {exc})"[:300]
            self._finish(base, record, ERROR, error, failures)
            return

        with self._lock:
            self._progress["message"] = f"enviando para {workspace}/{project_name}"

        done = 0
        for split, name in targets:
            if self._cancel.is_set():
                final_state = CANCELLED
                error = "cancelado pelo operador"
                break
            if name in uploaded:
                continue

            path = datasets.split_dir(base, split) / name
            if not path.is_file():
                # Excluída entre a montagem da lista e a vez dela.
                failures.append({"file": name, "split": split, "at": time.time(),
                                 "error": "arquivo não existe mais"})
                continue

            with self._lock:
                self._progress.update(current=name, current_split=split)

            try:
                self._upload_one(project, path, split, batch, tags)
            except _SplitUnsupported as exc:
                final_state, error = ERROR, str(exc)
                break
            except Exception as exc:
                consecutive += 1
                failures.append({"file": name, "split": split, "at": time.time(),
                                 "error": f"{type(exc).__name__}: {exc}"[:300]})
                with self._lock:
                    self._progress["failed"] = len(failures)
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    final_state = ERROR
                    error = (
                        f"{consecutive} falhas seguidas — interrompido. "
                        f"Último erro: {failures[-1]['error']}"
                    )
                    break
                continue

            consecutive = 0
            done += 1
            uploaded[name] = {"split": split, "at": time.time(), "batch": batch}
            record["uploaded"] = uploaded
            self._tick(done, len(targets))
            if done % FLUSH_EVERY == 0:
                self._save(base, record, RUNNING, None, failures)

        if final_state == DONE and failures:
            final_state = PARTIAL
            error = f"{len(failures)} imagem(ns) falharam"
        self._finish(base, record, final_state, error, failures)

    def _connect(self, key: str, workspace: str, project_name: str):
        from roboflow import Roboflow

        # A saída do SDK é capturada e descartada: nada que ele imprima chega ao
        # log do painel.
        with contextlib.redirect_stdout(io.StringIO()):
            rf = Roboflow(api_key=key)
            return rf.workspace(workspace).project(project_name)

    @staticmethod
    def _upload_one(project, path: Path, split: str, batch: str, tags: list[str]) -> None:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                project.upload(
                    str(path),
                    split=split,               # o argumento que preserva a partição
                    batch_name=batch,
                    tag_names=list(tags),
                )
        except TypeError as exc:
            # Subir sem `split` deixaria o Roboflow reparticionar aleatoriamente
            # e desfaria o split temporal. Melhor não subir nada.
            if "split" in str(exc):
                raise _SplitUnsupported(
                    "o SDK roboflow instalado não aceita o argumento split=. "
                    "Envio abortado: sem ele o Roboflow reparticiona aleatoriamente e "
                    "desfaz o split temporal. Atualize o pacote (pip install -U roboflow)."
                ) from exc
            raise

    def _tick(self, done: int, total: int) -> None:
        with self._lock:
            started = self._progress.get("started_at") or time.time()
            elapsed = time.time() - started
            rate = done / elapsed if elapsed > 0 and done else 0
            pending = max(self._progress.get("pending", 0) - done, 0)
            self._progress.update(
                done=done,
                elapsed_s=round(elapsed, 1),
                eta_s=round(pending / rate, 1) if rate > 0 else None,
            )

    # -- registro em disco --

    @staticmethod
    def _init_record(record, version, workspace, project_name, batch, tags, targets) -> dict:
        record = dict(record or {})
        record.update({
            "version": version,
            "workspace": workspace,
            "project": project_name,
            "batch_name": batch,
            "tags": list(tags),
            "state": RUNNING,
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
        })
        record.setdefault("uploaded", {})
        record.setdefault("failures", [])
        record.setdefault("runs", [])
        record["totals"] = {
            "selected": len(targets),
            "uploaded": len(record["uploaded"]),
            "failed": 0,
            "skipped": 0,
        }
        return record

    def _save(self, base: Path, record: dict, state: str, error: str | None,
              failures: list) -> None:
        record["state"] = state
        record["error"] = error
        record["failures"] = failures[-500:]
        record["totals"] = {
            "selected": record["totals"]["selected"],
            "uploaded": len(record.get("uploaded") or {}),
            "failed": len(failures),
            "skipped": max(
                record["totals"]["selected"] - len(record.get("uploaded") or {}) - len(failures), 0
            ),
        }
        datasets.write_json(base / datasets.ROBOFLOW_NAME, record)

    def _finish(self, base: Path, record: dict, state: str, error: str | None,
                failures: list) -> None:
        record["finished_at"] = time.time()
        with self._lock:
            progress = dict(self._progress)
        record.setdefault("runs", []).append({
            "at": record["finished_at"],
            "state": state,
            "uploaded_nesta_execucao": progress.get("done", 0),
            "falhas": len(failures),
            "puladas": progress.get("skipped", 0),
            "duracao_s": progress.get("elapsed_s"),
            "error": error,
        })
        self._save(base, record, state, error, failures)

        datasets.append_edit(base, {
            "action": "upload",
            "state": state,
            "workspace": record.get("workspace"),
            "project": record.get("project"),
            "batch_name": record.get("batch_name"),
            "tags": record.get("tags"),
            "uploaded_total": len(record.get("uploaded") or {}),
            "uploaded_nesta_execucao": progress.get("done", 0),
            "falhas": len(failures),
            "error": error,
        })

        with self._lock:
            self._state = state
            self._progress.update(
                message=error or "concluído",
                done=progress.get("done", 0),
                failed=len(failures),
                current=None,
                current_split=None,
                finished_at=record["finished_at"],
            )


class _SplitUnsupported(UploadError):
    pass


uploader = Uploader()
