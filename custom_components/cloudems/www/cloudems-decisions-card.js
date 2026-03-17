/**
 * CloudEMS Decisions History Card
 * Toont de laatste 24u beslissingen per categorie met tijdlijn.
 * v4.6.104
 */

const CARD_VERSION = "4.6.171";

const CAT_CONFIG = {
  battery:           { icon: "🔋", label: "Batterij",     color: "#4caf50" },
  battery_bde:       { icon: "🔋", label: "Batterij BDE",  color: "#4caf50" },
  zonneplan_auto:    { icon: "⚡", label: "Zonneplan",       color: "#60a5fa" },
  zonneplan:         { icon: "⚡", label: "Zonneplan",       color: "#60a5fa" },
  boiler:            { icon: "🚿", label: "Boiler",        color: "#ff8040" },
  decision_boiler:   { icon: "🚿", label: "Boiler",        color: "#ff8040" },
  ev:                { icon: "🚗", label: "EV",            color: "#2196f3" },
  ev_solar_plan:     { icon: "🚗", label: "EV planning",   color: "#2196f3" },
  decision_ev_solar_plan: { icon: "🚗", label: "EV planning", color: "#2196f3" },
  shutter:           { icon: "🪟", label: "Rolluiken",     color: "#9c27b0" },
  decision_shutter:  { icon: "🪟", label: "Rolluiken",     color: "#9c27b0" },
  battery_slider:    { icon: "🎚️", label: "Sliders",      color: "#ffd600" },
  price_hour:        { icon: "€",  label: "Prijs",         color: "#00bcd4" },
};

const ALL_CATS = Object.keys(CAT_CONFIG);

// Categorie-groepen voor filter knoppen
const FILTER_GROUPS = [
  { id: "all",     label: "Alles",     cats: ALL_CATS },
  { id: "battery", label: "🔋 Batterij", cats: ["battery", "battery_bde", "zonneplan_auto", "zonneplan"] },
  { id: "boiler",  label: "🚿 Boiler",  cats: ["boiler", "decision_boiler"] },
  { id: "ev",      label: "🚗 EV",      cats: ["ev", "ev_solar_plan", "decision_ev_solar_plan"] },
  { id: "shutter", label: "🪟 Rolluiken", cats: ["shutter", "decision_shutter"] },
];

const S = `
  :host { display: block; }
  .card { background: rgb(28,28,28); border-radius: 16px; border: 1px solid rgba(255,255,255,0.07);
          color: #fff; font-family: 'Inter', sans-serif; overflow: hidden; }
  .hdr { display: flex; align-items: center; justify-content: space-between;
         padding: 14px 16px 10px; border-bottom: 1px solid rgba(255,255,255,0.07); }
  .hdr-title { font-size: 14px; font-weight: 700; color: #fff; }
  .hdr-count  { font-size: 11px; color: rgba(255,255,255,0.4); }
  .filters { display: flex; gap: 6px; padding: 10px 12px 6px; flex-wrap: wrap; }
  .filter-btn { padding: 4px 10px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.15);
                background: transparent; color: rgba(255,255,255,0.6); font-size: 11px;
                cursor: pointer; transition: all 0.15s; }
  .filter-btn.active { background: rgba(255,255,255,0.12); color: #fff;
                       border-color: rgba(255,255,255,0.3); }
  .timeline { padding: 4px 0 8px; max-height: 600px; overflow-y: auto; }
  .entry { display: flex; gap: 10px; padding: 8px 14px; border-bottom: 1px solid rgba(255,255,255,0.04);
           transition: background 0.1s; }
  .entry:hover { background: rgba(255,255,255,0.03); }
  .entry-icon { font-size: 16px; width: 22px; text-align: center; padding-top: 1px; flex-shrink: 0; }
  .entry-body { flex: 1; min-width: 0; }
  .entry-header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .entry-cat  { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.7; }
  .entry-time { font-size: 10px; color: rgba(255,255,255,0.35); flex-shrink: 0; }
  .entry-msg  { font-size: 12px; color: rgba(255,255,255,0.85); margin-top: 2px;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .entry-ctx  { font-size: 10px; color: rgba(255,255,255,0.35); margin-top: 2px; }
  .entry.expanded .entry-msg { white-space: normal; overflow: visible; text-overflow: unset; }
  .empty { padding: 32px 16px; text-align: center; color: rgba(255,255,255,0.3); font-size: 13px; }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.15);
             border-top-color: #fff; border-radius: 50%; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
`;

class CloudEMSDecisionsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass       = null;
    this._cfg        = {};
    this._prevState  = "";
    this._activeFilter = "all";
    this._expanded   = new Set();
    this.shadowRoot.innerHTML = `<style>${S}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states["sensor.cloudems_decisions_history"];
    const sig = `${st?.last_updated}|${st?.state}`;
    if (sig !== this._prevState) {
      this._prevState = sig;
      this._render();
    }
  }

  setConfig(cfg) {
    this._cfg = cfg;
    this._render();
  }

  _render() {
    const sh = this.shadowRoot;
    if (!this._hass) return;

    const st = this._hass.states["sensor.cloudems_decisions_history"];
    if (!st) {
      sh.innerHTML = `<style>${S}</style><div class="card"><div class="empty">⏳ sensor.cloudems_decisions_history niet gevonden</div></div>`;
      return;
    }

    const all  = st.attributes?.decisions ?? [];
    const total = st.attributes?.total_24h ?? 0;

    // Filter op actieve categorie
    const groupCats = FILTER_GROUPS.find(g => g.id === this._activeFilter)?.cats ?? ALL_CATS;
    const filtered = all.filter(e => groupCats.includes(e.cat));

    const card = sh.querySelector(".card") || sh.appendChild(Object.assign(document.createElement("div"), {className: "card"}));
    card.innerHTML = `
      <div class="hdr">
        <span class="hdr-title">📋 Beslissingen (24u)</span>
        <span class="hdr-count">${total} totaal</span>
      </div>
      <div class="filters">
        ${FILTER_GROUPS.map(g => `
          <button class="filter-btn ${this._activeFilter === g.id ? 'active' : ''}"
                  data-filter="${g.id}">${g.label}</button>
        `).join("")}
      </div>
      <div class="timeline">
        ${filtered.length === 0
          ? `<div class="empty">Geen beslissingen in deze categorie</div>`
          : filtered.map((e, i) => this._renderEntry(e, i)).join("")
        }
      </div>`;

    // Filter button events
    card.querySelectorAll(".filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        this._activeFilter = btn.dataset.filter;
        this._render();
      });
    });

    // Expand/collapse on entry click
    card.querySelectorAll(".entry").forEach(el => {
      el.addEventListener("click", () => {
        const i = el.dataset.idx;
        if (this._expanded.has(i)) this._expanded.delete(i);
        else this._expanded.add(i);
        el.classList.toggle("expanded");
        el.querySelector(".entry-msg").style.whiteSpace =
          this._expanded.has(i) ? "normal" : "nowrap";
      });
    });
  }

  _renderEntry(e, i) {
    const cfg   = CAT_CONFIG[e.cat] || { icon: "📌", label: e.cat, color: "#888" };
    const time  = this._formatTime(e.iso || e.ts);
    const ctx   = this._formatCtx(e);
    const expanded = this._expanded.has(String(i));
    return `
      <div class="entry ${expanded ? 'expanded' : ''}" data-idx="${i}">
        <div class="entry-icon">${cfg.icon}</div>
        <div class="entry-body">
          <div class="entry-header">
            <span class="entry-cat" style="color:${cfg.color}">${cfg.label}</span>
            <span class="entry-time">${time}</span>
          </div>
          <div class="entry-msg" style="white-space:${expanded ? 'normal' : 'nowrap'}">${this._esc(e.message || e.reason || "")}</div>
          ${ctx ? `<div class="entry-ctx">${ctx}</div>` : ""}
        </div>
      </div>`;
  }

  _formatTime(iso) {
    if (!iso) return "";
    try {
      const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
      const now = new Date();
      const diff = Math.round((now - d) / 1000);
      if (diff < 60)  return `${diff}s geleden`;
      if (diff < 3600) return `${Math.round(diff/60)}m geleden`;
      const h = d.getHours().toString().padStart(2,"0");
      const m = d.getMinutes().toString().padStart(2,"0");
      return `${h}:${m}`;
    } catch { return ""; }
  }

  _formatCtx(e) {
    const parts = [];
    if (e.solar_w != null)  parts.push(`☀️ ${e.solar_w}W`);
    if (e.grid_w  != null)  parts.push(`⚡ ${e.grid_w > 0 ? "+":""}${e.grid_w}W`);
    if (e.soc_pct != null)  parts.push(`🔋 ${e.soc_pct}%`);
    if (e.price_eur != null) parts.push(`€ ${(e.price_eur * 100).toFixed(1)}ct`);
    return parts.join(" · ");
  }

  _esc(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  getCardSize() { return 6; }
  static getConfigElement() { return document.createElement("div"); }
  static getStubConfig() { return {}; }
}

customElements.define("cloudems-decisions-card", CloudEMSDecisionsCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "cloudems-decisions-card",
  name: "CloudEMS Beslissingen",
  description: "Tijdlijn van alle CloudEMS beslissingen (24u)",
});
