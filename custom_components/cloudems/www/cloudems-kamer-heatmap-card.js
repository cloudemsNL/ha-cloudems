// CloudEMS Kamer Temperatuur Heatmap Card v1.0.0

class CloudemsKamerHeatmapCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:"open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title:"🌡️ Kamer Temperaturen", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const zones = Object.values(h.states).filter(s =>
      s.entity_id.startsWith('sensor.cloudems_zone_') && !s.entity_id.includes('kosten'));
    const k = zones.map(s => s.state + (s.attributes?.doeltemperatuur||'')).join('|');
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;

    const zones = Object.values(h.states)
      .filter(s => s.entity_id.startsWith('sensor.cloudems_zone_') &&
                   !s.entity_id.includes('kosten') &&
                   s.state !== 'unavailable' && s.state !== 'unknown')
      .map(s => {
        const a = s.attributes || {};
        const cur  = parseFloat(s.state) || null;
        const doel = parseFloat(a.doeltemperatuur) || null;
        const name = a.area || s.entity_id.replace('sensor.cloudems_zone_','').replace(/_/g,' ');
        return { name, cur, doel,
          warmte:  !!a.warmtevraag,
          koeling: !!a.koelingsvraag,
          preset:  a.preset_nl || a.preset || 'comfort',
          raam:    !!a.raam_open,
          delta:   (cur != null && doel != null) ? cur - doel : null,
        };
      })
      .sort((a, b) => (b.cur || 0) - (a.cur || 0));

    // Also pick up any climate.* entities not in zones
    const climates = Object.values(h.states)
      .filter(s => s.entity_id.startsWith('climate.') &&
                   s.state !== 'unavailable' && s.state !== 'unknown' &&
                   !zones.some(z => z.name.toLowerCase().includes(
                     s.attributes?.friendly_name?.toLowerCase()?.split(' ')?.[0] || 'x')))
      .slice(0, 6)
      .map(s => {
        const a = s.attributes || {};
        return {
          name:    a.friendly_name || s.entity_id.replace('climate.','').replace(/_/g,' '),
          cur:     parseFloat(a.current_temperature) || null,
          doel:    parseFloat(a.temperature) || null,
          warmte:  s.state === 'heat' || s.state === 'heat_cool',
          koeling: s.state === 'cool' || s.state === 'heat_cool',
          preset:  a.preset_mode || s.state,
          raam:    false,
          delta:   a.current_temperature && a.temperature
                     ? parseFloat(a.current_temperature) - parseFloat(a.temperature) : null,
        };
      });

    const allZones = [...zones, ...climates];

    const tempColor = (cur, doel) => {
      if (cur == null) return 'rgba(80,80,90,.5)';
      if (doel == null) {
        if (cur < 15) return '#93c5fd';
        if (cur < 18) return '#60a5fa';
        if (cur < 21) return '#4ade80';
        if (cur < 24) return '#fbbf24';
        return '#f87171';
      }
      const delta = cur - doel;
      if (Math.abs(delta) < 0.5) return '#4ade80';
      if (delta < -2) return '#93c5fd';
      if (delta < -0.5) return '#60a5fa';
      if (delta > 2) return '#f87171';
      return '#fbbf24';
    };

    const outside = parseFloat(h.states["sensor.buitentemperatuur"]?.state ||
                               h.states["sensor.outside_temperature"]?.state ||
                               h.states["sensor.openweathermap_temperature"]?.state || 0);

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:rgba(255,255,255,.06)}
.tile{background:rgb(34,34,34);padding:12px 14px;position:relative;min-height:80px;transition:background .15s}
.tile.heating{background:rgba(251,146,60,.07)}
.tile.cooling{background:rgba(96,165,250,.07)}
.tile-name{font-size:11px;color:rgba(163,163,163,.7);margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile-temp{font-size:22px;font-weight:700;line-height:1}
.tile-doel{font-size:11px;margin-top:3px}
.tile-icons{position:absolute;top:8px;right:8px;display:flex;gap:3px;font-size:11px}
.delta-bar{height:3px;border-radius:1.5px;margin-top:5px;background:rgba(255,255,255,.08)}
.delta-fill{height:3px;border-radius:1.5px}
.footer{display:flex;justify-content:space-between;padding:8px 16px;border-top:1px solid rgba(255,255,255,.06);font-size:10px;color:rgba(100,100,110,.6)}
.empty{padding:20px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr">
    <span>🌡️</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    ${outside ? `<span style="font-size:11px;color:rgba(163,163,163,.5)">Buiten ${outside.toFixed(1)}°C</span>` : ''}
  </div>

  ${allZones.length === 0
    ? '<div class="empty">Geen klimaatzones geconfigureerd.<br>Activeer via CloudEMS → Klimaatbeheer wizard.</div>'
    : `<div class="grid">
    ${allZones.map(z => {
      const col = tempColor(z.cur, z.doel);
      const cls = z.warmte ? 'tile heating' : z.koeling ? 'tile cooling' : 'tile';
      const deltaAbs = z.delta != null ? Math.min(4, Math.abs(z.delta)) : 0;
      const deltaPct = (deltaAbs / 4 * 100).toFixed(0);
      const deltaCol = z.delta != null
        ? (Math.abs(z.delta) < 0.5 ? '#4ade80' : z.delta < 0 ? '#60a5fa' : '#fb923c')
        : '#6b7280';
      return `<div class="${cls}">
        <div class="tile-icons">
          ${z.warmte ? '🔥' : ''}${z.koeling ? '❄️' : ''}${z.raam ? '🪟' : ''}
        </div>
        <div class="tile-name">${z.name}</div>
        <div class="tile-temp" style="color:${col}">${z.cur != null ? z.cur.toFixed(1)+'°' : '—'}</div>
        <div class="tile-doel" style="color:rgba(163,163,163,.5)">
          doel ${z.doel != null ? z.doel.toFixed(1)+'°' : '—'}
          ${z.delta != null ? `<span style="color:${deltaCol}">(${z.delta > 0 ? '+' : ''}${z.delta.toFixed(1)})</span>` : ''}
        </div>
        ${z.delta != null ? `<div class="delta-bar"><div class="delta-fill" style="width:${deltaPct}%;background:${deltaCol}"></div></div>` : ''}
      </div>`;
    }).join('')}
  </div>`}

  <div class="footer">
    <span>${allZones.length} zones</span>
    <span>${allZones.filter(z=>z.warmte).length} verwarmen · ${allZones.filter(z=>z.koeling).length} koelen</span>
  </div>
</div>`;
  }
  getCardSize() { return Math.ceil(this._hass ? Object.values(this._hass.states).filter(s=>s.entity_id.startsWith('sensor.cloudems_zone_')&&!s.entity_id.includes('kosten')).length / 2 : 2) + 2; }
  static getConfigElement() { return document.createElement("cloudems-kamer-heatmap-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsKamerHeatmapCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'🌡️ Kamer Temperaturen'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-kamer-heatmap-card')) customElements.define("cloudems-kamer-heatmap-card", CloudemsKamerHeatmapCard);
if (!customElements.get('cloudems-kamer-heatmap-card-editor')) customElements.define("cloudems-kamer-heatmap-card-editor", CloudemsKamerHeatmapCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type:"cloudems-kamer-heatmap-card", name:"CloudEMS Kamer Temperaturen Heatmap" });
