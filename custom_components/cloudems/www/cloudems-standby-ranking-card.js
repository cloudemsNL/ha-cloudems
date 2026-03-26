// CloudEMS Standby Ranking Card v1.0.0
const CARD_STANDBY_RANKING_VERSION = '5.4.1';
// Top energy wasters with monthly cost

class CloudemsStandbyRankingCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "💤 Standby Top 5", max_items: 5, ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_standby_intelligence"];
    if (JSON.stringify(s?.last_changed) !== this._p) {
      this._p = JSON.stringify(s?.last_changed);
      this._r();
    }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const st   = h.states["sensor.cloudems_standby_intelligence"];
    const a    = st?.attributes || {};
    const score     = parseFloat(st?.state || 0);
    const devices   = (a.devices || []).filter(d => (d.standby_w || 0) > 0.5);
    const topDevs   = [...devices]
      .sort((a, b) => (b.cost_month_eur || 0) - (a.cost_month_eur || 0))
      .slice(0, parseInt(c.max_items) || 5);
    const totalStW   = parseFloat(a.total_standby_w || 0);
    const totalCost  = parseFloat(a.total_cost_month || 0);
    const topSavings = a.top_savings || [];

    const barW = (w, max) => Math.min(100, w / Math.max(max, 0.1) * 100);
    const scoreCol = score >= 7 ? '#4ade80' : score >= 4 ? '#fbbf24' : '#f87171';
    const maxW = topDevs.length > 0 ? topDevs[0].standby_w || 1 : 1;

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.summary{display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid rgba(255,255,255,.07)}
.sum{padding:10px 0;text-align:center}
.sum-val{font-size:16px;font-weight:700}
.sum-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}
.dev-row{display:flex;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
.dev-rank{font-size:14px;min-width:22px;text-align:center}
.dev-info{flex:1}
.dev-name{font-size:12px;font-weight:500;color:#fff}
.dev-bar-wrap{flex:1}
.dev-bar-bg{height:4px;background:rgba(255,255,255,.08);border-radius:2px}
.dev-bar{height:4px;border-radius:2px}
.dev-w{font-size:11px;color:rgba(163,163,163,.6);min-width:36px;text-align:right}
.dev-cost{font-size:11px;font-weight:600;min-width:40px;text-align:right}
.advice{padding:10px 16px 12px;font-size:11px;color:rgba(163,163,163,.7);font-style:italic;border-top:1px solid rgba(255,255,255,.06)}
.empty{padding:20px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr">
    <span>💤</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span style="font-size:13px;font-weight:700;color:${scoreCol}">${score.toFixed(1)}/10</span>
  </div>

  <div class="summary">
    <div class="sum">
      <div class="sum-val" style="color:${totalStW>100?'#f87171':totalStW>50?'#fbbf24':'#4ade80'}">${Math.round(totalStW)}</div>
      <div class="sum-lbl">W sluimer</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:${totalCost>5?'#f87171':totalCost>2?'#fbbf24':'#4ade80'}">€${totalCost.toFixed(2)}</div>
      <div class="sum-lbl">/maand</div>
    </div>
    <div class="sum">
      <div class="sum-val">${devices.length}</div>
      <div class="sum-lbl">apparaten</div>
    </div>
  </div>

  ${topDevs.length === 0
    ? '<div class="empty">Geen sluimerverbruikers gedetecteerd</div>'
    : topDevs.map((d, i) => {
        const medals = ['🥇','🥈','🥉','4️⃣','5️⃣'];
        const w = parseFloat(d.standby_w || 0);
        const cost = parseFloat(d.cost_month_eur || 0);
        const pct = barW(w, maxW);
        const barCol = i === 0 ? '#f87171' : i === 1 ? '#fb923c' : i === 2 ? '#fbbf24' : '#94a3b8';
        return `<div class="dev-row">
          <span class="dev-rank">${medals[i]||'·'}</span>
          <div class="dev-info">
            <div class="dev-name">${d.label || d.name || d.entity_id || 'Apparaat'}</div>
            <div class="dev-bar-wrap" style="margin-top:3px">
              <div class="dev-bar-bg">
                <div class="dev-bar" style="width:${pct.toFixed(0)}%;background:${barCol}"></div>
              </div>
            </div>
          </div>
          <span class="dev-w">${w.toFixed(1)} W</span>
          <span class="dev-cost" style="color:${cost>2?'#f87171':cost>1?'#fbbf24':'#94a3b8'}">€${cost.toFixed(2)}</span>
        </div>`;
      }).join("")
  }

  ${a.advice ? `<div class="advice">💡 ${a.advice}</div>` : ""}
</div>`;
  }
  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-standby-ranking-card-editor"); }
  static getStubConfig() { return { max_items: 5 }; }
}
class CloudemsStandbyRankingCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){
    if(!this.shadowRoot)this.attachShadow({mode:"open"});
    this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px;margin-bottom:8px" id="t" value="${this._config?.title||'💤 Standby Top 5'}"/><label style="font-size:12px;color:#aaa;display:block;margin-bottom:2px">Max apparaten</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="n" type="number" min="3" max="10" value="${this._config?.max_items||5}"/>`;
    const fire=()=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:this.shadowRoot.getElementById("t").value,max_items:parseInt(this.shadowRoot.getElementById("n").value)||5}}}));
    this.shadowRoot.querySelectorAll("input").forEach(i=>i.addEventListener("input",fire));
  }
}
if (!customElements.get('cloudems-standby-ranking-card')) customElements.define("cloudems-standby-ranking-card", CloudemsStandbyRankingCard);
if (!customElements.get('cloudems-standby-ranking-card-editor')) customElements.define("cloudems-standby-ranking-card-editor", CloudemsStandbyRankingCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-standby-ranking-card", name: "CloudEMS Standby Ranking" });
