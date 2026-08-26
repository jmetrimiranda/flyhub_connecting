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
  if (p.path_detected) $("stream-path").title = "detectado no MediaMTX (configurado: " + p.configured_path + ")";

  renderConnection(state);
  renderModel(state.model || {});

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

/* ---------- painel de conexão ---------- */

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return s + " s";
  const m = Math.floor(s / 60);
  if (m < 60) return m + " min " + String(s % 60).padStart(2, "0") + " s";
  return Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0") + " min";
}

// O path que o vídeo está lendo, quando houver mais de um publicando.
function activePath(state) {
  const paths = (state.stream && state.stream.paths) || [];
  const wanted = state.pipeline && state.pipeline.stream_path;
  return paths.find((x) => x.name === wanted) || paths.find((x) => x.ready) || paths[0] || null;
}

function renderConnection(state) {
  const v = state.video || {};
  const path = activePath(state);

  // Resolução: a do MediaMTX é a verdade do encoder; a do leitor é o que
  // chegou de fato ao OpenCV. Quando divergem, mostra as duas.
  const fromMtx = path && path.resolution;
  const fromReader = v.resolution;
  let resolution = fromMtx || fromReader || "—";
  if (fromMtx && fromReader && fromMtx !== fromReader) resolution = fromMtx + " → " + fromReader;
  $("f-resolution").textContent = resolution;

  $("f-mbps").textContent = path ? path.mbps.toFixed(2) + " Mbps" : "—";
  $("f-capture-fps").textContent = v.connected ? v.capture_fps.toFixed(1) : "—";
  $("f-infer-fps").textContent = v.connected ? v.infer_fps.toFixed(1) : "—";
  $("f-latency").textContent = v.connected && v.latency_ms ? Math.round(v.latency_ms) + " ms" : "—";
  $("f-dropped").textContent = v.dropped === undefined ? "—" : String(v.dropped);
  $("f-uptime").textContent = path ? fmtDuration(path.ready_for) : "—";

  const m = state.model || {};
  $("f-model").textContent = m.loaded ? m.weights_name : "nenhum modelo carregado";
  $("f-model").className = "field-value " + (m.loaded ? "good" : "muted");

  // Linha de detalhe: o que o leitor está fazendo agora.
  const consumers = v.consumers || {};
  let detail;
  if (v.connected) {
    detail = "lendo " + (v.source || "—") + " · " + v.frames + " quadros";
    if (consumers.collect) detail += " · coleta ativa";
  } else if (consumers.total === 0) {
    detail = "leitor ocioso — nenhum cliente de vídeo e nenhuma coleta ativa";
  } else if (v.retry_in_s !== null && v.retry_in_s !== undefined) {
    detail = (v.error || "desconectado") + " — nova tentativa em " + v.retry_in_s.toFixed(0) + " s";
  } else {
    detail = v.error || "conectando ao RTSP…";
  }
  if (v.reconnects) detail += " · " + v.reconnects + " reconexão(ões)";
  $("conn-detail").textContent = detail;

  renderResolutionWarning(v.resolution_change);
}

// Não é dispensável: enquanto a resolução oscila, o problema segue ativo e um
// dataset coletado agora sairia com resoluções misturadas. Some sozinho depois
// de 5 minutos sem nova troca — quem decide isso é o servidor.
function renderResolutionWarning(change) {
  const box = $("res-warning");
  if (!change) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  const at = new Date(change.at * 1000).toLocaleTimeString("pt-BR");
  box.hidden = false;
  box.textContent =
    "A resolução do stream mudou às " + at + ": " + change.from + " → " + change.to +
    ". Isso costuma ser a qualidade do canal em \"Automático\" no FlightHub — " +
    "troque para uma resolução fixa antes de coletar, ou o dataset sai misturado.";
}

function renderModel(m) {
  const badge = $("model-badge");
  const text = $("model-badge-text");
  if (m.loaded) {
    badge.className = "video-badge green";
    text.textContent = "MODELO ATIVO — " + m.weights_name +
      (m.classes && m.classes.length ? " · " + m.classes.length + " classes" : "");
  } else if (m.error) {
    badge.className = "video-badge red";
    text.textContent = "MODELO NÃO CARREGOU — vídeo cru, sem detecções";
  } else {
    badge.className = "video-badge yellow";
    text.textContent = "SEM MODELO — vídeo cru, sem detecções";
  }

  const detail = $("model-detail");
  if (m.error) detail.textContent = m.error + " (pesos: " + m.weights_path + ")";
  else if (m.loaded) detail.textContent = "Classes: " + (m.classes.join(", ") || "—") + " · limiar " + m.conf;
  else detail.textContent = "Nenhum arquivo de pesos em " + (m.weights_path || "—") +
    ". A aplicação roda em passthrough: o vídeo passa intacto e nada é detectado.";
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

$("btn-model-reload").addEventListener("click", async () => {
  const btn = $("btn-model-reload");
  btn.disabled = true;
  try {
    renderModel(await (await fetch("/api/model/reload", { method: "POST" })).json());
  } catch (err) {
    $("model-detail").textContent = "falha ao recarregar: " + err;
  } finally {
    btn.disabled = false;
  }
});

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
