"""Polling da API do MediaMTX.

Uma thread lê /v3/paths/list a cada 2 s e mantém o último snapshot em memória.
O dado que importa não é `ready` — é a *derivada* de bytesReceived: um path pode
estar publicado e ready com o encoder parado, e nesse caso não há voo para ver.
"""

from __future__ import annotations

import threading
import time

import httpx

from .pipeline import PATHS_LIST_URL

POLL_INTERVAL_S = 2.0
STALE_AFTER_S = 10.0  # sem bytes novos por mais que isso => amarelo


def _resolution(item: dict) -> str | None:
    """Extrai WxH do primeiro track de vídeo.

    tracks2[] traz codecProps (MediaMTX recente); versões antigas expõem apenas
    tracks[] com o nome do codec e nenhuma dimensão.
    """
    for track in item.get("tracks2") or []:
        props = track.get("codecProps") or {}
        w, h = props.get("width"), props.get("height")
        if w and h:
            return f"{w}×{h}"
    return None


def _codecs(item: dict) -> list[str]:
    tracks2 = item.get("tracks2") or []
    if tracks2:
        return [t.get("codec") or t.get("type") or "?" for t in tracks2]
    return list(item.get("tracks") or [])


class Monitor:
    def __init__(self, interval: float = POLL_INTERVAL_S) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # name -> {"bytes": int, "ts": float, "changed_at": float, "rate_bps": float}
        self._prev: dict[str, dict] = {}
        self._state: dict = {
            "api_ok": False,
            "error": None,
            "paths": [],
            "level": "red",
            "label": "Sem stream",
        }

    # -- ciclo de vida --

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                **self._state,
                "paths": [dict(p) for p in self._state["paths"]],
            }

    # -- polling --

    def _loop(self) -> None:
        with httpx.Client(timeout=1.5) as client:
            while not self._stop.is_set():
                try:
                    self._poll(client)
                except Exception as exc:  # nunca deixe a thread morrer
                    with self._lock:
                        self._state = {
                            "api_ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                            "paths": [],
                            "level": "red",
                            "label": "Sem stream",
                        }
                self._stop.wait(self.interval)

    def _poll(self, client: httpx.Client) -> None:
        try:
            resp = client.get(PATHS_LIST_URL)
            resp.raise_for_status()
            items = resp.json().get("items") or []
            api_ok, error = True, None
        except httpx.HTTPError as exc:
            api_ok, error, items = False, f"MediaMTX não responde ({type(exc).__name__})", []

        now = time.monotonic()
        paths = [self._describe(item, now) for item in items]

        if not api_ok:
            self._prev.clear()
        else:
            live = {item.get("name") for item in items}
            for gone in set(self._prev) - live:
                del self._prev[gone]

        level, label = self._traffic_light(paths, api_ok)
        with self._lock:
            self._state = {
                "api_ok": api_ok,
                "error": error,
                "paths": paths,
                "level": level,
                "label": label,
            }

    def _describe(self, item: dict, now: float) -> dict:
        name = item.get("name") or "?"
        received = int(item.get("bytesReceived") or 0)

        prev = self._prev.get(name)
        if prev is None:
            rate_bps = 0.0
            stalled_for = 0.0
            changed_at = now
        else:
            dt = max(now - prev["ts"], 1e-6)
            delta = max(received - prev["bytes"], 0)
            # suaviza o ruído do intervalo de polling
            rate_bps = 0.5 * prev["rate_bps"] + 0.5 * (delta * 8 / dt)
            changed_at = now if delta > 0 else prev["changed_at"]
            stalled_for = now - changed_at

        self._prev[name] = {
            "bytes": received,
            "ts": now,
            "changed_at": changed_at,
            "rate_bps": rate_bps,
        }

        return {
            "name": name,
            "ready": bool(item.get("ready")),
            "resolution": _resolution(item),
            "codecs": _codecs(item),
            "bytes_received": received,
            "mbps": round(rate_bps / 1e6, 2),
            "stalled_for": round(stalled_for, 1),
            "readers": len(item.get("readers") or []),
            "source": (item.get("source") or {}).get("type"),
        }

    @staticmethod
    def _traffic_light(paths: list[dict], api_ok: bool) -> tuple[str, str]:
        if not api_ok:
            return "red", "MediaMTX não responde"
        active = [p for p in paths if p["ready"]]
        if not active:
            return "red", "Sem stream"

        flowing = [p for p in active if p["stalled_for"] < STALE_AFTER_S and p["mbps"] > 0]
        if flowing:
            best = max(flowing, key=lambda p: p["mbps"])
            res = best["resolution"] or "resolução desconhecida"
            return "green", f"Recebendo — {res} · {best['mbps']:.2f} Mbps"

        worst = max(active, key=lambda p: p["stalled_for"])
        return "yellow", f"Conectado, sem dados há {worst['stalled_for']:.0f}s"


monitor = Monitor()
