"use strict";

const $ = (id) => document.getElementById(id);
const VERSION = document.body.dataset.version;
const SPLITS = ["train", "valid", "test"];

let detail = null;
let currentSplit = "train";
let selected = new Set();     // zerada a cada troca de aba
let uploadTimer = null;

/* ---------- utilidades ---------- */

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return s + " s";
  const m = Math.floor(s / 60);
  if (m < 60) return m + " min " + String(s % 60).padStart(2, "0") + " s";
  return Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0") + " min";
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
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

function jsonBody(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function showError(err) {
  $("d-error").hidden = false;
  $("d-error").textContent = String(err && err.message ? err.message : err);
}

/* ---------- carga e render ---------- */

async function load() {
  try {
    detail = await api("/api/datasets/" + VERSION);
    $("d-error").hidden = true;
  } catch (err) {
    showError(err);
    return;
  }
  renderHeader();
  renderDrift();
  renderDivergence();
  renderSession();
  renderManifest();
  renderHistory();
  renderTabs();
  renderGallery();
}

function renderHeader() {
  $("d-sub").textContent = [
    fmtDate(detail.created_at_iso),
    fmtDuration(detail.duration_s) + " de gravação",
    detail.counts.total + " imagens",
    detail.bytes_human,
  ].join(" · ");
  $("d-raw-count").textContent = detail.counts.raw;
}

/* O manifesto continua dizendo o que o split decidiu; esta faixa diz o quanto
   isso deixou de valer. Nunca se reescreve o manifesto para calar o aviso. */
function renderDrift() {
  const box = $("d-drift");
  const drift = detail.drift;
  if (!drift.stale) { box.hidden = true; return; }

  box.replaceChildren();
  box.hidden = false;

  const title = document.createElement("strong");
  title.textContent = detail.has_manifest
    ? "Manifesto desatualizado"
    : "Esta versão ainda não foi particionada";
  box.appendChild(title);

  if (drift.reason) {
    const reason = document.createElement("div");
    reason.textContent = drift.reason;
    box.appendChild(reason);
  }

  if (detail.has_manifest) {
    const table = document.createElement("table");
    table.className = "drift-table";
    for (const split of SPLITS) {
      const diff = drift.by_split[split];
      const tr = document.createElement("tr");
      const th = document.createElement("th");
      th.textContent = split;
      const before = document.createElement("td");
      before.textContent = drift.manifest_counts[split];
      const arrow = document.createElement("td");
      arrow.textContent = "→";
      arrow.className = "muted";
      const now = document.createElement("td");
      now.textContent = detail.counts[split];
      const delta = document.createElement("td");
      delta.textContent = diff === 0 ? "" : (diff > 0 ? "+" : "") + diff;
      delta.className = diff === 0 ? "muted" : "bad";
      tr.append(th, before, arrow, now, delta);
      table.appendChild(tr);
    }
    box.appendChild(table);

    const p = drift.proportions;
    const mp = drift.manifest_proportions;
    const line = document.createElement("div");
    line.className = "drift-prop";
    line.textContent =
      "Proporção agora: " + SPLITS.map((s) => (p[s] === null ? "—" : p[s] + "%")).join(" / ") +
      " — o manifesto registra " + SPLITS.map((s) => (mp[s] === null ? "—" : mp[s] + "%")).join(" / ") + ".";
    box.appendChild(line);
  }

  const action = document.createElement("button");
  action.textContent = "Refazer o split a partir de raw/";
  action.className = "inline-action";
  action.addEventListener("click", openResplit);
  box.appendChild(action);
}

/* Divergência com o Roboflow: só se torna visível. Nada é sincronizado nem
   apagado por API — lá é a fonte de verdade do que está lá. */
function renderDivergence() {
  const box = $("d-divergence");
  const d = detail.divergence;
  if (!d.any) { box.hidden = true; return; }

  const parts = [];
  if (d.deleted_after_upload)
    parts.push(d.deleted_after_upload + " imagem(ns) que já tinham sido enviadas foram excluídas daqui");
  if (d.discarded_after_upload)
    parts.push(d.discarded_after_upload + " saíram das partições num resplit, caindo na margem de descarte — " +
               "continuam em raw/, mas não estão mais em train, valid nem test");
  if (d.resplit_after_upload)
    parts.push(d.resplit_after_upload + " mudaram de partição depois do envio");

  box.replaceChildren();
  box.hidden = false;
  const title = document.createElement("strong");
  title.textContent = "Divergência com o Roboflow";
  const body = document.createElement("div");
  body.textContent = parts.join("; ") +
    ". O Roboflow continua com elas como estavam no envio — excluir aqui não " +
    "remove de lá. Se for necessário, faça isso pela interface do Roboflow.";
  box.append(title, body);
}

function renderSession() {
  const dl = $("d-session");
  dl.replaceChildren();
  const s = detail.session || {};
  const params = s.params || {};
  kv(dl, "Início", fmtDate(s.started_at_iso));
  kv(dl, "Duração", fmtDuration(s.duration_s));
  kv(dl, "Estado", s.status || "sem sessão",
     s.status && s.status !== "salvo" ? "bad" : null);
  kv(dl, "Intervalo", params.interval_s ? params.interval_s + " s" : null);
  kv(dl, "Dedup", params.dedup === undefined ? null : (params.dedup ? "ligada" : "desligada"));
  kv(dl, "Em raw/", detail.counts.raw);
  const counts = (s.counts || {});
  if (counts.dedup_skipped || counts.io_dropped || counts.stale_skipped) {
    kv(dl, "Descartados",
       [counts.dedup_skipped && counts.dedup_skipped + " quase idênticos",
        counts.stale_skipped && counts.stale_skipped + " sem quadro novo",
        counts.io_dropped && counts.io_dropped + " por I/O"].filter(Boolean).join(", "));
  }
}

function renderManifest() {
  const dl = $("d-manifest");
  dl.replaceChildren();
  const m = detail.manifest;
  const warnBox = $("d-warnings");
  warnBox.replaceChildren();

  if (!m) {
    kv(dl, "Estado", "nunca particionado", "bad");
    return;
  }
  kv(dl, "Estratégia", m.strategy === "temporal_contiguous"
     ? "blocos contíguos de tempo" : m.strategy);
  kv(dl, "Margem", m.margin_applied +
     (m.margin_applied !== m.margin_requested ? " (pedida: " + m.margin_requested + ")" : ""));
  kv(dl, "No split", SPLITS.map((s) => m.counts[s]).join(" / ") +
     " · " + m.counts.discarded + " na margem");
  kv(dl, "Gravação", fmtDuration(m.time_span && m.time_span.duration_s));
  for (const b of m.boundaries || []) {
    kv(dl, b.between.join(" | "), b.gap_s === null ? "—" : b.gap_s.toFixed(1) + " s de separação");
  }
  kv(dl, "Feito em", fmtDate(m.created_at_iso));

  for (const w of m.warnings || []) {
    const div = document.createElement("div");
    div.className = w.level === "error" ? "error strong" : "warning compact";
    div.textContent = (w.level === "error" ? "✕ " : "! ") + w.message;
    warnBox.appendChild(div);
  }
}

const ACTION_LABEL = {
  delete_images: "Exclusão de imagens",
  resplit: "Split refeito",
  upload: "Envio ao Roboflow",
};

function renderHistory() {
  const list = $("d-history");
  list.replaceChildren();
  const events = detail.edits || [];
  if (!events.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "Nada mudou desde o split.";
    list.appendChild(li);
    return;
  }
  for (const ev of events) {
    const li = document.createElement("li");
    const head = document.createElement("div");
    head.className = "history-head";
    const label = document.createElement("strong");
    label.textContent = ACTION_LABEL[ev.action] || ev.action;
    const when = document.createElement("span");
    when.className = "history-when";
    when.textContent = fmtDate(ev.at_iso);
    head.append(label, when);
    li.appendChild(head);

    const detailLine = document.createElement("div");
    detailLine.className = "history-detail";
    if (ev.action === "delete_images") {
      detailLine.textContent = ev.count + " de " + ev.split +
        " · " + ev.removed_from_raw + " também de raw/" +
        (ev.uploaded_before && ev.uploaded_before.length
          ? " · " + ev.uploaded_before.length + " já estavam no Roboflow"
          : "");
    } else if (ev.action === "resplit") {
      detailLine.textContent = "margem " + ev.margin_applied +
        " · " + SPLITS.map((s) => ev.counts_after[s]).join(" / ");
    } else if (ev.action === "upload") {
      detailLine.textContent = ev.state + " · " + ev.uploaded_nesta_execucao +
        " enviadas nesta execução" + (ev.falhas ? " · " + ev.falhas + " falhas" : "") +
        (ev.project ? " · " + ev.project : "");
    }
    li.appendChild(detailLine);
    list.appendChild(li);
  }
}

/* ---------- galeria ---------- */

function renderTabs() {
  for (const btn of $("d-tabs").querySelectorAll(".tab")) {
    const split = btn.dataset.split;
    btn.querySelector("span").textContent = detail.counts[split];
    btn.classList.toggle("current", split === currentSplit);
  }
}

function renderGallery() {
  const grid = $("g-grid");
  grid.replaceChildren();
  const images = (detail.images || {})[currentSplit] || [];
  $("g-empty").hidden = images.length > 0;

  for (const img of images) {
    const fig = document.createElement("figure");
    fig.className = "thumb";
    fig.dataset.file = img.file;
    if (selected.has(img.file)) fig.classList.add("selected");

    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = "/api/datasets/" + VERSION + "/thumb/" + currentSplit + "/" + encodeURIComponent(img.file);
    image.alt = img.file;
    image.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openLightbox(img.file);
    });

    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "thumb-check";
    check.checked = selected.has(img.file);
    check.addEventListener("change", () => toggle(img.file, check.checked));

    const caption = document.createElement("figcaption");
    caption.textContent = img.file;

    fig.append(check, image, caption);
    if (img.uploaded) {
      const mark = document.createElement("span");
      mark.className = "thumb-uploaded";
      mark.textContent = "enviada";
      mark.title = "já enviada ao Roboflow";
      fig.appendChild(mark);
    }
    grid.appendChild(fig);
  }
  renderSelection();
}

function toggle(file, on) {
  if (on) selected.add(file); else selected.delete(file);
  const fig = $("g-grid").querySelector(`[data-file="${CSS.escape(file)}"]`);
  if (fig) fig.classList.toggle("selected", on);
  renderSelection();
}

function renderSelection() {
  const n = selected.size;
  $("g-count").textContent = n === 1 ? "1 selecionada" : n + " selecionadas";
  $("btn-delete-selected").disabled = n === 0;
  $("btn-delete-selected").textContent = n ? "Excluir " + n : "Excluir selecionadas";
  const images = (detail.images || {})[currentSplit] || [];
  $("g-all").checked = images.length > 0 && n === images.length;
}

$("g-all").addEventListener("change", (ev) => {
  const images = (detail.images || {})[currentSplit] || [];
  selected = ev.target.checked ? new Set(images.map((i) => i.file)) : new Set();
  renderGallery();
});

for (const btn of document.querySelectorAll("#d-tabs .tab")) {
  btn.addEventListener("click", () => {
    currentSplit = btn.dataset.split;
    selected = new Set();   // seleção não atravessa partições: excluir é por partição
    renderTabs();
    renderGallery();
  });
}

/* ---------- lightbox ---------- */

function openLightbox(file) {
  $("lb-img").src = "/api/datasets/" + VERSION + "/image/" + currentSplit + "/" + encodeURIComponent(file);
  $("lb-name").textContent = currentSplit + "/" + file;
  $("lightbox").showModal();
}
$("lb-close").addEventListener("click", () => $("lightbox").close());
$("lightbox").addEventListener("click", (ev) => {
  if (ev.target.id === "lightbox") $("lightbox").close();
});

/* ---------- exclusão de imagens ---------- */

$("btn-delete-selected").addEventListener("click", async () => {
  if (!selected.size) return;
  const files = [...selected];
  let plan;
  try {
    plan = await api(
      "/api/datasets/" + VERSION + "/images/preview-delete",
      jsonBody("POST", { split: currentSplit, filenames: files })
    );
  } catch (err) { showError(err); return; }

  $("mdi-title").textContent = "Excluir " + plan.count +
    (plan.count === 1 ? " imagem de " : " imagens de ") + plan.split + "?";
  $("mdi-lead").textContent =
    "Os arquivos saem da partição e de raw/. Não é possível desfazer: refazer o " +
    "split não vai trazê-los de volta.";

  const up = $("mdi-uploaded");
  up.hidden = plan.uploaded_count === 0;
  if (plan.uploaded_count) {
    up.textContent = plan.uploaded_count + (plan.uploaded_count === 1
      ? " destas já foi enviada ao Roboflow."
      : " destas já foram enviadas ao Roboflow.") +
      " Excluir aqui não remove de lá — faça isso pela interface do Roboflow se necessário.";
  }

  const after = plan.counts_after;
  const prop = plan.proportions_after;
  $("mdi-after").textContent =
    "Depois da exclusão: " + SPLITS.map((s) => s + " " + after[s]).join(", ") +
    " (" + SPLITS.map((s) => (prop[s] === null ? "—" : prop[s] + "%")).join(" / ") + "). " +
    "As proporções mudam — refaça o split para redistribuir os quadros restantes.";

  $("mdi-ok").textContent = "Excluir " + plan.count;
  $("mdi-ok").onclick = () => confirmDelete(plan.targets);
  $("modal-delete-images").showModal();
});

async function confirmDelete(files) {
  $("mdi-ok").disabled = true;
  try {
    await api("/api/datasets/" + VERSION + "/images",
              jsonBody("DELETE", { split: currentSplit, filenames: files }));
    $("modal-delete-images").close();
    selected = new Set();
    await load();
  } catch (err) {
    $("modal-delete-images").close();
    showError(err);
  } finally {
    $("mdi-ok").disabled = false;
  }
}

$("mdi-cancel").addEventListener("click", () => $("modal-delete-images").close());

/* ---------- refazer o split ---------- */

function openResplit() {
  $("mrs-lead").textContent =
    "Os " + detail.counts.raw + " quadros em raw/ serão reparticionados em blocos " +
    "contíguos de tempo. Hoje as partições têm " +
    SPLITS.map((s) => detail.counts[s]).join(" / ") + ".";
  $("modal-resplit").showModal();
}

$("btn-resplit").addEventListener("click", openResplit);
$("mrs-cancel").addEventListener("click", () => $("modal-resplit").close());
$("mrs-ok").addEventListener("click", async () => {
  $("mrs-ok").disabled = true;
  try {
    await api("/api/datasets/" + VERSION + "/resplit", jsonBody("POST", {}));
    $("modal-resplit").close();
    selected = new Set();
    await load();
  } catch (err) {
    $("modal-resplit").close();
    showError(err);
  } finally {
    $("mrs-ok").disabled = false;
  }
});

/* ---------- excluir o dataset ---------- */

$("btn-delete-dataset").addEventListener("click", () => {
  $("mdd-lead").textContent =
    "Serão apagados " + detail.counts.raw + " quadros em raw/, " +
    detail.counts.total + " imagens nas partições, o manifesto e o histórico — " +
    detail.bytes_human + " no total.";
  $("mdd-confirm").value = "";
  $("mdd-ok").disabled = true;
  $("modal-delete-dataset").showModal();
  $("mdd-confirm").focus();
});

$("mdd-confirm").addEventListener("input", (ev) => {
  $("mdd-ok").disabled = ev.target.value.trim() !== VERSION;
});
$("mdd-cancel").addEventListener("click", () => $("modal-delete-dataset").close());
$("mdd-ok").addEventListener("click", async () => {
  $("mdd-ok").disabled = true;
  try {
    await api("/api/datasets/" + VERSION,
              jsonBody("DELETE", { confirm: $("mdd-confirm").value.trim() }));
    window.location.href = "/datasets";
  } catch (err) {
    $("modal-delete-dataset").close();
    showError(err);
    $("mdd-ok").disabled = false;
  }
});

/* ---------- roboflow ---------- */

async function loadUpload() {
  let status;
  try {
    status = await api("/api/roboflow/status");
  } catch (err) { return; }

  const cfg = status.config;
  const mine = status.version === VERSION;
  const running = status.active && mine;

  $("rf-form").hidden = running;
  $("rf-progress").hidden = !running;

  if (running) {
    renderProgress(status.progress);
    if (uploadTimer === null) uploadTimer = setInterval(loadUpload, 1000);
    return;
  }
  if (uploadTimer !== null) {
    clearInterval(uploadTimer);
    uploadTimer = null;
    load();   // terminou: recarrega o detalhe para refletir o registro novo
  }

  if (!cfg.sdk_available) {
    $("rf-state").textContent =
      "O pacote roboflow não está instalado — o envio fica indisponível. " +
      "Instale com: " + cfg.install_hint;
    $("rf-state").className = "hint bad";
    $("btn-upload").disabled = true;
  } else if (status.active) {
    $("rf-state").textContent = "Há um envio em andamento em " + status.version +
      ". Só um dataset sobe por vez.";
    $("rf-state").className = "hint warn";
    $("btn-upload").disabled = true;
  } else {
    const rf = detail ? detail.roboflow : null;
    $("rf-state").textContent = rf && rf.state !== "nunca enviado"
      ? rf.state + " — " + rf.uploaded + " de " + rf.total + " enviadas" +
        (rf.resumable ? ". Enviar de novo retoma de onde parou." : "")
      : "Nunca enviado.";
    $("rf-state").className = "hint" + (rf && rf.state === "parcial" ? " warn" : "");
    $("btn-upload").disabled = false;
    $("btn-upload").textContent = rf && rf.resumable ? "Retomar envio" : "Enviar ao Roboflow";
  }

  // A chave nunca é exibida: o servidor informa apenas se existe e de onde vem.
  $("rf-key-row").hidden = cfg.has_key;
  $("rf-key-hint").textContent = cfg.has_key
    ? "Chave lida de " + cfg.key_source + ". Não é exibida nem gravada em disco."
    : "Defina " + cfg.key_var + " no .env para não precisar digitar. A chave não é gravada.";

  if (detail && !$("rf-batch").value) $("rf-batch").value = VERSION;
  if (detail && !$("rf-tags").value) $("rf-tags").value = VERSION + ", drone";
  if (detail && detail.roboflow.workspace && !$("rf-workspace").value)
    $("rf-workspace").value = detail.roboflow.workspace;
  if (detail && detail.roboflow.project && !$("rf-project").value)
    $("rf-project").value = detail.roboflow.project;
}

function renderProgress(p) {
  if (!p) return;
  const total = p.pending || 0;
  const pct = total ? Math.min(p.done / total * 100, 100) : 0;
  $("rf-bar").style.width = pct.toFixed(1) + "%";
  const bits = [p.done + " de " + total + " enviadas"];
  if (p.skipped) bits.push(p.skipped + " já estavam lá");
  if (p.failed) bits.push(p.failed + " falharam");
  if (p.current) bits.push(p.current_split + "/" + p.current);
  if (p.eta_s !== null && p.eta_s !== undefined) bits.push("~" + fmtDuration(p.eta_s) + " restantes");
  $("rf-text").textContent = bits.join(" · ") + (p.message ? " — " + p.message : "");
}

$("btn-upload").addEventListener("click", () => {
  const workspace = $("rf-workspace").value.trim();
  const project = $("rf-project").value.trim();
  if (!workspace || !project) {
    showError("informe o workspace e o projeto do Roboflow");
    return;
  }
  const tags = $("rf-tags").value.split(",").map((t) => t.trim()).filter(Boolean);
  const dl = $("mup-detail");
  dl.replaceChildren();
  kv(dl, "Workspace", workspace);
  kv(dl, "Projeto", project);
  kv(dl, "Batch", $("rf-batch").value.trim() || VERSION);
  kv(dl, "Tags", tags.join(", "));
  kv(dl, "Imagens", SPLITS.map((s) => s + " " + detail.counts[s]).join(", ") +
     " · " + detail.counts.total + " no total");
  const already = detail.roboflow.uploaded;
  if (already) kv(dl, "Já enviadas", already + " serão puladas");

  $("mup-lead").textContent = "As imagens sobem com a partição preservada.";
  $("modal-upload").showModal();
});

$("mup-cancel").addEventListener("click", () => $("modal-upload").close());
$("mup-ok").addEventListener("click", async () => {
  $("mup-ok").disabled = true;
  try {
    const data = await api("/api/roboflow/upload", jsonBody("POST", {
      version: VERSION,
      workspace: $("rf-workspace").value.trim(),
      project: $("rf-project").value.trim(),
      batch_name: $("rf-batch").value.trim() || VERSION,
      tags: $("rf-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
      api_key: $("rf-key").value || null,
    }));
    $("modal-upload").close();
    $("rf-key").value = "";   // não deixa a chave no DOM depois do envio
    if (!data.ok) showError(data.error);
    else loadUpload();
  } catch (err) {
    $("modal-upload").close();
    showError(err);
  } finally {
    $("mup-ok").disabled = false;
  }
});

$("btn-upload-cancel").addEventListener("click", async () => {
  $("btn-upload-cancel").disabled = true;
  try {
    await api("/api/roboflow/cancel", jsonBody("POST", {}));
  } catch (err) {
    showError(err);
  } finally {
    $("btn-upload-cancel").disabled = false;
  }
});

/* ---------- início ---------- */

(async () => {
  await load();
  await loadUpload();
})();
