/**
 * CloudEMS Alerts Card  v1.0.0
 * Meldingen — actieve alerts, systeem-status, dempen
 */

const ALERTS_VERSION = '5.4.1';

// Prioriteit → kleur + icoon
const PRI = {
  critical: { col: '#f87171', bg: 'rgba(248,113,113,0.10)', border: 'rgba(248,113,113,0.3)', icon: '🔴' },
  warning:  { col: '#fbbf24', bg: 'rgba(251,191,36,0.08)',  border: 'rgba(251,191,36,0.25)', icon: '🟡' },
  info:     { col: '#7dd3fc', bg: 'rgba(125,211,252,0.07)', border: 'rgba(125,211,252,0.2)', icon: '🔵' },
};

// Categorie → icoon
const CAT_ICON = {
  pv: '☀️', battery: '🔋', boiler: '🛁', ev: '🚗', grid: '⚡',
  nilm: '🔍', shutter: '🪟', climate: '🌡️', system: '🤖',
  price: '💶', anomaly: '📊', gas: '🔥',
};

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const fmtAge = h => {
  if (h < 1)   return `${Math.round(h * 60)} min geleden`;
  if (h < 24)  return `${Math.round(h)} uur geleden`;
  return `${Math.round(h / 24)} dag${Math.round(h / 24) !== 1 ? 'en' : ''} geleden`;
};

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host{display:block}
  *{box-sizing:border-box;margin:0;padding:0}
  .card{background:#0e1520;border-radius:16px;border:1px solid rgba(255,255,255,0.06);font-family:'Syne',sans-serif;overflow:hidden}

  /* ── Header ── */
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid rgba(255,255,255,0.06)}
  .hdr-icon{font-size:20px}
  .hdr-texts{flex:1}
  .hdr-title{font-size:13px;font-weight:700;color:#f1f5f9;letter-spacing:.04em;text-transform:uppercase}
  .hdr-sub{font-size:11px;color:#6b7280;margin-top:2px}

  /* ── Stat strip ── */
  .stat-strip{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid rgba(255,255,255,0.05)}
  .stat-tile{padding:10px 6px;display:flex;flex-direction:column;align-items:center;gap:3px;border-right:1px solid rgba(255,255,255,0.05)}
  .stat-tile:last-child{border-right:none}
  .stat-lbl{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#374151;text-align:center}
  .stat-val{font-size:16px;font-weight:800;font-family:'JetBrains Mono',monospace}
  .c-green{color:#4ade80}.c-red{color:#f87171}.c-amber{color:#fbbf24}.c-blue{color:#7dd3fc}.c-muted{color:#4b5563}

  /* ── Alles goed banner ── */
  .all-ok{display:flex;align-items:center;gap:12px;padding:20px 18px;background:rgba(74,222,128,0.06);border-bottom:1px solid rgba(74,222,128,0.12)}
  .all-ok-icon{font-size:28px}
  .all-ok-text{font-size:13px;font-weight:600;color:#4ade80}
  .all-ok-sub{font-size:11px;color:#4b5563;margin-top:3px}

  /* ── Alert kaart ── */
  .alert-card{margin:10px 18px 0;border-radius:12px;overflow:hidden}
  .alert-card:last-of-type{margin-bottom:0}
  .alert-hdr{display:flex;align-items:center;gap:8px;padding:10px 14px 8px}
  .alert-icon{font-size:15px;flex-shrink:0}
  .alert-cat{font-size:10px;color:rgba(255,255,255,0.35)}
  .alert-title{font-size:13px;font-weight:700;flex:1}
  .alert-age{font-size:10px;font-family:'JetBrains Mono',monospace;white-space:nowrap}
  .alert-msg{padding:0 14px 8px;font-size:11px;color:rgba(255,255,255,0.55);line-height:1.6}
  .alert-footer{display:flex;justify-content:flex-end;padding:0 14px 10px}
  .mute-btn{font-size:10px;font-weight:700;padding:3px 10px;border-radius:8px;cursor:pointer;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.04);color:#4b5563;font-family:'Syne',sans-serif;transition:all .15s}
  .mute-btn:hover{background:rgba(255,255,255,0.08);color:#9ca3af}

  /* ── Sectie header ── */
  .sec-hdr{display:flex;align-items:center;gap:8px;padding:14px 18px 6px}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#374151}
  .sec-line{flex:1;height:1px;background:rgba(255,255,255,0.05)}

  /* ── Systeem status ── */
  .sys-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:0 18px 14px}
  .sys-tile{background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;display:flex;align-items:center;gap:10px;border:1px solid rgba(255,255,255,0.05)}
  .sys-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .sys-info{flex:1;min-width:0}
  .sys-name{font-size:11px;font-weight:600;color:#9ca3af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sys-val{font-size:10px;color:#4b5563;margin-top:2px;font-family:'JetBrains Mono',monospace}

  /* ── Uitleg ── */
  .info-box{margin:0 18px 14px;padding:12px 14px;background:rgba(255,255,255,0.02);border-radius:10px;border:1px solid rgba(255,255,255,0.05)}
  .info-row{display:flex;align-items:flex-start;gap:8px;padding:3px 0;font-size:11px;color:#4b5563;line-height:1.5}
  .info-row b{color:#6b7280}

  /* ── Footer links ── */
  .footer{display:flex;gap:8px;padding:10px 18px 14px;flex-wrap:wrap;border-top:1px solid rgba(255,255,255,0.05)}
  .flink{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:8px;font-size:11px;font-weight:600;text-decoration:none;cursor:pointer}
  .flink-bug{background:#1f2937;border:1px solid rgba(239,68,68,0.4);color:#f87171}
  .flink-feat{background:#1f2937;border:1px solid rgba(99,102,241,0.4);color:#a5b4fc}
  .flink-coffee{background:linear-gradient(135deg,rgb(245,158,11),rgb(217,119,6));color:rgb(26,16,0);border:none}
`;

class CloudEMSAlertsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._prev = '';
  }

  setConfig(c) { this._cfg = { title: 'Meldingen', ...c }; }

  set hass(h) {
    this._hass = h;
    const st = h.states['sensor.cloudems_actieve_meldingen'];
    const sig = [st?.state, JSON.stringify(st?.attributes?.active_alerts || [])].join('|');
    if (sig !== this._prev) { this._prev = sig; this._render(); }
  }

  _a(e, k, d = null) { return this._hass?.states?.[e]?.attributes?.[k] ?? d; }
  _s(e)              { return this._hass?.states?.[e] || null; }
  _sv(e, d = '—')    { const s = this._s(e); return s && !['unavailable','unknown'].includes(s.state) ? s.state : d; }

  _render() {
    const sh = this.shadowRoot;
    if (!sh || !this._hass) return;

    const alerts       = this._a('sensor.cloudems_actieve_meldingen', 'active_alerts', []);
    const critCount    = this._a('sensor.cloudems_actieve_meldingen', 'critical_count', 0);
    const warnCount    = this._a('sensor.cloudems_actieve_meldingen', 'warning_count', 0);
    const infoCount    = this._a('sensor.cloudems_actieve_meldingen', 'info_count', 0);
    const mutedCount   = this._a('sensor.cloudems_actieve_meldingen', 'muted_count', 0);
    const totalActive  = parseInt(this._sv('sensor.cloudems_actieve_meldingen', '0')) || 0;

    // ── Stat strip ────────────────────────────────────────────────────────
    const statHtml = `<div class="stat-strip">
      <div class="stat-tile">
        <span class="stat-lbl">Totaal</span>
        <span class="stat-val ${totalActive > 0 ? 'c-amber' : 'c-green'}">${totalActive}</span>
      </div>
      <div class="stat-tile">
        <span class="stat-lbl">Kritiek</span>
        <span class="stat-val ${critCount > 0 ? 'c-red' : 'c-muted'}">${critCount}</span>
      </div>
      <div class="stat-tile">
        <span class="stat-lbl">Waarschuwing</span>
        <span class="stat-val ${warnCount > 0 ? 'c-amber' : 'c-muted'}">${warnCount}</span>
      </div>
      <div class="stat-tile">
        <span class="stat-lbl">Gedempt</span>
        <span class="stat-val c-muted">${mutedCount}</span>
      </div>
    </div>`;

    // ── Alerts of alles-goed ──────────────────────────────────────────────
    let alertsHtml = '';
    if (alerts.length === 0) {
      alertsHtml = `<div class="all-ok">
        <span class="all-ok-icon">✅</span>
        <div>
          <div class="all-ok-text">Geen actieve meldingen</div>
          <div class="all-ok-sub">CloudEMS bewaakt alles en geeft een seintje als er iets is.</div>
        </div>
      </div>`;
    } else {
      // Sorteer: critical eerst, dan warning, dan info
      const sorted = [...alerts].sort((a, b) => {
        const order = { critical: 0, warning: 1, info: 2 };
        return (order[a.priority] ?? 3) - (order[b.priority] ?? 3);
      });
      alertsHtml = sorted.map(a => {
        const p   = PRI[a.priority] || PRI.info;
        const cat = CAT_ICON[a.category] || '⚡';
        return `<div class="alert-card" style="background:${p.bg};border:1px solid ${p.border}">
          <div class="alert-hdr">
            <span class="alert-icon">${p.icon}</span>
            <span class="alert-cat">${cat} ${esc(a.category || '')}</span>
            <span class="alert-title" style="color:${p.col}">${esc(a.title)}</span>
            <span class="alert-age" style="color:${p.col}88">${fmtAge(a.age_h || 0)}</span>
          </div>
          ${a.message ? `<div class="alert-msg">${esc(a.message)}</div>` : ''}
          ${a.key ? `<div class="alert-footer">
            <button class="mute-btn" data-mute="${esc(a.key)}">🔕 Dempen (24u)</button>
          </div>` : ''}
        </div>`;
      }).join('');
      alertsHtml = `<div style="padding:0 0 14px">${alertsHtml}</div>`;
    }

    // ── Systeem status ────────────────────────────────────────────────────
    const sysSensors = [
      { label: 'PV paneelgezondheid',  eid: 'sensor.cloudems_pv_paneelgezondheid',       unit: '%' },
      { label: 'Clipping verlies',      eid: 'sensor.cloudems_clipping_verlies',           unit: ' kWh' },
      { label: 'Apparaatdrift',         eid: 'sensor.cloudems_apparaat_efficientiedrift',  unit: '' },
      { label: 'Batterij gezondheid',   eid: 'sensor.cloudems_battery_state_of_health',    unit: '%' },
      { label: 'Verbruiksanomalie',     eid: 'binary_sensor.cloudems_home_baseline_anomalie', unit: '' },
      { label: 'Notificaties',          eid: 'switch.cloudems_module_notificaties',         unit: '' },
    ];

    const sysHtml = sysSensors.map(s => {
      const st    = this._s(s.eid);
      const avail = st && !['unavailable', 'unknown'].includes(st.state);
      if (!avail) return '';
      const val   = st.state;
      const isOk  = val === 'on' || val === 'off' || (parseFloat(val) > 80) || val === 'normal';
      const dotCol= val === 'on' ? '#4ade80'
                  : val === 'off' ? '#4b5563'
                  : '#9ca3af';
      const dispVal = val === 'on' ? 'Actief' : val === 'off' ? 'Inactief'
                    : val + (s.unit || '');
      return `<div class="sys-tile">
        <div class="sys-dot" style="background:${dotCol}"></div>
        <div class="sys-info">
          <div class="sys-name">${esc(s.label)}</div>
          <div class="sys-val">${esc(dispVal)}</div>
        </div>
      </div>`;
    }).filter(Boolean).join('');

    // ── Uitleg ────────────────────────────────────────────────────────────
    const infoHtml = `<div class="info-box">
      <div class="info-row"><b>🔴 Kritiek</b> — direct melding + herinnering na 6u</div>
      <div class="info-row"><b>🟡 Waarschuwing</b> — maximaal 1× per dag</div>
      <div class="info-row"><b>🔵 Info</b> — gebundeld in avonddigest (20:00)</div>
      <div class="info-row" style="margin-top:4px;color:#374151">Dempen onderdrukt een melding voor 24u via <code style="background:rgba(255,255,255,0.06);padding:1px 5px;border-radius:4px;font-size:10px">cloudems.mute_alert</code></div>
    </div>`;

    // ── Footer ────────────────────────────────────────────────────────────
    const footerHtml = `<div class="footer">
      <a class="flink flink-bug" href="https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.md" target="_blank">🐛 Bug melden</a>
      <a class="flink flink-feat" href="https://github.com/cloudemsNL/ha-cloudems/issues/new?template=feature_request.md" target="_blank">💡 Feature verzoek</a>
      <a class="flink flink-coffee" href="https://buymeacoffee.com/smarthost9m" target="_blank">☕ Steun CloudEMS</a>
    </div>`;

    sh.innerHTML = `<style>${CSS}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">🔔</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(this._cfg?.title || 'Meldingen')}</div>
          <div class="hdr-sub">${totalActive > 0 ? `${totalActive} actieve melding${totalActive !== 1 ? 'en' : ''}` : 'Alles in orde'}</div>
        </div>
      </div>
      ${statHtml}
      ${alertsHtml}
      <div class="sec-hdr"><span class="sec-title">Systeem status</span><div class="sec-line"></div></div>
      <div class="sys-grid">${sysHtml || '<div style="padding:0 18px 12px;font-size:11px;color:#374151">Geen status-sensoren beschikbaar</div>'}</div>
      <div class="sec-hdr"><span class="sec-title">Hoe werken meldingen?</span><div class="sec-line"></div></div>
      ${infoHtml}
      ${footerHtml}
    </div>`;

    // Dempen knoppen
    sh.querySelectorAll('[data-mute]').forEach(btn => {
      btn.addEventListener('click', () => {
        this._hass?.callService('cloudems', 'mute_alert', { alert_key: btn.dataset.mute });
        btn.textContent = '✓ Gedempt';
        btn.style.color = '#4ade80';
        btn.disabled = true;
      });
    });
  }

  getCardSize() { return 6; }
  static getConfigElement() { return document.createElement('cloudems-alerts-card-editor'); }
  static getStubConfig() { return { title: 'Meldingen' }; }
}

class CloudEMSAlertsCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); }
  setConfig(c) { this._cfg = { ...c }; this._render(); }
  _fire() { this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._cfg }, bubbles: true, composed: true })); }
  _render() {
    const cfg = this._cfg || {};
    this.shadowRoot.innerHTML = `
      <style>.wrap{padding:8px}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px}</style>
      <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" value="${esc(cfg.title || 'Meldingen')}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change', e => {
      this._cfg = { ...this._cfg, title: e.target.value }; this._fire();
    });
  }
}

if (!customElements.get('cloudems-alerts-card')) customElements.define('cloudems-alerts-card', CloudEMSAlertsCard);
if (!customElements.get('cloudems-alerts-card-editor')) customElements.define('cloudems-alerts-card-editor', CloudEMSAlertsCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: 'cloudems-alerts-card', name: 'CloudEMS Alerts Card', description: 'Meldingen, prioriteiten, systeem-status, dempen', preview: true });
console.info('%c CLOUDEMS-ALERTS-CARD %c v' + ALERTS_VERSION + ' ', 'background:#f87171;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px', 'background:#0e1520;color:#f87171;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
