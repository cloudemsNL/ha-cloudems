// CloudEMS E-bike & Scooter Card v5.5.465
const CARD_EBIKE_VERSION = '5.5.465';

class CloudemsEbikeCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "🚲 E-bike & Scooter", ...c }; this._r(); }
  
  static getConfigElement(){return document.createElement('cloudems-ebike-card-editor');}
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_micro_mobiliteit"];
    const k = JSON.stringify([s?.state, s?.last_changed]);
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const st   = h.states["sensor.cloudems_micro_mobiliteit"];
    const mod  = h.states["switch.cloudems_module_ebike"]?.state === "on";
    const attr = st?.attributes || {};
    const sessions  = attr.active_sessions || [];
    const profiles  = attr.vehicle_profiles || [];
    const kwhToday  = parseFloat(attr.kwh_today || 0);
    const costToday = parseFloat(attr.cost_today_eur || 0);
    const totalKwh  = parseFloat(st?.state || 0);
    const bestHour  = attr.best_charge_hour;
    const advice    = attr.advice || "";
    const weeklyAvg = parseFloat(attr.weekly_kwh_avg || 0);
    const priceNow  = parseFloat(h.states["sensor.cloudems_price_current_hour"]?.state || 0);
    const priceGood = priceNow < 0.15;

    const typeIcon = t => ({ ebike: "🚲", scooter: "🛴", cargo: "🚛", speed_pedelec: "⚡🚲" })[t] || "🔋";
    const kv = (l, v, col = "var(--color-text-primary)") =>
      `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)">
        <span style="font-size:12px;color:rgba(163,163,163,.7)">${l}</span>
        <span style="font-size:12px;font-weight:600;color:${col}">${v}</span>
      </div>`;

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.summary{display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid rgba(255,255,255,.07)}
.sum{padding:10px 16px;text-align:center}
.sum-val{font-size:18px;font-weight:700}.sum-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}
.section{padding:4px 16px 10px}
.section-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);text-transform:uppercase;padding:10px 0 4px}
.vehicle{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.veh-icon{font-size:20px;width:36px;text-align:center}
.veh-info{flex:1}
.veh-name{font-size:13px;font-weight:500;color:#fff}
.veh-sub{font-size:11px;color:rgba(163,163,163,.5)}
.veh-status{font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px}
.charging{background:rgba(74,222,128,.15);color:#4ade80}
.idle{background:rgba(163,163,163,.1);color:rgba(163,163,163,.6)}
.advice-box{margin:8px 16px 12px;padding:8px 12px;background:rgba(251,191,36,.08);border-left:3px solid #fbbf24;border-radius:4px;font-size:11px;color:rgba(251,191,36,.9)}
.best-hour{margin:8px 16px 12px;padding:8px 12px;background:${priceGood?'rgba(74,222,128,.08)':'rgba(163,163,163,.06)'};border-radius:8px;text-align:center}
.off-notice{padding:16px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr">
    <span>🚲</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    ${!mod ? `<span style="font-size:10px;padding:2px 8px;background:rgba(255,100,100,.15);color:#f87171;border-radius:6px">module uit</span>` : sessions.length > 0 ? `<span style="font-size:10px;padding:2px 8px;background:rgba(74,222,128,.15);color:#4ade80;border-radius:6px">⚡ ${sessions.length} laden</span>` : ""}
  </div>

  ${!mod ? `<div class="off-notice">E-bike module is uitgeschakeld.<br>Activeer via CloudEMS → Configuratie → Modules.</div>` : `

  <div class="summary">
    <div class="sum">
      <div class="sum-val" style="color:${kwhToday>0?'#60a5fa':'#6b7280'}">${kwhToday.toFixed(2)}</div>
      <div class="sum-lbl">kWh vandaag</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:${costToday>0?'#fbbf24':'#6b7280'}">€${costToday.toFixed(2)}</div>
      <div class="sum-lbl">Kosten vandaag</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:#94a3b8">${weeklyAvg.toFixed(1)}</div>
      <div class="sum-lbl">kWh/week gem.</div>
    </div>
  </div>

  ${profiles.length > 0 ? `
  <div class="section">
    <div class="section-title">Voertuigen</div>
    ${profiles.map(v => {
      const isCharging = sessions.some(s => (s.vehicle_id || s.entity_id) === (v.id || v.entity_id));
      return `<div class="vehicle">
        <div class="veh-icon">${typeIcon(v.type)}</div>
        <div class="veh-info">
          <div class="veh-name">${v.label || v.name || "Voertuig"}</div>
          <div class="veh-sub">${v.battery_wh ? Math.round(v.battery_wh) + ' Wh accu' : ''} ${v.range_km ? '· ' + v.range_km + ' km bereik' : ''}</div>
        </div>
        <span class="veh-status ${isCharging ? 'charging' : 'idle'}">${isCharging ? '⚡ Laden' : '○ Standby'}</span>
      </div>`;
    }).join("")}
  </div>` : sessions.length > 0 ? `
  <div class="section">
    <div class="section-title">Actieve laadsessies</div>
    ${sessions.map(s => `<div class="vehicle">
      <div class="veh-icon">🔋</div>
      <div class="veh-info">
        <div class="veh-name">${s.label || s.entity_id || "E-bike"}</div>
        <div class="veh-sub">${Math.round(s.power_w || 0)} W · ${(s.kwh || 0).toFixed(2)} kWh geladen</div>
      </div>
      <span class="veh-status charging">⚡ Laden</span>
    </div>`).join("")}
  </div>` : ""}

  <div class="section">
    <div class="section-title">Statistieken</div>
    ${kv("Totaal opgeladen", totalKwh.toFixed(1) + " kWh")}
    ${kv("Laadsessies vandaag", String(attr.vehicles_today || 0))}
    ${bestHour != null ? kv("Beste laadtijd", `${bestHour}:00 – ${bestHour+1}:00`, "#fbbf24") : ""}
    ${kv("Stroomprijs nu", (priceNow * 100).toFixed(1) + " ct/kWh", priceGood ? "#4ade80" : "#fb923c")}
  </div>

  ${bestHour != null ? `<div class="best-hour">
    <div style="font-size:11px;color:rgba(163,163,163,.6);margin-bottom:4px">Aanbevolen laadtijd</div>
    <div style="font-size:16px;font-weight:700;color:${priceGood?'#4ade80':'#fbbf24'}">${bestHour}:00 – ${bestHour+1}:00</div>
    <div style="font-size:10px;color:rgba(163,163,163,.5);margin-top:2px">${priceGood ? "Nu is een goed moment om te laden" : "Wacht op goedkoper uur"}</div>
  </div>` : ""}

  ${advice ? `<div class="advice-box">💡 ${advice}</div>` : ""}
  `}
</div>`;
  }
  getCardSize() { return 4; }
  static getConfigElement(){return document.createElement('cloudems-ebike-card-editor');}
  static getStubConfig() { return {}; }
}
class CloudemsEbikeCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'🚲 E-bike & Scooter'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-ebike-card')) customElements.define("cloudems-ebike-card", CloudemsEbikeCard);
if (!customElements.get('cloudems-ebike-card-editor')) customElements.define("cloudems-ebike-card-editor", CloudemsEbikeCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-ebike-card", name: "CloudEMS E-bike & Scooter", description: "Laadtracking en EPEX-sturing voor e-bikes en scooters" });
