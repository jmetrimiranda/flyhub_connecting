"use strict";

const $ = (id) => document.getElementById(id);

const MARKS = { ok: "✓", error: "✕", running: "…", pending: "·", skipped: "·" };

let currentRtmp = null;
let busy = false;
let pending = false; // POST em voo — segura os botões até a resposta chegar

let lastState = {};        // último payload do SSE — a guarda do cliente lê daqui
let collectState = null;   // bloco `collect`, atualizado também pelo poll de 1 s
let collectTimer = null;

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
  lastState = state;
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
  renderCollect(state);

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



/* ---------- coleta ---------- */

const COLLECT_DOT = {
  ocioso: "", gravando: "green", pausado: "yellow", salvando: "yellow", salvo: "green",
};

/* A mesma guarda do servidor, avaliada no cliente.

   Existe para o modal de erro abrir na hora, sem ida ao servidor, e para o
   botão nunca disparar um start que vai falhar. O servidor revalida no
   /api/collect/start: este payload pode ter dois segundos de idade. */
function localChecks(state) {
  const p = state.pipeline || {};
  const s = state.stream || {};
  const c = state.collect || {};
  const disk = c.disk || {};
  const paths = (s.paths || []).filter((x) => x.ready);
  const mtxUp = !!(p.mediamtx && p.mediamtx.running);
  const apiOk = !!s.api_ok;
  const tun = p.tunnel || {};
  const tunOk = !!(tun.running && tun.address);
  const diskOk = disk.ok !== false && !disk.over_limit;

  return [
    {
      key: "availability", label: "Disponibilidade",
      ok: s.level === "green", level: s.level || "red",
      detail: s.label || "—",
      fix: s.level === "yellow"
        ? "O drone está publicado mas sem enviar dados. Confira se o toggle do canal de encaminhamento está ligado no FlightHub."
        : "Nenhum stream chegando. Suba o pipeline e publique o endereço RTMP no FlightHub.",
    },
    {
      key: "mediamtx", label: "MediaMTX",
      ok: mtxUp && apiOk, level: mtxUp && apiOk ? "green" : mtxUp ? "yellow" : "red",
      detail: mtxUp && apiOk ? "no ar, API respondendo" : mtxUp ? "container no ar, API muda" : "parado",
      fix: "Clique em Iniciar pipeline.",
    },
    {
      key: "tunnel", label: "Túnel",
      ok: tunOk, level: tunOk ? "green" : tun.running ? "yellow" : "red",
      detail: tun.address || (tun.running ? "subindo…" : "parado"),
      fix: "Clique em Iniciar pipeline para reabrir o túnel.",
    },
    {
      key: "stream", label: "Stream",
      ok: paths.length > 0, level: paths.length ? "green" : "red",
      detail: paths.length ? paths.map((x) => x.name).join(", ") : "nenhum path ativo",
      fix: "Confira o endereço no FlightHub e religue o toggle do canal.",
    },
    {
      key: "disk", label: "Disco",
      ok: diskOk, level: diskOk ? "green" : "red",
      detail: disk.percent === null || disk.percent === undefined
        ? "indisponível"
        : disk.percent.toFixed(0) + "% usado · " + (disk.free_human || "—") + " livres",
      fix: "Acima de " + (disk.limit_pct || 90) + "% a coleta não inicia. Libere espaço em data/.",
    },
  ];
}

function renderCollect(state) {
  const c = state.collect || {};
  collectState = c;
  const session = c.session;
  const st = c.state || "ocioso";

  $("collect-idle").hidden = st !== "ocioso";
  $("collect-active").hidden = !(st === "gravando" || st === "pausado" || st === "salvando");
  $("collect-result").hidden = st !== "salvo";

  if (st === "ocioso") {
    const failed = localChecks(state).filter((x) => !x.ok);
    const btn = $("btn-collect");
    btn.classList.toggle("blocked", failed.length > 0);
    $("collect-guard").textContent = failed.length
      ? "Bloqueado: " + failed.map((x) => x.label.toLowerCase()).join(", ") +
        ". Clique para ver o que falta."
      : "Pré-condições atendidas. A coleta grava em data/datasets/ e particiona ao salvar.";
    $("collect-guard").className = "guard" + (failed.length ? " bad" : " good");
  }

  if (session && st !== "salvo") renderCollectActive(c, session, st);
  if (session && st === "salvo") renderCollectResult(session);

  schedulePoll(st);
}

function renderCollectActive(c, session, st) {
  const box = $("collect-state");
  box.className = "collect-state " + st;
  box.querySelector(".dot").className = "dot " + (COLLECT_DOT[st] || "");
  $("collect-state-text").textContent = c.state_label.toUpperCase();
  $("collect-version").textContent = session.version;

  $("c-saved").textContent = session.limit
    ? session.saved + " / " + session.limit
    : String(session.saved);
  $("c-elapsed").textContent = fmtDuration(session.elapsed_s);
  $("c-bytes").textContent = session.bytes_human;
  const q = c.queue || {};
  $("c-queue").textContent = q.depth + " / " + q.max;

  const drops = [];
  if (session.dedup_skipped) drops.push(session.dedup_skipped + " quase idênticos");
  if (session.stale_skipped) drops.push(session.stale_skipped + " sem quadro novo");
  if (session.io_dropped) drops.push(session.io_dropped + " descartados por I/O");
  if (session.write_errors) drops.push(session.write_errors + " erros de escrita");
  $("c-drops").textContent = drops.length ? "Descartados: " + drops.join(" · ") : "Nenhum quadro descartado";
  $("c-drops").classList.toggle("bad", session.io_dropped > 0 || session.write_errors > 0);

  const pausedBox = $("collect-paused-reason");
  pausedBox.hidden = !session.paused_reason;
  pausedBox.textContent = session.paused_reason || "";

  renderImpact(session.impact || {});

  const errBox = $("collect-error");
  errBox.hidden = !session.error;
  errBox.textContent = session.error || "";

  const saving = st === "salvando";
  $("btn-pause").hidden = st !== "gravando";
  $("btn-resume").hidden = st !== "pausado";
  $("btn-pause").disabled = saving;
  $("btn-resume").disabled = saving;
  $("btn-save").disabled = saving;
  $("btn-save").textContent = saving ? "Salvando…" : "Salvar";
  $("collect-hint").textContent = saving
    ? "Escoando a fila de escrita e particionando por blocos contíguos de tempo. Não feche a aba."
    : "Salvar encerra a sessão e dispara o split temporal — não dá para voltar a gravar nesta versão.";
}

/* Impacto da coleta sobre o vídeo. Exibir o vídeo é a função principal da tela;
   se a coleta derrubar o FPS além do limite, isso aparece aqui e não só num
   relatório depois do voo. */
function renderImpact(impact) {
  const box = $("collect-impact");
  if (!impact.available || !impact.degraded) {
    box.hidden = true;
    return;
  }
  const parts = [];
  if (impact.capture_drop_pct !== null && impact.capture_drop_pct > 0)
    parts.push("captura −" + impact.capture_drop_pct.toFixed(0) + "%");
  if (impact.infer_drop_pct !== null && impact.infer_drop_pct > 0)
    parts.push("inferência −" + impact.infer_drop_pct.toFixed(0) + "%");
  box.hidden = false;
  box.textContent =
    "A coleta está degradando o vídeo: " + parts.join(", ") +
    " em relação ao medido antes de começar (" +
    impact.baseline.capture_fps.toFixed(1) + " fps de captura, " +
    impact.baseline.infer_fps.toFixed(1) + " de inferência). Limite: " +
    impact.threshold_pct + "%. Aumente o intervalo de amostragem ou pause a coleta.";
}

function renderCollectResult(session) {
  const r = session.result;
  $("r-version").textContent = session.version;

  const errBox = $("r-error");
  errBox.hidden = !session.error;
  errBox.textContent = session.error || "";

  const warnBox = $("r-warnings");
  warnBox.replaceChildren();
  const counts = $("r-counts");
  counts.replaceChildren();

  if (!r) {
    $("r-detail").textContent =
      "O split não produziu manifesto. Os quadros continuam em raw/ e o dataset pode ser reparticionado.";
    return;
  }

  // Avisos do split em destaque: quem gravou 8 quadros por engano precisa ver
  // na tela que não há valid nem test, não só no manifesto.
  for (const w of r.warnings || []) {
    const div = document.createElement("div");
    div.className = w.level === "error" ? "error strong" : "warning compact";
    div.textContent = (w.level === "error" ? "✕ " : "! ") + w.message;
    warnBox.appendChild(div);
  }

  const rows = [
    ["train", r.counts.train],
    ["valid", r.counts.valid],
    ["test", r.counts.test],
    ["descartados na margem", r.counts.discarded],
    ["total em raw/", r.total_raw],
  ];
  for (const [label, value] of rows) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = label;
    const td = document.createElement("td");
    td.textContent = String(value);
    if (["train", "valid", "test"].includes(label) && value === 0) td.className = "bad";
    tr.append(th, td);
    counts.appendChild(tr);
  }

  const span = r.time_span || {};
  const gaps = (r.boundaries || [])
    .filter((b) => b.gap_s !== null && b.gap_s !== undefined)
    .map((b) => b.between.join("|") + " " + b.gap_s.toFixed(1) + " s");
  $("r-detail").textContent =
    "Blocos contíguos de tempo, margem " + r.margin_applied +
    (r.margin_applied !== r.margin_requested ? " (pedida: " + r.margin_requested + ")" : "") +
    " · " + fmtDuration(span.duration_s) + " de gravação" +
    (gaps.length ? " · separação nas fronteiras: " + gaps.join(", ") : "") +
    " · manifesto em " + r.manifest;
}

/* Enquanto há sessão aberta, os contadores vêm de /api/collect/status a cada
   segundo. O SSE segue a 2 s: acelerá-lo dobraria a frequência dos
   `docker inspect` do snapshot do pipeline durante o voo. */
function schedulePoll(st) {
  const wanted = st !== "ocioso";
  if (wanted && collectTimer === null) {
    collectTimer = setInterval(pollCollect, 1000);
  } else if (!wanted && collectTimer !== null) {
    clearInterval(collectTimer);
    collectTimer = null;
  }
}

async function pollCollect() {
  try {
    const c = await (await fetch("/api/collect/status")).json();
    renderCollect({ ...lastState, collect: c });
  } catch (err) {
    /* o SSE cobre a próxima atualização */
  }
}

/* ---------- modais ---------- */

function renderChecklist(list, checks) {
  list.replaceChildren();
  for (const c of checks) {
    const li = document.createElement("li");
    li.className = c.ok ? "ok" : "fail";

    const head = document.createElement("div");
    head.className = "check-head";
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = c.ok ? "✓" : "✕";
    const label = document.createElement("strong");
    label.textContent = c.label;
    const detail = document.createElement("span");
    detail.className = "check-detail";
    detail.textContent = c.ok ? "" : " — " + c.detail;
    head.append(mark, label, detail);
    li.appendChild(head);

    if (!c.ok && c.fix) {
      const fix = document.createElement("div");
      fix.className = "check-fix";
      fix.textContent = c.fix;
      li.appendChild(fix);
    }
    list.appendChild(li);
  }
}

function showErrorModal(checks) {
  // falhas primeiro: é o que o operador precisa ler
  const ordered = [...checks].sort((a, b) => Number(a.ok) - Number(b.ok));
  renderChecklist($("modal-error-list"), ordered);
  $("modal-error").showModal();
}

function showConfirmModal(pre) {
  $("confirm-version").textContent = pre.next_version;

  const select = $("in-interval");
  select.replaceChildren();
  for (const value of pre.defaults.interval_options) {
    const opt = document.createElement("option");
    opt.value = String(value);
    opt.textContent = value + " s";
    if (value === pre.defaults.interval) opt.selected = true;
    select.appendChild(opt);
  }
  $("in-limit").value = pre.defaults.limit;
  $("in-unlimited").checked = false;
  $("in-limit").disabled = false;
  $("in-dedup").checked = pre.defaults.dedup;

  const r = pre.defaults.ratios;
  $("confirm-note").textContent =
    "Ao salvar, o dataset é particionado por blocos contíguos de tempo — " +
    Math.round(r.train * 100) + "/" + Math.round(r.valid * 100) + "/" +
    Math.round(r.test * 100) + " com margem de " + pre.defaults.margin +
    " quadros nas fronteiras. Split aleatório colocaria quadros vizinhos em " +
    "partições diferentes e vazaria treino na validação.";

  $("modal-confirm").showModal();
}

$("in-unlimited").addEventListener("change", (ev) => {
  $("in-limit").disabled = ev.target.checked;
});

$("btn-error-close").addEventListener("click", () => $("modal-error").close());
$("btn-confirm-cancel").addEventListener("click", () => $("modal-confirm").close());

/* ---------- ações da coleta ---------- */

async function postCollect(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json();
  if (data.collect) renderCollect({ ...lastState, collect: data.collect });
  return data;
}

$("btn-collect").addEventListener("click", async () => {
  const btn = $("btn-collect");

  // Validação no cliente antes de qualquer requisição: o botão nunca dispara um
  // start que vai falhar.
  const checks = localChecks(lastState);
  if (checks.some((c) => !c.ok)) {
    showErrorModal(checks);
    return;
  }

  btn.disabled = true;
  try {
    const pre = await (await fetch("/api/collect/preflight")).json();
    if (!pre.ok) showErrorModal(pre.checks);
    else showConfirmModal(pre);
  } catch (err) {
    $("collect-guard").textContent = "falha ao validar pré-condições: " + err;
  } finally {
    btn.disabled = false;
  }
});

$("btn-confirm-ok").addEventListener("click", async () => {
  const unlimited = $("in-unlimited").checked;
  const body = {
    interval: parseFloat($("in-interval").value),
    limit: unlimited ? null : parseInt($("in-limit").value, 10),
    dedup: $("in-dedup").checked,
  };
  $("btn-confirm-ok").disabled = true;
  try {
    const data = await postCollect("/api/collect/start", body);
    $("modal-confirm").close();
    // O servidor revalidou e discordou do cliente: mostra a lista dele.
    if (!data.ok && data.preflight) showErrorModal(data.preflight.checks);
    else if (!data.ok) showErrorModal(localChecks(lastState));
  } finally {
    $("btn-confirm-ok").disabled = false;
  }
});

$("btn-pause").addEventListener("click", () => postCollect("/api/collect/pause"));
$("btn-resume").addEventListener("click", () => postCollect("/api/collect/resume"));
$("btn-save").addEventListener("click", () => {
  $("btn-save").disabled = true;
  postCollect("/api/collect/save");
});
$("btn-dismiss").addEventListener("click", () => postCollect("/api/collect/dismiss"));

connect();
