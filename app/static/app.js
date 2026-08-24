"use strict";

const $ = (id) => document.getElementById(id);

const MARKS = { ok: "✓", error: "✕", running: "…", pending: "·", skipped: "·" };

let currentRtmp = null;
let busy = false;
let pending = false; // POST em voo — segura os botões até a resposta chegar

/* ---------- SSE ---------- */

let source = null;

function connect() {
  source = new EventSource("/events");

  source.onopen = () => {
    $("sse-state").textContent = "SSE: conectado";
    $("sse-state").classList.remove("down");
  };

  source.onmessage = (ev) => {
    try {
      render(JSON.parse(ev.data));
    } catch (err) {
      console.error("payload inválido", err);
    }
  };

  // EventSource já reconecta sozinho; aqui só refletimos a queda na interface.
  source.onerror = () => {
    $("sse-state").textContent = "SSE: reconectando…";
    $("sse-state").classList.add("down");
  };
}

/* ---------- render ---------- */

function setDot(id, level) {
  const dot = $(id);
  dot.className = "dot" + (level ? " " + level : "");
}

function render(state) {
  const p = state.pipeline || {};
  const s = state.stream || {};

  // MediaMTX
  const mtxUp = p.mediamtx && p.mediamtx.running;
  setDot("dot-mtx", mtxUp ? (s.api_ok ? "green" : "yellow") : "red");
  $("mtx-label").textContent = !mtxUp
    ? "Parado"
    : s.api_ok
      ? "No ar"
      : "Container no ar, API muda";

  // Túnel
  const tunUp = p.tunnel && p.tunnel.running;
  setDot("dot-tunnel", tunUp ? (p.tunnel.address ? "green" : "yellow") : "red");
  $("tunnel-label").textContent = !tunUp
    ? "Parado"
    : p.tunnel.address || "Subindo…";

  // Stream + semáforo de disponibilidade
  setDot("dot-availability", s.level || "red");
  $("availability-label").textContent = s.label || "—";
  setDot("dot-stream", s.level || "red");

  const paths = s.paths || [];
  $("stream-label").textContent = paths.length
    ? paths.map((x) => x.name).join(", ")
    : "Nenhum path ativo";

  renderPaths(paths);
  renderSteps(p.steps || []);

  // erro do pipeline
  const errBox = $("pipeline-error");
  const errText = p.error || s.error || "";
  errBox.hidden = !errText;
  errBox.textContent = errText;

  // endereço RTMP
  updateRtmp(p.rtmp_url || null);

  $("stream-path").textContent = p.stream_path || "—";
  $("hls-url").textContent = p.hls_url || "—";
  $("rtsp-url").textContent = p.rtsp_url || "—";

  busy = !!p.busy;
  $("btn-start").disabled = busy || pending;
  $("btn-stop").disabled = busy || pending;
}

function renderPaths(paths) {
  const table = $("paths-table");
  const tbody = table.querySelector("tbody");
  table.hidden = paths.length === 0;
  tbody.replaceChildren();

  for (const p of paths) {
    const tr = document.createElement("tr");
    const cells = [
      p.name,
      p.ready ? "sim" : "não",
      p.resolution || "—",
      p.mbps.toFixed(2) + " Mbps",
      (p.codecs || []).join(", ") || "—",
      p.stalled_for > 0 ? p.stalled_for.toFixed(0) + " s" : "—",
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderSteps(steps) {
  const list = $("steps");
  list.replaceChildren();

  for (const step of steps) {
    const li = document.createElement("li");
    li.className = step.status;

    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = MARKS[step.status] || "·";

    const name = document.createElement("span");
    name.className = "step-name";
    name.textContent = step.name;

    const detail = document.createElement("span");
    detail.className = "step-detail";
    detail.textContent = step.detail || "";

    li.append(mark, name, detail);
    list.appendChild(li);
  }
}

function updateRtmp(url) {
  if (url === currentRtmp) return;
  currentRtmp = url;

  const box = $("rtmp-url");
  const copy = $("btn-copy");

  box.textContent = url || "pipeline parado";
  box.classList.toggle("live", !!url);
  copy.disabled = !url;
  copy.classList.remove("copied");
  copy.textContent = "Copiar";
}

/* ---------- ações ---------- */

async function post(url, body) {
  pending = true;
  $("btn-start").disabled = true;
  $("btn-stop").disabled = true;
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json();
    pending = false;
    if (data.pipeline) render(data);
    else throw new Error(data.detail || "resposta inesperada");
  } catch (err) {
    pending = false;
    const box = $("pipeline-error");
    box.hidden = false;
    box.textContent = String(err);
    $("btn-start").disabled = false;
    $("btn-stop").disabled = false;
  }
}

$("btn-start").addEventListener("click", () => post("/api/pipeline/start"));
$("btn-stop").addEventListener("click", () => post("/api/pipeline/stop"));

$("btn-copy").addEventListener("click", async () => {
  if (!currentRtmp) return;
  const btn = $("btn-copy");
  try {
    // clipboard API exige contexto seguro; em Codespace via HTTP cai no fallback
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(currentRtmp);
    } else {
      legacyCopy(currentRtmp);
    }
    btn.textContent = "Copiado";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent = "Copiar";
      btn.classList.remove("copied");
    }, 1800);
  } catch (err) {
    btn.textContent = "Falhou";
    console.error(err);
  }
});

function legacyCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(ta);
  if (!ok) throw new Error("cópia bloqueada pelo navegador");
}

connect();
