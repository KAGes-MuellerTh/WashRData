// WashRData panel: overview of all appliances, their cycles and how well
// programs are recognised. Plain web component, no build step. Texts come
// from the integration's translations (selector "panel").

const TEXT_PREFIX = "component.washrdata.selector.panel.options.";
const AUTO_LABEL_CONFIDENCE = 0.6;
const REFRESH_MS = 5000;
const NEW_PROGRAM = "__new__";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class WashRDataPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._devices = [];
    this._texts = {};
    this._selected = null; // entry id
    this._open = null; // cycle id with details shown
    this._compare = {}; // cycle id -> program to compare with
    this._loaded = false;
    this._pending = null;
    this._last = 0;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._init();
    if (this._menu) {
      this._menu.hass = hass;
      this._menu.narrow = this.narrow;
    }
  }

  get hass() {
    return this._hass;
  }

  disconnectedCallback() {
    this._unsub?.then((unsub) => unsub()).catch(() => {});
    this._unsub = null;
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  async _init() {
    try {
      const res = await this._hass.callWS({
        type: "frontend/get_translations",
        language: this._hass.language,
        category: "selector",
        integration: ["washrdata"],
      });
      this._texts = res.resources || {};
    } catch (err) {
      this._texts = {};
    }
    await this._load();
    this._subscribe();
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(() => this._scheduleLoad(), { type: "washrdata/subscribe" });
  }

  // Power reports arrive every few seconds while a cycle runs; refresh at most every REFRESH_MS.
  _scheduleLoad() {
    if (this._pending) return;
    const wait = Math.max(0, this._last + REFRESH_MS - Date.now());
    this._pending = setTimeout(() => {
      this._pending = null;
      this._load();
    }, wait);
  }

  async _load() {
    this._last = Date.now();
    try {
      const res = await this._hass.callWS({ type: "washrdata/overview" });
      this._devices = res.devices;
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._loaded = true;
    this._render();
  }

  t(key, vars = {}) {
    let text = this._texts[TEXT_PREFIX + key] ?? key;
    for (const [k, v] of Object.entries(vars)) text = text.replace(`{${k}}`, v);
    return text;
  }

  // -- formatting -------------------------------------------------------

  _when(ts) {
    return new Date(ts * 1000).toLocaleString(this._hass.locale?.language || this._hass.language, {
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _num(value, digits) {
    return Number(value).toLocaleString(this._hass.language, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  _duration(seconds) {
    const minutes = Math.round(seconds / 60);
    return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")} h`;
  }

  _percent(value) {
    return value == null ? "–" : `${Math.round(value * 100)} %`;
  }

  // -- charts -----------------------------------------------------------

  _sparkline(curve) {
    if (!curve.length) return "";
    const peak = Math.max(...curve, 1);
    const w = 120;
    const h = 28;
    const step = w / Math.max(1, curve.length - 1);
    const pts = curve.map((v, i) => `${(i * step).toFixed(1)},${(h - (Math.sqrt(v / peak) * (h - 2)) - 1).toFixed(1)}`);
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <polyline points="${pts.join(" ")}" /></svg>`;
  }

  // Curves in watts per minute. The first is drawn on top in the accent colour.
  // Lines stretch with the card; labels are HTML so their size stays fixed.
  _chart(series, { live = false } = {}) {
    const all = series.flatMap((s) => s.curve);
    if (!all.length) return `<div class="empty">${esc(this.t("no_curve"))}</div>`;
    const peak = Math.max(...all, 10);
    const minutes = Math.max(...series.map((s) => s.curve.length), 10);
    const x = (i) => (i / minutes) * 1000;
    const y = (v) => (1 - v / peak) * 1000;
    const path = (curve) => curve.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");

    let grid = "";
    let labels = "";
    for (const v of niceTicks(peak, 4)) {
      grid += `<line class="grid" x1="0" x2="1000" y1="${y(v)}" y2="${y(v)}" />`;
      const text = v >= 1000 ? `${this._num(v / 1000, 1)} kW` : `${v} W`;
      labels += `<span class="ylabel" style="top:${y(v) / 10}%">${text}</span>`;
    }
    const xStep = minutes > 150 ? 60 : 30;
    for (let m = 0; m <= minutes; m += xStep) {
      labels += `<span class="xlabel" style="left:${x(m) / 10}%">${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}</span>`;
    }
    const lines = [...series]
      .reverse()
      .map((s) => `<path class="${s.main ? "main" : "ref"}${live && s.main ? " live" : ""}" d="${path(s.curve)}" />`)
      .join("");
    return `<div class="chart"><div class="plot">
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img">${grid}${lines}</svg>${labels}
    </div></div>`;
  }

  // -- rendering --------------------------------------------------------

  _device() {
    return this._devices.find((d) => d.entry_id === this._selected) || this._devices[0];
  }

  _render() {
    const root = this.shadowRoot;
    // Do not pull an open dropdown away from under the user; render when it closes.
    if (root.activeElement?.tagName === "SELECT") {
      if (!this._deferred) {
        this._deferred = true;
        root.activeElement.addEventListener("blur", () => this._render(), { once: true });
      }
      return;
    }
    this._deferred = false;
    const scroll = root.querySelector(".content")?.scrollTop ?? 0;
    root.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar"><span class="menu"></span><h1>WashRData</h1></div>
      <div class="content">${this._body()}</div>`;
    this._menu = document.createElement("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this.narrow;
    root.querySelector(".menu").appendChild(this._menu);
    root.querySelector(".content").scrollTop = scroll;
    this._bind();
  }

  _body() {
    if (!this._loaded) return `<div class="empty">…</div>`;
    if (this._error) return `<div class="card error">${esc(this._error)}</div>`;
    if (!this._devices.length) return `<div class="card empty">${esc(this.t("no_devices"))}</div>`;
    const device = this._device();
    this._selected = device.entry_id;
    const tabs =
      this._devices.length > 1
        ? `<div class="tabs">${this._devices
            .map(
              (d) =>
                `<button class="tab${d.entry_id === device.entry_id ? " active" : ""}" data-device="${esc(d.entry_id)}">${esc(d.title)}</button>`
            )
            .join("")}</div>`
        : "";
    return `${tabs}<div class="grid">
        ${this._now(device)}
        ${this._accuracy(device)}
      </div>
      ${this._cycles(device)}
      ${this._programs(device)}`;
  }

  _now(device) {
    const cycle = device.current;
    const match = device.match;
    let body;
    if (!cycle) {
      body = `<div class="state">${esc(this.t(`state_${device.state}`))}</div>`;
    } else {
      const program = cycle.program || match?.program;
      const rows = [
        [this.t("program"), program ? esc(program) + (match?.manual ? ` <span class="badge">${esc(this.t("manual"))}</span>` : "") : esc(this.t("unknown"))],
        [this.t("recognition"), match ? `${esc(match.recognised ?? this.t("unknown"))} · ${this._percent(match.recognition_confidence)}` : esc(this.t("too_early"))],
        [this.t("remaining"), match?.remaining_s != null ? this._duration(match.remaining_s) : "–"],
        [this.t("running_for"), `${this._duration(cycle.duration_s)} · ${this._num(cycle.energy_kwh, 2)} kWh`],
      ];
      const bar = match ? Math.round(match.recognition_confidence * 100) : 0;
      const refs = this._refs(device, program || match?.recognised, cycle.id);
      body = `<div class="state">${esc(this.t(`state_${device.state}`))}</div>
        <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>
        <div class="meter" title="${bar} %"><div style="width:${bar}%"></div></div>
        ${this._chart([{ curve: cycle.curve, main: true }, ...refs], { live: true })}
        ${refs.length ? `<div class="legend"><span class="key main"></span>${esc(this.t("this_cycle"))}<span class="key ref"></span>${esc(this.t("references_of", { program: program || match?.recognised }))}</div>` : ""}`;
    }
    return `<section class="card"><h2>${esc(this.t("now"))}</h2>${body}</section>`;
  }

  _accuracy(device) {
    const acc = device.accuracy;
    const rate = acc.cycles ? acc.hits / acc.cycles : null;
    const rows = device.programs
      .map((p) => {
        const a = acc.programs[p] || { cycles: 0, hits: 0 };
        const refs = device.cycles.filter((c) => c.reference && c.program === p).length;
        return `<tr><td>${esc(p)}</td><td>${a.cycles}</td><td>${a.hits}</td><td>${a.cycles ? this._percent(a.hits / a.cycles) : "–"}</td><td>${refs}</td></tr>`;
      })
      .join("");
    return `<section class="card"><h2>${esc(this.t("accuracy"))}</h2>
      <div class="big">${rate == null ? "–" : `${Math.round(rate * 100)} %`}</div>
      <div class="muted">${esc(acc.cycles ? this.t("hits_of", { hits: acc.hits, cycles: acc.cycles }) : this.t("no_rated"))}</div>
      ${rows ? `<table><thead><tr><th>${esc(this.t("program"))}</th><th>${esc(this.t("rated"))}</th><th>${esc(this.t("hits"))}</th><th>${esc(this.t("rate"))}</th><th>${esc(this.t("references"))}</th></tr></thead><tbody>${rows}</tbody></table>` : ""}
      <p class="muted small">${esc(this.t("accuracy_help"))}</p>
    </section>`;
  }

  _refs(device, program, exclude) {
    if (!program) return [];
    return device.cycles.filter((c) => c.reference && c.program === program && c.id !== exclude).map((c) => ({ curve: c.curve }));
  }

  _verdict(c) {
    if (c.confidence == null) return `<span class="muted">${esc(this.t("not_rated"))}</span>`;
    const sure = c.recognised && c.confidence >= AUTO_LABEL_CONFIDENCE;
    const said = c.recognised ? `${esc(c.recognised)} · ${this._percent(c.confidence)}` : esc(this.t("unknown"));
    const rated = c.program && c.known_programs.includes(c.program) && !c.interrupted;
    const mark = !rated ? "" : sure && c.recognised === c.program ? `<span class="hit">✓</span>` : `<span class="miss">✗</span>`;
    return `${mark}<span class="${sure ? "" : "muted"}">${said}</span>`;
  }

  _select(device, c) {
    const options = [
      `<option value=""${c.program ? "" : " selected"}>${esc(this.t("none"))}</option>`,
      ...device.programs.map((p) => `<option value="${esc(p)}"${p === c.program ? " selected" : ""}>${esc(p)}</option>`),
      `<option value="${NEW_PROGRAM}">${esc(this.t("new_program"))}</option>`,
    ];
    return `<select data-label="${esc(c.id)}" aria-label="${esc(this.t("program"))}">${options.join("")}</select>`;
  }

  _cycles(device) {
    if (!device.cycles.length) return `<section class="card"><h2>${esc(this.t("cycles"))}</h2><div class="empty">${esc(this.t("no_cycles"))}</div></section>`;
    const rows = device.cycles
      .map((c) => {
        const open = this._open === c.id;
        const source = c.program_source ? `<span class="badge">${esc(this.t(c.program_source))}</span>` : "";
        return `<div class="cycle${open ? " open" : ""}">
          <button class="row" data-open="${esc(c.id)}" aria-expanded="${open}">
            <span class="when">${esc(this._when(c.start))}</span>
            <span class="facts">${this._duration(c.duration_s)} · ${this._num(c.energy_kwh, 2)} kWh${c.interrupted ? ` · ${esc(this.t("interrupted"))}` : ""}${c.reference ? ` · ${esc(this.t("reference"))}` : ""}</span>
            ${this._sparkline(c.curve)}
          </button>
          <div class="labels">
            <label>${esc(this.t("program"))} ${source}${this._select(device, c)}</label>
            <div class="verdict"><span class="muted small">${esc(this.t("recognition"))}</span> ${this._verdict(c)}</div>
          </div>
          ${open ? this._detail(device, c) : ""}
        </div>`;
      })
      .join("");
    return `<section class="card"><h2>${esc(this.t("cycles"))}</h2><div class="cycles">${rows}</div></section>`;
  }

  _detail(device, c) {
    const fallback = c.program || c.recognised || device.programs[0] || "";
    const compare = this._compare[c.id] ?? fallback;
    const refs = this._refs(device, compare, c.id);
    const options = [`<option value="">${esc(this.t("nothing"))}</option>`, ...device.programs.map((p) => `<option value="${esc(p)}"${p === compare ? " selected" : ""}>${esc(p)}</option>`)];
    return `<div class="detail">
      <label class="compare">${esc(this.t("compare_with"))} <select data-compare="${esc(c.id)}">${options.join("")}</select></label>
      ${this._chart([{ curve: c.curve, main: true }, ...refs])}
      <div class="legend"><span class="key main"></span>${esc(this.t("this_cycle"))}${compare ? `<span class="key ref"></span>${esc(refs.length ? this.t("references_of", { program: compare }) : this.t("no_references", { program: compare }))}` : ""}</div>
      <div class="muted small">${esc(this.t("peak"))} ${c.peak_w} W</div>
    </div>`;
  }

  _programs(device) {
    if (!device.programs.length) return "";
    const rows = device.programs
      .map((p) => {
        const count = device.cycles.filter((c) => c.program === p).length;
        return `<li><span>${esc(p)} <span class="muted">· ${esc(this.t("cycle_count", { count }))}</span></span>
          <span><button class="text" data-rename="${esc(p)}">${esc(this.t("rename"))}</button><button class="text danger" data-delete="${esc(p)}">${esc(this.t("delete"))}</button></span></li>`;
      })
      .join("");
    return `<section class="card"><h2>${esc(this.t("programs"))}</h2><ul class="programs">${rows}</ul></section>`;
  }

  // -- actions ----------------------------------------------------------

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-device]").forEach((el) =>
      el.addEventListener("click", () => {
        this._selected = el.dataset.device;
        this._open = null;
        this._render();
      })
    );
    root.querySelectorAll("[data-open]").forEach((el) =>
      el.addEventListener("click", () => {
        this._open = this._open === el.dataset.open ? null : el.dataset.open;
        this._render();
      })
    );
    root.querySelectorAll("[data-compare]").forEach((el) =>
      el.addEventListener("change", () => {
        this._compare[el.dataset.compare] = el.value;
        this._render();
      })
    );
    root.querySelectorAll("[data-label]").forEach((el) =>
      el.addEventListener("change", () => this._label(el.dataset.label, el.value))
    );
    root.querySelectorAll("[data-rename]").forEach((el) =>
      el.addEventListener("click", () => this._rename(el.dataset.rename))
    );
    root.querySelectorAll("[data-delete]").forEach((el) =>
      el.addEventListener("click", () => this._delete(el.dataset.delete))
    );
  }

  async _call(msg) {
    try {
      await this._hass.callWS({ entry_id: this._selected, ...msg });
    } catch (err) {
      alert(err.message || String(err));
    }
    await this._load();
  }

  async _label(cycleId, value) {
    let program = value || null;
    if (value === NEW_PROGRAM) {
      program = (prompt(this.t("new_program_prompt")) || "").trim();
      if (!program) return this._render();
    }
    await this._call({ type: "washrdata/label", cycle_id: cycleId, program });
  }

  async _rename(program) {
    const name = (prompt(this.t("rename_prompt", { program }), program) || "").trim();
    if (name && name !== program) await this._call({ type: "washrdata/rename_program", program, new_name: name });
  }

  async _delete(program) {
    if (confirm(this.t("delete_confirm", { program }))) await this._call({ type: "washrdata/delete_program", program });
  }
}

function niceTicks(max, count) {
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) || raw;
  const ticks = [];
  for (let v = 0; v <= max + 1e-9; v += step) ticks.push(Math.round(v));
  return ticks;
}

const STYLE = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .toolbar { display: flex; align-items: center; gap: 8px; height: var(--header-height, 56px); padding: 0 12px;
    background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff);
    border-bottom: var(--app-header-border-bottom, none); box-sizing: border-box; }
  .toolbar h1 { font-size: 20px; font-weight: 400; margin: 0; }
  .content { padding: 16px; max-width: 1100px; margin: 0 auto; box-sizing: border-box; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
  .card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--divider-color); padding: 16px; margin-bottom: 16px; box-shadow: var(--ha-card-box-shadow, none); }
  .grid .card { margin-bottom: 0; }
  .grid { margin-bottom: 16px; }
  h2 { font-size: 16px; font-weight: 500; margin: 0 0 12px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  button { font: inherit; color: inherit; }
  .tab { border: 1px solid var(--divider-color); background: var(--card-background-color); border-radius: 18px; padding: 6px 14px; cursor: pointer; }
  .tab.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .state { font-size: 22px; margin-bottom: 8px; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0 0 12px; }
  dt { color: var(--secondary-text-color); }
  dd { margin: 0; }
  .meter { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-bottom: 12px; }
  .meter div { height: 100%; background: var(--primary-color); }
  .big { font-size: 40px; font-weight: 300; }
  .muted { color: var(--secondary-text-color); }
  .small { font-size: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px; }
  th, td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--divider-color); }
  th:first-child, td:first-child { text-align: left; }
  th { font-weight: 500; color: var(--secondary-text-color); }
  .chart { padding: 8px 4px 22px 52px; }
  .plot { position: relative; height: 180px; }
  .detail .plot { height: 240px; }
  .plot svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
  .plot line, .plot path { vector-effect: non-scaling-stroke; }
  .plot .grid { stroke: var(--divider-color); stroke-width: 1; }
  .plot path { fill: none; stroke-linejoin: round; }
  .plot .main { stroke: var(--primary-color); stroke-width: 2; }
  .plot .ref { stroke: var(--secondary-text-color); stroke-width: 1.2; opacity: 0.45; }
  .ylabel, .xlabel { position: absolute; font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; }
  .ylabel { right: calc(100% + 6px); transform: translateY(-50%); }
  .xlabel { top: calc(100% + 4px); transform: translateX(-50%); }
  .legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .key { display: inline-block; width: 16px; height: 3px; border-radius: 2px; }
  .key.main { background: var(--primary-color); }
  .key.ref { background: var(--secondary-text-color); opacity: 0.6; }
  .cycles { display: flex; flex-direction: column; }
  .cycle { border-bottom: 1px solid var(--divider-color); padding: 8px 0; }
  .cycle:last-child { border-bottom: none; }
  .row { display: grid; grid-template-columns: minmax(110px, max-content) 1fr 120px; gap: 12px; align-items: center;
    width: 100%; background: none; border: none; text-align: left; padding: 4px 0; cursor: pointer; }
  .when { font-weight: 500; }
  .spark { width: 120px; height: 28px; }
  .spark polyline { fill: none; stroke: var(--primary-color); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
  .labels { display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: center; margin-top: 4px; }
  .labels label { display: flex; align-items: center; gap: 8px; }
  select { font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px; padding: 4px 6px; max-width: 220px; }
  .verdict { display: flex; gap: 6px; align-items: center; }
  .badge { font-size: 11px; padding: 1px 6px; border-radius: 8px; background: var(--secondary-background-color, #eee); color: var(--secondary-text-color); }
  .hit { color: var(--success-color, #2e7d32); font-weight: 700; }
  .miss { color: var(--error-color, #c62828); font-weight: 700; }
  .detail { margin-top: 12px; }
  .compare { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .programs { list-style: none; margin: 0; padding: 0; }
  .programs li { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--divider-color); }
  .programs li:last-child { border-bottom: none; }
  .programs li > span:last-child { white-space: nowrap; }
  .text { background: none; border: none; color: var(--primary-color); cursor: pointer; padding: 4px 8px; }
  .text.danger { color: var(--error-color, #c62828); }
  .empty { color: var(--secondary-text-color); padding: 8px 0; }
  .error { color: var(--error-color, #c62828); }
  @media (max-width: 600px) {
    .content { padding: 8px; }
    .grid { grid-template-columns: 1fr; }
    .row { grid-template-columns: 1fr 90px; }
    .row .facts { grid-column: 1; grid-row: 2; font-size: 13px; color: var(--secondary-text-color); }
    .row .spark { grid-column: 2; grid-row: 1 / span 2; width: 90px; }
  }
`;

customElements.define("washrdata-panel", WashRDataPanel);
