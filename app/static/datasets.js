"use strict";

const $ = (id) => document.getElementById(id);

const SPLITS = ["train", "valid", "test"];

const RF_CLASS = {
  "concluído": "good",
  "parcial": "warn",
  "erro": "bad",
  "cancelado": "warn",
  "enviando": "warn",
  "nunca enviado": "muted",
};

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

/* Barra de distribuição: proporção **e** número. Só a barra obrigaria o
   operador a estimar de olho quantas imagens tem cada partição. */
function distribution(counts) {
  const wrap = document.createElement("div");
  wrap.className = "dist";

  const bar = document.createElement("div");
  bar.className = "dist-bar";
  const total = counts.total || 0;
  for (const split of SPLITS) {
    const piece = document.createElement("span");
    piece.className = "dist-" + split;
    piece.style.width = total ? (counts[split] / total * 100).toFixed(1) + "%" : "0";
    piece.title = split + ": " + counts[split];
    bar.appendChild(piece);
  }

  const text = document.createElement("div");
  text.className = "dist-text";
  text.textContent = SPLITS.map((s) => counts[s]).join(" / ");

  wrap.append(bar, text);
  return wrap;
}

function cell(tr, content, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  if (content instanceof Node) td.appendChild(content);
  else td.textContent = content;
  tr.appendChild(td);
  return td;
}

function render(list) {
  const table = $("ds-table");
  const tbody = table.querySelector("tbody");
  tbody.replaceChildren();

  $("ds-empty").hidden = list.length > 0;
  table.hidden = list.length === 0;

  const totalImages = list.reduce((n, d) => n + d.counts.total, 0);
  const totalBytes = list.reduce((n, d) => n + d.bytes, 0);
  $("ds-summary").textContent = list.length
    ? `${list.length} versão(ões) · ${totalImages} imagens · ${humanBytes(totalBytes)}`
    : "";

  for (const d of list) {
    const tr = document.createElement("tr");

    const link = document.createElement("a");
    link.href = "/datasets/" + d.version;
    link.className = "version-link";
    link.textContent = d.version;
    const versionCell = document.createElement("div");
    versionCell.className = "version-cell";
    versionCell.appendChild(link);

    // Um dataset com manifesto desatualizado ou sessão interrompida não pode
    // parecer igual aos outros na lista.
    if (d.drift.stale) versionCell.appendChild(badge("manifesto desatualizado", "warn"));
    if (d.session_status && d.session_status !== "salvo")
      versionCell.appendChild(badge("sessão " + d.session_status, "bad"));
    if (d.divergence.any) versionCell.appendChild(badge("divergente do Roboflow", "warn"));
    cell(tr, versionCell);

    cell(tr, fmtDate(d.created_at_iso), "mono");
    cell(tr, fmtDuration(d.duration_s), "mono");
    cell(tr, String(d.counts.total), "mono strong");
    cell(tr, distribution(d.counts));
    cell(tr, d.bytes_human, "mono");

    const rf = d.roboflow;
    const rfCell = document.createElement("div");
    const state = document.createElement("span");
    state.className = "rf-state " + (RF_CLASS[rf.state] || "muted");
    state.textContent = rf.state;
    rfCell.appendChild(state);
    if (rf.total) {
      const detail = document.createElement("div");
      detail.className = "rf-detail";
      detail.textContent = rf.uploaded + " / " + rf.total +
        (rf.project ? " · " + rf.project : "");
      rfCell.appendChild(detail);
    }
    cell(tr, rfCell);

    tbody.appendChild(tr);
  }
}

function badge(text, kind) {
  const span = document.createElement("span");
  span.className = "badge " + kind;
  span.textContent = text;
  return span;
}

function humanBytes(n) {
  let v = Number(n) || 0;
  for (const unit of ["B", "KB", "MB", "GB", "TB"]) {
    if (v < 1024 || unit === "TB") return unit === "B" ? v.toFixed(0) + " B" : v.toFixed(1) + " " + unit;
    v /= 1024;
  }
  return v.toFixed(1) + " TB";
}

async function load() {
  try {
    const data = await (await fetch("/api/datasets")).json();
    render(data.datasets || []);
  } catch (err) {
    $("ds-error").hidden = false;
    $("ds-error").textContent = "falha ao carregar: " + err;
    $("ds-summary").textContent = "";
  }
}

load();
