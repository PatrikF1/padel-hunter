// Odabir točne verzije reketa iz kataloga: kaskadni filteri (brend, model, godina, specifikacije).
// Novi filter = jedan red u FILTERS (key mora postojati u Racket iz core/catalog.py).
"use strict";

const T = {  // prijevodi vrijednosti iz kataloga
  Round: "Okrugli", Diamond: "Dijamant", Teardrop: "Suza", Hybrid: "Hibridni",
  Low: "Nizak", Medium: "Srednji", High: "Visok",
  Beginners: "Početnik", Advanced: "Napredni", Professional: "Profesionalac",
  Control: "Kontrola", Power: "Snaga", Balance: "Balans",
  Man: "Muški", Woman: "Ženski", Kids: "Dječji",
};
const tr = (v) => T[v] || v;

const FILTERS = [
  { key: "brand", label: "Brend" },
  { key: "family", label: "Model" },
  { key: "year", label: "Godina", sort: (a, b) => b - a },
  { key: "shape", label: "Oblik" },
  { key: "balance", label: "Balans" },
  { key: "level", label: "Razina" },
  { key: "play", label: "Tip igre" },
  { key: "face", label: "Površina" },
  { key: "core", label: "Jezgra" },
  { key: "gender", label: "Spol" },
];
const MAX_CARDS = 60;

// "High, Medium" -> ["High", "Medium"]; godina je broj
const valuesOf = (r, key) => r[key] == null || r[key] === "" ? [] : String(r[key]).split(/,\s*/);

function initCatalog({ onPick }) {
  const box = document.querySelector("#finder");
  const grid = box.querySelector(".filters-grid");
  const list = box.querySelector("#versions");
  const text = box.querySelector("#v-text");
  const selected = {};  // key -> vrijednost
  let rackets = [];

  for (const f of FILTERS) {
    const sel = document.createElement("select");
    sel.dataset.key = f.key;
    sel.addEventListener("change", () => {
      selected[f.key] = sel.value;
      if (f.key === "brand") selected.family = "";  // promjena brenda poništava model
      update();
    });
    const wrap = document.createElement("label");
    wrap.append(f.label, sel);
    grid.append(wrap);
  }
  text.addEventListener("input", update);
  box.querySelector("#v-reset").addEventListener("click", () => {
    for (const k in selected) selected[k] = "";
    text.value = "";
    update();
  });

  function matches(r, except) {
    const words = text.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (words.some((w) => !r.title.toLowerCase().includes(w))) return false;
    return FILTERS.every((f) => f.key === except || !selected[f.key] || valuesOf(r, f.key).includes(selected[f.key]));
  }

  function update() {
    // svaki filter nudi samo vrijednosti koje postoje uz ostale odabrane filtere (kaskadno)
    for (const f of FILTERS) {
      const counts = {};
      for (const r of rackets) if (matches(r, f.key)) for (const v of valuesOf(r, f.key)) counts[v] = (counts[v] || 0) + 1;
      const values = Object.keys(counts).sort(f.sort || ((a, b) => a.localeCompare(b)));
      const sel = grid.querySelector(`[data-key="${f.key}"]`);
      sel.innerHTML = `<option value="">sve</option>` +
        values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(tr(v))} (${counts[v]})</option>`).join("");
      sel.value = selected[f.key] && counts[selected[f.key]] ? selected[f.key] : "";
      selected[f.key] = sel.value;
    }
    renderVersions(rackets.filter((r) => matches(r)));
  }

  function renderVersions(found) {
    const sorted = found.sort((a, b) => (b.year || 0) - (a.year || 0) || a.title.localeCompare(b.title));
    list.innerHTML = "";
    box.querySelector("#v-count").textContent = `${found.length} verzija`;
    for (const r of sorted.slice(0, MAX_CARDS)) list.append(versionCard(r));
    if (found.length > MAX_CARDS) {
      list.insertAdjacentHTML("beforeend", `<p class="hint">+${found.length - MAX_CARDS} još, suzi filtere.</p>`);
    }
  }

  function versionCard(r) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "version";
    const specs = [r.year, ...["shape", "balance", "level", "play", "face", "core", "gender"].map((k) => r[k] && tr(r[k]))]
      .filter(Boolean).map((s) => `<span class="spec">${escapeHtml(String(s).split(/,\s*/).map(tr).join(", "))}</span>`).join("");
    const price = r.price ? `od ${eur(r.price)}` + (r.list_price > r.price ? ` <s>${eur(r.list_price)}</s>` : "") : "";
    el.innerHTML = `<img loading="lazy" src="${escapeHtml(safeUrl(r.image))}" alt="">
      <div><div class="title">${escapeHtml(r.title)}</div><div class="specs">${specs}</div><div class="hint">${price}</div></div>`;
    el.addEventListener("click", () => onPick(r));
    return el;
  }

  async function load() {
    const data = await api.get("/api/catalog");
    rackets = data.rackets;
    box.querySelector("summary .hint").textContent = rackets.length
      ? `${rackets.length} reketa · osvježeno ${new Date(data.updated * 1000).toLocaleDateString("hr-HR")}`
      : "katalog se učitava…";
    document.querySelector("#titles").innerHTML = rackets.map((r) => `<option value="${escapeHtml(r.title)}">`).join("");
    if (!rackets.length) setTimeout(load, 5000);  // prvo pokretanje: katalog se još skida
    update();
  }

  load();
}
