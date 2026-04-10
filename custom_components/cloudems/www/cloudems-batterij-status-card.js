// CloudEMS Batterij Status Card — Off-grid + Energiekosten gecombineerd
const BST_VERSION = "5.5.465";

class CloudEMSBatterijStatusCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); this._tab = 'offgrid'; }
  setConfig(c) { this._cfg = { house_avg_w: 500, ...c }; }

  set hass(h) {
    this._hass = h;
    const sig = [
      h?.states['sensor.cloudems_battery_so_c']?.state,
      h?.states['sensor.cloudems_energy_cost']?.state,
      h?.states['sensor.cloudems_price_current_hour']?.state,
    ].join('|');
    if (sig === this._prev) return;
    this._prev = sig;
    this._render();
  }

  _render() {
    const h = this._hass;
    if (!h) return;

    // ── Off-grid data ─────────────────────────────────────────────────────────
    const bat    = h.states['sensor.cloudems_battery_so_c'];
    const pv     = h.states['sensor.cloudems_pv_forecast_today'];
    const solar  = h.states['sensor.cloudems_solar_system'];
    const home   = h.states['sensor.cloudems_home_rest'];
    const soc_pct   = parseFloat(bat?.state || 0) || 0;
    const cap_kwh   = parseFloat(bat?.attributes?.capacity_kwh || 10) || 10;
    const bat_kwh   = cap_kwh * soc_pct / 100;
    const solar_w   = parseFloat(solar?.state || 0) || 0;
    const pv_today  = parseFloat(pv?.state || 0) || 0;
    const pv_done   = parseFloat(solar?.attributes?.pv_today_kwh || 0) || 0;
    const pv_remain = Math.max(0, pv_today - pv_done);
    const house_w   = parseFloat(home?.state || 0) || this._cfg.house_avg_w;
    const survival  = home?.attributes?.survival ?? null;
    const total_kwh = bat_kwh + pv_remain;

    // ── Kosten data ───────────────────────────────────────────────────────────
    const price  = h.states['sensor.cloudems_price_current_hour'];
    const cost   = h.states['sensor.cloudems_energy_cost'];
    const sc     = h.states['sensor.cloudems_self_consumption'];
    const dagk   = h.states['sensor.cloudems_dagkosten_stroom'];
    const cur_price  = parseFloat(price?.state || 0.25) || 0.25;
    const today_eur  = parseFloat(dagk?.state || 0) || 0;
    const sc_pct     = parseFloat(sc?.state || 0) || 0;
    const month_eur  = parseFloat(cost?.attributes?.month_eur || 0) || 0;
    const year_eur   = parseFloat(cost?.attributes?.year_eur || 0) || 0;
    const saved_today = parseFloat(solar?.attributes?.saved_eur || 0) || parseFloat(cost?.attributes?.solar_saved_today || 0) || 0;

    const tab = this._tab;
    const priceCol = cur_price < 0.10 ? '#4ade80' : cur_price < 0.25 ? '#fbbf24' : cur_price > 0.40 ? '#f87171' : '#e2e8f0';
    const batCol = soc_pct >= 50 ? '#4ade80' : soc_pct >= 20 ? '#fbbf24' : '#f87171';

    // ── Off-grid scenarios ────────────────────────────────────────────────────
    const offgridHtml = (() => {
      const scenarios = [
        { label: 'Essentieel',   w: 200,              icon: '💡', desc: 'verlichting + koelkast' },
        { label: 'Normaal',      w: house_w || 500,   icon: '🏠', desc: 'huidig patroon' },
        { label: 'Met airco',    w: (house_w||500)+1500, icon: '❄️', desc: '+ klimaat' },
        { label: 'Met EV',       w: (house_w||500)+3700, icon: '🚗', desc: '+ 3.7kW laden' },
      ];
      const fmtH = h => h >= 24 ? '24u+' : h >= 1 ? h.toFixed(1) + 'u' : (h*60).toFixed(0) + 'min';

      return scenarios.map(sc => {
        const h_bat = sc.w > 0 ? bat_kwh / (sc.w / 1000) : 999;
        const h_tot = sc.w > 0 ? total_kwh / (sc.w / 1000) : 999;
        const pct_bat = Math.min(100, h_bat / 24 * 100);
        const pct_pv  = Math.min(100, Math.max(0, (h_tot - h_bat) / 24 * 100));
        const col = h_bat >= 8 ? '#4ade80' : h_bat >= 4 ? '#fbbf24' : '#f87171';
        return `<div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.04)">
          <div style="font-size:16px;width:22px;text-align:center">${sc.icon}</div>
          <div style="width:80px;flex-shrink:0">
            <div style="font-size:11px;font-weight:600;color:#e2e8f0">${sc.label}</div>
            <div style="font-size:9px;color:#475569">${sc.desc}</div>
          </div>
          <div style="flex:1">
            <div style="height:7px;background:rgba(255,255,255,.06);border-radius:4px;position:relative;overflow:hidden">
              <div style="position:absolute;left:0;top:0;height:100%;width:${pct_bat}%;background:${col};border-radius:4px;transition:width .5s"></div>
              <div style="position:absolute;top:0;height:100%;left:${pct_bat}%;width:${pct_pv}%;background:rgba(251,191,36,.35);border-radius:0 4px 4px 0"></div>
            </div>
          </div>
          <div style="font-size:12px;font-weight:700;font-family:monospace;color:${col};width:40px;text-align:right">${fmtH(h_bat)}</div>
          ${h_tot > h_bat ? `<div style="font-size:10px;color:#fbbf24;width:48px">+${fmtH(h_tot-h_bat)}☀️</div>` : '<div style="width:48px"></div>'}
        </div>`;
      }).join('') + `
      ${survival ? `<div style="margin-top:10px;padding:8px 10px;background:rgba(96,165,250,.08);border-radius:8px;display:flex;justify-content:space-between">
        <div style="font-size:11px;color:#94a3b8">🧠 Op geleerd patroon autonoom tot</div>
        <div style="font-size:13px;font-weight:700;font-family:monospace;color:#60a5fa">${survival.until_time||'—'}</div>
      </div>` : ''}
      <div style="display:flex;gap:12px;margin-top:10px;font-size:9px;color:#374151;justify-content:center">
        <span><span style="display:inline-block;width:8px;height:8px;background:#4ade80;border-radius:1px;margin-right:3px"></span>Batterij</span>
        <span><span style="display:inline-block;width:8px;height:8px;background:rgba(251,191,36,.5);border-radius:1px;margin-right:3px"></span>PV vandaag nog</span>
      </div>`;
    })();

    // ── Kosten ────────────────────────────────────────────────────────────────
    const kostenHtml = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
        <div style="background:rgba(255,255,255,.04);border-radius:9px;padding:10px 12px">
          <div style="font-size:9px;color:#64748b;margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px">Huidig tarief</div>
          <div style="font-size:20px;font-weight:700;font-family:monospace;color:${priceCol}">€${cur_price.toFixed(3)}</div>
          <div style="font-size:10px;color:#475569;margin-top:2px">per kWh all-in</div>
        </div>
        <div style="background:rgba(255,255,255,.04);border-radius:9px;padding:10px 12px">
          <div style="font-size:9px;color:#64748b;margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px">Kosten vandaag</div>
          <div style="font-size:20px;font-weight:700;font-family:monospace;color:#e2e8f0">€${today_eur.toFixed(2)}</div>
          <div style="font-size:10px;color:#475569;margin-top:2px">${saved_today > 0 ? 'PV bespaard: €' + saved_today.toFixed(2) : sc_pct > 0 ? 'Zelfconsumptie: ' + sc_pct.toFixed(0) + '%' : ''}</div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
        ${[
          ['Deze maand', '€'+month_eur.toFixed(2), '~€'+(month_eur/Math.max(1,new Date().getDate())).toFixed(2)+'/dag'],
          ['Dit jaar',   '€'+Math.round(year_eur), '~€'+Math.round(year_eur/12)+'/mnd'],
          ['Zelfcons.',  sc_pct.toFixed(0)+'%',    pv_done > 0 ? pv_done.toFixed(1)+' kWh PV' : '—'],
        ].map(([l,v,s]) => `<div style="background:rgba(255,255,255,.04);border-radius:9px;padding:8px 10px">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">${l}</div>
          <div style="font-size:15px;font-weight:700;font-family:monospace;color:#e2e8f0">${v}</div>
          <div style="font-size:9px;color:#475569;margin-top:2px">${s}</div>
        </div>`).join('')}
      </div>`;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block }
        ha-card { background:var(--ha-card-background,#1c1c1c); border-radius:12px; border:1px solid rgba(255,255,255,0.06); padding:14px 16px; font-family:var(--primary-font-family,sans-serif); color:#cbd5e1 }
        .tab-bar { display:flex; gap:2px; margin-bottom:14px; background:rgba(255,255,255,.04); border-radius:8px; padding:3px }
        .tab { flex:1; text-align:center; padding:5px 4px; font-size:11px; font-weight:600; border-radius:6px; cursor:pointer; color:#475569; transition:all .15s }
        .tab.active { background:rgba(255,255,255,.08); color:#f1f5f9 }
        .hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px }
      </style>
      <ha-card>
        <div class="hdr">
          <span style="font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#64748b">
            ${tab === 'offgrid' ? '⚡ Off-Grid Overleving' : '💶 Energiekosten'}
          </span>
          <span style="font-size:11px;font-weight:700;font-family:monospace;color:${batCol}">🔋 ${soc_pct.toFixed(0)}% · ${bat_kwh.toFixed(1)}kWh</span>
        </div>
        <div class="tab-bar">
          <div class="tab ${tab==='offgrid'?'active':''}" data-tab="offgrid">Off-Grid</div>
          <div class="tab ${tab==='kosten'?'active':''}" data-tab="kosten">Kosten</div>
        </div>
        ${tab === 'offgrid' ? offgridHtml : kostenHtml}
      </ha-card>`;

    this.shadowRoot.querySelectorAll('.tab').forEach(el =>
      el.addEventListener('click', () => { this._tab = el.dataset.tab; this._render(); }));
  }

  getCardSize() { return 3; }
  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-batterij-status-card'))
  customElements.define('cloudems-batterij-status-card', CloudEMSBatterijStatusCard);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-batterij-status-card'))
  window.customCards.push({ type: 'cloudems-batterij-status-card', name: 'CloudEMS Batterij Status' });
console.info(`%c CLOUDEMS-BATTERIJ-STATUS %c v${BST_VERSION} `, 'background:#4ade80;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px', 'background:#0e1520;color:#4ade80;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
