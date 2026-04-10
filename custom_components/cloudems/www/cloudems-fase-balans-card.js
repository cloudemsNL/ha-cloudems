// CloudEMS Fase Balans Card v5.5.465 — Phase balance with cos phi
const CARD_FASE_BALANS_VERSION = '5.5.465';

class CloudemsFaseBalansCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "⚡ Fase Balans", ...c }; this._r(); }
  
  static getConfigElement(){return document.createElement('cloudems-fase-balans-card-editor');}
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_power_quality"];
    const k = JSON.stringify([s?.last_changed, h.states["sensor.cloudems_grid_phase_imbalance"]?.last_changed]);
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const pq  = h.states["sensor.cloudems_power_quality"]?.attributes || {};
    const bal = h.states["sensor.cloudems_grid_phase_imbalance"]?.attributes || {};
    const phases = h.states["sensor.cloudems_fasen"]?.attributes?.phases || bal.phases || [];
    const imbalance = parseFloat(h.states["sensor.cloudems_grid_phase_imbalance"]?.state || 0);
    const pfAvg = pq.pf_avg;
    const imbalCol = imbalance < 3 ? "#4ade80" : imbalance < 8 ? "#fbbf24" : "#f87171";
    const pfCol = pfAvg == null ? "#6b7280" : pfAvg > 0.95 ? "#4ade80" : pfAvg > 0.85 ? "#fbbf24" : "#f87171";
    const phaseRow = (label, A, pf) => {
      const col = A > 20 ? "#f87171" : A > 15 ? "#fbbf24" : "#4ade80";
      const pct = Math.min(100, A / 25 * 100);
      return `<div style="padding:6px 16px;border-bottom:1px solid rgba(255,255,255,.04)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">
          <span style="font-size:11px;color:rgba(163,163,163,.7);min-width:16px">${label}</span>
          <div style="flex:1;height:6px;background:rgba(255,255,255,.1);border-radius:3px">
            <div style="height:6px;background:${col};border-radius:3px;width:${pct}%;transition:width .3s"></div>
          </div>
          <span style="font-size:12px;font-weight:600;color:${col};min-width:44px;text-align:right">${A.toFixed(1)} A</span>
          ${pf!=null?`<span style="font-size:10px;color:rgba(163,163,163,.5);min-width:36px;text-align:right">φ ${pf.toFixed(2)}</span>`:""}
        </div>
      </div>`;
    };
    // Stroom uit sensor.cloudems_grid_net_power (backend berekend, gesigneerd)
    // Fallback naar sensor.cloudems_status.phases (limiter, zelfde bron als piekschaving)
    const _gna = h.states['sensor.cloudems_grid_net_power']?.attributes || {};
    const _st_phases = h.states['sensor.cloudems_status']?.attributes?.phases || {};
    const l1 = Math.abs(parseFloat(_gna.current_l1 ?? _st_phases['L1']?.current_a ?? bal.current_l1 ?? 0));
    const l2 = Math.abs(parseFloat(_gna.current_l2 ?? _st_phases['L2']?.current_a ?? bal.current_l2 ?? 0));
    const l3 = Math.abs(parseFloat(_gna.current_l3 ?? _st_phases['L3']?.current_a ?? bal.current_l3 ?? 0));
    sh.innerHTML = `
<style>:host{display:block;width:100%}.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}.summary{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid rgba(255,255,255,.07)}.sum{padding:10px 16px;text-align:center}.sum-val{font-size:18px;font-weight:700}.sum-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}</style>
<div class="card">
  <div class="hdr"><span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span></div>
  <div class="summary">
    <div class="sum">
      <div class="sum-val" style="color:${imbalCol}">${imbalance.toFixed(1)} A</div>
      <div class="sum-lbl">Fase onbalans</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:${pfCol}">${pfAvg!=null?pfAvg.toFixed(3):'—'}</div>
      <div class="sum-lbl">cos φ gemiddeld</div>
    </div>
  </div>
  ${phaseRow("L1", l1, pq.pf_l1)}
  ${phaseRow("L2", l2, pq.pf_l2)}
  ${phaseRow("L3", l3, pq.pf_l3)}
  ${pq.reactive_l1!=null?`<div style="padding:6px 16px;font-size:10px;color:rgba(163,163,163,.4)">Reactief: L1=${pq.reactive_l1?.toFixed(0)}W · L2=${pq.reactive_l2?.toFixed(0)}W · L3=${pq.reactive_l3?.toFixed(0)}W</div>`:""}
</div>`;
  }
  getCardSize() { return 3; }
  static getConfigElement(){return document.createElement('cloudems-fase-balans-card-editor');}
  static getStubConfig() { return {}; }
}
class CloudemsFaseBalansCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px;margin-top:4px" id="t" value="${this._config?.title||'⚡ Fase Balans'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-fase-balans-card')) customElements.define("cloudems-fase-balans-card",CloudemsFaseBalansCard);
if (!customElements.get('cloudems-fase-balans-card-editor')) customElements.define("cloudems-fase-balans-card-editor",CloudemsFaseBalansCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:"cloudems-fase-balans-card",name:"CloudEMS Fase Balans + cos φ"});
