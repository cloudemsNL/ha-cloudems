// CloudEMS EV Trip Planner Card v1.0.0
const CARD_EV_TRIP_VERSION = '5.4.8';
// Calendar-based EV charging recommendations

class CloudemsEvTripCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "🗓️ EV Ritplanning", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_ev_trip_planner"];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_ev_trip_planner"]?.attributes || {};
    const rec = attr.recommendation || {};
    const needed = rec.needed === true;
    const trip = rec.trip || {};
    const currentSoc = rec.current_soc_pct;
    const targetSoc = rec.target_soc_pct;
    const kwhToAdd = rec.kwh_to_add;
    const cheapestStart = rec.cheapest_window_start;
    const priceAtWindow = rec.price_at_window;
    const reason = rec.reason || attr.reason || "";
    const upcoming = attr.upcoming_trips || [];

    const fmtTime = dt => dt ? new Date(dt).toLocaleTimeString("nl-NL", {hour:"2-digit",minute:"2-digit"}) : "—";
    const statusColor = needed ? "#fb923c" : "#4ade80";
    const statusLabel = needed ? "Opladen aanbevolen" : "SOC voldoende";

    sh.innerHTML = `
<style>
  :host { display: block; width: 100%; }
  .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,.06);
    border-radius: 16px; overflow: hidden; font-family: var(--primary-font-family, sans-serif); }
  .hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px;
    border-bottom: 1px solid rgba(255,255,255,.07); }
  .hdr-title { font-size: 12px; font-weight: 600; letter-spacing: .04em; color: #fff; flex: 1; }
  .badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 8px;
    background: ${needed ? "rgba(251,146,60,.15)" : "rgba(74,222,128,.15)"}; color: ${statusColor}; }
  .row { display: flex; align-items: center; justify-content: space-between;
    padding: 9px 16px; border-bottom: 1px solid rgba(255,255,255,.04); }
  .row:last-child { border-bottom: none; }
  .lbl { font-size: 12px; color: rgba(163,163,163,1); }
  .val { font-size: 12px; font-weight: 600; color: #fff; }
  .trip-box { margin: 8px 16px; padding: 8px 12px;
    background: rgba(251,146,60,.08); border: 1px solid rgba(251,146,60,.2); border-radius: 8px; }
  .trip-title { font-size: 11px; font-weight: 600; color: #fb923c; margin-bottom: 4px; }
  .trip-row { display: flex; justify-content: space-between; font-size: 11px;
    color: rgba(163,163,163,.8); padding: 1px 0; }
  .reason { padding: 10px 16px; font-size: 11px; color: rgba(163,163,163,.7); font-style: italic; }
  .na { padding: 16px; text-align: center; font-size: 12px; color: rgba(163,163,163,.5); }
  .upcoming { padding: 4px 16px 8px; }
  .upcoming-title { font-size: 11px; color: rgba(163,163,163,.5); margin-bottom: 4px; }
  .upcoming-item { font-size: 11px; color: rgba(163,163,163,.7); padding: 2px 0; }
</style>
<div class="card">
  <div class="hdr">
    <span>🗓️</span>
    <span class="hdr-title">${c.title}</span>
    <span class="badge">${statusLabel}</span>
  </div>
  ${currentSoc != null ? `
  <div class="row"><span class="lbl">Huidige SOC</span><span class="val">${Math.round(currentSoc)}%</span></div>
  ` : ""}
  ${needed && trip.title ? `
  <div class="trip-box">
    <div class="trip-title">📅 ${trip.title}</div>
    <div class="trip-row"><span>Vertrek</span><span>${fmtTime(trip.start_dt)}</span></div>
    <div class="trip-row"><span>Geschatte afstand</span><span>~${Math.round(trip.estimated_km || 0)} km</span></div>
    <div class="trip-row"><span>Benodigd SOC</span><span>${Math.round(targetSoc || 0)}%</span></div>
    <div class="trip-row"><span>Op te laden</span><span>${kwhToAdd ? kwhToAdd + " kWh" : "—"}</span></div>
    ${cheapestStart ? `<div class="trip-row"><span>Goedkoopste laadtijd</span><span>${fmtTime(cheapestStart)} (€${priceAtWindow}/kWh)</span></div>` : ""}
  </div>` : ""}
  ${reason ? `<div class="reason">${reason}</div>` : ""}
  ${upcoming.length > 1 ? `
  <div class="upcoming">
    <div class="upcoming-title">Meer ritten</div>
    ${upcoming.slice(1,4).map(t => `<div class="upcoming-item">📅 ${t.title} — ${fmtTime(t.start_dt)}</div>`).join("")}
  </div>` : ""}
  ${!attr.recommendation ? `<div class="na">Geen agenda-integratie gevonden</div>` : ""}
</div>`;
  }

  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-ev-trip-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsEvTripCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;
color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Card title</label>
<input id="title" value="${this._config?.title || "🗓️ EV Ritplanning"}" />`;
    this.shadowRoot.getElementById("title").addEventListener("input", e => {
      this.dispatchEvent(new CustomEvent("config-changed", {
        detail: { config: { ...this._config, title: e.target.value } }
      }));
    });
  }
}

if (!customElements.get('cloudems-ev-trip-card')) customElements.define("cloudems-ev-trip-card", CloudemsEvTripCard);
if (!customElements.get('cloudems-ev-trip-card-editor')) customElements.define("cloudems-ev-trip-card-editor", CloudemsEvTripCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-ev-trip-card", name: "CloudEMS EV Trip Planner",
  description: "Calendar-based EV charging recommendations" });
