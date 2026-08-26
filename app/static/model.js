"use strict";

const $ = (id) => document.getElementById(id);

let sampleTimer = null;
let askedToGenerate = false;   // dispara a geração automática no máximo uma vez

/* ---------- utilidades ---------- */

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function pct(value) {
  return value === null || value === undefined ? "—" : (value * 100).toFixed(1) + "%";
}

function kv(dl, label, value, className) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
  if (className) dd.className = className;
  dl.append(dt, dd);
}

async function api(url, options) {
  const resp = await fetch(url, options);
  let data = null;
  try { data = await resp.json(); } catch (err) { /* corpo vazio */ }
  if (!resp.ok) throw new Error((data && data.detail) || resp.status + " " + resp.statusText);
  return data;
}

function showError(err) {
  $("m-error").hidden = false;
  $("m-error").textContent = String(err && err.message ? err.message : err);
}

/* ---------- pesos carregados ---------- */

function renderModel(model) {
  const box = $("m-badge");
  const text = $("m-badge-text");
  if (model.loaded) {
    box.className = "collect-state saved";
    text.textContent = "MODELO ATIVO";
  } else if (model.error) {
    box.className = "collect-state erro";
    text.textContent = "MODELO NÃO CARREGOU";
  } else {
    box.className = "collect-state pausado";
    text.textContent = "SEM MODELO";
  }

  const dl = $("m-model");
  dl.replaceChildren();
  kv(dl, "Arquivo", model.weights_name);
  kv(dl, "Caminho", model.weights_path);
  kv(dl, "Existe", model.weights_exists ? "sim" : "não",
     model.weights_exists ? null : "bad");
  kv(dl, "Modo", model.mode);
  kv(dl, "Limiar", model.conf);
  kv(dl, "Classes", (model.classes || []).join(", ") || "—");
  if (model.error) kv(dl, "Erro", model.error, "bad");
}

/* ---------- métricas ---------- */

const MATCH_TEXT = {
  divergente: "error",
  sem_pesos: "warn",
  desconhecido: "warn",
};

function renderMetrics(state) {
  const panel = $("m-metrics");
  const model = state.model || {};

  // Estado vazio principal: sem pesos E sem métricas não há nada a mostrar.
  if (!state.present && !model.weights_exists) {
    panel.hidden = true;
    $("m-empty").hidden = false;
    $("m-empty-title").textContent = "Nenhum modelo carregado";
    $("m-empty-body").textContent =
      "É o estado inicial do projeto: ainda não existe modelo treinado. Coloque " +
      "os pesos em " + (model.weights_path || "data/models/best.pt") +
      " ou colete um voo, anote no Roboflow e treine — a aplicação passa a " +
      "detectar os pesos sozinha, sem reiniciar.";
    const actions = $("m-empty-actions");
    actions.replaceChildren();
    const link = document.createElement("a");
    link.className = "btn-link";
    link.href = "/datasets";
    link.textContent = "Ver datasets";
    actions.appendChild(link);
    return;
  }
  $("m-empty").hidden = true;
  panel.hidden = false;

  const warn = $("m-metrics-warning");
  warn.hidden = !state.reason;
  if (state.reason) {
    warn.textContent = state.reason;
    warn.className = MATCH_TEXT[state.match] === "error"
      ? "error strong" : "warning compact";
  }

  const headline = $("m-headline");
  headline.replaceChildren();

  if (!state.present) {
    // Há pesos, mas ninguém gerou métricas ainda. A tela não quebra: explica.
    headline.appendChild(note(
      state.error
        ? "O arquivo de métricas existe mas não pôde ser lido: " + state.error
        : "Há pesos carregados, mas nenhum arquivo de métricas em " + state.path +
          ". Quem o produz é train/train.py, ao final do treino. Os exemplos " +
          "abaixo continuam funcionando — eles só precisam do modelo."
    ));
    $("m-perclass-table").hidden = true;
    $("m-perclass-empty").hidden = true;
    return;
  }

  const doc = state.document || {};
  const m = doc.metrics || {};
  for (const [label, value, hint] of [
    ["mAP@50", m.map50, "IoU 0,5"],
    ["mAP@50-95", m.map50_95, "média de IoU 0,5 a 0,95"],
    ["Precision", m.precision, "das detecções, quantas estavam certas"],
    ["Recall", m.recall, "dos objetos, quantos foram encontrados"],
  ]) {
    const card = document.createElement("div");
    card.className = "metric";
    const l = document.createElement("div");
    l.className = "metric-label";
    l.textContent = label;
    const v = document.createElement("div");
    v.className = "metric-value";
    v.textContent = pct(value);
    const h = document.createElement("div");
    h.className = "metric-hint";
    h.textContent = hint;
    card.append(l, v, h);
    headline.appendChild(card);
  }

  const rows = doc.per_class || [];
  const table = $("m-perclass-table");
  const tbody = table.querySelector("tbody");
  tbody.replaceChildren();
  table.hidden = rows.length === 0;
  $("m-perclass-empty").hidden = rows.length > 0;
  for (const row of rows) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = row.name;
    tr.appendChild(th);
    for (const key of ["map50", "map50_95", "precision", "recall"]) {
      const td = document.createElement("td");
      td.textContent = pct(row[key]);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }

  renderTraining(doc);
  renderDataset(doc);

  $("m-sub").textContent = [
    "treinado em " + fmtDate(doc.generated_at_iso),
    (doc.training || {}).base_model,
    (doc.training || {}).epochs ? doc.training.epochs + " épocas" : null,
  ].filter(Boolean).join(" · ");
}

function note(text) {
  const div = document.createElement("div");
  div.className = "hint";
  div.textContent = text;
  return div;
}

function renderTraining(doc) {
  const t = doc.training || {};
  if (!Object.keys(t).length) return;
  $("m-training-panel").hidden = false;
  const dl = $("m-training");
  dl.replaceChildren();
  kv(dl, "Modelo base", t.base_model);
  kv(dl, "Épocas", t.epochs);
  kv(dl, "imgsz", t.imgsz);
  kv(dl, "Batch", t.batch);
  kv(dl, "Device", t.device || "automático");
  kv(dl, "Run", t.name);
  kv(dl, "Pasta", t.run_dir);
  kv(dl, "Gerado em", fmtDate(doc.generated_at_iso));
}

function renderDataset(doc) {
  const d = doc.dataset || {};
  if (!Object.keys(d).length) return;
  $("m-dataset-panel").hidden = false;
  const dl = $("m-dataset");
  dl.replaceChildren();
  kv(dl, "Nome", d.name);
  kv(dl, "data.yaml", d.data_yaml);
  const counts = d.counts || {};
  kv(dl, "Imagens", ["train", "valid", "test"].map((s) => counts[s]).join(" / "));
  kv(dl, "Split local", d.split_manifest_version);

  // A mesma disciplina da fatia 4: o dataset baixado do Roboflow pode ter sido
  // reparticionado, e isso torna estas métricas otimistas.
  const box = $("m-split-warning");
  const warnings = d.split_warnings || [];
  box.hidden = d.split_check_ok !== false;
  if (!box.hidden) {
    box.textContent =
      "A partição do dataset usado no treino divergiu do split temporal: " +
      warnings.join("; ") + ". As métricas acima podem estar otimistas — " +
      "o Roboflow reparticiona ao gerar uma versão.";
  }
}

/* ---------- exemplos ---------- */

function renderSamples(state) {
  const panel = $("m-samples");
  panel.hidden = false;

  $("m-samples-state").textContent = state.reason ||
    (state.state === "pronto"
      ? "Gerados em " + fmtDate(state.generated_at_iso) + " · " + state.version +
        " · primeira, do meio e última do conjunto de teste"
      : "");

  const warn = $("m-samples-warning");
  warn.hidden = !state.error;
  if (state.error) warn.textContent = "falha ao gerar: " + state.error;

  const actions = $("m-samples-actions");
  actions.hidden = state.state === "indisponível";
  $("btn-generate").disabled = state.state === "gerando";
  $("btn-generate").textContent =
    state.state === "gerando" ? "Gerando…" :
    state.state === "pronto" ? "Gerar de novo" : "Gerar exemplos";

  const grid = $("m-samples-grid");
  grid.replaceChildren();

  if (state.state === "gerando" && state.progress) {
    grid.appendChild(note(
      (state.progress.message || "gerando…") + " (" +
      state.progress.done + " de " + state.progress.total + ")" +
      " — a primeira geração carrega o modelo e pode levar alguns segundos."
    ));
    return;
  }

  for (const s of state.samples || []) {
    const fig = document.createElement("figure");
    fig.className = "sample";

    const img = document.createElement("img");
    img.src = s.url + "?t=" + (state.generated_at || 0);
    img.alt = s.source;
    img.loading = "lazy";
    img.addEventListener("click", () => {
      $("lb-img").src = img.src;
      $("lb-name").textContent = s.version + "/test/images/" + s.source;
      $("lightbox").showModal();
    });

    const cap = document.createElement("figcaption");
    const name = document.createElement("code");
    name.textContent = s.source;
    const count = document.createElement("div");
    count.className = "sample-count";
    if (s.count === 0) {
      count.textContent = "nenhuma detecção";
      count.classList.add("muted");
    } else {
      count.textContent = s.count + (s.count === 1 ? " detecção" : " detecções") +
        " · " + Object.entries(s.by_class).map(([k, v]) => v + "× " + k).join(", ");
    }
    cap.append(name, count);

    const list = document.createElement("ul");
    list.className = "sample-dets";
    for (const det of (s.detections || []).slice(0, 8)) {
      const li = document.createElement("li");
      li.textContent = det.name + " " + (det.conf * 100).toFixed(0) + "%";
      list.appendChild(li);
    }
    if ((s.detections || []).length > 8) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "+" + (s.detections.length - 8) + " outras";
      list.appendChild(li);
    }

    fig.append(img, cap, list);
    grid.appendChild(fig);
  }

  /* Cache ausente com modelo e dataset disponíveis: dispara a geração uma vez,
     sozinha. A rota de leitura nunca computa — quem computa é esta chamada. */
  if (state.state === "ausente" && !askedToGenerate) {
    askedToGenerate = true;
    generate();
  }
}

function schedulePoll(state) {
  const wanted = state.state === "gerando";
  if (wanted && sampleTimer === null) {
    sampleTimer = setInterval(loadSamples, 1000);
  } else if (!wanted && sampleTimer !== null) {
    clearInterval(sampleTimer);
    sampleTimer = null;
    loadMetrics();   // terminou: as classes do modelo podem ter mudado
  }
}

async function loadSamples() {
  try {
    const state = await api("/api/model/samples");
    renderModel(state.model || {});
    renderSamples(state);
    schedulePoll(state);
  } catch (err) {
    showError(err);
  }
}

async function generate() {
  try {
    const data = await api("/api/model/samples/generate", { method: "POST" });
    if (!data.ok) showError(data.error);
    else { renderSamples(data.samples); schedulePoll(data.samples); }
  } catch (err) {
    showError(err);
  }
}

async function loadMetrics() {
  try {
    const state = await api("/api/model/metrics");
    renderModel(state.model || {});
    renderMetrics(state);
    $("m-error").hidden = true;
  } catch (err) {
    showError(err);
  }
}

/* ---------- ações ---------- */

$("btn-generate").addEventListener("click", generate);
$("lb-close").addEventListener("click", () => $("lightbox").close());
$("lightbox").addEventListener("click", (ev) => {
  if (ev.target.id === "lightbox") $("lightbox").close();
});

$("btn-reload").addEventListener("click", async () => {
  const btn = $("btn-reload");
  btn.disabled = true;
  try {
    renderModel(await api("/api/model/reload", { method: "POST" }));
    askedToGenerate = false;   // pesos novos, exemplos novos
    await loadMetrics();
    await loadSamples();
  } catch (err) {
    showError(err);
  } finally {
    btn.disabled = false;
  }
});

(async () => {
  await loadMetrics();
  await loadSamples();
})();
