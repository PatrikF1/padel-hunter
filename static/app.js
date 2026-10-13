// Padel Hunter - sučelje (čisti JavaScript, bez frameworka).
// Odjeljci: pomoćne funkcije · tabovi · pretraga · prikaz rezultata · praćenje · postavke · start.
// Izračun "uobičajene cijene" i apsurdnih ponuda isti je kao u core/engine.py (reference_price, mark_deals).
"use strict";

// ---------- konstante (iste vrijednosti kao u core/engine.py) ----------
const EXACT_MIN = 0.8;        // od ove ocjene ponuda je "točan model"
const DEAL_THRESHOLD = 0.30;  // 30 % ispod uobičajene cijene = apsurdno
const RENDER_STEP = 100;      // koliko ponuda se iscrtava odjednom ("Prikaži još")

// ---------- pomoćne funkcije ----------
const $ = (selector) => document.querySelector(selector);
const safeUrl = (url) => /^https?:\/\//i.test(url || "") ? url : "#";
const eur = (amount) => amount == null ? "?"
  : amount.toLocaleString("hr-HR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const api = {
  get: (url) => fetch(url).then((response) => response.json()),
  send: (url, method, body) => fetch(url, {
    method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body),
  }).then((response) => response.json()),
};

// ---------- tabovi ----------
document.querySelectorAll("nav button").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("nav button, .tab").forEach((el) => el.classList.remove("active"));
  button.classList.add("active");
  $(`#tab-${button.dataset.tab}`).classList.add("active");
  if (button.dataset.tab === "watch") loadWatches();
  if (button.dataset.tab === "settings") { loadSettings(); loadSourceHealth(); loadMobileQr(); }
}));

// ---------- pretraga ----------
const search = {
  query: "",
  offers: [],          // sve ponude koje su stigle (svi izvori)
  condition: "all",    // filter "Sve / Novo / Rabljeno"
  events: null,        // EventSource veza sa serverom
  shown: RENDER_STEP,  // koliko ponuda je trenutno iscrtano
};

$("#search-form").addEventListener("submit", (event) => { event.preventDefault(); runSearch($("#q").value.trim()); });

// ---------- filteri rezultata ----------
// Svaka kontrola u .toolbar mijenja prikaz odmah; ponude se ne dohvaćaju ponovno.
const FILTER_INPUTS = ["#f-view", "#f-sort", "#f-source", "#f-min", "#f-max", "#f-deals"];
for (const selector of FILTER_INPUTS) {
  $(selector).addEventListener("input", () => { search.shown = RENDER_STEP; renderResults(); });
}
$("#f-cond").addEventListener("click", (event) => {
  if (event.target.dataset.v) setCondition(event.target.dataset.v);
});
$("#f-reset").addEventListener("click", () => {
  $("#f-view").value = "all";
  $("#f-source").value = $("#f-min").value = $("#f-max").value = "";
  $("#f-deals").checked = false;
  setCondition("all");
});

function setCondition(condition) {
  search.condition = condition;
  $("#f-cond").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.v === condition));
  renderResults();
}

// trenutno stanje kontrola kao jedan objekt
function readFilters() {
  return {
    condition: search.condition,
    onlyExact: $("#f-view").value === "exact",
    onlyDeals: $("#f-deals").checked,
    source: $("#f-source").value,
    minTotal: parseFloat($("#f-min").value) || 0,
    maxTotal: parseFloat($("#f-max").value) || Infinity,
  };
}

function passesFilters(offer, filters) {
  return (filters.condition === "all" || offer.condition === filters.condition)
    && (!filters.onlyExact || offer.match >= EXACT_MIN)
    && (!filters.onlyDeals || offer.is_deal)
    && (!filters.source || offer.source === filters.source)
    && offer.total >= filters.minTotal && offer.total <= filters.maxTotal;
}

function isFiltering(filters) {
  return filters.condition !== "all" || filters.onlyExact || filters.onlyDeals || Boolean(filters.source)
    || filters.minTotal > 0 || filters.maxTotal < Infinity;
}

// izbornik izvora nudi samo izvore koji su nešto pronašli, s brojem ponuda
function renderSourceOptions() {
  const counts = new Map();
  for (const offer of search.offers) {
    const entry = counts.get(offer.source) || { name: offer.source_name, count: 0 };
    entry.count += 1;
    counts.set(offer.source, entry);
  }
  const select = $("#f-source"), selected = select.value;
  const options = [...counts].sort((a, b) => a[1].name.localeCompare(b[1].name))
    .map(([source, entry]) => `<option value="${escapeHtml(source)}">${escapeHtml(entry.name)} (${entry.count})</option>`);
  select.innerHTML = `<option value="">Svi izvori</option>` + options.join("");
  select.value = counts.has(selected) ? selected : "";
}

// Server šalje rezultate izvor po izvor (Server-Sent Events): "start" -> "source" (×N) -> "done"
function runSearch(query) {
  if (query.length < 2) return;
  search.events?.close();
  Object.assign(search, { query, offers: [], shown: RENDER_STEP });
  history.replaceState(null, "", "?q=" + encodeURIComponent(query));
  $("#sources").innerHTML = "";
  $("#summary").textContent = "Tražim…";
  delete $("#summary").dataset.time;
  $("#watch-btn").hidden = false;
  renderResults();

  const started = performance.now();
  const events = search.events = new EventSource("/api/search?q=" + encodeURIComponent(query));
  events.addEventListener("start", (event) => {
    for (const label of JSON.parse(event.data).sources) {
      $("#sources").insertAdjacentHTML("beforeend", `<span class="chip wait" data-label="${label}">${label}</span>`);
    }
    updateSourcesSummary();
  });
  events.addEventListener("source", (event) => {
    const result = JSON.parse(event.data);
    const chip = $(`#sources [data-label="${CSS.escape(result.label)}"]`);
    chip.className = "chip " + (result.ok ? "ok" : "err");
    const note = result.error ? " (spremljeno)" : "";  // izvor nije odgovorio, prikazani su nedavni rezultati
    chip.textContent = result.ok ? `${result.label} ${result.offers.length}${note}` : `${result.label}: greška`;
    chip.title = result.error || `${result.ms} ms`;  // izvor koji radi može imati napomenu (npr. spremljeni rezultati)
    updateSourcesSummary();
    search.offers.push(...result.offers);
    renderResults();
  });
  events.addEventListener("done", () => {
    events.close();
    $("#summary").dataset.time = ((performance.now() - started) / 1000).toFixed(1);
    renderResults();
  });
  events.onerror = () => { events.close(); $("#summary").textContent = "Veza sa serverom prekinuta."; };
}

function updateSourcesSummary() {
  const count = (state) => document.querySelectorAll(`#sources .chip.${state}`).length;
  const [ok, failed, waiting] = [count("ok"), count("err"), count("wait")];
  $("#sources-sum").textContent = `Izvori: ${ok} radi` + (failed ? ` · ${failed} ne radi` : "")
    + (waiting ? ` · ${waiting} traži…` : "");
}

// ---------- prikaz rezultata ----------
// "Uobičajena cijena" = medijan ukupne cijene točnog modela (iz novih ponuda ako ih ima barem 2)
function referencePrice(offers) {
  const exact = offers.filter((offer) => offer.match >= EXACT_MIN);
  const newTotals = exact.filter((offer) => offer.condition === "new").map((offer) => offer.total);
  const pool = newTotals.length >= 2 ? newTotals : exact.map((offer) => offer.total);
  if (pool.length < 2) return null;
  const sorted = [...pool].sort((a, b) => a - b), middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

// poredak (izbornik "Ukupno ↑" itd.): ključ -> usporedba
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

function renderResults() {
  const reference = referencePrice(search.offers);
  for (const offer of search.offers) {
    offer.deal_pct = reference && offer.match >= EXACT_MIN ? 1 - offer.total / reference : 0;
    offer.is_deal = offer.deal_pct >= DEAL_THRESHOLD;
  }
  renderSourceOptions();
  const filters = readFilters();
  $("#f-reset").hidden = !isFiltering(filters);
  const visible = search.offers.filter((offer) => passesFilters(offer, filters))
    .sort(SORTS[$("#f-sort").value] || SORTS["total-asc"]);
  const exact = visible.filter((offer) => offer.match >= EXACT_MIN);
  const cheapestExact = [...exact].sort(SORTS["total-asc"])[0];

  const list = $("#results");
  list.innerHTML = "";
  list.append(...visible.slice(0, search.shown).map((offer) => offerCard(offer, offer === cheapestExact)));
  if (visible.length > search.shown) {
    const more = document.createElement("button");
    more.className = "ghost more";
    more.textContent = `Prikaži još (${visible.length - search.shown})`;
    more.onclick = () => { search.shown += RENDER_STEP; renderResults(); };
    list.append(more);
  }
  renderSummary(visible, exact, cheapestExact, reference);
}

function renderSummary(visible, exact, cheapestExact, reference) {
  const seconds = $("#summary").dataset.time;
  const sourceCount = new Set(visible.map((offer) => offer.source)).size;
  const deals = exact.filter((offer) => offer.is_deal).length;
  const hidden = search.offers.length - visible.length;
  const parts = [];
  if (visible.length) parts.push(`<b>${visible.length}</b> ponuda iz ${sourceCount} izvora (${exact.length} točan model)`);
  if (hidden) parts.push(`${hidden} skriveno filterima`);
  if (cheapestExact) parts.push(`najjeftiniji točan: <b>${eur(cheapestExact.total)}</b> (${escapeHtml(cheapestExact.source_name)})`);
  if (reference) parts.push(`uobičajena cijena ~${eur(reference)}`);
  if (deals) parts.push(`<span class="tag deal">${deals} apsurdno jeftinih</span>`);
  if (seconds) parts.push(`${seconds} s`);
  if (search.query) $("#summary").innerHTML = parts.join(" · ") || (seconds ? "Ništa nije pronađeno." : "Tražim…");
}

function offerCard(offer, isCheapestExact) {
  const card = $("#offer-tpl").content.firstElementChild.cloneNode(true);
  card.href = safeUrl(offer.url);
  card.classList.toggle("deal", offer.is_deal);
  card.classList.toggle("best", isCheapestExact);
  card.querySelector("img").src = offer.image || "";
  card.querySelector(".title").textContent = offer.title;

  // jedan red podataka: oznake koje nešto znače su istaknute (.tag), ostalo je običan tekst
  const meta = [];
  if (offer.is_deal) meta.push(`<span class="tag deal">−${Math.round(offer.deal_pct * 100)} %</span>`);
  if (isCheapestExact) meta.push(`<span class="tag good">najjeftiniji točan</span>`);
  else meta.push(offer.match >= EXACT_MIN ? `<span class="tag good">točan model</span>` : "varijanta");
  meta.push(offer.condition === "new" ? "novo" : "rabljeno");
  if (offer.is_auction) meta.push("aukcija");
  meta.push(...[offer.source_name, offer.location].filter(Boolean).map(escapeHtml));
  card.querySelector(".meta").innerHTML = meta.join(" · ");
  card.querySelector(".note").textContent = [offer.match_note, offer.shipping_note].filter(Boolean).join(" · ");

  card.querySelector(".total").textContent = eur(offer.total);
  const shipping = offer.shipping == null ? "dostava ?" : `${offer.shipping_exact ? "" : "~"}${eur(offer.shipping)} dostava`;
  const fees = offer.fees ? ` + ${eur(offer.fees)} naknada` : "";
  card.querySelector(".breakdown").innerHTML = `${eur(offer.price)}${fees} + `
    + `<span class="${offer.shipping_exact ? "" : "est"}" title="${escapeHtml(offer.shipping_note)}">${shipping}</span>`;
  return card;
}

// ---------- praćenje ----------
$("#watch-btn").addEventListener("click", () => {  // "Prati ovaj model": predloži prag 30 % ispod uobičajene cijene
  $("#w-q").value = search.query;
  const reference = referencePrice(search.offers);
  if (reference) $("#w-max").value = Math.round(reference * (1 - DEAL_THRESHOLD));
  document.querySelector('nav button[data-tab="watch"]').click();
});

$("#watch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
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
  const watches = await api.get("/api/watches");
  $("#watch-count").textContent = watches.length ? `(${watches.length})` : "";
  $("#watches").innerHTML = watches.length ? "" : `<p class="hint">Još ništa ne pratiš.</p>`;
  for (const watch of watches) $("#watches").append(watchRow(watch));
}

function watchRow(watch) {
  const rule = watch.max_total ? `javi ispod ${eur(watch.max_total)}` : "javi apsurdne cijene";
  const options = (watch.include_used ? "" : " · samo novo") + (watch.include_similar ? " · i varijante" : "");
  const best = watch.best_total
    ? ` · najniže viđeno <a href="${escapeHtml(safeUrl(watch.best_url))}" target="_blank">${eur(watch.best_total)}</a>` : "";
  const lastCheck = watch.last_market
    ? ` · provjereno ${new Date(watch.last_market * 1000).toLocaleTimeString("hr-HR")}` : " · čeka prvu provjeru";

  const row = document.createElement("div");
  row.className = "watch";
  row.innerHTML = `<div><b>${escapeHtml(watch.query)}</b><div class="hint">${rule}${options}${best}${lastCheck}</div></div>`;
  const remove = document.createElement("button");
  remove.className = "ghost";
  remove.textContent = "Ukloni";
  remove.onclick = async () => { await api.send(`/api/watches/${watch.id}`, "DELETE"); loadWatches(); };
  row.append(remove);
  return row;
}

// ---------- postavke ----------
async function loadSettings() {
  const settings = await api.get("/api/settings");
  $("#tg-dot").classList.toggle("on", settings.configured);
  $("#tg-token").placeholder = settings.tg_token_set ? `spremljen (${settings.tg_token_hint})` : "token bota";
  $("#tg-status").textContent = settings.configured ? `Povezano (chat ${settings.tg_chat}).` : "Nije povezano.";
  $("#ebay-status").textContent = settings.ebay_set
    ? `Ključ spremljen (${settings.ebay_hint}) - eBay koristi službeni API.` : "Nije upisano - koristi se scraping.";
}

$("#tg-save").addEventListener("click", async () => {
  const token = $("#tg-token").value.trim();
  if (!token) return;
  await api.send("/api/settings", "POST", { tg_token: token });
  $("#tg-token").value = "";
  loadSettings();
});
$("#tg-detect").addEventListener("click", async () => {
  const result = await api.send("/api/telegram/detect", "POST");
  $("#tg-status").textContent = result.chat ? `Povezano s: ${result.info}` : result.info;
  if (result.chat) loadSettings();
});
$("#tg-test").addEventListener("click", async () => {
  const result = await api.send("/api/telegram/test", "POST");
  $("#tg-status").textContent = result.ok ? "Poruka poslana." : `Nije uspjelo: ${result.error}`;
});

$("#ebay-save").addEventListener("click", async () => {
  const clientId = $("#ebay-id").value.trim(), clientSecret = $("#ebay-secret").value.trim();
  if (!clientId || !clientSecret) return;
  await api.send("/api/settings", "POST", { ebay_client_id: clientId, ebay_client_secret: clientSecret });
  $("#ebay-id").value = $("#ebay-secret").value = "";
  loadSettings();
});

async function loadMobileQr() {
  const response = await fetch("/api/mobile");
  if (!response.ok) return;  // na mobitelu se QR ne prikazuje (samo na računalu)
  const mobile = await response.json();
  $("#mobile-box").hidden = false;
  $("#mobile-qr").innerHTML = mobile.qr;  // SVG generira naš server (core/access.py), nije vanjski sadržaj
  $("#mobile-url").textContent = mobile.url;
}

async function loadSourceHealth() {
  const sources = await api.get("/api/health");
  $("#health").innerHTML = Object.values(sources).map((source) => {
    const status = source.ok === null ? "još nije korišten"
      : source.ok ? `<span class="good">radi</span> · ${source.found} ponuda · ${source.ms} ms`
      : `<span class="bad">ne radi</span> · ${escapeHtml(source.error)}`;
    const kind = source.kind === "market" ? "oglasnik" : "trgovina";
    return `<div class="health"><span>${source.label} <span class="hint">${kind}</span></span><span class="hint">${status}</span></div>`;
  }).join("");
}

// ---------- start ----------
const IS_PHONE = matchMedia("(max-width: 600px)").matches;  // ista širina kao u style.css
$("#finder").open = !IS_PHONE;  // na mobitelu je katalog zatvoren, da pretraga i rezultati budu odmah vidljivi
initCatalog({
  onPick(racket) {  // klik na verziju iz kataloga = pretraga točno te verzije (+ godina ako je nema u nazivu)
    const titleHasYear = racket.year && racket.title.includes(String(racket.year));
    const query = titleHasYear || !racket.year ? racket.title : `${racket.title} ${racket.year}`;
    $("#q").value = query;
    $("#finder").open = false;
    runSearch(query);
  },
});
loadSettings();
loadWatches();
const queryFromUrl = new URLSearchParams(location.search).get("q");
if (queryFromUrl) { $("#q").value = queryFromUrl; runSearch(queryFromUrl); }
