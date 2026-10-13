// Padel Hunter - frontend (bez frameworka). Logika rangiranja je ista kao u core/engine.py.
"use strict";

const EXACT = 0.8, DEAL_THRESHOLD = 0.30;
const $ = (sel) => document.querySelector(sel);
const safeUrl = (u) => /^https?:\/\//i.test(u || "") ? u : "#";
const eur = (n) => n == null ? "?" : n.toLocaleString("hr-HR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";

const api = {
  get: (url) => fetch(url).then((r) => r.json()),
  send: (url, method, body) => fetch(url, {
    method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body),
  }).then((r) => r.json()),
};

// ---------- tabovi ----------
document.querySelectorAll("nav button").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll("nav button, .tab").forEach((el) => el.classList.remove("active"));
  btn.classList.add("active");
  $(`#tab-${btn.dataset.tab}`).classList.add("active");
  if (btn.dataset.tab === "watch") loadWatches();
  if (btn.dataset.tab === "settings") { loadSettings(); loadHealth(); loadMobile(); }
}));

// ---------- pretraga ----------
const state = { query: "", offers: [], cond: "all", es: null, shown: 100 };

$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch($("#q").value.trim()); });
$("#f-view").addEventListener("change", () => { state.shown = RENDER_STEP; render(); });
$("#f-sort").addEventListener("change", () => { state.shown = RENDER_STEP; render(); });
$("#f-max").addEventListener("input", render);
$("#f-cond").addEventListener("click", (e) => {
  if (!e.target.dataset.v) return;
  state.cond = e.target.dataset.v;
  $("#f-cond").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === e.target));
  render();
});

function runSearch(q) {
  if (q.length < 2) return;
  state.es?.close();
  Object.assign(state, { query: q, offers: [], shown: RENDER_STEP });
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));
  $("#sources").innerHTML = "";
  $("#summary").textContent = "Tražim…";
  $("#watch-btn").hidden = false;
  render();

  const t0 = performance.now();
  const es = state.es = new EventSource("/api/search?q=" + encodeURIComponent(q));
  es.addEventListener("start", (e) => {
    for (const label of JSON.parse(e.data).sources) {
      $("#sources").insertAdjacentHTML("beforeend", `<span class="chip wait" data-label="${label}">${label}</span>`);
    }
    updateSourcesSummary();
  });
  es.addEventListener("source", (e) => {
    const d = JSON.parse(e.data);
    const chip = $(`#sources [data-label="${CSS.escape(d.label)}"]`);
    chip.className = "chip " + (d.ok ? "ok" : "err");
    chip.textContent = d.ok ? `${d.label} ${d.offers.length}` : `${d.label} ✕`;
    chip.title = d.ok ? `${d.ms} ms` : d.error;
    updateSourcesSummary();
    state.offers.push(...d.offers);
    render();
  });
  es.addEventListener("done", () => {
    es.close();
    $("#summary").dataset.time = ((performance.now() - t0) / 1000).toFixed(1);
    render();
  });
  es.onerror = () => { es.close(); $("#summary").textContent = "Veza sa serverom prekinuta."; };
}

function updateSourcesSummary() {
  const count = (cls) => document.querySelectorAll(`#sources .chip.${cls}`).length;
  const [ok, err, wait] = [count("ok"), count("err"), count("wait")];
  $("#sources-sum").textContent = `Izvori: ✓ ${ok} radi` + (err ? ` · ✕ ${err} ne radi` : "") + (wait ? ` · ⏳ ${wait} traži…` : "");
}

function referencePrice(offers) {
  const exact = offers.filter((o) => o.match >= EXACT);
  const fresh = exact.filter((o) => o.condition === "new").map((o) => o.total);
  const pool = fresh.length >= 2 ? fresh : exact.map((o) => o.total);
  if (pool.length < 2) return null;
  const s = [...pool].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// sortiranje: ključ -> usporedba (sve ponude u jednoj listi, korisnik bira poredak)
const SORTS = {
  "total-asc": (a, b) => a.total - b.total,
  "total-desc": (a, b) => b.total - a.total,
  "price-asc": (a, b) => a.price - b.price,
  "price-desc": (a, b) => b.price - a.price,
  "deal": (a, b) => b.deal_pct - a.deal_pct || a.total - b.total,
  "newest": (a, b) => (b.posted || "").localeCompare(a.posted || "") || a.total - b.total,
  "source": (a, b) => a.source_name.localeCompare(b.source_name) || a.total - b.total,
  "match": (a, b) => b.match - a.match || a.total - b.total,
};
const RENDER_STEP = 100;  // koliko ponuda se iscrtava odjednom ("Prikaži još")

function render() {
  const ref = referencePrice(state.offers);
  for (const o of state.offers) {
    o.deal_pct = ref && o.match >= EXACT ? 1 - o.total / ref : 0;
    o.is_deal = o.deal_pct >= DEAL_THRESHOLD;
  }
  const max = parseFloat($("#f-max").value) || Infinity;
  const onlyExact = $("#f-view").value === "exact";
  const filtered = state.offers
    .filter((o) => state.cond === "all" || o.condition === state.cond)
    .filter((o) => o.total <= max);
  const exact = filtered.filter((o) => o.match >= EXACT);
  const visible = (onlyExact ? exact : filtered).sort(SORTS[$("#f-sort").value] || SORTS["total-asc"]);

  const box = $("#results");
  box.innerHTML = "";
  const cheapestExact = [...exact].sort(SORTS["total-asc"])[0];
  box.append(...visible.slice(0, state.shown).map((o) => offerEl(o, o === cheapestExact)));
  if (visible.length > state.shown) {
    const more = document.createElement("button");
    more.className = "ghost more";
    more.textContent = `Prikaži još (${visible.length - state.shown})`;
    more.onclick = () => { state.shown += RENDER_STEP; render(); };
    box.append(more);
  }

  const time = $("#summary").dataset.time;
  const sources = new Set(filtered.map((o) => o.source)).size;
  const parts = [];
  if (filtered.length) parts.push(`<b>${filtered.length}</b> ponuda iz ${sources} izvora (${exact.length} točan model)`);
  if (cheapestExact) parts.push(`najjeftiniji točan: <b>${eur(cheapestExact.total)}</b> (${escapeHtml(cheapestExact.source_name)})`);
  if (ref) parts.push(`uobičajena cijena ~${eur(ref)}`);
  const deals = exact.filter((o) => o.is_deal).length;
  if (deals) parts.push(`🔥 ${deals} apsurdnih`);
  if (time) parts.push(`${time} s`);
  if (state.query) $("#summary").innerHTML = parts.join(" · ") || (time ? "Ništa nije pronađeno." : "Tražim…");
}

function group(text) {
  const el = document.createElement("div");
  el.className = "group";
  el.textContent = text;
  return el;
}

function offerEl(o, best = false) {
  const el = $("#offer-tpl").content.firstElementChild.cloneNode(true);
  el.href = safeUrl(o.url);
  el.classList.toggle("deal", o.is_deal);
  el.classList.toggle("best", best);
  el.querySelector("img").src = o.image || "";
  el.querySelector(".title").textContent = o.title;

  const badges = [o.match >= EXACT
    ? `<span class="badge exact">✓ točan model</span>`
    : `<span class="badge variant">varijanta</span>`];
  if (o.is_deal) badges.push(`<span class="badge deal">🔥 −${Math.round(o.deal_pct * 100)}%</span>`);
  badges.push(`<span class="badge ${o.condition}">${o.condition === "new" ? "novo" : "rabljeno"}</span>`);
  if (o.is_auction) badges.push(`<span class="badge">aukcija</span>`);
  const meta = [o.source_name, o.location].filter(Boolean).map(escapeHtml).join(" · ");
  el.querySelector(".meta").innerHTML = badges.join("") + meta;
  el.querySelector(".note").textContent = [o.match_note, o.shipping_note].filter(Boolean).join(" · ");

  el.querySelector(".total").textContent = eur(o.total);
  const ship = o.shipping == null ? "dostava ?" : `${o.shipping_exact ? "" : "~"}${eur(o.shipping)} dostava`;
  const fees = o.fees ? ` + ${eur(o.fees)} naknada` : "";
  el.querySelector(".breakdown").innerHTML =
    `${eur(o.price)}${fees} + <span class="${o.shipping_exact ? "" : "est"}" title="${escapeHtml(o.shipping_note)}">${ship}</span>`;
  return el;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- praćenje ----------
$("#watch-btn").addEventListener("click", () => {
  $("#w-q").value = state.query;
  const ref = referencePrice(state.offers);
  if (ref) $("#w-max").value = Math.round(ref * (1 - DEAL_THRESHOLD));
  document.querySelector('nav button[data-tab="watch"]').click();
});

$("#watch-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = $("#w-q").value.trim();
  if (query.length < 2) return;
  await api.send("/api/watches", "POST", {
    query, max_total: parseFloat($("#w-max").value) || null,
    include_used: $("#w-used").checked, include_similar: $("#w-similar").checked,
  });
  $("#w-q").value = $("#w-max").value = "";
  loadWatches();
});

async function loadWatches() {
  const list = await api.get("/api/watches");
  $("#watch-count").textContent = list.length ? `(${list.length})` : "";
  $("#watches").innerHTML = list.length ? "" : `<p class="hint">Još ništa ne pratiš.</p>`;
  for (const w of list) {
    const el = document.createElement("div");
    el.className = "watch";
    const rule = w.max_total ? `javi ispod ${eur(w.max_total)}` : "javi apsurdne cijene";
    const best = w.best_total ? ` · najniže viđeno <a href="${escapeHtml(safeUrl(w.best_url))}" target="_blank">${eur(w.best_total)}</a>` : "";
    const last = w.last_market ? ` · provjereno ${new Date(w.last_market * 1000).toLocaleTimeString("hr-HR")}` : " · čeka prvu provjeru";
    el.innerHTML = `<div><b>${escapeHtml(w.query)}</b><div class="hint">${rule}${w.include_used ? "" : " · samo novo"}${w.include_similar ? " · i varijante" : ""}${best}${last}</div></div>`;
    const del = document.createElement("button");
    del.className = "ghost";
    del.textContent = "Ukloni";
    del.onclick = async () => { await api.send(`/api/watches/${w.id}`, "DELETE"); loadWatches(); };
    el.append(del);
    $("#watches").append(el);
  }
}

// ---------- postavke ----------
async function loadSettings() {
  const s = await api.get("/api/settings");
  $("#tg-dot").classList.toggle("on", s.configured);
  $("#tg-token").placeholder = s.tg_token_set ? `spremljen (${s.tg_token_hint})` : "token bota";
  $("#tg-status").textContent = s.configured ? `Povezano (chat ${s.tg_chat}).` : "Nije povezano.";
  $("#ebay-status").textContent = s.ebay_set ? `Ključ spremljen (${s.ebay_hint}) - eBay koristi službeni API.` : "Nije upisano - koristi se scraping.";
}

$("#ebay-save").addEventListener("click", async () => {
  const id = $("#ebay-id").value.trim(), secret = $("#ebay-secret").value.trim();
  if (!id || !secret) return;
  await api.send("/api/settings", "POST", { ebay_client_id: id, ebay_client_secret: secret });
  $("#ebay-id").value = $("#ebay-secret").value = "";
  loadSettings();
});

$("#tg-save").addEventListener("click", async () => {
  const token = $("#tg-token").value.trim();
  if (!token) return;
  await api.send("/api/settings", "POST", { tg_token: token });
  $("#tg-token").value = "";
  loadSettings();
});
$("#tg-detect").addEventListener("click", async () => {
  const r = await api.send("/api/telegram/detect", "POST");
  $("#tg-status").textContent = r.chat ? `Povezano s: ${r.info}` : r.info;
  if (r.chat) loadSettings();
});
$("#tg-test").addEventListener("click", async () => {
  const r = await api.send("/api/telegram/test", "POST");
  $("#tg-status").textContent = r.ok ? "Poruka poslana ✅" : `Nije uspjelo: ${r.error}`;
});

async function loadMobile() {
  const r = await fetch("/api/mobile");
  if (!r.ok) return;  // na mobitelu se QR ne prikazuje
  const m = await r.json();
  $("#mobile-box").hidden = false;
  $("#mobile-qr").innerHTML = m.qr;  // SVG generira naš server (segno), nije vanjski sadržaj
  $("#mobile-url").textContent = m.url;
}

async function loadHealth() {
  const h = await api.get("/api/health");
  $("#health").innerHTML = Object.values(h).map((s) => {
    const status = s.ok === null ? "još nije korišten" : s.ok ? `✅ radi · ${s.ms} ms` : `❌ ${escapeHtml(s.error)}`;
    return `<div class="health"><span>${s.label} <span class="hint">${s.kind === "market" ? "oglasnik" : "trgovina"}</span></span><span class="hint">${status}</span></div>`;
  }).join("");
}

// ---------- start ----------
initCatalog({
  onPick(racket) {  // klik na verziju iz kataloga = pretraga točno te verzije
    const hasYear = racket.year && racket.title.includes(String(racket.year));
    const query = hasYear || !racket.year ? racket.title : `${racket.title} ${racket.year}`;
    $("#q").value = query;
    $("#finder").open = false;
    runSearch(query);
  },
});
loadSettings();
loadWatches();
const initial = new URLSearchParams(location.search).get("q");
if (initial) { $("#q").value = initial; runSearch(initial); }
