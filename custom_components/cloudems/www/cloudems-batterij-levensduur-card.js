// CloudEMS Batterij Levensduur Card v5.4.96
const CARD_BATTERIJ_LEVENSDUUR_VERSION = '5.4.96';
// Tracks battery cycles, DoD, estimated remaining capacity

class CloudemsBatterijLevensduurCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "🔋 Batterij Levensduur", nominal_capacity_kwh: 10, max_cycles: 6000, ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const k = JSON.stringify([
      h.states["sensor.cloudems_battery_savings"]?.last_changed,
      h.states["sensor.cloudems_battery_so_c"]?.state,
    ]);
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const a   = h.states["sensor.cloudems_battery_savings"]?.attributes || {};
    const _sohRaw = parseFloat(h.states["sensor.cloudems_battery_state_of_health"]?.state); const soh = isNaN(_sohRaw) ? 100 : _sohRaw;
    const soc = parseFloat(h.states["sensor.cloudems_battery_so_c"]?.state || 0);

    const totalCycles  = parseInt(a.sessions_year || 0) + (a.history_years||[]).reduce((s,y)=>s+y.sessions,0);
    const nomKwh       = parseFloat(c.nominal_capacity_kwh) || 10;
    const maxCycles    = parseFloat(c.max_cycles) || 6000;
    const kwhYear      = parseFloat(a.kwh_charged_year || 0);
    const kwhTotal     = kwhYear + (a.history_years||[]).reduce((s,y)=>s+(y.kwh_charged||0),0);
    const cyclePct     = Math.min(100, totalCycles / maxCycles * 100);
    const remainPct    = 100 - cyclePct;
    const estRemainCyc = Math.max(0, maxCycles - totalCycles);
    // Estimate years remaining: based on average cycles per year
    const currentYear  = new Date().getFullYear();
    const yearsData    = (a.history_years||[]).length + 1;
    const cyclesPerYear = yearsData > 0 ? totalCycles / yearsData : (a.sessions_year||0);
    const yearsRemain  = cyclesPerYear > 0 ? Math.round(estRemainCyc / cyclesPerYear) : null;
    // Efficiency: discharged / charged
    const kwhInYear  = parseFloat(a.kwh_charged_year || 0);
    const kwhOutYear = parseFloat(a.kwh_discharged_year || 0);
    const eff = kwhInYear > 0 ? Math.round(kwhOutYear / kwhInYear * 100) : null;

    const colCycle = cyclePct < 30 ? '#4ade80' : cyclePct < 60 ? '#fbbf24' : cyclePct < 85 ? '#fb923c' : '#f87171';
    const colSoh   = soh > 90 ? '#4ade80' : soh > 75 ? '#fbbf24' : '#f87171';

    const arc = (pct, r, col) => {
      const c2 = 60, cy = 55;
      const rad = r, circ = 2 * Math.PI * rad;
      const dash = circ * (pct/100);
      const rot = -90;
      return `<circle cx="${c2}" cy="${cy}" r="${rad}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="8"/>
              <circle cx="${c2}" cy="${cy}" r="${rad}" fill="none" stroke="${col}" stroke-width="8"
                stroke-dasharray="${dash.toFixed(1)} ${circ.toFixed(1)}"
                stroke-linecap="round"
                transform="rotate(${rot} ${c2} ${cy})"/>`;
    };

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.body{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:14px 16px}
.gauge{display:flex;flex-direction:column;align-items:center}
.gauge-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:4px;text-align:center}
.stats{padding:0 16px 12px;border-top:1px solid rgba(255,255,255,.07)}
.stat{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px}
.stat-l{color:rgba(163,163,163,.7)}
.stat-v{font-weight:600;color:#fff}
</style>
<div class="card">
  <div class="hdr">
    
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span style="font-size:11px;color:rgba(163,163,163,.5)">SOC ${soc.toFixed(0)}%</span>
  </div>

  <div class="body">
    <div class="gauge">
      <svg width="120" height="110" viewBox="0 0 120 110">
        ${arc(cyclePct, 44, colCycle)}
        <text x="60" y="52" text-anchor="middle" font-size="18" font-weight="700" fill="${colCycle}" font-family="sans-serif">${cyclePct.toFixed(0)}%</text>
        <text x="60" y="66" text-anchor="middle" font-size="10" fill="rgba(163,163,163,.5)" font-family="sans-serif">gebruik</text>
      </svg>
      <div class="gauge-lbl">Cycli verbruikt<br>${totalCycles.toLocaleString()} / ${maxCycles.toLocaleString()}</div>
    </div>

    <div class="gauge">
      <svg width="120" height="110" viewBox="0 0 120 110">
        ${arc(soh, 44, colSoh)}
        <text x="60" y="52" text-anchor="middle" font-size="18" font-weight="700" fill="${colSoh}" font-family="sans-serif">${soh.toFixed(0)}%</text>
        <text x="60" y="66" text-anchor="middle" font-size="10" fill="rgba(163,163,163,.5)" font-family="sans-serif">SoH</text>
      </svg>
      <div class="gauge-lbl">State of Health<br>${soh > 90 ? 'Uitstekend' : soh > 75 ? 'Goed' : 'Matig'}</div>
    </div>
  </div>

  <div class="stats">
    ${yearsRemain != null ? `<div class="stat"><span class="stat-l">📅 Verwachte resterende levensduur</span><span class="stat-v" style="color:${colCycle}">~${yearsRemain} jaar</span></div>` : ""}
    <div class="stat"><span class="stat-l">⚡ Gereden cycli totaal</span><span class="stat-v">${totalCycles.toLocaleString()}</span></div>
    <div class="stat"><span class="stat-l">🔌 Geladen dit jaar</span><span class="stat-v">${kwhYear.toFixed(0)} kWh</span></div>
    ${eff != null ? `<div class="stat"><span class="stat-l">♻️ Laad rendement</span><span class="stat-v" style="color:${eff>88?'#4ade80':eff>80?'#fbbf24':'#fb923c'}">${eff}%</span></div>` : ""}
    <div class="stat"><span class="stat-l">📦 Nominale capaciteit</span><span class="stat-v">${nomKwh} kWh</span></div>
    ${soh < 100 ? `<div class="stat"><span class="stat-l">📉 Geschatte huidige capaciteit</span><span class="stat-v">${(nomKwh * soh/100).toFixed(1)} kWh</span></div>` : ""}
  </div>
</div>`;
  }
  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-batterij-levensduur-card-editor"); }
  static getStubConfig() { return { nominal_capacity_kwh: 10, max_cycles: 6000 }; }
}
class CloudemsBatterijLevensduurCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){
    if(!this.shadowRoot)this.attachShadow({mode:"open"});
    this.shadowRoot.innerHTML=`
      <style>label{display:block;font-size:12px;color:#aaa;margin:8px 0 2px}input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
      <label>Titel</label><input id="t" value="${this._config?.title||'🔋 Batterij Levensduur'}"/>
      <label>Nominale capaciteit (kWh)</label><input id="kwh" type="number" value="${this._config?.nominal_capacity_kwh||10}"/>
      <label>Max cycli</label><input id="cyc" type="number" value="${this._config?.max_cycles||6000}"/>`;
    const fire = () => this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{
      ...this._config,
      title: this.shadowRoot.getElementById("t").value,
      nominal_capacity_kwh: parseFloat(this.shadowRoot.getElementById("kwh").value)||10,
      max_cycles: parseFloat(this.shadowRoot.getElementById("cyc").value)||6000,
    }}}));
    this.shadowRoot.querySelectorAll("input").forEach(i=>i.addEventListener("input",fire));
  }
}
if (!customElements.get('cloudems-batterij-levensduur-card')) customElements.define("cloudems-batterij-levensduur-card", CloudemsBatterijLevensduurCard);
if (!customElements.get('cloudems-batterij-levensduur-card-editor')) customElements.define("cloudems-batterij-levensduur-card-editor", CloudemsBatterijLevensduurCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-batterij-levensduur-card", name: "CloudEMS Batterij Levensduur" });
