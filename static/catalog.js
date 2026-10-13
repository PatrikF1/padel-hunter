// Odabir točne verzije reketa iz kataloga: kaskadni filteri (brend, model, godina, specifikacije, ocjene).
// Novi filter = jedan red u SPEC_FILTERS (key mora postojati u Racket iz core/catalog.py) ili RATING_FILTERS.
// Koristi pomoćne funkcije iz app.js (api, eur, escapeHtml, safeUrl) - učitava se prije njega, poziva se iz njega.
"use strict";

const TRANSLATIONS = {  // vrijednosti iz kataloga (engleski) -> hrvatski
  Round: "Okrugli", Diamond: "Dijamant", Teardrop: "Suza", Hybrid: "Hibridni",
  Low: "Nizak", Medium: "Srednji", High: "Visok",
  Beginners: "Početnik", Advanced: "Napredni", Professional: "Profesionalac",
  Control: "Kontrola", Power: "Snaga", Balance: "Balans",
  Man: "Muški", Woman: "Ženski", Kids: "Dječji",
};
const translate = (value) => TRANSLATIONS[value] || value;

const SPEC_FILTERS = [
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
const RATING_FILTERS = [  // ocjene iz Padelfula (0-10), filter "barem X"
  { key: "power", label: "Snaga" },
  { key: "control", label: "Kontrola" },
  { key: "sweetSpot", label: "Sweet spot" },
  { key: "maneuverability", label: "Upravljivost" },
  { key: "rebound", label: "Odskok" },
];
const RATING_STEPS = [7, 8, 8.5, 9, 9.5];
const SPECS_ON_CARD = ["shape", "balance", "level", "play", "face", "core", "gender"];
const MAX_CARDS = 60;

// "High, Medium" -> ["High", "Medium"]; godina je broj
const valuesOf = (racket, key) => racket[key] == null || racket[key] === "" ? [] : String(racket[key]).split(/,\s*/);

function initCatalog({ onPick }) {
  const finder = document.querySelector("#finder");
  const grid = finder.querySelector(".filters-grid");
  const versionList = finder.querySelector("#versions");
  const nameFilter = finder.querySelector("#v-text");
  const selectedSpec = {};  // npr. { brand: "Adidas", family: "METALBONE" }
  const minRating = {};     // npr. { power: 9 }
  let rackets = [];

  for (const filter of SPEC_FILTERS) {
    const select = labeledSelect(filter.label);
    select.dataset.key = filter.key;
    select.addEventListener("change", () => {
      selectedSpec[filter.key] = select.value;
      if (filter.key === "brand") selectedSpec.family = "";  // promjena brenda poništava model
      refresh();
    });
  }
  // ocjene su u posebnom podizborniku da filteri ne zauzmu cijeli ekran na mobitelu
  const ratingsBox = document.createElement("details");
  ratingsBox.className = "ratings";
  ratingsBox.innerHTML = `<summary>Ocjene (snaga, kontrola, sweet spot…)</summary><div class="filters-grid"></div>`;
  grid.after(ratingsBox);
  const ratingsGrid = ratingsBox.querySelector(".filters-grid");
  for (const filter of RATING_FILTERS) {
    const select = labeledSelect(filter.label, ratingsGrid);
    select.dataset.rating = filter.key;
    select.innerHTML = `<option value="">sve</option>` + RATING_STEPS.map((step) => `<option value="${step}">≥ ${step}</option>`).join("");
    select.addEventListener("change", () => { minRating[filter.key] = parseFloat(select.value) || 0; refresh(); });
  }
  nameFilter.addEventListener("input", refresh);
  finder.querySelector("#v-reset").addEventListener("click", () => {
    for (const key in selectedSpec) selectedSpec[key] = "";
    for (const key in minRating) minRating[key] = 0;
    finder.querySelectorAll("[data-rating]").forEach((select) => { select.value = ""; });
    nameFilter.value = "";
    refresh();
  });

  function labeledSelect(label, container = grid) {
    const select = document.createElement("select");
    const wrapper = document.createElement("label");
    wrapper.append(label, select);
    container.append(wrapper);
    return select;
  }

  // ignoreKey: kod brojanja opcija jednog filtera, taj filter se ne primjenjuje (inače bi nudio samo sebe)
  function passesFilters(racket, ignoreKey = null) {
    const words = nameFilter.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (words.some((word) => !racket.title.toLowerCase().includes(word))) return false;
    if (Object.entries(minRating).some(([key, min]) => min && !((racket.ratings || {})[key] >= min))) return false;
    return SPEC_FILTERS.every((filter) => filter.key === ignoreKey || !selectedSpec[filter.key]
      || valuesOf(racket, filter.key).includes(selectedSpec[filter.key]));
  }

  // svaki filter nudi samo vrijednosti koje postoje uz ostale odabrane filtere (kaskadno)
  function refresh() {
    for (const filter of SPEC_FILTERS) {
      const counts = {};
      for (const racket of rackets) {
        if (!passesFilters(racket, filter.key)) continue;
        for (const value of valuesOf(racket, filter.key)) counts[value] = (counts[value] || 0) + 1;
      }
      const values = Object.keys(counts).sort(filter.sort || ((a, b) => a.localeCompare(b)));
      const select = grid.querySelector(`[data-key="${filter.key}"]`);
      select.innerHTML = `<option value="">sve</option>`
        + values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(translate(value))} (${counts[value]})</option>`).join("");
      select.value = selectedSpec[filter.key] && counts[selectedSpec[filter.key]] ? selectedSpec[filter.key] : "";
      selectedSpec[filter.key] = select.value;
    }
    renderVersions(rackets.filter((racket) => passesFilters(racket)));
  }

  function renderVersions(found) {
    found.sort((a, b) => (b.year || 0) - (a.year || 0) || a.title.localeCompare(b.title));
    versionList.innerHTML = "";
    finder.querySelector("#v-count").textContent = `${found.length} verzija`;
    for (const racket of found.slice(0, MAX_CARDS)) versionList.append(versionCard(racket));
    if (found.length > MAX_CARDS) {
      versionList.insertAdjacentHTML("beforeend", `<p class="hint">+${found.length - MAX_CARDS} još, suzi filtere.</p>`);
    }
  }

  function versionCard(racket) {
    const specs = [racket.year, ...SPECS_ON_CARD.map((key) => valuesOf(racket, key).map(translate).join(", "))]
      .filter(Boolean).map((spec) => `<span>${escapeHtml(spec)}</span>`).join("");
    const ratings = RATING_FILTERS.filter((filter) => (racket.ratings || {})[filter.key] != null)
      .map((filter) => `${filter.label} ${racket.ratings[filter.key]}`).join(" · ");
    const price = racket.price
      ? `od ${eur(racket.price)}` + (racket.list_price > racket.price ? ` <s>${eur(racket.list_price)}</s>` : "") : "";

    const card = document.createElement("button");
    card.type = "button";
    card.className = "version";
    card.innerHTML = `<img loading="lazy" src="${escapeHtml(safeUrl(racket.image))}" alt="">
      <div><div class="title">${escapeHtml(racket.title)}</div><div class="specs">${specs}</div>
      <div class="hint">${escapeHtml(ratings)}</div><div class="hint">${price}</div></div>`;
    card.addEventListener("click", () => onPick(racket));
    return card;
  }

  async function loadCatalog() {
    const data = await api.get("/api/catalog");
    rackets = data.rackets;
    finder.querySelector("summary .hint").textContent = rackets.length
      ? `${rackets.length} reketa · osvježeno ${new Date(data.updated * 1000).toLocaleDateString("hr-HR")}`
      : "katalog se učitava…";
    document.querySelector("#titles").innerHTML = rackets.map((racket) => `<option value="${escapeHtml(racket.title)}">`).join("");
    if (!rackets.length) setTimeout(loadCatalog, 5000);  // prvo pokretanje: katalog se još skida
    refresh();
  }

  loadCatalog();
}
