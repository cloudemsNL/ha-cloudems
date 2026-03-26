// CloudEMS Apparaat Tijdlijn Card v1.0.0 — Today's appliance activity swimlane
const CARD_APPARAAT_TIJDLIJN_VERSION = '5.4.8';

class CloudemsApparaatTijdlijnCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "📅 Apparaat Tijdlijn", max_devices: 8, ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_nilm_running_devices"];
    const k = JSON.stringify(s?.last_changed);
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const devs = h.states["sensor.cloudems_nilm_devices"]?.attributes?.devices || [];
    const running = h.states["sensor.cloudems_nilm_running_devices"]?.attributes?.devices || [];
    const runningIds = new Set(running.map(d => d.name || d.label || d.id));
    const now = new Date();
    const dayStart = new Date(now); dayStart.setHours(0,0,0,0);
    const maxDevs = parseInt(c.max_devices) || 8;
    // Sort: running first, then by last_seen desc
    const sorted = [...devs]
      .sort((a,b) => {
        const aOn = runningIds.has(a.name||a.label||a.id) ? 1 : 0;
        const bOn = runningIds.has(b.name||b.label||b.id) ? 1 : 0;
        return bOn - aOn;
      })
      .slice(0, maxDevs);
    const totalMins = 24 * 60;
    const nowMins = now.getHours()*60 + now.getMinutes();
    const pct = (min) => Math.min(100, min / totalMins * 100);
    const colors = ["#60a5fa","#34d399","#fbbf24","#f87171","#a78bfa","#fb923c","#38bdf8","#4ade80"];
    sh.innerHTML = `
<style>:host{display:block;width:100%}.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 10px;border-bottom:1px solid rgba(255,255,255,.07)}.row{display:flex;align-items:center;gap:8px;padding:5px 16px}.name{font-size:11px;color:rgba(163,163,163,.9);min-width:90px;max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.track{flex:1;height:8px;background:rgba(255,255,255,.06);border-radius:4px;position:relative;overflow:visible}.power{font-size:10px;color:rgba(163,163,163,.5);min-width:40px;text-align:right}.time-axis{display:flex;justify-content:space-between;padding:2px 16px 10px 114px;font-size:9px;color:rgba(163,163,163,.3)}.now-line{position:absolute;top:-2px;bottom:-2px;width:2px;background:rgba(255,255,255,.3);border-radius:1px;z-index:2}</style>
<div class="card">
  <div class="hdr"><span>📅</span><span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span><span style="font-size:10px;color:rgba(163,163,163,.4)">vandaag</span></div>
  ${sorted.length === 0 ? `<div style="padding:20px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)">Geen NILM-data beschikbaar</div>` :
    sorted.map((d, i) => {
      const isOn = runningIds.has(d.name || d.label || d.id);
      const col = colors[i % colors.length];
      const pw = d.current_power != null ? Math.round(d.current_power) : (d.avg_power_w != null ? Math.round(d.avg_power_w) : null);
      // Build activity bars from today_events if available
      const events = d.today_events || d.events_today || [];
      let bars = "";
      if (events.length > 0) {
        bars = events.map(e => {
          const s = new Date(e.start || e.ts || 0);
          const end = e.end ? new Date(e.end) : (isOn ? now : new Date(s.getTime() + 30*60000));
          const sMin = s.getHours()*60+s.getMinutes();
          const eMin = Math.min(end.getHours()*60+end.getMinutes(), nowMins+1);
          const left = pct(sMin);
          const width = Math.max(0.5, pct(eMin - sMin));
          return `<div style="position:absolute;left:${left}%;width:${width}%;height:8px;background:${col};border-radius:2px;top:0"></div>`;
        }).join("");
      } else if (isOn) {
        // Just show running indicator at current time
        bars = `<div style="position:absolute;right:0;width:${pct(30)}%;height:8px;background:${col};border-radius:2px;opacity:.8;top:0"></div>`;
      }
      return `<div class="row">
        <span class="name" style="color:${isOn?col:'rgba(163,163,163,.6)'}">${isOn?'●':' '} ${d.name||d.label||'Apparaat '+(i+1)}</span>
        <div class="track">
          <div class="now-line" style="left:${pct(nowMins)}%"></div>
          ${bars}
        </div>
        <span class="power">${pw!=null?pw+'W':''}</span>
      </div>`;
    }).join("")}
  <div class="time-axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
</div>`;
  }
  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-apparaat-tijdlijn-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsApparaatTijdlijnCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px;margin-top:4px" id="t" value="${this._config?.title||'📅 Apparaat Tijdlijn'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-apparaat-tijdlijn-card')) customElements.define("cloudems-apparaat-tijdlijn-card",CloudemsApparaatTijdlijnCard);
if (!customElements.get('cloudems-apparaat-tijdlijn-card-editor')) customElements.define("cloudems-apparaat-tijdlijn-card-editor",CloudemsApparaatTijdlijnCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:"cloudems-apparaat-tijdlijn-card",name:"CloudEMS Apparaat Tijdlijn"});
