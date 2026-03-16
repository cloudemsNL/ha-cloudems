// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. Unauthorized copying, redistribution, or commercial
// use of this file is strictly prohibited. See LICENSE for full terms.

/**
 * CloudEMS Custom Card Bundle
 * Version: 1.6.5
 * 
 * Cards:
 *   cloudems-chip-card    — status chip met template rendering (vervangt mushroom-template-card)
 *   cloudems-graph-card   — lijngrafieken uit HA history API (vervangt mini-graph-card)
 *   cloudems-flow-card    — energie-flow SVG diagram (vervangt power-flow-card-plus)
 *   cloudems-stack-card   — kaarten stapelen zonder extra rand (vervangt stack-in-card)
 *   cloudems-entity-list  — dynamische entiteitslijst (vervangt auto-entities)
 *
 * Proprietary — zie LICENSE. Niet kopiëren of herdistribueren.
 */

(function () {
  'use strict';

  // ─────────────────────────────────────────────────────────────────────────
  // GEMEENSCHAPPELIJKE STIJLEN
  // ─────────────────────────────────────────────────────────────────────────
  const BASE_CARD_STYLE = `
    :host { display: block; }
    ha-card {
      background: rgb(34,34,34);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.4);
      overflow: hidden;
      transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
    }
    ha-card:hover {
      border-color: rgba(0,177,64,0.5);
      box-shadow: 0 4px 20px rgba(0,0,0,0.5), 0 0 16px rgba(0,177,64,0.12);
      transform: translateY(-1px);
    }
  `;

  const COLOR_MAP = {
    green:  'rgb(0,212,78)',   red:    'rgb(240,100,100)',
    orange: 'rgb(255,165,0)',  blue:   'rgb(52,152,219)',
    yellow: 'rgb(255,214,0)',  purple: 'rgb(180,100,255)',
    grey:   'rgb(120,120,120)',gray:   'rgb(120,120,120)',
    teal:   'rgb(0,188,188)',  white:  'rgb(255,255,255)',
  };

  function resolveColor(name) {
    if (!name) return COLOR_MAP.grey;
    if (name.startsWith('rgb') || name.startsWith('#')) return name;
    return COLOR_MAP[name.toLowerCase()] || COLOR_MAP.grey;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-chip-card  ·  vervangt mushroom-template-card
  // Config: primary, secondary, icon, icon_color, tap_action
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsChipCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._config   = {};
      this._hass     = null;
      this._unsubs   = [];
      this._rendered = { primary: '', secondary: '', icon: '', icon_color: 'grey' };
    }

    setConfig(config) {
      this._config = config;
      this._render();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first) this._subscribeTemplates();
    }

    _subscribeTemplates() {
      const fields = ['primary', 'secondary', 'icon', 'icon_color'];
      fields.forEach(field => {
        const tpl = this._config[field];
        if (!tpl) return;
        // If it's a plain string (no template syntax), use directly
        if (!tpl.includes('{%') && !tpl.includes('{{')) {
          this._rendered[field] = tpl;
          this._render();
          return;
        }
        this._hass.connection.subscribeMessage(
          (msg) => {
            if (msg.result !== undefined) {
              this._rendered[field] = msg.result;
              this._render();
            }
          },
          { type: 'render_template', template: tpl, variables: {}, timeout: 30 }
        ).then(unsub => this._unsubs.push(unsub)).catch(() => {
          this._rendered[field] = tpl;
          this._render();
        });
      });
    }

    disconnectedCallback() {
      this._unsubs.forEach(u => { try { u(); } catch(_) {} });
      this._unsubs = [];
    }

    _render() {
      const { primary, secondary, icon, icon_color } = this._rendered;
      const color = resolveColor(icon_color);
      const hasTap = !!this._config.tap_action;

      this.shadowRoot.innerHTML = `
        <style>
          ${BASE_CARD_STYLE}
          ha-card {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 14px 16px;
            cursor: ${hasTap ? 'pointer' : 'default'};
          }
          .icon-wrap {
            width: 40px; height: 40px; border-radius: 50%;
            background: ${color}22;
            display: flex; align-items: center; justify-content: center;
            flex-shrink: 0;
          }
          .icon-wrap ha-icon { color: ${color}; --mdc-icon-size: 22px; }
          .icon-wrap .emoji { font-size: 20px; line-height: 1; }
          .text { flex: 1; min-width: 0; }
          .primary {
            color: rgb(255,255,255); font-size: 14px; font-weight: 600;
            line-height: 1.3; white-space: pre-wrap;
          }
          .secondary {
            color: rgb(163,163,163); font-size: 12px; line-height: 1.4;
            margin-top: 3px; white-space: pre-wrap;
          }
        </style>
        <ha-card>
          ${icon ? `
          <div class="icon-wrap">
            ${icon.startsWith('mdi:')
              ? `<ha-icon icon="${icon}"></ha-icon>`
              : `<span class="emoji">${icon}</span>`}
          </div>` : ''}
          <div class="text">
            ${primary   ? `<div class="primary">${primary}</div>`     : ''}
            ${secondary ? `<div class="secondary">${secondary}</div>` : ''}
          </div>
        </ha-card>
      `;

      if (hasTap) {
        this.shadowRoot.querySelector('ha-card').addEventListener('click', () => {
          this._handleTapAction();
        });
      }
    }

    _handleTapAction() {
      const action = this._config.tap_action;
      if (!action || !this._hass) return;
      if (action.action === 'perform-action' || action.action === 'call-service') {
        const svc = (action.perform_action || action.service || '').split('.');
        if (svc.length === 2) {
          this._hass.callService(svc[0], svc[1], action.data || {});
        }
      } else if (action.action === 'navigate') {
        history.pushState(null, '', action.navigation_path);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
    }

    static getConfigElement() { const el = document.createElement('div'); el.setConfig = () => {}; return el; }
    static getStubConfig()    { return { primary: 'CloudEMS', secondary: 'Status', icon: 'mdi:lightning-bolt' }; }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-graph-card  ·  vervangt mini-graph-card
  // Config: name, entities[], hours_to_show, points_per_hour, line_width, show{}
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsGraphCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._config  = { entities: [], hours_to_show: 24, line_width: 2, name: '' };
      this._hass    = null;
      this._history = {};
      this._loading = true;
      this._timer   = null;
      this._rendered = false;
    }

    setConfig(config) {
      this._config = {
        hours_to_show:   Number(config.hours_to_show)   || 24,
        points_per_hour: Number(config.points_per_hour) || 4,
        line_width:      Number(config.line_width)       || 2,
        name:            config.name || '',
        show:            Object.assign({ extrema: false, average: false }, config.show || {}),
        entities: (config.entities || []).map(e =>
          typeof e === 'string' ? { entity: e } : { ...e }
        ),
      };
    }

    set hass(hass) {
      this._hass = hass;
      // Update live waarden in config voor legenda
      (this._config.entities || []).forEach(e => {
        if (!e || !e.entity) return;
        const st = hass.states[e.entity];
        if (st) e._live = parseFloat(st.state);
      });
      if (!this._rendered) {
        this._rendered = true;
        this._render();
        this._fetch();
      }
    }

    connectedCallback() { if (this._hass && !this._rendered) { this._rendered = true; this._render(); this._fetch(); } }
    disconnectedCallback() { if (this._timer) clearTimeout(this._timer); }
    getCardSize() { return 3; }

    // ── Data ophalen ────────────────────────────────────────────────────────

    async _fetch() {
      if (!this._hass) return;
      const entities = (this._config.entities || []).filter(e => e && e.entity);
      if (entities.length === 0) { this._loading = false; this._render(); return; }

      const now   = new Date();
      const start = new Date(now - this._config.hours_to_show * 3600 * 1000);
      const ids   = entities.map(e => e.entity).join(',');

      try {
        const url = `history/period/${start.toISOString()}?filter_entity_id=${ids}&end_time=${now.toISOString()}&minimal_response&no_attributes`;
        const raw = await this._hass.callApi('GET', url);
        this._history = {};
        (raw || []).forEach(series => {
          if (!Array.isArray(series) || series.length === 0) return;
          const eid = series[0].entity_id;
          if (!eid) return;
          this._history[eid] = series
            .map(s => ({ t: new Date(s.last_changed).getTime(), v: parseFloat(s.state) }))
            .filter(s => isFinite(s.v));
        });
      } catch (err) {
        console.error('[CloudEMS graph-card] fetch fout:', err);
      }
      this._loading = false;
      this._render();
      // Refresh elke 5 minuten
      this._timer = setTimeout(() => this._fetch(), 300000);
    }

    // ── Render ──────────────────────────────────────────────────────────────

    _render() {
      if (!this.shadowRoot) return;
      try {
        this._renderInner();
      } catch(err) {
        console.error('[CloudEMS graph-card] render fout:', err);
        this.shadowRoot.innerHTML = `<ha-card><div style="padding:12px;color:#e74c3c;font-size:11px;font-family:monospace">
          ⚠️ Graph fout:<br><pre style="white-space:pre-wrap">${String(err)}</pre></div></ha-card>`;
      }
    }

    _renderInner() {
      const cfg      = this._config;
      const entities = Array.isArray(cfg.entities) ? cfg.entities.filter(e => e && e.entity) : [];
      const now      = Date.now();
      const start    = now - cfg.hours_to_show * 3600 * 1000;

      // Verzamel alle waarden voor schaal
      const allVals = [];
      entities.forEach(e => {
        (this._history[e.entity] || []).forEach(p => { if (p.t >= start && isFinite(p.v)) allVals.push(p.v); });
      });

      let vMin = allVals.length ? Math.min(...allVals) : 0;
      let vMax = allVals.length ? Math.max(...allVals) : 1;
      if (vMax <= vMin) { vMin = vMin - 1; vMax = vMax + 1; }
      const vRange = vMax - vMin;

      const W = 300, H = 90;
      const P = { t: 8, r: 6, b: 22, l: 38 };
      const gW = W - P.l - P.r;
      const gH = H - P.t - P.b;

      const tx = t => P.l + ((t - start) / (now - start)) * gW;
      const ty = v => P.t + (1 - (v - vMin) / vRange) * gH;

      // Grid
      const grid = [0, 0.25, 0.5, 0.75, 1].map(f =>
        `<line x1="${P.l}" y1="${(P.t + f*gH).toFixed(1)}" x2="${P.l+gW}" y2="${(P.t + f*gH).toFixed(1)}"
          stroke="rgba(255,255,255,0.04)" stroke-width="1"/>`
      ).join('') +
      `<line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${P.t+gH}" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
       <line x1="${P.l}" y1="${P.t+gH}" x2="${P.l+gW}" y2="${P.t+gH}" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>`;

      // Y labels
      const yLbls = [vMax, vMin + vRange*0.5, vMin].map((v, i) => {
        const y = [P.t + 4, P.t + gH/2 + 4, P.t + gH].map(n=>n.toFixed(1))[i];
        const lbl = Math.abs(v) >= 1000 ? (v/1000).toFixed(1)+'k' : v.toFixed(0);
        return `<text x="${P.l-3}" y="${y}" text-anchor="end" fill="rgba(255,255,255,0.3)" font-size="8">${lbl}</text>`;
      }).join('');

      // X labels — 4 tijdstippen
      const xLbls = [0,1,2,3,4].map(i => {
        const t = start + i * (now - start) / 4;
        const lbl = new Date(t).toLocaleTimeString('nl', { hour:'2-digit', minute:'2-digit' });
        return `<text x="${tx(t).toFixed(1)}" y="${H-4}" text-anchor="${i===0?'start':i===4?'end':'middle'}"
          fill="rgba(255,255,255,0.25)" font-size="8">${lbl}</text>`;
      }).join('');

      // Lijnen
      const lines = entities.map((e, ei) => {
        const series = (this._history[e.entity] || []).filter(p => p.t >= start && isFinite(p.v));
        if (series.length < 2) return '';
        const color = e.color || ['#00b140','#5dade2','#f39c12','#e74c3c','#9b59b6'][ei % 5];
        const lw    = cfg.line_width || 2;
        const pts   = series.map(p => `${tx(p.t).toFixed(1)},${ty(p.v).toFixed(1)}`).join(' ');
        const bot   = (P.t + gH).toFixed(1);
        const fill  = color.startsWith('#')
          ? color + '14'
          : color.replace('rgb(','rgba(').replace(')',',0.08)');
        return `
          <polygon points="${tx(series[0].t).toFixed(1)},${bot} ${pts} ${tx(series[series.length-1].t).toFixed(1)},${bot}"
            fill="${fill}" stroke="none"/>
          <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="${lw}"
            stroke-linecap="round" stroke-linejoin="round"/>`;
      }).join('');

      // Legenda
      const legend = entities.map((e, ei) => {
        const color = e.color || ['#00b140','#5dade2','#f39c12','#e74c3c','#9b59b6'][ei % 5];
        const name  = e.name || (e.entity||'').split('.').pop().replace(/_/g,' ');
        const live  = isFinite(e._live) ? ` <strong>${Math.abs(e._live) >= 1000 ? (e._live/1000).toFixed(2)+' kW' : e._live+' W'}</strong>` : '';
        return `<div class="li"><span class="ld" style="background:${color}"></span>${name}${live}</div>`;
      }).join('');

      // Stats
      let stats = '';
      if (allVals.length && (cfg.show.extrema || cfg.show.average)) {
        const parts = [];
        if (cfg.show.extrema)  parts.push(`Min: ${vMin.toFixed(1)} · Max: ${vMax.toFixed(1)}`);
        if (cfg.show.average)  parts.push(`Gem: ${(allVals.reduce((a,b)=>a+b,0)/allVals.length).toFixed(1)}`);
        stats = `<div class="st">${parts.join(' &nbsp; ')}</div>`;
      }

      const loading = this._loading
        ? `<div class="load">Laden…</div>`
        : (allVals.length === 0 ? `<div class="load">Geen data</div>` : '');

      this.shadowRoot.innerHTML = `
        <style>
          :host { display:block }
          ha-card { background:#111827; border:1px solid rgba(255,255,255,0.07); border-radius:12px; overflow:hidden; font-family:ui-monospace,monospace }
          .cc { padding:14px 14px 10px }
          .ttl { color:#e2e8f0; font-size:12px; font-weight:700; margin-bottom:10px }
          svg { width:100%; display:block }
          .leg { display:flex; flex-wrap:wrap; gap:10px; margin-top:10px }
          .li { display:flex; align-items:center; gap:5px; font-size:11px; color:rgba(255,255,255,0.55) }
          .li strong { color:#e2e8f0 }
          .ld { width:14px; height:3px; border-radius:2px; flex-shrink:0 }
          .st { font-size:10px; color:rgba(255,255,255,0.3); margin-top:5px }
          .load { font-size:11px; color:rgba(255,255,255,0.25); text-align:center; padding:20px 0 }
        </style>
        <ha-card>
          <div class="cc">
            ${cfg.name ? `<div class="ttl">${cfg.name}</div>` : ''}
            ${loading || `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
              ${grid}${yLbls}${xLbls}${lines}
            </svg>
            <div class="leg">${legend}</div>
            ${stats}`}
          </div>
        </ha-card>`;
    }

    static getConfigElement() { return document.createElement('cloudems-graph-card-editor'); }
    static getStubConfig() {
      return { name: 'Grafiek', hours_to_show: 24, entities: [{ entity: 'sensor.cloudems_home_rest', color: '#00b140', name: 'Thuis' }] };
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-flow-card  ·  v3.0 — redesign met CloudEMS inverter integratie
  // - Leest sensor.cloudems_solar_system voor live per-inverter data
  // - Dynamisch aantal solar nodes op basis van geconfigureerde inverters
  // - Moderne card layout met duidelijke nodes en vloeiende dot-animaties
  // - Stabiele render-architectuur: animatie loop losgekoppeld van hass updates
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsFlowCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._config         = {};
      this._hass           = null;
      this._animId         = null;
      this._dots           = {};
      this._tick           = 0;
      this._needsFullRender = true;
      this._valuesChanged  = false;
    }

    setConfig(config) {
      this._config = config;
      this._needsFullRender = true;
      this._startAnim();
    }

    set hass(hass) {
      this._hass = hass;
      this._valuesChanged = true;
    }

    disconnectedCallback() {
      if (this._animId) cancelAnimationFrame(this._animId);
      this._animId = null;
      if (this._visHandler) {
        document.removeEventListener('visibilitychange', this._visHandler);
        this._visHandler = null;
      }
    }

    connectedCallback() {
      if (!document.hidden && !this._animId) this._startAnim();
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    _getVal(entityConf) {
      if (!entityConf || !entityConf.entity || !this._hass) return 0;
      const state = this._hass.states[entityConf.entity];
      if (!state) return 0;
      let v = parseFloat(state.state) || 0;
      // Auto-convert kW sensors to W so all internal values are in Watts
      const unit = (state.attributes && state.attributes.unit_of_measurement) || '';
      if (unit.toLowerCase() === 'kw') v = v * 1000;
      // Manual multiply factor (e.g. multiply: 1000 in config)
      if (entityConf.multiply) v = v * entityConf.multiply;
      if (entityConf.invert_state) v = -v;
      return v;
    }

    _getSoc(entityConf) {
      if (!entityConf || !entityConf.state_of_charge || !this._hass) return null;
      const state = this._hass.states[entityConf.state_of_charge];
      return state ? Math.min(100, Math.max(0, parseFloat(state.state))) : null;
    }

    _fmt(w) {
      const thr = this._config.watt_threshold || 1000;
      if (Math.abs(w) >= thr) return (w / 1000).toFixed(2) + ' kW';
      return Math.round(w) + ' W';
    }

    // ── Multi-battery nodes uit sensor.cloudems_battery_so_c ─────────────────
    _getBatteryNodes() {
      if (!this._hass) return [];
      // Probeer battery_so_c sensor met all_batteries attribuut (multi-accu)
      const socState = this._hass.states['sensor.cloudems_battery_so_c'];
      if (socState && socState.attributes && socState.attributes.all_batteries) {
        return socState.attributes.all_batteries.map(b => ({
          label:   b.label || 'Batterij',
          soc_pct: b.soc_pct != null ? b.soc_pct : null,
          power_w: b.power_w || 0,
          action:  b.action || '',
        }));
      }
      // Fallback: single battery uit config
      const e = this._config.entities || {};
      if (e.battery) {
        const battState = this._hass.states[e.battery.entity];
        const socSt     = e.battery.state_of_charge ? this._hass.states[e.battery.state_of_charge] : null;
        let pw = battState ? parseFloat(battState.state) || 0 : 0;
        const unit = battState?.attributes?.unit_of_measurement || '';
        if (unit.toLowerCase() === 'kw') pw *= 1000;
        if (e.battery.invert_state) pw = -pw;
        return [{ label: e.battery.name || 'Batterij', soc_pct: socSt ? parseFloat(socSt.state) : null, power_w: pw, action: '' }];
      }
      return [];
    }

    // ── NILM top 3 uit sensor.cloudems_nilm_top_N_device ────────────────────
    _getNilmNodes() {
      if (!this._hass) return [];
      const nodes = [];
      for (let rank = 1; rank <= 4; rank++) {
        const st = this._hass.states[`sensor.cloudems_nilm_top_${rank}_device`];
        if (!st || st.state == null || st.state === 'unknown' || st.state === 'unavailable') continue;
        const pw = parseFloat(st.state) || 0;
        if (pw < 5) continue; // skip inactive
        const attr  = st.attributes || {};
        const name  = attr.name || attr.friendly_name || `Verbruiker ${rank}`;
        const color = attr.color || '#94a3b8';
        nodes.push({ label: name, power_w: pw, color });
      }
      return nodes;
    }

    // ── CloudEMS inverter data uit sensor.cloudems_solar_system ──────────────
    _getInverters() {
      if (!this._hass) return [];
      const e   = this._config.entities || {};
      const sysEntityId = (e.solar_system || {}).entity || 'sensor.cloudems_solar_system';
      // Try intelligence entity first (old name kept by HA entity registry with live data)
      const state = this._hass.states['sensor.cloudems_solar_system_intelligence']
                 ?? this._hass.states[sysEntityId];
      if (!state || !state.attributes) return [];
      const invs = state.attributes.inverters || [];
      if (invs.length === 0) return [];
      // Eenmalig loggen voor debug
      if (!this._invLogged) {
        this._invLogged = true;
        console.debug('[CloudEMS] inverters raw:', JSON.stringify(invs));
      }
      return invs
        .filter(i => i != null)  // null-entries verwijderen; peak_w=0 of null is OK (nog aan het leren)
        .map((i, idx) => ({
          label:   (i.label != null && String(i.label) !== '') ? String(i.label) : `Omvormer ${idx+1}`,
          w:       Math.max(0, parseFloat(i.current_w) || 0),
          peak_w:  parseFloat(i.peak_w) || 0,
        }))
        .slice(0, 3);
    }

    // ── Bewolkingsgraad uit utilisation_pct van solar_system ───────────────
    // Geeft 0 (helder) tot 1 (volledig bewolkt) terug
    _getCloudCover() {
      if (!this._hass) return null;
      const hour = new Date().getHours();
      const isDaytime = hour >= 6 && hour <= 21;
      if (!isDaytime) return null;

      // Gebruik HA weather entity als die geconfigureerd is
      const e = this._config.entities || {};
      const weatherId = (e.weather || {}).entity || null;
      if (weatherId) {
        const wst = this._hass.states[weatherId];
        if (wst) {
          const cond = (wst.state || '').toLowerCase();
          const condMap = {
            'sunny': 0.0, 'clear-night': null,
            'partlycloudy': 0.45, 'partly-cloudy': 0.45,
            'cloudy': 0.75, 'overcast': 0.90,
            'fog': 0.85, 'rainy': 0.88,
            'snowy': 0.80, 'pouring': 0.92,
            'lightning': 0.88, 'hail': 0.85,
            'windy': 0.15, 'windy-variant': 0.25,
          };
          if (cond in condMap) return condMap[cond];
          // Zoek op gedeeltelijke match
          for (const [k, v] of Object.entries(condMap)) {
            if (cond.includes(k)) return v;
          }
        }
      }

      // Fallback: gebruik solar utilisation uit cloudems_solar_system
      const sysId = (e.solar_system || {}).entity || 'sensor.cloudems_solar_system';
      const st = this._hass.states[sysId];
      if (!st || !st.attributes) return 0.5;
      const invs = st.attributes.inverters || [];
      if (invs.length === 0) return 0.5;
      const totalPeak = st.attributes.total_peak_w
        || invs.reduce((s, i) => s + (parseFloat(i.peak_w) || 0), 0);
      const totalNow  = invs.reduce((s, i) => s + (parseFloat(i.current_w) || 0), 0);
      if (totalPeak <= 0) return 0.5;
      return Math.max(0, Math.min(1, 1 - totalNow / totalPeak));
    }

    // Als geen CloudEMS solar_system beschikbaar: fallback op solar/solar2/solar3 entities
    _getSolarNodes() {
      const invs = this._getInverters();
      console.debug('[CloudEMS flow] _getSolarNodes: invs=', invs.length, invs.map(i=>i.label));
      if (invs.length > 0) return invs;
      const e = this._config.entities || {};
      const nodes = [];
      ['solar', 'solar2', 'solar3'].forEach((key, idx) => {
        if (e[key]) {
          nodes.push({
            label: (e[key].name || (idx === 0 ? 'Zon' : `Zon ${idx+1}`)),
            w:     Math.max(0, this._getVal(e[key])),
          });
        }
      });
      if (nodes.length === 0) nodes.push({ label: 'Zon', w: 0 });
      return nodes;
    }

    // ── Extra flow helpers ────────────────────────────────────────────────────

    _getBoilerNodes() {
      if (!this._hass) return [];
      const e = this._config.entities || {};
      if (e.boiler) return [{ label: e.boiler.name || 'Boiler', power_w: Math.max(0, this._getVal(e.boiler)) }];
      const st = this._hass.states['sensor.cloudems_boiler_status'];
      if (st) {
        const boilers = st.attributes?.boilers || [];
        if (boilers.length > 0) return boilers.map(b => ({
          label:   b.label || 'Boiler',
          power_w: Math.max(0, b.power_w ?? b.current_power_w ?? 0),
        }));
      }
      return [];
    }
    _getBoilerPower() {
      return this._getBoilerNodes().reduce((s, b) => s + b.power_w, 0);
    }

    _getEvPower() {
      if (!this._hass) return 0;
      const e = this._config.entities || {};
      if (e.ev) return Math.max(0, this._getVal(e.ev));
      // Lees uit cloudems_ev_sessie_leermodel → session_current_a * 230V
      const st = this._hass.states['sensor.cloudems_ev_sessie_leermodel'];
      if (st && st.attributes?.session_active) {
        const a = parseFloat(st.attributes.session_current_a) || 0;
        return a * 230;
      }
      return 0;
    }

    _getEbikePower() {
      if (!this._hass) return 0;
      const e = this._config.entities || {};
      if (e.ebike) return Math.max(0, this._getVal(e.ebike));
      // Lees uit cloudems_micro_mobiliteit → active_sessions[].power_w
      const st = this._hass.states['sensor.cloudems_micro_mobiliteit'];
      if (!st) return 0;
      return (st.attributes?.active_sessions || []).reduce((s, x) => s + (x.power_w || 0), 0);
    }

    _getPoolPower() {
      if (!this._hass) return 0;
      const e = this._config.entities || {};
      if (e.pool) return Math.max(0, this._getVal(e.pool));
      // Lees uit cloudems_zwembad_status → filter_entity + heat_entity vermogen
      const st = this._hass.states['sensor.cloudems_zwembad_status'];
      if (!st) return 0;
      let pw = 0;
      const filterEid = st.attributes?.filter_entity_id;
      const heatEid   = st.attributes?.heat_entity_id;
      if (filterEid && st.attributes?.filter_is_on) {
        const fst = this._hass.states[filterEid];
        pw += fst ? (parseFloat(fst.attributes?.current_power_w || fst.attributes?.power || 0)) : 150;
      }
      if (heatEid && st.attributes?.heat_is_on) {
        const hst = this._hass.states[heatEid];
        pw += hst ? (parseFloat(hst.attributes?.current_power_w || hst.attributes?.power || 0)) : 2000;
      }
      return pw;
    }

    // Device types die eigen nodes hebben — NOOIT in NILM laag tonen
    _isDedicatedNode(label, deviceType) {
      const dt = (deviceType || '').toLowerCase();
      const lb = (label || '').toLowerCase();
      const dedicated = ['boiler','water_heater','heat_pump','ev_charger','ev_lader',
                         'pool','zwembad','ebike','e-bike','micro_mobility','micro_mobiliteit'];
      return dedicated.some(k => dt.includes(k) || lb.includes(k));
    }

    // Layer2: max 5 nodes — topology meters (purple, with children) + direct NILM
    _getFlowLayer2() {
      if (!this._hass) return [];

      // Lees direct uit sensor.cloudems_nilm_running_devices — zelfde bron als detail panel
      const runSt = this._hass.states['sensor.cloudems_nilm_running_devices'];
      const running = runSt?.attributes?.device_list || runSt?.attributes?.devices || [];

      // Fallback: topology tree
      if (running.length === 0) {
        const topoSt = this._hass.states['sensor.cloudems_meter_topology'];
        const tree = topoSt?.attributes?.tree || [];
        const nodes = [];
        for (const node of tree) {
          if (nodes.length >= 5) break;
          if (!node.is_topology_meter) continue;
          const children = (node.children || [])
            .filter(c => !this._isDedicatedNode(c.name, c.device_type))
            .slice(0, 2)
            .map(c => ({ label: c.name || 'Apparaat', power_w: c.power_w || 0, color: '#a78bfa' }));
          nodes.push({ label: node.name || 'Meter', power_w: node.power_w || 0, color: '#a78bfa', isSub: true, children });
        }
        return nodes.slice(0, 5);
      }

      const TYPE_COLORS = {
        washing_machine:'#60a5fa', dryer:'#60a5fa', dishwasher:'#60a5fa',
        oven:'#f97316', microwave:'#f97316', boiler:'#f97316', cv_boiler:'#f97316',
        refrigerator:'#34d399', freezer:'#34d399',
        ev_charger:'#3bba4c', heat_pump:'#f59e0b',
        entertainment:'#c084fc', light:'#fbbf24', computer:'#94a3b8',
      };

      // Top 5 op vermogen, skip dedicated nodes
      return running
        .filter(d => (d.power_w || d.current_power || 0) > 1)
        .filter(d => !this._isDedicatedNode(d.name, d.device_type || d.type))
        .sort((a, b) => (b.power_w || b.current_power || 0) - (a.power_w || a.current_power || 0))
        .slice(0, 5)
        .map(d => ({
          label:   d.name || d.device_type || '?',
          power_w: d.power_w || d.current_power || 0,
          color:   TYPE_COLORS[d.device_type || d.type || ''] || '#94a3b8',
          phase:   d.phase || '',
          device_type: d.device_type || d.type || '',
          confidence:  d.confidence || 100,
          on_events:   d.on_events || 0,
          room:        d.room || '—',
          isSub: false, children: [],
        }));
    }

    // Sparkline history tracking (60 samples per key)
    _histPush(key, val) {
      if (!this._hist) this._hist = {};
      if (!this._hist[key]) this._hist[key] = Array.from({length: 60}, () => Math.abs(val));
      this._hist[key].push(Math.abs(val));
      if (this._hist[key].length > 60) this._hist[key].shift();
    }
    _sparkSvg(key, x, y, w, h, color) {
      const d = this._hist?.[key]; if (!d || d.length < 2) return '';
      const mx = Math.max(...d, 1);
      const pts = d.map((v, i) =>
        `${(x + i/(d.length-1)*w).toFixed(1)},${(y + h - (v/mx)*h).toFixed(1)}`
      ).join(' ');
      return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="0.9" opacity="0.28" stroke-linecap="round" stroke-linejoin="round"/>`;
    }

    // ── Animation loop ────────────────────────────────────────────────────────

    _initDots(pipeKeys) {
      pipeKeys.forEach(k => {
        if (!this._dots[k]) {
          this._dots[k] = Array.from({length: 5}, (_, i) => ({
            pos:   i * 0.2,
            speed: 0.0035 + Math.random() * 0.002,
          }));
        }
      });
    }

    _startAnim() {
      if (this._animId) cancelAnimationFrame(this._animId);
      // Mobile fix: pauzeer animatie als tab/pagina niet zichtbaar is
      if (!this._visHandler) {
        this._visHandler = () => {
          if (document.hidden) {
            if (this._animId) { cancelAnimationFrame(this._animId); this._animId = null; }
          } else {
            if (this.isConnected && !this._animId) this._startAnim();
          }
        };
        document.addEventListener('visibilitychange', this._visHandler, { passive: true });
      }
      let errorCount = 0;
      const loop = () => {
        if (!this.isConnected || document.hidden) { this._animId = null; return; }
        this._tick++;
        try {
          if (this._needsFullRender || (this._valuesChanged && this._tick % 30 === 0 && !this._activeNid)) {
            this._needsFullRender = false;
            this._valuesChanged   = false;
            this._renderFull();
          }
          Object.values(this._dots).forEach(arr => arr.forEach(d => {
            d.pos = (d.pos + d.speed) % 1;
          }));
          this._renderDots();
          errorCount = 0;
        } catch(e) {
          errorCount++;
          if (errorCount > 10) { this._animId = null; return; }
        }
        this._animId = requestAnimationFrame(loop);
      };
      this._animId = requestAnimationFrame(loop);
    }

    // ── Full render ───────────────────────────────────────────────────────────

    _renderFull() {
      const e           = this._config.entities || {};
      const grid        = this._getVal(e.grid);
      const home        = this._getVal(e.home);
      const solarNodes  = this._getSolarNodes();
      const battNodes   = this._getBatteryNodes();
      const boilerNodes = this._getBoilerNodes();
      const cloudCover  = this._getCloudCover();
      const ev          = this._getEvPower();
      const ebike       = this._getEbikePower();
      const pool        = this._getPoolPower();
      const layer2      = this._getFlowLayer2();
      const subs        = layer2.filter(n => n.isSub && n.children.length > 0);

      const totalSolar = solarNodes.reduce((s, n) => s + n.w, 0);
      const totalBattPw = battNodes.reduce((s, b) => s + b.power_w, 0);
      const totalBoiler = boilerNodes.reduce((s, b) => s + b.power_w, 0);

      const hour = new Date().getHours();
      const isNight = hour < 6 || hour > 21;

      // Sparkline history
      this._histPush('solar',  totalSolar);
      this._histPush('grid',   Math.abs(grid));
      this._histPush('home',   home);
      this._histPush('boiler', totalBoiler);
      this._histPush('batt',   Math.abs(totalBattPw));
      this._histPush('ev',     ev);
      this._histPush('ebike',  ebike);
      this._histPush('pool',   pool);
      layer2.forEach((n, i) => this._histPush(`l2_${i}`, n.power_w));

      // ── Layout ─────────────────────────────────────────────────────────────
      const W = 500;
      const COL_LEFT = 78, COL_HUB = 250, COL_R = 430;
      const R_SUN   = 30,  R_GRID  = 52,  R_BATT = 110;
      const R_EV    = 122, R_HUB   = 172, R_BOI  = 230;
      const R_EBIKE = 232, R_POOL  = 302;
      const R_HOME  = 400, R_L2    = 480, R_L3   = 556;
      const hasL3 = subs.some(s => s.children.length > 0);
      const H = hasL3 ? R_L3 + 46 : layer2.length > 0 ? R_L2 + 46 : R_HOME + 40;

      const T = 10;
      const gc      = grid > T ? '#e74c3c' : '#2ecc71';
      const bfc     = totalBattPw < -T ? '#2ecc71' : '#e74c3c';
      const battActive   = Math.abs(totalBattPw) > T;
      const gridActive   = Math.abs(grid) > T;
      const homeActive   = home > T;
      const boilerActive = totalBoiler > T;
      const solarActive  = totalSolar > T;

      const C = {
        solar: '#f5c518', grid_in: '#e74c3c', grid_ex: '#2ecc71',
        bc: '#2ecc71', bd: '#e74c3c', batt: '#5dade2',
        home: '#27ae60', boiler: '#e67e22',
        ev: '#3bba4c', ebike: '#06b6d4', pool: '#38bdf8',
        sub: '#a78bfa', text: '#e2e8f0',
      };

      // Single positions for solar/batt/boiler
      const solarX = COL_HUB, solarY = R_SUN;
      const battX  = COL_R - 38, battY = R_BATT;
      const bolX   = COL_R - 34 + 34, bolY = R_BOI + 17;

      // Init dots
      const pipeKeys = [
        'grid', 'solar', 'batt', 'boiler', 'home', 'ev', 'ebike', 'pool',
        ...layer2.map((_, i) => `l2_${i}`),
        ...subs.flatMap((s, si) => s.children.map((_, ci) => `l3_${si}_${ci}`)),
      ];
      this._initDots(pipeKeys);

      // ── SVG helpers ───────────────────────────────────────────────────────
      const pipe = (x1, y1, x2, y2, color, on) =>
        `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"
          stroke="${color}" stroke-width="2.5" stroke-linecap="round" opacity="${on ? .32 : .15}"/>`;

      const arw = (x1, y1, x2, y2, color, on) => {
        if (!on) return '';
        const dx = x2-x1, dy = y2-y1, len = Math.hypot(dx, dy);
        if (len < 1) return '';
        const ux = dx/len, uy = dy/len;
        const mx = (x1+x2)/2, my = (y1+y2)/2;
        const ax = mx-ux*5, ay = my-uy*5, bx = mx+ux*5, by = my+uy*5;
        const px = -uy*3.5, py = ux*3.5;
        return `<polygon points="${bx.toFixed(1)},${by.toFixed(1)} ${(ax+px).toFixed(1)},${(ay+py).toFixed(1)} ${(ax-px).toFixed(1)},${(ay-py).toFixed(1)}"
          fill="${color}" opacity="0.8"/>`;
      };

      const hubEdge = (fx, fy, inset=26) => {
        const dx = COL_HUB - fx, dy = R_HUB - fy;
        const len = Math.hypot(dx, dy);
        if (len < 1) return [COL_HUB, R_HUB];
        return [COL_HUB - dx/len*inset, R_HUB - dy/len*inset];
      };

      // Clickable nodeBox — all main nodes get data-nid
      const nodeBox = (cx, cy, bw, bh, color, on, label, val, sub2, sk, nid) => {
        const x = cx-bw/2, y = cy-bh/2;
        const glow = on ? `filter:drop-shadow(0 0 8px ${color}50)` : '';
        const click = nid ? `data-nid="${nid}" data-npw="${val}" data-ncolor="${color}" style="${glow};cursor:pointer"` : `style="${glow}"`;
        const sp = sk ? this._sparkSvg(sk, x+5, y+bh-14, bw-10, 10, color) : '';
        return `<g ${click}>
          <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="8"
            fill="#111827" stroke="${on?color:'rgba(255,255,255,0.09)'}" stroke-width="${on?1.5:1}"/>
          <text x="${cx}" y="${cy-(sub2?8:3)}" text-anchor="middle" font-size="12" font-weight="700"
            fill="${on?C.text:'rgba(255,255,255,0.25)'}">${val}</text>
          <text x="${cx}" y="${cy+10}" text-anchor="middle" font-size="8" font-weight="600"
            letter-spacing="0.07em" fill="${on?color:'rgba(255,255,255,0.16)'}">${label}</text>
          ${sub2?`<text x="${cx}" y="${cy+22}" text-anchor="middle" font-size="7.5"
            fill="rgba(255,255,255,0.25)">${sub2}</text>`:''}
          ${sp}
        </g>`;
      };

      // Single battery node (clickable)
      const battBox = () => {
        const pw  = totalBattPw;
        const soc = battNodes[0]?.soc_pct ?? null;
        const on  = Math.abs(pw) > T, ch = pw < -T;
        const fc  = ch ? C.bc : C.bd;
        const sc  = !soc ? C.batt : soc > 60 ? '#2ecc71' : soc > 25 ? '#f39c12' : '#e74c3c';
        const bw  = 76, bh = soc != null ? 60 : 44, x = battX-bw/2, y = battY-bh/2;
        const fw  = ((soc||0)/100*52).toFixed(1);
        const sp  = this._sparkSvg('batt', x+5, y+bh-14, bw-10, 10, fc);
        const glow = on ? `filter:drop-shadow(0 0 10px ${fc}55)` : '';
        return `<g style="${glow};cursor:pointer" data-nid="bat" data-ncolor="${fc}" data-npw="${Math.abs(pw)}">
          <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="8"
            fill="#111827" stroke="${on?fc:'rgba(255,255,255,0.09)'}" stroke-width="${on?1.5:1}"/>
          <text x="${battX}" y="${battY-(soc!=null?13:3)}" text-anchor="middle" font-size="12" font-weight="700"
            fill="${on?C.text:'rgba(255,255,255,0.25)'}">${this._fmt(Math.abs(pw))}</text>
          <text x="${battX}" y="${battY+(soc!=null?1:10)}" text-anchor="middle" font-size="7.5" font-weight="600"
            letter-spacing="0.07em" fill="${on?fc:'rgba(255,255,255,0.16)'}">${ch?'▽ LADEN':'△ ONTLADEN'}</text>
          ${soc!=null?`
            <rect x="${battX-26}" y="${battY+9}" width="52" height="4" rx="2" fill="rgba(255,255,255,0.07)"/>
            <rect x="${battX-26}" y="${battY+9}" width="${fw}" height="4" rx="2" fill="${sc}"/>
            <text x="${battX}" y="${battY+23}" text-anchor="middle" font-size="7.5" fill="rgba(255,255,255,0.28)">${(soc||0).toFixed(0)}% SoC</text>
          `:''}
          ${sp}
        </g>`;
      };

      const hubSvg = () => {
        const active = gridActive||homeActive||battActive||solarActive||boilerActive;
        return `<g style="${active?'filter:drop-shadow(0 0 14px rgba(255,255,255,0.12))':''}">
          <circle cx="${COL_HUB}" cy="${R_HUB}" r="26" fill="#0d1117" stroke="rgba(255,255,255,0.12)" stroke-width="1.5"/>
          <circle cx="${COL_HUB}" cy="${R_HUB}" r="20" fill="#111827" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
          <text x="${COL_HUB}" y="${R_HUB+4}" text-anchor="middle" font-size="9" font-weight="700"
            letter-spacing="0.1em" fill="rgba(255,255,255,0.4)">HUB</text>
        </g>`;
      };

      const solarNodeSvg = () => {
        if (isNight) {
          const moonR = 9, moonColor = '#b0c8e8';
          const sp = this._sparkSvg('solar', solarX-30, solarY+18, 60, 10, moonColor);
          return `<g style="cursor:pointer" data-nid="solar" data-ncolor="${moonColor}" data-npw="0">
            <defs><clipPath id="moon-clip"><rect x="${solarX}" y="${solarY-moonR-2}" width="${moonR+4}" height="${(moonR+2)*2}"/></clipPath></defs>
            <g style="filter:drop-shadow(0 0 6px rgba(176,200,232,0.4))">
              <circle cx="${solarX}" cy="${solarY}" r="${moonR}" fill="${moonColor}" clip-path="url(#moon-clip)"/>
              <circle cx="${solarX+moonR*.55}" cy="${solarY-moonR*.1}" r="${moonR*.75}" fill="#0f172a"/>
            </g>
            <text x="${solarX}" y="${solarY+27}" text-anchor="middle" font-size="11" font-weight="700" fill="rgba(255,255,255,0.2)">0 W</text>
            <text x="${solarX}" y="${solarY+38}" text-anchor="middle" font-size="8" font-weight="600" letter-spacing=".06em" fill="${moonColor}">NACHT</text>
            ${sp}
          </g>`;
        }
        const w = totalSolar;
        const on = w > T;
        const lbl = solarNodes.length > 1 ? `${solarNodes.length} omvormers` : (solarNodes[0]?.label || 'Zon');
        const cover = cloudCover != null ? cloudCover : (on ? 0.1 : 0.9);
        const bright = Math.pow(1 - cover, 0.6);
        const r = Math.round(245*bright + 140*(1-bright));
        const g = Math.round(197*bright + 140*(1-bright));
        const b = Math.round(24 *bright + 140*(1-bright));
        const sunColor = `rgb(${r},${g},${b})`;
        const sunR = on ? Math.round(9 + bright*4) : 7;
        const nRays = on ? (cover<0.3 ? 12 : cover<0.6 ? 8 : 6) : 0;
        const rayIn = sunR+2.5, rayOut = sunR+(cover<0.3?8:cover<0.6?5:3);
        const rays = on ? Array.from({length:nRays},(_,i)=>{
          const a=(i*360/nRays)*Math.PI/180;
          return `<line x1="${(solarX+Math.cos(a)*rayIn).toFixed(1)}" y1="${(solarY+Math.sin(a)*rayIn).toFixed(1)}"
            x2="${(solarX+Math.cos(a)*rayOut).toFixed(1)}" y2="${(solarY+Math.sin(a)*rayOut).toFixed(1)}"
            stroke="${sunColor}" stroke-width="${cover<0.3?1.8:1.4}" stroke-linecap="round" opacity="${(bright*.9).toFixed(2)}"/>`;
        }).join('') : '';
        const glowSz = Math.round(3+bright*10);
        const glow = on ? `filter:drop-shadow(0 0 ${glowSz}px ${sunColor})` : '';
        const showCloud = cover > 0.25 && on;
        const cloudOp = Math.min(1,(cover-0.25)/0.6).toFixed(2);
        const cOX = Math.round((cover-0.25)*18), cOY = Math.round((cover-0.25)*6);
        const cloud = showCloud ? (() => {
          const ox=solarX+cOX-8, oy=solarY+cOY-4;
          return `<g opacity="${cloudOp}">
            <ellipse cx="${ox+10}" cy="${oy+6}" rx="9"  ry="6" fill="#b0bec5"/>
            <ellipse cx="${ox+18}" cy="${oy+4}" rx="7"  ry="5" fill="#cfd8dc"/>
            <ellipse cx="${ox+25}" cy="${oy+6}" rx="8"  ry="6" fill="#b0bec5"/>
            <ellipse cx="${ox+17}" cy="${oy+9}" rx="13" ry="5" fill="#cfd8dc"/>
          </g>`;
        })() : '';
        const sp = this._sparkSvg('solar', solarX-30, solarY+18, 60, 10, sunColor);
        return `<g style="${glow};cursor:pointer" data-nid="solar" data-ncolor="${sunColor}" data-npw="${w}">
          ${on&&bright>0.3?`<circle cx="${solarX}" cy="${solarY}" r="${sunR+12}" fill="${sunColor}" opacity="${(bright*.10).toFixed(2)}"/>`:``}
          <circle cx="${solarX}" cy="${solarY}" r="${sunR}" fill="${on?sunColor:'rgba(255,255,255,0.07)'}"/>
          ${rays}${cloud}
          <text x="${solarX}" y="${solarY+27}" text-anchor="middle" font-size="11" font-weight="700"
            fill="${on?C.text:'rgba(255,255,255,0.25)'}">${this._fmt(w)}</text>
          <text x="${solarX}" y="${solarY+38}" text-anchor="middle" font-size="8" font-weight="600"
            letter-spacing="0.06em" fill="${on?sunColor:'rgba(255,255,255,0.2)'}">${lbl.toUpperCase().slice(0,12)}</text>
          ${sp}
        </g>`;
      };

      // ── Build SVG ─────────────────────────────────────────────────────────
      let h = '';

      const subBox = (cx, cy, node, idx) => {
        const on = node.power_w > T;
        const bw = 86, bh = 46, x = cx-bw/2, y = cy-bh/2;
        const sp = this._sparkSvg(`l2_${idx}`, x+5, y+bh-14, bw-10, 10, C.sub);
        const glow = on ? `filter:drop-shadow(0 0 8px #a78bfa44)` : '';
        return `<g style="${glow};cursor:pointer" data-nid="sub_${idx}" data-nlabel="${node.label}" data-npw="${node.power_w}" data-ncolor="${C.sub}">
          <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="8"
            fill="#160f2a" stroke="${on?C.sub:'rgba(167,139,250,0.18)'}" stroke-width="${on?1.8:1}"/>
          <text x="${cx}" y="${cy-4}" text-anchor="middle" font-size="12" font-weight="700"
            fill="${on?C.text:'rgba(255,255,255,0.25)'}">${this._fmt(node.power_w)}</text>
          <text x="${cx}" y="${cy+10}" text-anchor="middle" font-size="8" font-weight="600"
            letter-spacing="0.07em" fill="${on?C.sub:'rgba(167,139,250,0.28)'}">${node.label.toUpperCase()}</text>
          ${sp}
        </g>`;
      };

      const nilmBox = (cx, cy, node) => {
        const on = node.power_w > T;
        const color = node.color || '#94a3b8';
        const short = node.label.length > 9 ? node.label.slice(0,8)+'…' : node.label;
        const bw = 74, bh = 44, x = cx-bw/2, y = cy-bh/2;
        const glow = on ? `filter:drop-shadow(0 0 7px ${color}44)` : '';
        const nid = `nilm_${node.label}`;
        return `<g style="${glow};cursor:pointer" data-nid="${nid}" data-nlabel="${node.label}" data-npw="${node.power_w}" data-ncolor="${color}" data-nphase="${node.phase||''}" data-ntype="${node.device_type||''}" data-nconf="${node.confidence||100}" data-nevents="${node.on_events||0}" data-nroom="${node.room||'—'}">
          <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="8"
            fill="#0d1117" stroke="${on?color:'rgba(255,255,255,0.08)'}" stroke-width="${on?1.5:1}"/>
          <text x="${cx}" y="${cy-4}" text-anchor="middle" font-size="11" font-weight="700"
            fill="${on?C.text:'rgba(255,255,255,0.25)'}">${this._fmt(node.power_w)}</text>
          <text x="${cx}" y="${cy+10}" text-anchor="middle" font-size="7.5" font-weight="600"
            letter-spacing="0.07em" fill="${on?color:'rgba(255,255,255,0.2)'}">${short.toUpperCase()}</text>
        </g>`;
      };

      // Pipes
      const [_heGrid_x, _heGrid_y] = hubEdge(COL_LEFT+44, R_GRID);
      const [_heSol_x,  _heSol_y ] = hubEdge(solarX, solarY+46);
      const [_heBat_x,  _heBat_y ] = hubEdge(battX, battY);
      const [_heBol_x,  _heBol_y ] = hubEdge(bolX, bolY);
      const [_heEv_x,   _heEv_y  ] = hubEdge(COL_LEFT+44, R_EV);
      const [_heEbike_x,_heEbike_y] = hubEdge(COL_LEFT+44, R_EBIKE);
      const [_hePool_x, _hePool_y ] = hubEdge(COL_LEFT+44, R_POOL);
      const [_heHome_x, _heHome_y ] = hubEdge(COL_HUB, R_HOME);

      // L2 spread — moet vóór pipes/arrows staan
      const spreadXs = (n, w, margin) => {
        if (n === 1) return [w / 2];
        const step = (w - 2 * margin) / (n - 1);
        return Array.from({length: n}, (_, i) => margin + i * step);
      };
      const L2_XS = layer2.length > 0 ? spreadXs(layer2.length, W, 50) : [];

      h += pipe(COL_LEFT+44, R_GRID, _heGrid_x, _heGrid_y, gc, gridActive);
      h += pipe(solarX, solarY+46, _heSol_x, _heSol_y, C.solar, solarActive);
      h += pipe(battX, battY, _heBat_x, _heBat_y, bfc, battActive);
      h += pipe(_heBol_x, _heBol_y, bolX, bolY, C.boiler, boilerActive);
      h += pipe(_heHome_x, _heHome_y, COL_HUB, R_HOME-17, C.home, homeActive);
      h += pipe(COL_LEFT+44, R_EV,    _heEv_x,    _heEv_y,    C.ev,    ev>T);
      h += pipe(COL_LEFT+44, R_EBIKE, _heEbike_x, _heEbike_y, C.ebike, ebike>T);
      h += pipe(COL_LEFT+44, R_POOL,  _hePool_x,  _hePool_y,  C.pool,  pool>T);
      layer2.forEach((node, i) =>
        h += pipe(COL_HUB, R_HOME+17, L2_XS[i], R_L2-22, node.isSub?C.sub:node.color, node.power_w>T));
      subs.forEach((s, si) => {
        const sx = L2_XS[layer2.indexOf(s)];
        const cxs = s.children.length===1 ? [sx] : [sx-40, sx+40];
        s._cxs = cxs;
        s.children.forEach((c, ci) => h += pipe(sx, R_L2+22, cxs[ci], R_L3-18, C.sub, c.power_w>T));
      });

      // Arrows
      h += grid>T ? arw(COL_LEFT+44,R_GRID,_heGrid_x,_heGrid_y,gc,true) : arw(_heGrid_x,_heGrid_y,COL_LEFT+44,R_GRID,gc,gridActive);
      h += arw(solarX, solarY+46, _heSol_x, _heSol_y, C.solar, solarActive);
      h += totalBattPw < -T ? arw(_heBat_x,_heBat_y,battX,battY,bfc,battActive) : arw(battX,battY,_heBat_x,_heBat_y,bfc,battActive);
      h += arw(_heBol_x,_heBol_y,bolX,bolY,C.boiler,boilerActive);
      h += arw(_heHome_x,_heHome_y,COL_HUB,R_HOME-17,C.home,homeActive);
      h += arw(_heEv_x,_heEv_y,COL_LEFT+44,R_EV,C.ev,ev>T);
      h += arw(_heEbike_x,_heEbike_y,COL_LEFT+44,R_EBIKE,C.ebike,ebike>T);
      h += arw(_hePool_x,_hePool_y,COL_LEFT+44,R_POOL,C.pool,pool>T);
      layer2.forEach((node, i) =>
        h += arw(COL_HUB,R_HOME+17,L2_XS[i],R_L2-22,node.isSub?C.sub:node.color,node.power_w>T));
      subs.forEach(s => {
        const sx = L2_XS[layer2.indexOf(s)];
        (s._cxs||[]).forEach((cx, ci) => h += arw(sx,R_L2+22,cx,R_L3-18,C.sub,s.children[ci].power_w>T));
      });

      h += `<g id="dots-layer"></g>`;

      // Nodes
      h += solarNodeSvg();
      h += hubSvg();
      const gridLabel = `${grid > T ? '▲' : '▼'} NET`;
      const gridSub2  = grid > T ? 'import' : 'export';
      h += nodeBox(COL_LEFT, R_GRID,  88, 38, gc,       gridActive,   gridLabel,    this._fmt(Math.abs(grid)), gridSub2,  'grid',   'grid');
      h += nodeBox(COL_LEFT, R_EV,    88, 38, C.ev,     ev>T,         '🚗 EV LADER', this._fmt(ev),            null,      'ev',     'ev');
      h += nodeBox(COL_LEFT, R_EBIKE, 88, 38, C.ebike,  ebike>T,      '🚲 E-BIKE',   this._fmt(ebike),          null,      'ebike',  'ebike');
      h += nodeBox(COL_LEFT, R_POOL,  88, 38, C.pool,   pool>T,       '🏊 ZWEMBAD',  this._fmt(pool),           null,      'pool',   'pool');
      h += nodeBox(bolX,     bolY,    76, 38, C.boiler, boilerActive, '🚿 BOILER',   this._fmt(totalBoiler),    null,      'boiler', 'boiler');
      h += battBox();
      const homeName = (e.home||{}).name || 'Thuis';
      h += nodeBox(COL_HUB, R_HOME, 64, 38, C.home, homeActive, homeName.toUpperCase(), this._fmt(home), null, 'home', 'home');
      layer2.forEach((node, i) => {
        if (node.isSub) h += subBox(L2_XS[i], R_L2, node, i);
        else            h += nilmBox(L2_XS[i], R_L2, node);
      });
      subs.forEach(s => (s._cxs||[]).forEach((cx, ci) => h += nilmBox(cx, R_L3, s.children[ci])));

      // Pipe defs for animation
      this._pipeDefs = [
        { key:'grid',   color:gc,      on:gridActive,   pw:Math.abs(grid),
          x1:grid>T?COL_LEFT+44:_heGrid_x, y1:grid>T?R_GRID:_heGrid_y,
          x2:grid>T?_heGrid_x:COL_LEFT+44, y2:grid>T?_heGrid_y:R_GRID },
        { key:'solar',  color:C.solar, on:solarActive,  pw:totalSolar,   x1:solarX, y1:solarY+46, x2:_heSol_x, y2:_heSol_y },
        { key:'batt',   color:bfc,     on:battActive,   pw:Math.abs(totalBattPw),
          x1:totalBattPw<-T?_heBat_x:battX, y1:totalBattPw<-T?_heBat_y:battY,
          x2:totalBattPw<-T?battX:_heBat_x, y2:totalBattPw<-T?battY:_heBat_y },
        { key:'boiler', color:C.boiler,on:boilerActive, pw:totalBoiler,  x1:_heBol_x, y1:_heBol_y, x2:bolX, y2:bolY },
        { key:'home',   color:C.home,  on:homeActive,   pw:home,
          x1:_heHome_x, y1:_heHome_y, x2:COL_HUB, y2:R_HOME-17 },
        { key:'ev',     color:C.ev,    on:ev>T,    pw:ev,    x1:_heEv_x,    y1:_heEv_y,    x2:COL_LEFT+44, y2:R_EV },
        { key:'ebike',  color:C.ebike, on:ebike>T, pw:ebike, x1:_heEbike_x, y1:_heEbike_y, x2:COL_LEFT+44, y2:R_EBIKE },
        { key:'pool',   color:C.pool,  on:pool>T,  pw:pool,  x1:_hePool_x,  y1:_hePool_y,  x2:COL_LEFT+44, y2:R_POOL },
        ...layer2.map((node, i) => ({
          key:`l2_${i}`, color:node.isSub?C.sub:node.color,
          on:node.power_w>T, pw:node.power_w,
          x1:COL_HUB, y1:R_HOME+17, x2:L2_XS[i], y2:R_L2-22 })),
        ...subs.flatMap((s, si) => {
          const sx = L2_XS[layer2.indexOf(s)];
          return (s._cxs||[]).map((cx, ci) => ({
            key:`l3_${si}_${ci}`, color:C.sub,
            on:s.children[ci].power_w>T, pw:s.children[ci].power_w,
            x1:sx, y1:R_L2+22, x2:cx, y2:R_L3-18 }));
        }),
      ];

      // ── Build detail content for main nodes ───────────────────────────────
      const H_HASS = this._hass;
      const _fa = (eid, attr, def) => H_HASS?.states[eid]?.attributes?.[attr] ?? def;
      const _fv = (eid, def=0) => { const s=H_HASS?.states[eid]; if(!s||s.state==='unavailable'||s.state==='unknown') return def; return parseFloat(s.state)||def; };

      this._nodeData = {
        grid: {
          title: 'Net · import/export', color: gc,
          metrics: [
            {l:'Nu', v:this._fmt(Math.abs(grid)), sub: grid>T?'import':'export'},
            {l:'Import vandaag', v:this._fmt(_fv('sensor.cloudems_import_energy_today')*1000)},
            {l:'Export vandaag', v:this._fmt(_fv('sensor.cloudems_export_energy_today')*1000)},
            {l:'EPEX prijs', v:_fa('sensor.cloudems_price_current_hour',null,null) !== null ? (parseFloat(H_HASS?.states['sensor.cloudems_price_current_hour']?.state||0)*100).toFixed(1)+' ct' : '—'},
            {l:'Tarief', v:_fa('sensor.cloudems_batterij_epex_schema','zonneplan',{})?.tariff_group || '—'},
          ],
          note: grid > T ? `Importeert ${this._fmt(grid)} van het net.` : `Exporteert ${this._fmt(Math.abs(grid))} naar het net.`,
        },
        solar: {
          title: 'Zonnepanelen', color: C.solar,
          metrics: [
            {l:'Productie nu',  v: this._fmt(totalSolar)},
            {l:'Vandaag',       v: (() => { const s=H_HASS?.states['sensor.cloudems_pv_forecast_today']; return s&&s.state!=='unavailable'?parseFloat(s.state).toFixed(2)+' kWh':'—'; })()},
            {l:'Morgen fcst',   v: (() => { const s=H_HASS?.states['sensor.cloudems_pv_forecast_tomorrow']; return s&&s.state!=='unavailable'?parseFloat(s.state).toFixed(2)+' kWh':'—'; })()},
            {l:'Piek 7d',       v: this._fmt(Math.max(...solarNodes.map(n=>n.peak_w||0)))},
            {l:'Zekerheid',     v: (() => { const s=H_HASS?.states['sensor.cloudems_pv_forecast_accuracy']; return s&&s.state!=='unavailable'?Math.round(parseFloat(s.state))+'%':'—'; })()},
            ...solarNodes.map(n => ({l: n.label, v: this._fmt(n.w), sub: n.peak_w?'piek: '+this._fmt(n.peak_w):''})),
          ],
          note: `${solarNodes.length} omvormer${solarNodes.length>1?'s':''} · totaal ${this._fmt(totalSolar)}`,
        },
        bat: {
          title: 'Batterijen', color: bfc,
          metrics: battNodes.map(b => ({
            l: b.label||'Batterij',
            v: `${this._fmt(Math.abs(b.power_w))} · ${b.soc_pct!=null?b.soc_pct.toFixed(0)+'%':'—'}`,
            sub: b.power_w<-T?'laden':b.power_w>T?'ontladen':'idle',
          })),
          note: `${battNodes.length} batter${battNodes.length>1?'ijen':'ij'} · totaal ${this._fmt(Math.abs(totalBattPw))}`,
        },
        boiler: {
          title: 'Warm water', color: C.boiler,
          metrics: boilerNodes.map(b => ({
            l: b.label||'Boiler',
            v: `${this._fmt(b.power_w)}`,
            sub: `${b.temp_c!=null?b.temp_c.toFixed(0)+'°C':'—'} / ${b.setpoint_c!=null?b.setpoint_c.toFixed(0)+'°C':'—'}`,
          })),
          note: boilerNodes.length ? `${boilerNodes.length} boiler${boilerNodes.length>1?'s':''} · totaal ${this._fmt(totalBoiler)}` : 'Geen boiler geconfigureerd.',
        },
        ev: {
          title: 'EV & Mobiliteit', color: C.ev,
          metrics: [{l:'Vermogen',v:this._fmt(ev)},{l:'Sessie',v:ev>T?'actief':'geen'},{l:'Geladen vandaag',v:this._fmt(_fv('sensor.cloudems_ev_charged_today')*1000)}],
          note: ev > T ? `Laadt met ${this._fmt(ev)}.` : 'Geen actieve laadsessie.',
        },
        ebike: {
          title: 'E-bike & Scooter', color: C.ebike,
          metrics: [{l:'Vermogen',v:this._fmt(ebike)},{l:'Status',v:ebike>T?'laden':'idle'}],
          note: ebike > T ? `Laadt met ${this._fmt(ebike)}.` : 'Niet actief.',
        },
        pool: {
          title: 'Zwembad', color: C.pool,
          metrics: [{l:'Vermogen',v:this._fmt(pool)},{l:'Status',v:pool>T?'actief':'uit'}],
          note: pool > T ? `Verwarming actief: ${this._fmt(pool)}.` : 'Verwarming uit.',
        },
        home: {
          title: 'Huisverbruik', color: C.home,
          metrics: [
            {l:'Nu',v:this._fmt(home)},
            {l:'Vandaag',v:(_fv('sensor.cloudems_energy_cost',null)!==null?_fv('sensor.cloudems_energie_vandaag_kwh')||'—':'-')+' kWh'},
            {l:'Zelfconsumptie',v:(_fv('sensor.cloudems_self_consumption')||0).toFixed(1)+'%'},
            {l:'Aanwezig',v:H_HASS?.states['binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom']?.state==='on'?'Ja':'Nee'},
          ],
          note: 'Huisverbruik inclusief alle NILM-herkende apparaten.',
          nilm: true,
        },
      };

      // Write to shadow DOM
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          ha-card {
            background: linear-gradient(145deg, #0d1117 0%, #111827 100%);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px; overflow: hidden;
            font-family: ui-monospace, 'Cascadia Code', 'Roboto Mono', monospace;
          }
          .wrap { padding: 14px 16px 16px; }
          .title {
            font-size: 10px; font-weight: 700; letter-spacing: 0.15em;
            text-transform: uppercase; color: rgba(255,255,255,0.35);
            margin-bottom: 10px; display: flex; align-items: center; gap: 6px;
          }
          .title::before { content: '⚡'; font-size: 11px; }
          svg { width: 100%; display: block; overflow: visible; }
          #detail-panel {
            border-top: 1px solid rgba(255,255,255,0.07);
            animation: dp-in .18s ease;
          }
          @keyframes dp-in { from{opacity:0;transform:translateY(-4px)} to{opacity:1;transform:translateY(0)} }
          .dp { padding: 12px 16px 14px; }
          .dp-hdr { display:flex;align-items:center;justify-content:space-between;margin-bottom:10px; }
          .dp-title { font-size:13px;font-weight:700;letter-spacing:.04em; }
          .dp-close { background:rgba(255,255,255,0.08);border:none;color:rgba(255,255,255,0.5);cursor:pointer;border-radius:6px;padding:2px 9px;font-size:13px;line-height:1.6; }
          .dp-close:hover { background:rgba(255,255,255,0.15); }
          .dp-grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:6px;margin-bottom:8px; }
          .dp-metric { background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:8px 10px; }
          .dp-ml { font-size:9px;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px; }
          .dp-mv { font-size:13px;font-weight:700;color:#e2e8f0; }
          .dp-sub { font-size:9px;color:rgba(255,255,255,0.35);margin-top:1px; }
          .dp-note { font-size:11px;color:rgba(255,255,255,0.35);line-height:1.55;padding:7px 9px;background:rgba(255,255,255,0.03);border-radius:7px;margin-bottom:6px; }
          .nilm-section { margin-top:8px;border-top:1px solid rgba(255,255,255,0.06);padding-top:8px; }
          .nilm-hdr { font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,0.3);margin-bottom:6px; }
          .nilm-list { display:flex;flex-direction:column;gap:3px; }
          .nilm-row { display:grid;grid-template-columns:8px 1fr 54px 34px 36px;gap:7px;align-items:center;padding:6px 8px;border-radius:7px;cursor:pointer;transition:background .1s;border:0.5px solid transparent; }
          .nilm-row:hover { background:rgba(255,255,255,0.05); }
          .nilm-row.sel { background:rgba(255,255,255,0.07);border-color:rgba(255,255,255,0.1); }
          .nilm-dot { width:7px;height:7px;border-radius:50%; }
          .nilm-name { font-size:11px;color:rgba(255,255,255,0.75);white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
          .nilm-w { font-size:11px;font-weight:700;text-align:right;font-variant-numeric:tabular-nums; }
          .nilm-ph { font-size:9px;font-weight:700;padding:2px 4px;border-radius:4px;text-align:center; }
          .nilm-bar { height:3px;background:rgba(255,255,255,0.07);border-radius:2px;overflow:hidden; }
          .nilm-bar-fill { height:100%;border-radius:2px; }
          .nilm-detail-box { margin-top:6px;padding:10px 12px;background:rgba(255,255,255,0.03);border-radius:8px;border:0.5px solid rgba(255,255,255,0.08); }
          .nilm-detail-grid { display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-bottom:5px; }
          .nilm-bar-lbl { display:flex;justify-content:space-between;font-size:9px;color:rgba(255,255,255,0.3);margin-bottom:3px; }
          .nilm-hint { font-size:10px;color:rgba(255,255,255,0.25);font-style:italic; }
          .nilm-actions { display:flex;gap:6px;margin-top:10px; }
          .na-btn { flex:1;padding:6px 4px;border-radius:7px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;background:rgba(255,255,255,0.04);transition:background .12s; }
          .na-confirm { color:#34d399;border-color:rgba(52,211,153,0.3); }
          .na-confirm:hover { background:rgba(52,211,153,0.12); }
          .na-dismiss { color:#f87171;border-color:rgba(248,113,113,0.3); }
          .na-dismiss:hover { background:rgba(248,113,113,0.12); }
          .na-ignore  { color:#94a3b8;border-color:rgba(148,163,184,0.25); }
          .na-ignore:hover  { background:rgba(148,163,184,0.08); }
          .na-feedback { font-size:11px;font-weight:600;margin-top:8px;padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.04); }
        </style>
        <ha-card>
          <div class="wrap">
            ${this._config.title ? `<div class="title">${this._config.title}</div>` : ''}
            <svg id="flow-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
              ${h}
            </svg>
          </div>
          <div id="detail-panel" style="display:none"></div>
        </ha-card>`;

      // Bind all node clicks (main + NILM)
      const svg = this.shadowRoot.getElementById('flow-svg');
      if (svg) {
        svg.addEventListener('click', (ev) => {
          const g = ev.target.closest('g[data-nid]');
          if (!g) { this._closeDetail(); return; }
          const nid = g.dataset.nid;
          if (this._activeNid === nid) { this._closeDetail(); return; }
          this._activeNid = nid;
          if (nid.startsWith('nilm_') || nid.startsWith('sub_')) {
            this._showNilmDetail(g.dataset);
          } else {
            this._showNodeDetail(nid);
          }
        });
      }
    }

    _closeDetail() {
      this._activeNid = null;
      this._activeNilmNid = null;
      const panel = this.shadowRoot?.getElementById('detail-panel');
      if (panel) { panel.style.display='none'; panel.innerHTML=''; }
    }

    _showNodeDetail(nid) {
      const panel = this.shadowRoot?.getElementById('detail-panel');
      if (!panel) return;

      // Build detail data LIVE from hass so it's always fresh
      const nd = this._buildNodeDetail(nid);
      if (!nd) { this._closeDetail(); return; }

      const metrics = nd.metrics.map(m => `
        <div class="dp-metric">
          <div class="dp-ml">${m.l}</div>
          <div class="dp-mv" style="color:${nd.color}">${m.v}</div>
          ${m.sub ? `<div class="dp-sub">${m.sub}</div>` : ''}
        </div>`).join('');

      let nilmHtml = '';
      if (nd.nilm) {
        const running = this._hass?.states['sensor.cloudems_nilm_running_devices']?.attributes?.device_list || [];
        const allDevs = this._hass?.states['sensor.cloudems_nilm_devices']?.attributes?.device_list || [];
        const active = running.sort((a,b)=>(b.power_w||0)-(a.power_w||0));
        const inactive = allDevs.filter(d => !running.find(r=>r.device_id===d.device_id||r.name===d.name)).filter(d=>!d.device_id?.startsWith('__')).slice(0,5);
        const phCol = ph => ph==='L1'?'#06b6d4':ph==='L2'?'#f59e0b':ph==='L3'?'#34d399':'#94a3b8';
        const unknownW = this._hass?.states['sensor.cloudems_nilm_devices']?.attributes?.undefined_power_w || 0;

        const nilmRow = (d, isOn) => {
          const ph = d.phase||'?';
          const conf = Math.min(100, Math.round((d.confidence||1)*100 < 2 ? (d.confidence||100) : (d.confidence||100)));
          const cconf = conf>=70?'#34d399':conf>=50?'#f59e0b':'#ef4444';
          const nid2 = `nilm_${(d.name||d.device_id||'?').replace(/[^a-zA-Z0-9]/g,'_')}`;
          const nid2safe = nid2.replace(/'/g, "\\'");
          return `<div class="nilm-row" id="nr-${nid2}" onclick="this.getRootNode().host._clickNilmRow('${nid2safe}','${(d.name||'?').replace(/'/g,"\\'")}',${isOn?Math.round(d.power_w||0):0},'${phCol(ph)}','${ph}','${d.device_type||d.type||'—'}',${conf},${d.on_events||0},'${d.room||'—'}')">
            <div class="nilm-dot" style="background:${isOn?phCol(ph):'rgba(255,255,255,0.12)'}"></div>
            <div class="nilm-name">${d.name||d.device_type||'?'}</div>
            <div class="nilm-w" style="color:${isOn?'#e2e8f0':'rgba(255,255,255,0.25)'}">${isOn?Math.round(d.power_w||0)+' W':'—'}</div>
            <div class="nilm-ph" style="background:${phCol(ph)}22;color:${phCol(ph)}">${ph}</div>
            <div class="nilm-bar"><div class="nilm-bar-fill" style="width:${conf}%;background:${cconf}"></div></div>
          </div>`;
        };

        nilmHtml = `<div class="nilm-section">
          <div class="nilm-hdr">NILM apparaten · ${active.length} actief · klik voor details</div>
          <div class="nilm-list" id="nilm-list">
            ${active.map(d => nilmRow(d, true)).join('')}
            ${inactive.map(d => nilmRow(d, false)).join('')}
            ${unknownW > 50 ? `<div style="padding:5px 8px;font-size:10px;color:rgba(255,255,255,0.3)">Onverklaard: ${Math.round(unknownW)} W</div>` : ''}
          </div>
          <div id="nilm-inline-detail"></div>
        </div>`;
      }

      panel.innerHTML = `<div class="dp">
        <div class="dp-hdr">
          <span class="dp-title" style="color:${nd.color}">${nd.title}</span>
          <button class="dp-close" id="dp-close-btn">✕</button>
        </div>
        <div class="dp-grid">${metrics}</div>
        <div class="dp-note">${nd.note}</div>
        ${nilmHtml}
      </div>`;
      panel.style.display = 'block';
      panel.querySelector('#dp-close-btn')?.addEventListener('click', () => this._closeDetail());
    }

    _buildNodeDetail(nid) {
      const h = this._hass;
      if (!h) return null;
      const T = 10;
      const fmt = w => { const thr=this._config?.watt_threshold||1000; return Math.abs(w)>=thr?(w/1000).toFixed(2)+' kW':Math.round(w)+' W'; };
      const fv = (eid, def='—') => { const s=h.states[eid]; return s&&s.state!=='unavailable'&&s.state!=='unknown'?s.state:def; };
      const fa = (eid, attr, def=null) => h.states[eid]?.attributes?.[attr] ?? def;

      if (nid === 'solar') {
        const invs = this._getInverters();
        const totalSolar = invs.reduce((s,n)=>s+n.w, 0);
        const C = '#f5c518';
        // Also try solar_system sensor directly for all inverters
        const sysInvs = (h.states['sensor.cloudems_solar_system_intelligence'] ?? h.states['sensor.cloudems_solar_system'])?.attributes?.inverters || [];
        // Use sysInvs (full sensor attr) if available, else _getInverters(), else empty
        const allInvs = sysInvs.length > 0 ? sysInvs.map(i => ({
          label: i.label || '?',
          w: parseFloat(i.current_w||0),
          peak_w: parseFloat(i.peak_w||0),
          peak_w_7d: parseFloat(i.peak_w_7d||0),
          phase: i.phase_display || i.phase || '?',
        })) : invs;
        const todaySt = h.states['sensor.cloudems_pv_forecast_today'];
        const tomSt   = h.states['sensor.cloudems_pv_forecast_tomorrow'];
        const accSt   = h.states['sensor.cloudems_pv_forecast_accuracy'];
        return {
          title: 'Zonnepanelen', color: C,
          metrics: [
            {l:'Productie nu',  v: fmt(totalSolar)},
            {l:'Vandaag',       v: todaySt&&todaySt.state!=='unavailable'? parseFloat(todaySt.state).toFixed(2)+' kWh':'—'},
            {l:'Morgen fcst',   v: tomSt&&tomSt.state!=='unavailable'?    parseFloat(tomSt.state).toFixed(2)+' kWh':'—'},
            {l:'Piek 7d',       v: allInvs.length ? fmt(Math.max(...allInvs.map(n=>n.peak_w||n.peak_w_7d||0))) : '—'},
            {l:'Zekerheid',     v: accSt&&accSt.state!=='unavailable'?    Math.round(parseFloat(accSt.state))+'%':'—'},
            ...allInvs.map(n => ({l: n.label, v: fmt(n.w), sub: n.peak_w?'piek: '+fmt(n.peak_w):''})),
          ],
          note: `${allInvs.length} omvormer${allInvs.length!==1?'s':''} · totaal ${fmt(totalSolar)}`,
        };
      }

      if (nid === 'bat') {
        const bats = this._getBatteryNodes();
        const total = bats.reduce((s,b)=>s+b.power_w,0);
        const bfc = total < -T ? '#2ecc71' : '#e74c3c';
        return {
          title: 'Batterijen', color: bfc,
          metrics: bats.map(b => ({
            l: b.label||'Batterij',
            v: `${fmt(Math.abs(b.power_w))} · ${b.soc_pct!=null?b.soc_pct.toFixed(0)+'%':'—'}`,
            sub: b.power_w<-T?'laden':b.power_w>T?'ontladen':'idle',
          })),
          note: `${bats.length} batter${bats.length!==1?'ijen':'ij'} · totaal ${fmt(Math.abs(total))}`,
        };
      }

      if (nid === 'boiler') {
        const bols = this._getBoilerNodes();
        const total = bols.reduce((s,b)=>s+b.power_w,0);
        return {
          title: 'Warm water', color: '#e67e22',
          metrics: bols.length ? bols.map(b => ({
            l: b.label||'Boiler',
            v: fmt(b.power_w),
            sub: `${b.temp_c!=null?b.temp_c.toFixed(0)+'°C':'—'} / ${b.setpoint_c!=null?b.setpoint_c.toFixed(0)+'°C':'—'}`,
          })) : [{l:'Status',v:'Geen data'}],
          note: bols.length ? `${bols.length} boiler${bols.length!==1?'s':''} · totaal ${fmt(total)}` : 'Geen boiler geconfigureerd.',
        };
      }

      if (nid === 'grid') {
        const grid = this._getVal((this._config.entities||{}).grid);
        const gc = grid > T ? '#e74c3c' : '#2ecc71';
        const priceCt = parseFloat(h.states['sensor.cloudems_price_current_hour']?.state||0)*100||0;
        const tariff = fa('sensor.cloudems_batterij_epex_schema','zonneplan',{})?.tariff_group || '—';
        return {
          title: 'Net · import/export', color: gc,
          metrics: [
            {l:'Nu', v: fmt(Math.abs(grid)), sub: grid>T?'import':'export'},
            {l:'Import vandaag', v: fmt((parseFloat(fv('sensor.cloudems_import_energy_today','0'))||0)*1000)},
            {l:'Export vandaag', v: fmt((parseFloat(fv('sensor.cloudems_export_energy_today','0'))||0)*1000)},
            {l:'EPEX prijs', v: priceCt?priceCt.toFixed(1)+' ct':'—'},
            {l:'Tarief', v: tariff},
          ],
          note: grid > T ? `Importeert ${fmt(grid)} van het net.` : `Exporteert ${fmt(Math.abs(grid))} naar het net.`,
        };
      }

      if (nid === 'ev') {
        const ev = this._getEvPower();
        return {
          title: 'EV & Mobiliteit', color: '#3bba4c',
          metrics: [{l:'Vermogen',v:fmt(ev)},{l:'Sessie',v:ev>T?'actief':'geen'}],
          note: ev > T ? `Laadt met ${fmt(ev)}.` : 'Geen actieve laadsessie.',
        };
      }

      if (nid === 'ebike') {
        const eb = this._getEbikePower();
        return {
          title: 'E-bike & Scooter', color: '#06b6d4',
          metrics: [{l:'Vermogen',v:fmt(eb)},{l:'Status',v:eb>T?'laden':'idle'}],
          note: eb > T ? `Laadt met ${fmt(eb)}.` : 'Niet actief.',
        };
      }

      if (nid === 'pool') {
        const pool = this._getPoolPower();
        return {
          title: 'Zwembad', color: '#38bdf8',
          metrics: [{l:'Vermogen',v:fmt(pool)},{l:'Status',v:pool>T?'actief':'uit'}],
          note: pool > T ? `Verwarming actief: ${fmt(pool)}.` : 'Verwarming uit.',
        };
      }

      if (nid === 'home') {
        const home = this._getVal((this._config.entities||{}).home);
        return {
          title: 'Huisverbruik', color: '#27ae60',
          metrics: [
            {l:'Nu', v:fmt(home)},
            {l:'Vandaag', v: (() => { const s=h.states['sensor.cloudems_energie_vandaag_kwh']; return s&&s.state!=='unavailable'?(parseFloat(s.state)||0).toFixed(2)+' kWh':'—'; })()},
            {l:'Zelfconsumptie', v: (parseFloat(fv('sensor.cloudems_self_consumption','0'))||0).toFixed(1)+'%'},
            {l:'Aanwezig', v: h.states['binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom']?.state==='on'?'Ja':'Nee'},
          ],
          note: 'Huisverbruik inclusief alle NILM-herkende apparaten.',
          nilm: true,
        };
      }

      // Fallback: use stale _nodeData
      return this._nodeData?.[nid] || null;
    }


    _clickNilmRow(nid, name, pw, color, phase, type, conf, events, room) {
      const list = this.shadowRoot?.getElementById('nilm-list');
      const det  = this.shadowRoot?.getElementById('nilm-inline-detail');
      if (!list || !det) return;
      if (this._activeNilmNid === nid) {
        this._activeNilmNid = null;
        list.querySelectorAll('.nilm-row').forEach(r => r.classList.remove('sel'));
        det.innerHTML = '';
        return;
      }
      this._activeNilmNid = nid;
      list.querySelectorAll('.nilm-row').forEach(r => r.classList.remove('sel'));
      list.querySelector(`#nr-${nid}`)?.classList.add('sel');
      const phCol = phase==='L1'?'#06b6d4':phase==='L2'?'#f59e0b':phase==='L3'?'#34d399':'#94a3b8';
      const confCol = conf>=70?'#34d399':conf>=50?'#f59e0b':'#ef4444';
      det.innerHTML = `<div class="nilm-detail-box">
        <div class="nilm-detail-grid">
          <div class="dp-metric"><div class="dp-ml">Vermogen</div><div class="dp-mv" style="color:${color};font-size:12px">${pw} W</div></div>
          <div class="dp-metric"><div class="dp-ml">Fase</div><div class="dp-mv" style="color:${phCol};font-size:12px">${phase}</div></div>
          <div class="dp-metric"><div class="dp-ml">Type</div><div class="dp-mv" style="font-size:11px">${type}</div></div>
          <div class="dp-metric"><div class="dp-ml">On events</div><div class="dp-mv" style="font-size:12px">${events}x</div></div>
          <div class="dp-metric"><div class="dp-ml">Kamer</div><div class="dp-mv" style="font-size:11px">${room}</div></div>
          <div class="dp-metric"><div class="dp-ml">Status</div><div class="dp-mv" style="font-size:11px;color:${conf>=70?'#34d399':'#f59e0b'}">${conf>=70?'Bevestigd':'Lerend'}</div></div>
        </div>
        <div class="nilm-bar-lbl"><span>Betrouwbaarheid</span><span style="color:${confCol}">${conf}%</span></div>
        <div class="nilm-bar"><div class="nilm-bar-fill" style="width:${conf}%;background:${confCol}"></div></div>
        <div class="nilm-actions" id="na-${nid}">
          <button class="na-btn na-confirm" id="nb-confirm-${nid}">✓ Bevestigen</button>
          <button class="na-btn na-dismiss" id="nb-dismiss-${nid}">✗ Afwijzen</button>
          <button class="na-btn na-ignore" id="nb-ignore-${nid}">○ Negeren</button>
        </div>
        <div class="na-feedback" id="nf-${nid}" style="display:none"></div>
      </div>`;

      // Bind action buttons
      const callSvc = (svc, extra={}) => {
        if(!this._hass) return;
        this._hass.callService('cloudems', svc, {device_name: name, ...extra});
      };
      const feedback = (msg, col) => {
        const fb = det.querySelector(`#nf-${nid}`);
        const ab = det.querySelector(`#na-${nid}`);
        if(fb){fb.textContent=msg;fb.style.color=col;fb.style.display='block';}
        if(ab) ab.style.display='none';
      };

      det.querySelector(`#nb-confirm-${nid}`)?.addEventListener('click', () => {
        callSvc('confirm_nilm_device');
        feedback('✓ Bevestigd — apparaat opgeslagen', '#34d399');
      });
      det.querySelector(`#nb-dismiss-${nid}`)?.addEventListener('click', () => {
        callSvc('dismiss_nilm_device');
        feedback('✗ Afgewezen — apparaat verwijderd', '#f87171');
      });
      det.querySelector(`#nb-ignore-${nid}`)?.addEventListener('click', () => {
        callSvc('suppress_nilm_device');
        feedback('○ Genegeerd — niet meer tonen', '#94a3b8');
      });
    }

    _showNilmDetail(ds) { this._showNodeDetail('home'); }

    _closeNilmDetail() { this._closeDetail(); }

    _renderDots() {
      if (!this.shadowRoot || !this._pipeDefs) return;
      const layer = this.shadowRoot.getElementById('dots-layer');
      if (!layer) return;

      const spd = w => 0.003 + Math.min(Math.abs(w) / 5000, 1) * 0.013;
      let html = '';

      this._pipeDefs.forEach(p => {
        if (!p.on) return;
        const d = this._dots[p.key]; if (!d) return;
        const s = spd(p.pw), dx = p.x2-p.x1, dy = p.y2-p.y1;
        d.forEach(dot => {
          dot.speed = s;
          const t = dot.pos, fade = Math.sin(t * Math.PI);
          const x = (p.x1 + dx*t).toFixed(1), y = (p.y1 + dy*t).toFixed(1);
          // Glow halo + solid core
          html += `<circle cx="${x}" cy="${y}" r="5.5" fill="${p.color}" opacity="${(fade*.15).toFixed(2)}"/>`;
          html += `<circle cx="${x}" cy="${y}" r="2.8" fill="${p.color}" opacity="${(fade*.92).toFixed(2)}"/>`;
        });
      });

      layer.innerHTML = html;
    }

    // ── Config stub ──────────────────────────────────────────────────────────

    static getConfigElement() {
      return document.createElement('cloudems-flow-card-editor');
    }
    static getStubConfig() {
      return {
        title: 'Energiestroom',
        watt_threshold: 1000,
        entities: {
          solar_system: { entity: 'sensor.cloudems_solar_system' },
          grid:    { entity: 'sensor.cloudems_grid_net_power',   name: 'Net' },
          home:    { entity: 'sensor.cloudems_home_rest',       name: 'Thuis' },
          weather: { entity: 'weather.forecast_thuis' },
          // Optioneel — worden anders auto-detected via CloudEMS sensors:
          // boiler: { entity: 'sensor.cloudems_boiler_power' },
          // ev:     { entity: 'sensor.cloudems_ev_lader_power' },
          // ebike:  { entity: 'sensor.cloudems_micro_mobiliteit_power' },
          // pool:   { entity: 'sensor.cloudems_zwembad_power' },
        }
      };
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-stack-card  ·  vervangt stack-in-card
  // Config: mode (vertical/horizontal), cards[]
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsStackCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._cards = [];
      this._hass  = null;
    }

    setConfig(config) {
      this._config = config;
      this._buildCards(config.cards || []);
    }

    async _buildCards(cardConfigs) {
      const helpers = await window.loadCardHelpers();
      this._cards   = cardConfigs.map(c => helpers.createCardElement(c));
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._cards.forEach(c => { if (c) c.hass = hass; });
    }

    _render() {
      const isHoriz = (this._config.mode || 'vertical') === 'horizontal';
      const style = this._config.card_mod?.style || '';

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          .stack-outer {
            background: rgb(34,34,34);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.4);
            overflow: hidden;
            display: ${isHoriz ? 'flex' : 'block'};
            ${style}
          }
          .stack-outer > * {
            flex: ${isHoriz ? '1' : 'unset'};
          }
          /* Verwijder individuele card-stijlen zodat ze naadloos stapelen */
          .stack-outer ::slotted(*),
          .stack-outer > * {
            --ha-card-border-radius: 0 !important;
            --ha-card-box-shadow: none !important;
          }
        </style>
        <div class="stack-outer"></div>`;

      const container = this.shadowRoot.querySelector('.stack-outer');
      this._cards.forEach(c => { if (c) container.appendChild(c); });
      if (this._hass) this._cards.forEach(c => { if (c) c.hass = this._hass; });
    }

    static getConfigElement() { const el = document.createElement('div'); el.setConfig = () => {}; return el; }
    static getStubConfig()    { return { mode: 'vertical', cards: [] }; }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-entity-list  ·  vervangt auto-entities
  // Config: filter{include[{entity_id, domain, state_not}]}, card{type,title}, 
  //         sort{method,reverse}, show_empty, empty_state_content
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsEntityList extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._config    = {};
      this._hass      = null;
      this._innerCard = null;
    }

    setConfig(config) {
      this._config = config;
    }

    set hass(hass) {
      this._hass = hass;

      // Always propagate hass to existing inner card
      if (this._innerCard) this._innerCard.hass = hass;

      const entities = this._filterEntities(hass);
      const entitiesKey = entities.join(',');
      if (this._lastEntitiesKey === entitiesKey) return;
      this._lastEntitiesKey = entitiesKey;

      if (entities.length === 0 && !this._config.show_empty) {
        this.shadowRoot.innerHTML = '';
        this._innerCard = null;
        return;
      }

      const cardConfig = { ...(this._config.card || { type: 'entities' }) };
      if (entities.length === 0 && this._config.empty_state_content) {
        cardConfig.entities = [{ type: 'section', label: this._config.empty_state_content }];
      } else {
        cardConfig.entities = entities.map(eid => ({ entity: eid }));
      }

      this._buildInnerCard(cardConfig);
    }

    async _buildInnerCard(cardConfig) {
      const helpers = await window.loadCardHelpers();
      if (this._innerCard) {
        try { this._innerCard.setConfig(cardConfig); }
        catch(_) {
          this._innerCard = helpers.createCardElement(cardConfig);
          this.shadowRoot.innerHTML = '<style>:host{display:block}</style>';
          this.shadowRoot.appendChild(this._innerCard);
        }
      } else {
        this._innerCard = helpers.createCardElement(cardConfig);
        this.shadowRoot.innerHTML = '<style>:host{display:block}</style>';
        this.shadowRoot.appendChild(this._innerCard);
      }
      // Set hass after card is created and in DOM
      if (this._hass) this._innerCard.hass = this._hass;
    }

    _matchEntityId(pattern, eid) {
      if (!pattern) return true;
      // Wildcard support: "button.cloudems_shutter_*" → regex
      const regex = new RegExp('^' + pattern.replace(/\./g, '\\.').replace(/\*/g, '.*') + '$');
      return regex.test(eid);
    }

    _filterEntities(hass) {
      const include = (this._config.filter || {}).include || [];
      const exclude = (this._config.filter || {}).exclude || [];
      const unique  = this._config.unique !== false;

      let result = [];
      include.forEach(rule => {
        Object.keys(hass.states).forEach(eid => {
          const state = hass.states[eid];
          if (rule.entity_id && !this._matchEntityId(rule.entity_id, eid)) return;
          if (rule.domain    && !eid.startsWith(rule.domain + '.'))  return;
          if (rule.state_not !== undefined && state.state === String(rule.state_not)) return;
          if (rule.state     !== undefined && state.state !== String(rule.state))     return;
          result.push(eid);
        });
      });

      // Exclude filter (with wildcard + state conditions)
      exclude.forEach(rule => {
        result = result.filter(eid => {
          const state = hass.states[eid];
          const matchesId     = rule.entity_id ? this._matchEntityId(rule.entity_id, eid) : true;
          const matchesDomain = rule.domain    ? eid.startsWith(rule.domain + '.')        : true;
          const matchesState  = rule.state     !== undefined ? state?.state === String(rule.state)     : true;
          const matchesNot    = rule.state_not !== undefined ? state?.state === String(rule.state_not) : false;
          if ((matchesId || matchesDomain) && matchesState && !matchesNot) return false;
          return true;
        });
      });

      // Dedup
      if (unique) result = [...new Set(result)];

      // Sort
      const sort = this._config.sort || {};
      if (sort.method === 'state') {
        result.sort((a, b) => {
          const va = parseFloat(hass.states[a]?.state) || 0;
          const vb = parseFloat(hass.states[b]?.state) || 0;
          return sort.reverse ? vb - va : va - vb;
        });
      } else if (sort.method === 'friendly_name') {
        result.sort((a, b) => {
          const na = (hass.states[a]?.attributes?.friendly_name || a).toLowerCase();
          const nb = (hass.states[b]?.attributes?.friendly_name || b).toLowerCase();
          return sort.reverse ? nb.localeCompare(na) : na.localeCompare(nb);
        });
      }

      return result;
    }

    static getConfigElement() { const el = document.createElement('div'); el.setConfig = () => {}; return el; }
    static getStubConfig()    { return { filter: { include: [{ domain: 'switch' }] }, card: { type: 'entities', title: 'Entiteiten' } }; }
  }


  // ═════════════════════════════════════════════════════════════════════════
  // VISUELE EDITORS
  // ═════════════════════════════════════════════════════════════════════════

  // ── Gedeelde stijl voor alle editors ─────────────────────────────────────
  const EDITOR_STYLE = `
    :host { display: block; font-family: var(--primary-font-family, sans-serif); }
    .editor { padding: 4px 0; }
    .section { margin-bottom: 16px; }
    .section-title {
      font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--secondary-text-color);
      margin: 0 0 8px; padding-bottom: 4px;
      border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));
    }
    .row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
    .row label { font-size: 13px; color: var(--primary-text-color); min-width: 130px; flex-shrink: 0; }
    .row input[type=text], .row input[type=number] {
      flex: 1; background: var(--input-fill-color, rgba(255,255,255,0.06));
      border: 1px solid var(--input-ink-color, rgba(255,255,255,0.15));
      border-radius: 6px; padding: 7px 10px;
      color: var(--primary-text-color); font-size: 13px;
      outline: none; transition: border-color 0.2s;
    }
    .row input:focus { border-color: var(--primary-color, #00b140); }
    .row input[type=checkbox] { width: 16px; height: 16px; cursor: pointer; accent-color: var(--primary-color, #00b140); }
    .entity-row { display: grid; grid-template-columns: 1fr 100px 80px; gap: 6px; margin-bottom: 6px; align-items: center; }
    .entity-row input { width: 100%; box-sizing: border-box;
      background: var(--input-fill-color, rgba(255,255,255,0.06));
      border: 1px solid var(--input-ink-color, rgba(255,255,255,0.15));
      border-radius: 6px; padding: 6px 8px;
      color: var(--primary-text-color); font-size: 12px; outline: none;
    }
    .entity-row input:focus { border-color: var(--primary-color, #00b140); }
    .color-dot { width: 16px; height: 16px; border-radius: 50%; cursor: pointer; flex-shrink: 0; border: 2px solid rgba(255,255,255,0.2); }
    .add-btn, .del-btn {
      background: none; border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
      border-radius: 6px; padding: 5px 10px; cursor: pointer;
      color: var(--secondary-text-color); font-size: 12px;
      transition: all 0.15s;
    }
    .add-btn:hover { border-color: var(--primary-color, #00b140); color: var(--primary-color, #00b140); }
    .del-btn:hover { border-color: #e74c3c; color: #e74c3c; }
    .hint { font-size: 11px; color: var(--secondary-text-color); margin-top: -4px; margin-bottom: 8px; opacity: 0.7; }
  `;

  // ── Graph Card Editor ─────────────────────────────────────────────────────
  class CloudemsGraphCardEditor extends HTMLElement {
    constructor() { super(); this.attachShadow({ mode: 'open' }); this._config = {}; }

    setConfig(config) {
      this._config = JSON.parse(JSON.stringify(config));
      this._render();
    }

    _fire() {
      this.dispatchEvent(new CustomEvent('config-changed', {
        detail: { config: this._config }, bubbles: true, composed: true,
      }));
    }

    _render() {
      const c = this._config;
      const entities = c.entities || [];
      const show = c.show || {};

      this.shadowRoot.innerHTML = `
        <style>${EDITOR_STYLE}</style>
        <div class="editor">
          <div class="section">
            <div class="section-title">Algemeen</div>
            <div class="row">
              <label>Naam</label>
              <input type="text" id="name" value="${c.name || ''}" placeholder="bijv. Import · Export (24u)"/>
            </div>
            <div class="row">
              <label>Uren weergeven</label>
              <input type="number" id="hours_to_show" value="${c.hours_to_show || 24}" min="1" max="168" style="width:80px;flex:none"/>
            </div>
            <div class="row">
              <label>Punten per uur</label>
              <input type="number" id="points_per_hour" value="${c.points_per_hour || 4}" min="1" max="12" style="width:80px;flex:none"/>
            </div>
            <div class="row">
              <label>Lijndikte</label>
              <input type="number" id="line_width" value="${c.line_width || 2}" min="1" max="6" style="width:80px;flex:none"/>
            </div>
          </div>

          <div class="section">
            <div class="section-title">Weergave</div>
            <div class="row">
              <label>Toon min/max</label>
              <input type="checkbox" id="show_extrema" ${show.extrema ? 'checked' : ''}/>
            </div>
            <div class="row">
              <label>Toon gemiddelde</label>
              <input type="checkbox" id="show_average" ${show.average ? 'checked' : ''}/>
            </div>
          </div>

          <div class="section">
            <div class="section-title">Entiteiten</div>
            <div class="hint">Entiteit-ID · Naam · Kleur (rgb(r,g,b))</div>
            <div id="entities-list">
              ${entities.map((e, i) => `
                <div class="entity-row" data-idx="${i}">
                  <input type="text" class="e-entity" value="${e.entity || ''}" placeholder="sensor.example"/>
                  <input type="text" class="e-name"   value="${e.name   || ''}" placeholder="Label"/>
                  <input type="text" class="e-color"  value="${e.color  || 'rgb(0,177,64)'}" placeholder="rgb(…)"/>
                  <button class="del-btn" data-del="${i}">✕</button>
                </div>`).join('')}
            </div>
            <button class="add-btn" id="add-entity">+ Entiteit toevoegen</button>
          </div>
        </div>`;

      // Events
      const bind = (id, key, type) => {
        const el = this.shadowRoot.getElementById(id);
        if (!el) return;
        el.addEventListener('change', () => {
          this._config[key] = type === 'bool' ? el.checked : type === 'num' ? (parseFloat(el.value) || 0) : el.value;
          if (key === 'show_extrema' || key === 'show_average') {
            this._config.show = this._config.show || {};
            this._config.show[key === 'show_extrema' ? 'extrema' : 'average'] = el.checked;
            delete this._config[key];
          }
          this._fire();
        });
      };
      bind('name', 'name', 'str');
      bind('hours_to_show', 'hours_to_show', 'num');
      bind('points_per_hour', 'points_per_hour', 'num');
      bind('line_width', 'line_width', 'num');
      bind('show_extrema', 'show_extrema', 'bool');
      bind('show_average', 'show_average', 'bool');

      // Entity field changes
      this.shadowRoot.getElementById('entities-list').addEventListener('change', e => {
        const row = e.target.closest('[data-idx]');
        if (!row) return;
        const i = parseInt(row.dataset.idx);
        const ents = this._config.entities || [];
        if (!ents[i]) return;
        if (e.target.classList.contains('e-entity')) ents[i].entity = e.target.value;
        if (e.target.classList.contains('e-name'))   ents[i].name   = e.target.value;
        if (e.target.classList.contains('e-color'))  ents[i].color  = e.target.value;
        this._fire();
      });

      // Delete entity
      this.shadowRoot.querySelectorAll('[data-del]').forEach(btn => {
        btn.addEventListener('click', () => {
          const i = parseInt(btn.dataset.del);
          this._config.entities.splice(i, 1);
          this._render(); this._fire();
        });
      });

      // Add entity
      this.shadowRoot.getElementById('add-entity').addEventListener('click', () => {
        this._config.entities = this._config.entities || [];
        this._config.entities.push({ entity: '', name: '', color: 'rgb(0,177,64)' });
        this._render(); this._fire();
      });
    }
  }
  customElements.define('cloudems-graph-card-editor', CloudemsGraphCardEditor);

  // ── Flow Card Editor ──────────────────────────────────────────────────────
  class CloudemsFlowCardEditor extends HTMLElement {
    constructor() { super(); this.attachShadow({ mode: 'open' }); this._config = {}; }

    setConfig(config) {
      this._config = JSON.parse(JSON.stringify(config));
      this._render();
    }

    _fire() {
      this.dispatchEvent(new CustomEvent('config-changed', {
        detail: { config: this._config }, bubbles: true, composed: true,
      }));
    }

    _field(label, id, value, placeholder, hint) {
      return `
        <div class="row">
          <label>${label}</label>
          <input type="text" id="${id}" value="${value || ''}" placeholder="${placeholder || ''}"/>
        </div>
        ${hint ? `<div class="hint">${hint}</div>` : ''}`;
    }

    _render() {
      const c = this._config;
      const e = c.entities || {};

      const entityRow = (key, label, defaultEntity, hint) => {
        const ent = e[key] || {};
        return `
          <div class="section">
            <div class="section-title">${label}</div>
            ${hint ? `<div class="hint">${hint}</div>` : ''}
            ${this._field('Entiteit', `${key}_entity`, ent.entity || defaultEntity, `sensor.cloudems_…`)}
            ${this._field('Naam', `${key}_name`, ent.name, label)}
            ${key === 'battery' ? `
              <div class="row">
                <label>State of Charge</label>
                <input type="text" id="battery_soc" value="${ent.state_of_charge || ''}" placeholder="sensor.cloudems_battery_so_c"/>
              </div>
              <div class="row">
                <label>Waarde inverteren</label>
                <input type="checkbox" id="battery_invert" ${ent.invert_state ? 'checked' : ''}/>
              </div>` : ''}
          </div>`;
      };

      this.shadowRoot.innerHTML = `
        <style>${EDITOR_STYLE}</style>
        <div class="editor">
          <div class="section">
            <div class="section-title">Algemeen</div>
            ${this._field('Titel', 'title', c.title, 'Energiestroom')}
            <div class="row">
              <label>kW drempel (W)</label>
              <input type="number" id="watt_threshold" value="${c.watt_threshold || 1000}" min="100" max="10000" style="width:90px;flex:none"/>
            </div>
          </div>

          ${entityRow('solar_system', '☀️ Zonne-energie systeem',
            'sensor.cloudems_solar_system',
            'Leest automatisch alle omvormers uit dit sensor attribuut')}

          ${entityRow('grid', '⚡ Net', 'sensor.cloudems_grid_net_power')}

          ${entityRow('home', '🏠 Thuis', 'sensor.cloudems_home_rest')}

          ${entityRow('battery', '🔋 Batterij', 'sensor.cloudems_battery_power')}

          <div class="section">
            <div class="section-title">ℹ️ Auto-detectie</div>
            <div class="hint">Meerdere omvormers worden automatisch gelezen uit het solar_system sensor attribuut.<br>
            Meerdere accu's worden automatisch gelezen uit sensor.cloudems_battery_so_c.<br>
            NILM Top 3 apparaten worden automatisch gelezen uit sensor.cloudems_nilm_top_N_device.</div>
          </div>
        </div>`;

      // General fields
      [['title','title','str'], ['watt_threshold','watt_threshold','num']].forEach(([id, key, type]) => {
        const el = this.shadowRoot.getElementById(id);
        if (!el) return;
        el.addEventListener('change', () => {
          this._config[key] = type === 'num' ? (parseFloat(el.value) || 1000) : el.value;
          this._fire();
        });
      });

      // Entity fields
      const entityKeys = ['solar_system', 'grid', 'home', 'battery'];
      entityKeys.forEach(key => {
        const setEnt = (field, val) => {
          this._config.entities = this._config.entities || {};
          this._config.entities[key] = this._config.entities[key] || {};
          if (val === '' || val == null) {
            delete this._config.entities[key][field];
          } else {
            this._config.entities[key][field] = val;
          }
          this._fire();
        };
        const entityEl = this.shadowRoot.getElementById(`${key}_entity`);
        const nameEl   = this.shadowRoot.getElementById(`${key}_name`);
        if (entityEl) entityEl.addEventListener('change', () => setEnt('entity', entityEl.value));
        if (nameEl)   nameEl.addEventListener('change',   () => setEnt('name',   nameEl.value));
        if (key === 'battery') {
          const socEl    = this.shadowRoot.getElementById('battery_soc');
          const invertEl = this.shadowRoot.getElementById('battery_invert');
          if (socEl)    socEl.addEventListener('change',    () => setEnt('state_of_charge', socEl.value));
          if (invertEl) invertEl.addEventListener('change', () => setEnt('invert_state', invertEl.checked));
        }
      });
    }
  }
  customElements.define('cloudems-flow-card-editor', CloudemsFlowCardEditor);

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-nilm-card  ·  v4.5.55 — NILM + Kamer + Topologie superdashboard
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsNilmCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass        = null;
      this._config      = {};
      this._view        = 'rooms';    // 'rooms' | 'room' | 'topology' | 'review' | 'all'
      this._activeRoom  = null;
      this._filter      = 'all';      // 'all'|'pending'|'approved'|'tentative'|'declined'
      this._editDevice  = null;
      this._editField   = null;
      this._inputVal    = '';
      this._topoFilter  = 'all';      // 'all'|'approved'|'tentative'|'declined'
      this._tick        = 0;
      this._animId      = null;
    }

    setConfig(c) {
      this._config = { title: 'NILM Apparaten', ...c };
      this._startAnim();
    }

    set hass(h) { this._hass = h; }
    getCardSize() { return 10; }

    connectedCallback()    { this._startAnim(); }
    disconnectedCallback() { if (this._animId) { cancelAnimationFrame(this._animId); this._animId = null; } }

    _startAnim() {
      if (this._animId) return;
      const loop = () => {
        this._tick++;
        if (this._tick % 4 === 0) this._render();
        this._animId = requestAnimationFrame(loop);
      };
      this._animId = requestAnimationFrame(loop);
    }

    // ── Data ─────────────────────────────────────────────────────────────────

    _allDevices() {
      if (!this._hass) return [];
      const st = this._hass.states['sensor.cloudems_nilm_devices'];
      return st?.attributes?.devices || st?.attributes?.device_list || [];
    }

    _deviceStatus(d) {
      if (d.user_suppressed || d.dismissed) return 'declined';
      if (d.confirmed)  return 'approved';
      if (d.pending_confirmation || d.pending) return 'pending';
      return 'tentative';
    }

    _roomsData() {
      const rooms = {};
      for (const d of this._allDevices()) {
        const r = d.room || '__none__';
        if (!rooms[r]) rooms[r] = { name: r, devices: [], powerOn: 0, kwh: 0 };
        rooms[r].devices.push(d);
        if (d.is_on) rooms[r].powerOn += (d.power_w || 0);
        rooms[r].kwh += (d.energy_kwh_today || 0);
      }
      return rooms;
    }

    _topoTree() {
      if (!this._hass) return { nodes: [], stats: {} };
      const st = this._hass.states['sensor.cloudems_meter_topology'];
      const tree = st?.attributes?.tree || [];
      const stats = st?.attributes?.stats || {};
      const suggestions = st?.attributes?.suggestions || [];
      return { tree, stats, suggestions };
    }

    _pendingReview() {
      if (!this._hass) return null;
      const st = this._hass.states['sensor.cloudems_nilm_review_current'];
      if (!st || st.state === 'none' || st.state === 'unknown') return null;
      return { name: st.state, ...st.attributes };
    }

    // ── Services ─────────────────────────────────────────────────────────────

    _svc(service, data) { this._hass?.callService('cloudems', service, data); }

    _approve(d)    { this._svc('confirm_device',     { device_id: d.device_id, name: d.name, device_type: d.device_type || 'unknown' }); }
    _decline(d)    { this._svc('suppress_nilm_device', { device_id: d.device_id }); }
    _tentative(d)  { this._svc('nilm_feedback',      { device_id: d.device_id, feedback: 'maybe' }); }
    _setRoom(d, r) { this._svc('assign_device_to_room', { device_id: d.device_id, room: r }); }
    _rename(d, n)  { this._svc('rename_nilm_device',  { device_id: d.device_id, name: n }); }

    _topoApprove(up, dn) { this._svc('meter_topology_approve', { upstream_id: up, downstream_id: dn }); }
    _topoDecline(up, dn) { this._svc('meter_topology_decline', { upstream_id: up, downstream_id: dn }); }

    _reviewConfirm()  { this._hass?.callService('button', 'press', { entity_id: 'button.cloudems_nilm_review_confirm' }); }
    _reviewDismiss()  { this._hass?.callService('button', 'press', { entity_id: 'button.cloudems_nilm_review_dismiss' }); }
    _reviewMaybe()    { this._hass?.callService('button', 'press', { entity_id: 'button.cloudems_nilm_review_maybe' }); }
    _reviewSkip()     { this._hass?.callService('button', 'press', { entity_id: 'button.cloudems_nilm_review_skip' }); }
    _reviewPrev()     { this._hass?.callService('button', 'press', { entity_id: 'button.cloudems_nilm_review_previous' }); }

    // ── Helpers ──────────────────────────────────────────────────────────────

    _typeIcon(t) {
      return ({ refrigerator:'🧊', fridge:'🧊', washing_machine:'🫧', washer:'🫧',
        dryer:'♨️', dishwasher:'🍽️', oven:'🍳', microwave:'📡', kettle:'☕',
        coffee_machine:'☕', television:'📺', tv:'📺', computer:'💻', laptop:'💻',
        server:'🖥️', heat_pump:'♻️', boiler:'🚿', water_heater:'🚿',
        ev_charger:'⚡', charger:'⚡', light:'💡', lamp:'💡', socket:'🔌',
        plug:'🔌', vacuum:'🌀', robot:'🤖', freezer:'🧊', airco:'❄️',
        garden:'🌿', pool:'🏊', unknown:'❓' })[t?.toLowerCase()] || '⚡';
    }

    _roomIcon(r) {
      return ({ meterkast:'⚡', keuken:'🍳', woonkamer:'🛋️', slaapkamer:'🛏️',
        badkamer:'🚿', garage:'🚗', kantoor:'💻', hal:'🚪', bijkeuken:'🧺',
        tuin:'🌿', overloop:'🏠', zolder:'🏚️', kelder:'🏗️',
        studeerkamer:'📚', kinderkamer:'🧸', __none__:'❓' })[r?.toLowerCase()] || '🏠';
    }

    _fmt(w) { return w >= 1000 ? (w/1000).toFixed(2)+' kW' : Math.round(w)+' W'; }
    _cc(p)  { return p >= 92 ? '#2ecc71' : p >= 75 ? '#f39c12' : '#e74c3c'; }

    _stLabel(d) {
      const s = this._deviceStatus(d);
      return { approved:{icon:'✓',label:'Bevestigd',cls:'approved',c:'#2ecc71'},
               pending: {icon:'!',label:'Jij beslist',cls:'pending', c:'#ffa500'},
               declined:{icon:'✗',label:'Afgewezen', cls:'declined',c:'#e74c3c'},
               tentative:{icon:'?',label:'Onzeker',  cls:'tentative',c:'#f39c12'} }[s]
            || {icon:'?',label:'Onzeker',cls:'tentative',c:'#f39c12'};
    }

    // ── CSS ──────────────────────────────────────────────────────────────────

    _css() { return `
      :host { display: block; }
      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

      ha-card {
        background: #0a0e17;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 18px;
        font-family: 'SF Pro Display', ui-sans-serif, system-ui, sans-serif;
        overflow: hidden; color: #e2e8f0;
      }

      /* ── Nav bar ── */
      .nav {
        display: flex; align-items: stretch;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        background: rgba(255,255,255,0.015);
        overflow-x: auto; scrollbar-width: none;
      }
      .nav::-webkit-scrollbar { display: none; }
      .nav-tab {
        display: flex; flex-direction: column; align-items: center;
        padding: 10px 14px 8px; gap: 3px; cursor: pointer;
        border-bottom: 2px solid transparent; transition: all 0.12s;
        flex-shrink: 0; white-space: nowrap;
      }
      .nav-tab:hover { background: rgba(255,255,255,0.04); }
      .nav-tab.active { border-bottom-color: #00b140; }
      .nav-tab .ti { font-size: 16px; line-height: 1; }
      .nav-tab .tl {
        font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(255,255,255,0.35);
      }
      .nav-tab.active .tl { color: #00b140; }
      .nav-badge {
        min-width: 16px; height: 16px; border-radius: 8px;
        background: #ffa500; color: #000;
        font-size: 9px; font-weight: 800; padding: 0 4px;
        display: inline-flex; align-items: center; justify-content: center;
        position: relative; top: -2px; left: 2px;
        animation: badge-pulse 2s infinite;
      }
      @keyframes badge-pulse {
        0%,100% { box-shadow: 0 0 0 0 rgba(255,165,0,0.5); }
        50%      { box-shadow: 0 0 0 4px rgba(255,165,0,0); }
      }

      /* ── Stats bar ── */
      .stats-bar {
        display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,0.05);
      }
      .stat-item {
        flex: 1; padding: 10px 8px; text-align: center;
        border-right: 1px solid rgba(255,255,255,0.05);
      }
      .stat-item:last-child { border-right: none; }
      .stat-val {
        font-size: 18px; font-weight: 800; line-height: 1;
        font-variant-numeric: tabular-nums;
      }
      .stat-lbl {
        font-size: 9px; font-weight: 600; letter-spacing: 0.08em;
        text-transform: uppercase; color: rgba(255,255,255,0.3); margin-top: 3px;
      }

      /* ── Kamer grid ── */
      .room-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(145px, 1fr));
        gap: 8px; padding: 12px;
      }
      .room-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 14px; padding: 13px 12px;
        cursor: pointer; transition: all 0.14s; position: relative;
        overflow: hidden;
      }
      .room-card::after {
        content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3px;
        background: var(--room-c, rgba(255,255,255,0.06));
        transition: height 0.3s;
      }
      .room-card:hover { background: rgba(255,255,255,0.06); transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
      .room-card.has-pending { border-color: rgba(255,165,0,0.4); }
      .room-card.has-pending::after { background: #ffa500; }
      .room-card.all-card { border-style: dashed; opacity: 0.6; }
      .rc-icon { font-size: 26px; margin-bottom: 7px; }
      .rc-name { font-size: 12px; font-weight: 700; color: #e2e8f0; }
      .rc-sub  { font-size: 10px; color: rgba(255,255,255,0.3); margin-top: 2px; }
      .rc-pwr  {
        font-size: 13px; font-weight: 800; color: #5dade2;
        margin-top: 7px; font-variant-numeric: tabular-nums;
      }
      .rc-bar-wrap {
        height: 3px; background: rgba(255,255,255,0.06);
        border-radius: 2px; margin-top: 6px; overflow: hidden;
      }
      .rc-bar { height: 100%; border-radius: 2px; transition: width 0.5s; }
      .rc-badge {
        position: absolute; top: 8px; right: 8px;
        background: #ffa500; color: #000;
        font-size: 9px; font-weight: 800; padding: 2px 5px;
        border-radius: 8px;
      }
      .rc-dot-row {
        display: flex; gap: 3px; margin-top: 6px; flex-wrap: wrap;
      }
      .rc-dot {
        width: 7px; height: 7px; border-radius: 50%;
        transition: all 0.2s;
      }

      /* ── Filter bar ── */
      .fbar {
        display: flex; gap: 5px; padding: 8px 12px 4px;
        overflow-x: auto; scrollbar-width: none; flex-wrap: wrap;
      }
      .fbar::-webkit-scrollbar { display: none; }
      .ftab {
        font-size: 10px; font-weight: 700; padding: 4px 11px;
        border-radius: 20px; cursor: pointer; transition: all 0.1s;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.04);
        color: rgba(255,255,255,0.4); white-space: nowrap; flex-shrink: 0;
      }
      .ftab.active { background: rgba(93,173,226,0.18); color: #5dade2; border-color: rgba(93,173,226,0.4); }
      .ftab.f-ap.active { background: rgba(46,204,113,0.15); color:#2ecc71; border-color:rgba(46,204,113,0.35); }
      .ftab.f-pe.active { background: rgba(255,165,0,0.15); color:#ffa500; border-color:rgba(255,165,0,0.4); }
      .ftab.f-te.active { background: rgba(243,156,18,0.12); color:#f39c12; border-color:rgba(243,156,18,0.3); }
      .ftab.f-de.active { background: rgba(231,76,60,0.1); color:#e74c3c; border-color:rgba(231,76,60,0.25); }

      /* ── Apparaten lijst ── */
      .dlist { padding: 6px 12px 12px; display: flex; flex-direction: column; gap: 5px; }

      .drow {
        display: flex; align-items: center; gap: 9px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 11px; padding: 9px 10px;
        transition: border-color 0.1s; position: relative; overflow: hidden;
      }
      .drow::before {
        content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
        background: var(--row-c, rgba(255,255,255,0.1));
        border-radius: 11px 0 0 11px;
      }
      .drow:hover { border-color: rgba(255,255,255,0.13); }
      .drow.declined { opacity: 0.45; }

      .d-live {
        width: 7px; height: 7px; border-radius: 50%;
        background: var(--live-c, rgba(255,255,255,0.15));
        flex-shrink: 0; transition: all 0.2s;
      }
      .d-live.on { animation: live-pulse 1.5s infinite; }
      @keyframes live-pulse {
        0%,100% { box-shadow: 0 0 0 0 var(--live-c, #5dade2); }
        50%      { box-shadow: 0 0 0 4px rgba(0,0,0,0); }
      }

      .dicon { font-size: 20px; flex-shrink: 0; line-height: 1; }
      .dinfo { flex: 1; min-width: 0; }
      .dname {
        font-size: 12px; font-weight: 700; color: #e2e8f0;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        display: flex; align-items: center; gap: 5px; cursor: pointer;
      }
      .dname:hover .ei { opacity: 1; }
      .ei { opacity: 0; font-size: 10px; color: rgba(255,255,255,0.35); transition: opacity 0.1s; }
      .dmeta {
        font-size: 10px; color: rgba(255,255,255,0.28);
        margin-top: 2px; display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
      }
      .conf-ring {
        display: inline-flex; align-items: center; justify-content: center;
        width: 22px; height: 22px;
      }
      .pbadge {
        font-size: 8px; font-weight: 800; padding: 2px 5px;
        border-radius: 6px; background: #ffa500; color: #000;
        animation: badge-pulse 2s infinite; flex-shrink: 0;
      }
      .dpow {
        font-size: 12px; font-weight: 800; flex-shrink: 0;
        min-width: 52px; text-align: right; font-variant-numeric: tabular-nums;
        color: #5dade2; transition: color 0.2s;
      }
      .dpow.off { color: rgba(255,255,255,0.18); font-weight: 400; font-size: 11px; }
      .dact { display: flex; gap: 3px; flex-shrink: 0; }

      /* ── Actie-knoppen ── */
      .btn {
        font-size: 12px; font-weight: 800; padding: 5px 9px;
        border-radius: 7px; cursor: pointer; border: 1px solid transparent;
        background: none; transition: all 0.1s; color: #e2e8f0;
        line-height: 1; font-family: inherit;
      }
      .ba { color:#2ecc71; border-color:rgba(46,204,113,0.3); background:rgba(46,204,113,0.07); }
      .ba:hover { background:rgba(46,204,113,0.2); box-shadow:0 0 8px rgba(46,204,113,0.25); }
      .ba.cur { background:rgba(46,204,113,0.22); box-shadow:0 0 8px rgba(46,204,113,0.4); }
      .bd { color:#e74c3c; border-color:rgba(231,76,60,0.25); background:rgba(231,76,60,0.06); }
      .bd:hover { background:rgba(231,76,60,0.2); }
      .bt { color:#f39c12; border-color:rgba(243,156,18,0.25); background:rgba(243,156,18,0.06); }
      .bt:hover { background:rgba(243,156,18,0.2); }
      .bt.cur { background:rgba(243,156,18,0.2); box-shadow:0 0 8px rgba(243,156,18,0.35); }
      .br { color:rgba(255,255,255,0.4); border-color:rgba(255,255,255,0.1); background:rgba(255,255,255,0.04); }
      .br:hover { color:#e2e8f0; background:rgba(255,255,255,0.1); }

      /* ── Back header ── */
      .sub-hdr {
        display: flex; align-items: center; gap: 9px;
        padding: 10px 14px 8px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
      }
      .sh-icon { font-size: 20px; }
      .sh-title { flex:1; font-size: 13px; font-weight: 700; color: #e2e8f0; }
      .sh-meta  { font-size: 10px; color: rgba(255,255,255,0.3); }
      .btn-back {
        font-size: 10px; font-weight: 700; padding: 5px 11px;
        border-radius: 20px; cursor: pointer;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.04);
        color: rgba(255,255,255,0.45); transition: all 0.1s;
      }
      .btn-back:hover { background:rgba(255,255,255,0.09); color:#e2e8f0; }

      /* ── Topology view ── */
      .topo-wrap { padding: 10px 12px 14px; }

      .topo-legend {
        display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap;
        padding: 0 2px;
      }
      .tleg {
        display: flex; align-items: center; gap: 5px;
        font-size: 10px; color: rgba(255,255,255,0.4);
      }
      .tleg-dot { width: 8px; height: 8px; border-radius: 50%; }

      .topo-tree { display: flex; flex-direction: column; gap: 4px; }

      .tnode {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 10px; border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.06);
        background: rgba(255,255,255,0.025);
        transition: all 0.12s; position: relative;
        animation: node-in 0.2s ease;
      }
      @keyframes node-in { from { opacity:0; transform:translateX(-6px); } to { opacity:1; transform:none; } }
      .tnode:hover { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.12); }
      .tnode.depth-0 { border-color:rgba(0,177,64,0.25); background:rgba(0,177,64,0.04); }
      .tnode.depth-1 { margin-left: 18px; }
      .tnode.depth-1::before {
        content: ''; position: absolute; left: -10px; top: 50%;
        width: 10px; height: 1px; background: rgba(255,255,255,0.15);
      }
      .tnode.depth-2 { margin-left: 36px; }
      .tnode.depth-2::before {
        content: ''; position: absolute; left: -10px; top: 50%;
        width: 10px; height: 1px; background: rgba(255,255,255,0.1);
      }
      .tnode.st-approved { border-left: 3px solid #2ecc71; }
      .tnode.st-tentative { border-left: 3px solid #f39c12; }
      .tnode.st-declined  { border-left: 3px solid rgba(231,76,60,0.4); opacity:0.5; }
      .tnode.st-suggest   { border-left: 3px solid #f39c12; border-style: dashed;
                             background: rgba(243,156,18,0.04); }

      .tn-icon { font-size: 16px; flex-shrink: 0; }
      .tn-name { flex: 1; font-size: 11px; font-weight: 600; color: #e2e8f0;
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .tn-eid  { font-size: 9px; color: rgba(255,255,255,0.25); max-width: 140px;
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .tn-pwr  { font-size: 11px; font-weight: 700; color: #5dade2;
                 flex-shrink: 0; font-variant-numeric: tabular-nums; }
      .tn-status {
        font-size: 9px; font-weight: 700; padding: 2px 7px;
        border-radius: 10px; flex-shrink: 0; letter-spacing: 0.05em;
      }
      .st-ap { background:rgba(46,204,113,0.15); color:#2ecc71; }
      .st-te { background:rgba(243,156,18,0.12); color:#f39c12; }
      .st-de { background:rgba(231,76,60,0.1); color:#e74c3c; }
      .st-sg { background:rgba(243,156,18,0.08); color:#f39c12; border:1px dashed rgba(243,156,18,0.4); }
      .tn-acts { display:flex; gap:3px; flex-shrink:0; }

      .topo-stats {
        display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap;
      }
      .topo-stat {
        padding: 5px 10px; border-radius: 20px; font-size: 10px; font-weight: 700;
        display: flex; align-items: center; gap: 4px;
      }
      .topo-empty {
        padding: 24px; text-align: center;
        color: rgba(255,255,255,0.2); font-size: 12px; line-height: 1.7;
      }

      /* ── Review view ── */
      .review-wrap { padding: 12px; }
      .review-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 14px; padding: 16px 14px; margin-bottom: 10px;
        position: relative; overflow: hidden;
      }
      .review-card::before {
        content: ''; position: absolute; inset: 0;
        background: radial-gradient(ellipse at 50% -20%, rgba(0,177,64,0.06), transparent 60%);
        pointer-events: none;
      }
      .rv-name {
        font-size: 18px; font-weight: 800; color: #e2e8f0; margin-bottom: 4px;
      }
      .rv-type { font-size: 12px; color: rgba(255,255,255,0.4); margin-bottom: 12px; }
      .rv-grid {
        display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 14px;
      }
      .rv-cell {
        background: rgba(255,255,255,0.04); border-radius: 10px;
        padding: 8px 10px; text-align: center;
        border: 1px solid rgba(255,255,255,0.06);
      }
      .rv-cell-val {
        font-size: 16px; font-weight: 800; line-height: 1;
        font-variant-numeric: tabular-nums; color: #e2e8f0;
      }
      .rv-cell-lbl {
        font-size: 9px; color: rgba(255,255,255,0.3);
        margin-top: 3px; text-transform: uppercase; letter-spacing: 0.08em;
      }
      .rv-conf-bar {
        height: 5px; border-radius: 3px; margin-bottom: 12px;
        background: rgba(255,255,255,0.06); overflow: hidden;
      }
      .rv-conf-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
      .rv-meta { font-size: 10px; color: rgba(255,255,255,0.3); margin-bottom: 14px; }

      .review-btns {
        display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;
      }
      .rbtn {
        padding: 12px 6px; border-radius: 11px; cursor: pointer;
        border: none; font-size: 12px; font-weight: 700;
        font-family: inherit; transition: all 0.12s;
        display: flex; flex-direction: column; align-items: center; gap: 4px;
      }
      .rbtn-icon { font-size: 20px; }
      .rbtn.confirm { background: rgba(46,204,113,0.18); color: #2ecc71;
                      border: 1px solid rgba(46,204,113,0.4); }
      .rbtn.confirm:hover { background: rgba(46,204,113,0.3); transform: translateY(-1px); }
      .rbtn.dismiss { background: rgba(231,76,60,0.12); color: #e74c3c;
                      border: 1px solid rgba(231,76,60,0.3); }
      .rbtn.dismiss:hover { background: rgba(231,76,60,0.22); transform: translateY(-1px); }
      .rbtn.maybe  { background: rgba(243,156,18,0.12); color: #f39c12;
                     border: 1px solid rgba(243,156,18,0.3); }
      .rbtn.maybe:hover  { background: rgba(243,156,18,0.22); transform: translateY(-1px); }

      .review-nav {
        display: flex; gap: 6px; margin-top: 8px; justify-content: center;
      }
      .rnbtn {
        font-size: 10px; font-weight: 700; padding: 5px 14px; border-radius: 20px;
        cursor: pointer; background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        color: rgba(255,255,255,0.4); transition: all 0.1s; font-family: inherit;
      }
      .rnbtn:hover { background:rgba(255,255,255,0.1); color:#e2e8f0; }

      .rv-empty {
        padding: 30px 20px; text-align: center; color: rgba(255,255,255,0.2);
        font-size: 12px; line-height: 1.8;
      }

      /* ── Modal ── */
      .modal-ov {
        position: fixed; inset: 0; z-index: 9999;
        background: rgba(0,0,0,0.8); backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
      }
      .modal {
        background: #12181f; border: 1px solid rgba(255,255,255,0.12);
        border-radius: 18px; padding: 20px; width: min(380px, 94vw);
        box-shadow: 0 24px 64px rgba(0,0,0,0.7);
        animation: modal-in 0.15s ease;
      }
      @keyframes modal-in { from { opacity:0; transform:scale(0.95); } to { opacity:1; transform:none; } }
      .mtitle { font-size: 14px; font-weight: 700; color: #e2e8f0; margin-bottom: 14px; }
      .mlabel {
        font-size: 9px; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: rgba(255,255,255,0.3); margin: 12px 0 7px;
      }
      .rchips { display: flex; flex-wrap: wrap; gap: 6px; }
      .rchip {
        font-size: 11px; padding: 5px 12px; border-radius: 20px; cursor: pointer;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.55);
        transition: all 0.1s;
      }
      .rchip:hover { background:rgba(255,255,255,0.1); color:#e2e8f0; }
      .rchip.sel { background:rgba(93,173,226,0.2); color:#5dade2; border-color:rgba(93,173,226,0.4); }
      .minput {
        width: 100%; background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 9px; padding: 10px 12px; color: #e2e8f0;
        font-size: 13px; font-family: inherit; margin-top: 6px;
      }
      .minput:focus { outline: none; border-color: #5dade2;
        box-shadow: 0 0 0 3px rgba(93,173,226,0.15); }
      .mact { display:flex; gap:8px; margin-top:16px; justify-content:flex-end; }
      .bprim { padding:9px 20px; border-radius:9px; cursor:pointer; font-size:12px;
               font-weight:700; background:#00b140; color:#fff; border:none; font-family:inherit; }
      .bprim:hover { background:#00d44e; }
      .bcanc { padding:9px 14px; border-radius:9px; cursor:pointer; font-size:12px;
               font-weight:700; background:rgba(255,255,255,0.06);
               color:rgba(255,255,255,0.45); border:1px solid rgba(255,255,255,0.1); font-family:inherit; }

      .empty { padding:28px 16px; text-align:center; color:rgba(255,255,255,0.2);
               font-size:12px; line-height:1.7; }
    `; }

    // ── Renders ───────────────────────────────────────────────────────────────

    _renderNav(allD) {
      const pendingReview = this._pendingReview();
      const pendingCount = allD.filter(d => this._deviceStatus(d) === 'pending').length;
      const reviewCount  = pendingReview ? (pendingReview.pending_count || 1) : 0;

      const tabs = [
        { id:'rooms',    icon:'🏠', label:'Kamers' },
        { id:'topology', icon:'⚡', label:'Topologie' },
        { id:'review',   icon:'👁', label:'Review', badge: reviewCount || pendingCount },
        { id:'all',      icon:'📋', label:'Alle' },
      ];
      return `<div class="nav">${tabs.map(t => `
        <div class="nav-tab ${this._view===t.id?'active':''}" data-nav="${t.id}">
          <span class="ti">${t.icon}${t.badge > 0 ? `<span class="nav-badge">${t.badge}</span>` : ''}</span>
          <span class="tl">${t.label}</span>
        </div>`).join('')}</div>`;
    }

    _renderStats(allD) {
      const approved  = allD.filter(d => this._deviceStatus(d) === 'approved').length;
      const pending   = allD.filter(d => this._deviceStatus(d) === 'pending').length;
      const tentative = allD.filter(d => this._deviceStatus(d) === 'tentative').length;
      const active    = allD.filter(d => d.is_on).length;
      const powerOn   = allD.filter(d => d.is_on).reduce((s,d) => s + (d.power_w||0), 0);

      return `<div class="stats-bar">
        <div class="stat-item">
          <div class="stat-val" style="color:#2ecc71">${approved}</div>
          <div class="stat-lbl">Bevestigd</div>
        </div>
        <div class="stat-item">
          <div class="stat-val" style="color:#ffa500">${pending}</div>
          <div class="stat-lbl">Wacht</div>
        </div>
        <div class="stat-item">
          <div class="stat-val" style="color:#f39c12">${tentative}</div>
          <div class="stat-lbl">Onzeker</div>
        </div>
        <div class="stat-item">
          <div class="stat-val" style="color:#5dade2">${active}</div>
          <div class="stat-lbl">Actief nu</div>
        </div>
        <div class="stat-item">
          <div class="stat-val" style="color:#e2e8f0;font-size:14px">${this._fmt(powerOn)}</div>
          <div class="stat-lbl">Herkend W</div>
        </div>
      </div>`;
    }

    _renderRooms(allD) {
      const rooms = this._roomsData();
      const maxPower = Math.max(...Object.values(rooms).map(r => r.powerOn), 1);
      const roomNames = Object.keys(rooms).filter(r => r !== '__none__').sort();
      const noRoom    = rooms['__none__'];

      const colors = ['#2ecc71','#5dade2','#f39c12','#e74c3c','#9b59b6',
                      '#1abc9c','#e67e22','#3498db','#e91e63'];

      const makeCard = (r, idx) => {
        const room = rooms[r];
        const isPending = room.devices.some(d => this._deviceStatus(d) === 'pending');
        const pCount    = room.devices.filter(d => this._deviceStatus(d) === 'pending').length;
        const aCount    = room.devices.filter(d => d.is_on).length;
        const pct       = (room.powerOn / maxPower * 100).toFixed(0);
        const c         = colors[idx % colors.length];
        const dots      = room.devices.slice(0, 12).map(d => {
          const sc = this._deviceStatus(d);
          const dc = sc==='approved'?'#2ecc71' : sc==='pending'?'#ffa500' : sc==='declined'?'rgba(231,76,60,0.4)' : '#f39c12';
          return `<div class="rc-dot" style="background:${dc};${d.is_on?`box-shadow:0 0 4px ${dc}`:'opacity:0.4'}"></div>`;
        }).join('');

        const name = r === '__none__' ? 'Geen kamer' : r.charAt(0).toUpperCase() + r.slice(1);
        return `
          <div class="room-card ${isPending?'has-pending':''}" data-room="${r}"
               style="--room-c:${c}">
            ${pCount > 0 ? `<div class="rc-badge">! ${pCount}</div>` : ''}
            <div class="rc-icon">${this._roomIcon(r)}</div>
            <div class="rc-name">${name}</div>
            <div class="rc-sub">${room.devices.length} apparaat${room.devices.length!==1?'en':''} · ${aCount} aan</div>
            ${room.powerOn > 0 ? `<div class="rc-pwr">${this._fmt(room.powerOn)}</div>` : ''}
            <div class="rc-bar-wrap">
              <div class="rc-bar" style="width:${pct}%;background:${c}"></div>
            </div>
            <div class="rc-dot-row">${dots}</div>
          </div>`;
      };

      const allCard = `
        <div class="room-card all-card" data-room="__all__">
          <div class="rc-icon">📋</div>
          <div class="rc-name">Alle apparaten</div>
          <div class="rc-sub">${allD.length} totaal</div>
        </div>`;

      return `<div class="room-grid">
        ${roomNames.map((r,i) => makeCard(r,i)).join('')}
        ${noRoom?.devices.length > 0 ? makeCard('__none__', roomNames.length) : ''}
        ${allCard}
      </div>`;
    }

    _renderDeviceRow(d) {
      const st  = this._deviceStatus(d);
      const sl  = this._stLabel(d);
      const c   = sl.c;
      const lc  = d.is_on ? c : 'rgba(255,255,255,0.15)';
      const conf = d.confidence || 0;

      const meta = [
        d.device_type && d.device_type!=='unknown' ? d.device_type.replace(/_/g,' ') : null,
        d.phase && d.phase!=='?' ? d.phase : null,
        conf > 0 ? `${conf}%` : null,
        d.on_events ? `${d.on_events}× gezien` : null,
        d.energy_kwh_today > 0 ? `${d.energy_kwh_today.toFixed(2)} kWh` : null,
      ].filter(Boolean).join(' · ');

      const acts = [
        st!=='approved'  ? `<button class="btn ba ${st==='approved'?'cur':''}" data-a="approve" data-id="${d.device_id}" title="Bevestigen">✓</button>` : '',
        (st==='approved'||st==='declined') ? `<button class="btn bt" data-a="tentative" data-id="${d.device_id}" title="Twijfel">?</button>` : '',
        st!=='declined'  ? `<button class="btn bd" data-a="decline" data-id="${d.device_id}" title="Afwijzen">✗</button>` : '',
        `<button class="btn br" data-a="room" data-id="${d.device_id}" title="Kamer">🏠</button>`,
      ].filter(Boolean).join('');

      return `
        <div class="drow ${sl.cls}" style="--row-c:${c}">
          <div class="d-live ${d.is_on?'on':''}" style="--live-c:${lc}"></div>
          <div class="dicon">${this._typeIcon(d.device_type)}</div>
          <div class="dinfo">
            <div class="dname" data-a="rename" data-id="${d.device_id}">
              ${d.name || 'Onbekend'}
              <span class="ei">✏</span>
              ${st==='pending' ? `<span class="pbadge">!</span>` : ''}
            </div>
            <div class="dmeta">${meta}</div>
          </div>
          <div class="dpow ${d.is_on?'':'off'}">${d.is_on ? this._fmt(d.power_w||0) : 'uit'}</div>
          <div class="dact">${acts}</div>
        </div>`;
    }

    _renderDeviceList(roomKey) {
      const devs = roomKey === '__all__' ? this._allDevices()
        : roomKey === '__none__' ? this._allDevices().filter(d => !d.room)
        : this._allDevices().filter(d => d.room === roomKey);

      const filtered = this._filter === 'all' ? devs
        : devs.filter(d => this._deviceStatus(d) === this._filter);

      const order = { pending:0, approved:1, tentative:2, declined:3 };
      const sorted = [...filtered].sort((a,b) => {
        const ao = order[this._deviceStatus(a)]??9;
        const bo = order[this._deviceStatus(b)]??9;
        return ao!==bo ? ao-bo : (b.power_w||0)-(a.power_w||0);
      });

      const counts = {
        pending:  devs.filter(d=>this._deviceStatus(d)==='pending').length,
        approved: devs.filter(d=>this._deviceStatus(d)==='approved').length,
        tentative:devs.filter(d=>this._deviceStatus(d)==='tentative').length,
        declined: devs.filter(d=>this._deviceStatus(d)==='declined').length,
      };

      const roomName = roomKey==='__none__' ? 'Geen kamer'
        : roomKey==='__all__' ? 'Alle apparaten'
        : roomKey.charAt(0).toUpperCase() + roomKey.slice(1);

      const activePower = devs.filter(d=>d.is_on).reduce((s,d)=>s+(d.power_w||0),0);

      return `
        <div class="sub-hdr">
          <span class="sh-icon">${this._roomIcon(roomKey)}</span>
          <span class="sh-title">${roomName}</span>
          ${activePower>0?`<span class="sh-meta">${this._fmt(activePower)}</span>`:''}
          <button class="btn-back" id="btn-back">← Terug</button>
        </div>
        <div class="fbar">
          <span class="ftab ${this._filter==='all'?'active':''}" data-f="all">Alle (${devs.length})</span>
          ${counts.pending>0  ?`<span class="ftab f-pe ${this._filter==='pending'  ?'active':''}" data-f="pending">! ${counts.pending}</span>`:''}
          ${counts.approved>0 ?`<span class="ftab f-ap ${this._filter==='approved' ?'active':''}" data-f="approved">✓ ${counts.approved}</span>`:''}
          ${counts.tentative>0?`<span class="ftab f-te ${this._filter==='tentative'?'active':''}" data-f="tentative">? ${counts.tentative}</span>`:''}
          ${counts.declined>0 ?`<span class="ftab f-de ${this._filter==='declined' ?'active':''}" data-f="declined">✗ ${counts.declined}</span>`:''}
        </div>
        <div class="dlist">${sorted.length
          ? sorted.map(d=>this._renderDeviceRow(d)).join('')
          : `<div class="empty">Geen apparaten in deze categorie.</div>`
        }</div>`;
    }

    _renderTopology() {
      const { tree, stats, suggestions } = this._topoTree();
      const allD = this._allDevices();

      // Bouw lookup naam → apparaat
      const devByEid = {};
      for (const d of allD) {
        if (d.entity_id) devByEid[d.entity_id] = d;
      }

      const getName = (node) => {
        if (!this._hass) return node.name || node.entity_id || 'Onbekend';
        const st = this._hass.states[node.entity_id || ''];
        return st?.attributes?.friendly_name || node.name || node.entity_id || 'Onbekend';
      };

      const renderNode = (node, depth = 0) => {
        const st  = node.status || 'approved';
        const stc = st==='approved'?'st-ap' : st==='tentative'?'st-te' : 'st-de';
        const stl = st==='approved'?'Bevestigd' : st==='tentative'?'Onzeker' : 'Afgewezen';
        const icon = depth===0 ? '⚡' : (devByEid[node.entity_id] ? this._typeIcon(devByEid[node.entity_id].device_type) : '🔌');
        const pwr  = node.power_w ? this._fmt(node.power_w) : null;
        const acts = st!=='approved'
          ? `<button class="btn ba" data-ta="approve" data-up="${node.upstream_id||''}" data-dn="${node.entity_id}" title="Bevestigen">✓</button>`
          : '';
        const decl = st!=='declined'
          ? `<button class="btn bd" data-ta="decline" data-up="${node.upstream_id||''}" data-dn="${node.entity_id}" title="Afwijzen">✗</button>`
          : '';

        const children = (node.children || []).map(c => renderNode({...c, upstream_id: node.entity_id}, depth+1)).join('');

        return `
          <div class="tnode depth-${Math.min(depth,2)} st-${st}">
            <span class="tn-icon">${icon}</span>
            <div style="flex:1;min-width:0">
              <div class="tn-name">${getName(node)}</div>
              <div class="tn-eid">${node.entity_id || ''}</div>
            </div>
            ${pwr ? `<span class="tn-pwr">${pwr}</span>` : ''}
            <span class="tn-status ${stc}">${stl}</span>
            <div class="tn-acts">${acts}${decl}</div>
          </div>
          ${children}`;
      };

      const suggNodes = suggestions.filter(s => {
        if (this._topoFilter === 'tentative') return true;
        if (this._topoFilter === 'all') return true;
        return false;
      }).map(s => {
        const upName = (() => {
          const st = this._hass?.states[s.upstream_id];
          return st?.attributes?.friendly_name || s.upstream_id || '?';
        })();
        const dnName = (() => {
          const st = this._hass?.states[s.downstream_id];
          return st?.attributes?.friendly_name || s.downstream_id || '?';
        })();
        return `
          <div class="tnode depth-1 st-suggest">
            <span class="tn-icon">❓</span>
            <div style="flex:1;min-width:0">
              <div class="tn-name" style="color:#f39c12">${dnName}</div>
              <div class="tn-eid">${upName} → ${dnName} · ${s.score||0} metingen</div>
            </div>
            <span class="tn-status st-sg">Suggestie</span>
            <div class="tn-acts">
              <button class="btn ba" data-ta="approve" data-up="${s.upstream_id}" data-dn="${s.downstream_id}" title="Bevestigen">✓</button>
              <button class="btn bd" data-ta="decline" data-up="${s.upstream_id}" data-dn="${s.downstream_id}" title="Afwijzen">✗</button>
            </div>
          </div>`;
      }).join('');

      const statsBar = `<div class="topo-stats">
        <span class="topo-stat" style="background:rgba(46,204,113,0.1);color:#2ecc71">
          ✓ ${stats.approved||0} bevestigd
        </span>
        <span class="topo-stat" style="background:rgba(243,156,18,0.1);color:#f39c12">
          ? ${stats.tentative||0} onzeker
        </span>
        ${suggestions.length>0?`<span class="topo-stat" style="background:rgba(243,156,18,0.07);color:#f39c12;border:1px dashed rgba(243,156,18,0.3)">
          💡 ${suggestions.length} suggestie${suggestions.length!==1?'s':''}
        </span>`:''}
        <span class="topo-stat" style="background:rgba(231,76,60,0.08);color:#e74c3c">
          ✗ ${stats.declined||0} afgewezen
        </span>
      </div>`;

      const fbar = `<div class="fbar">
        <span class="ftab ${this._topoFilter==='all'?'active':''}" data-tf="all">Alles</span>
        <span class="ftab f-ap ${this._topoFilter==='approved'?'active':''}" data-tf="approved">✓ Bevestigd</span>
        <span class="ftab f-te ${this._topoFilter==='tentative'?'active':''}" data-tf="tentative">? + Suggesties</span>
        <span class="ftab f-de ${this._topoFilter==='declined'?'active':''}" data-tf="declined">✗ Afgewezen</span>
      </div>`;

      const treeContent = tree.length === 0 && suggestions.length === 0
        ? `<div class="topo-empty">
            🔌 Nog geen meter-topologie geleerd.<br>
            <small>CloudEMS observeert automatisch co-bewegingen<br>
            tussen stroommeters. Na ~8 metingen verschijnen suggesties.</small>
          </div>`
        : `<div class="topo-tree">
            ${tree.map(n => renderNode(n)).join('')}
            ${suggestions.length>0 && (this._topoFilter==='all'||this._topoFilter==='tentative') ? `
              <div style="padding:8px 4px 4px;font-size:9px;font-weight:700;letter-spacing:0.1em;
                text-transform:uppercase;color:rgba(243,156,18,0.6)">
                💡 Suggesties — bevestig of wijs af
              </div>
              ${suggNodes}` : ''}
          </div>`;

      return `<div class="topo-wrap">
        ${statsBar}
        ${fbar}
        ${treeContent}
      </div>`;
    }

    _renderReview() {
      const pending = this._pendingReview();
      const allPending = this._allDevices().filter(d => this._deviceStatus(d) === 'pending');

      if (!pending && allPending.length === 0) {
        return `<div class="review-wrap">
          <div class="rv-empty">
            ✅ <strong style="color:#2ecc71;display:block;font-size:16px;margin-bottom:6px">Alles beoordeeld!</strong>
            Geen apparaten die wachten op jouw beslissing.<br>
            <small style="opacity:0.6">Nieuwe apparaten verschijnen hier zodra CloudEMS ze detecteert.</small>
          </div>
        </div>`;
      }

      // Gebruik review_current sensor als die beschikbaar is
      const d = pending || allPending[0];
      if (!d) return '';

      const conf = d.confidence || d.confidence_pct || 0;
      const confColor = this._cc(conf);
      const pw = d.power_w || 0;
      const phase = d.phase || '—';
      const events = d.on_events || d.event_count || 0;
      const dtype = (d.device_type || '?').replace(/_/g, ' ');
      const pCount = d.pending_count || allPending.length;
      const icon = this._typeIcon(d.device_type);
      const name = d.name || 'Onbekend apparaat';

      return `<div class="review-wrap">
        ${pCount > 1 ? `<div style="font-size:10px;color:rgba(255,255,255,0.3);margin-bottom:8px;text-align:center">
          ${pCount} apparaten wachten · dit is nr. 1
        </div>` : ''}

        <div class="review-card">
          <div style="font-size:36px;text-align:center;margin-bottom:10px">${icon}</div>
          <div class="rv-name" style="text-align:center">${name}</div>
          <div class="rv-type" style="text-align:center">${dtype} · Fase ${phase}</div>

          <div class="rv-conf-bar">
            <div class="rv-conf-fill" style="width:${conf}%;background:${confColor}"></div>
          </div>

          <div class="rv-grid">
            <div class="rv-cell">
              <div class="rv-cell-val" style="color:${confColor}">${conf}%</div>
              <div class="rv-cell-lbl">Zekerheid</div>
            </div>
            <div class="rv-cell">
              <div class="rv-cell-val">${this._fmt(pw)}</div>
              <div class="rv-cell-lbl">Vermogen</div>
            </div>
            <div class="rv-cell">
              <div class="rv-cell-val">${events}</div>
              <div class="rv-cell-lbl">× Gezien</div>
            </div>
          </div>

          ${d.device_id ? `<div class="rv-meta">ID: <code style="font-size:9px;color:rgba(255,255,255,0.3)">${d.device_id}</code></div>` : ''}
        </div>

        <div class="review-btns">
          <button class="rbtn confirm" id="rv-confirm">
            <span class="rbtn-icon">✅</span>
            Ja, bevestigen
          </button>
          <button class="rbtn maybe" id="rv-maybe">
            <span class="rbtn-icon">🤔</span>
            Weet ik niet
          </button>
          <button class="rbtn dismiss" id="rv-dismiss">
            <span class="rbtn-icon">❌</span>
            Afwijzen
          </button>
        </div>

        <div class="review-nav">
          <button class="rnbtn" id="rv-prev">← Vorige</button>
          <button class="rnbtn" id="rv-skip">Overslaan →</button>
        </div>

        ${allPending.length > 1 ? `
        <div style="margin-top:14px">
          <div style="font-size:9px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
            color:rgba(255,255,255,0.25);margin-bottom:8px;padding:0 2px">
            Andere apparaten die wachten
          </div>
          <div class="dlist" style="padding:0">
            ${allPending.slice(0,5).map(pd => this._renderDeviceRow(pd)).join('')}
          </div>
        </div>` : ''}
      </div>`;
    }

    _renderModal() {
      if (!this._editDevice) return '';
      const d = this._editDevice;

      if (this._editField === 'room') {
        const rooms = ['meterkast','keuken','woonkamer','slaapkamer','badkamer',
          'garage','kantoor','hal','bijkeuken','tuin','overloop',
          'studeerkamer','kinderkamer','zolder','kelder'];
        const allRooms = [...new Set([...(d.room?[d.room]:[]), ...rooms])].sort();
        return `<div class="modal-ov" id="modal-ov">
          <div class="modal">
            <div class="mtitle">📍 Kamer instellen — ${d.name||'Apparaat'}</div>
            <div class="mlabel">Kies kamer</div>
            <div class="rchips">
              ${allRooms.map(r=>`<span class="rchip ${d.room===r?'sel':''}" data-room="${r}">${this._roomIcon(r)} ${r}</span>`).join('')}
            </div>
            <div class="mlabel">Of typ een naam</div>
            <input class="minput" id="room-input" type="text"
              placeholder="bijv. kantoor" value="${this._inputVal||d.room||''}"/>
            <div class="mact">
              <button class="bcanc" id="m-cancel">Annuleer</button>
              <button class="bprim" id="m-save">Opslaan</button>
            </div>
          </div>
        </div>`;
      }

      if (this._editField === 'name') {
        const types = ['washing_machine','dryer','dishwasher','refrigerator','oven',
          'microwave','television','computer','boiler','heat_pump','ev_charger',
          'light','socket','vacuum','unknown'];
        return `<div class="modal-ov" id="modal-ov">
          <div class="modal">
            <div class="mtitle">✏️ Naam wijzigen — ${d.name||'Apparaat'}</div>
            <div class="mlabel">Nieuwe naam</div>
            <input class="minput" id="name-input" type="text"
              placeholder="${d.name||'Apparaat'}" value="${this._inputVal||d.name||''}"/>
            <div class="mlabel">Type apparaat</div>
            <div class="rchips">
              ${types.map(t=>`<span class="rchip ${d.device_type===t?'sel':''}" data-type="${t}">${this._typeIcon(t)} ${t.replace(/_/g,' ')}</span>`).join('')}
            </div>
            <div class="mact">
              <button class="bcanc" id="m-cancel">Annuleer</button>
              <button class="bprim" id="m-save">Opslaan</button>
            </div>
          </div>
        </div>`;
      }
      return '';
    }

    // ── Hoofd render ──────────────────────────────────────────────────────────

    _render() {
      if (!this._hass) return;
      const allD = this._allDevices();

      let body = '';
      if (this._view === 'room') {
        body = this._renderDeviceList(this._activeRoom);
      } else if (this._view === 'topology') {
        body = this._renderTopology();
      } else if (this._view === 'review') {
        body = this._renderReview();
      } else if (this._view === 'all') {
        body = this._renderDeviceList('__all__');
      } else {
        body = this._renderRooms(allD);
      }

      this.shadowRoot.innerHTML = `
        <style>${this._css()}</style>
        <ha-card>
          ${this._renderNav(allD)}
          ${['rooms','topology','review','all'].includes(this._view) ? this._renderStats(allD) : ''}
          ${body}
          ${this._renderModal()}
        </ha-card>`;

      this._bindEvents();
    }

    _bindEvents() {
      const sr = this.shadowRoot;

      // Nav tabs
      sr.querySelectorAll('[data-nav]').forEach(el => {
        el.addEventListener('click', () => {
          this._view = el.dataset.nav;
          this._filter = 'all';
          this._render();
        });
      });

      // Terug
      sr.getElementById('btn-back')?.addEventListener('click', () => {
        this._view = 'rooms'; this._activeRoom = null; this._filter = 'all';
        this._render();
      });

      // Kamer kaarten
      sr.querySelectorAll('[data-room]').forEach(el => {
        el.addEventListener('click', () => {
          this._activeRoom = el.dataset.room;
          this._view = 'room'; this._filter = 'all';
          this._render();
        });
      });

      // Device filter
      sr.querySelectorAll('[data-f]').forEach(el => {
        el.addEventListener('click', () => { this._filter = el.dataset.f; this._render(); });
      });

      // Topo filter
      sr.querySelectorAll('[data-tf]').forEach(el => {
        el.addEventListener('click', () => { this._topoFilter = el.dataset.tf; this._render(); });
      });

      // Device acties
      sr.querySelectorAll('[data-a]').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          const d = this._allDevices().find(x => x.device_id === btn.dataset.id);
          const a = btn.dataset.a;
          if (a==='approve' && d)   this._approve(d);
          if (a==='decline' && d)   this._decline(d);
          if (a==='tentative' && d) this._tentative(d);
          if (a==='room') {
            this._editDevice = d || this._allDevices().find(x=>x.device_id===btn.dataset.id);
            this._editField = 'room'; this._inputVal = d?.room||'';
            this._render();
          }
          if (a==='rename') {
            this._editDevice = d;
            this._editField = 'name'; this._inputVal = d?.name||'';
            this._render();
          }
        });
      });

      // Topology acties
      sr.querySelectorAll('[data-ta]').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          const up = btn.dataset.up, dn = btn.dataset.dn;
          if (!dn) return;
          if (btn.dataset.ta === 'approve') this._topoApprove(up, dn);
          if (btn.dataset.ta === 'decline') this._topoDecline(up, dn);
        });
      });

      // Review knoppen
      sr.getElementById('rv-confirm')?.addEventListener('click', () => this._reviewConfirm());
      sr.getElementById('rv-dismiss')?.addEventListener('click', () => this._reviewDismiss());
      sr.getElementById('rv-maybe')?.addEventListener('click',   () => this._reviewMaybe());
      sr.getElementById('rv-skip')?.addEventListener('click',    () => this._reviewSkip());
      sr.getElementById('rv-prev')?.addEventListener('click',    () => this._reviewPrev());

      // Modal
      if (this._editDevice) {
        if (this._editField === 'room') {
          sr.querySelectorAll('[data-room]').forEach(chip => {
            chip.addEventListener('click', () => {
              this._inputVal = chip.dataset.room;
              sr.getElementById('room-input').value = this._inputVal;
              sr.querySelectorAll('.rchip').forEach(c=>c.classList.remove('sel'));
              chip.classList.add('sel');
            });
          });
          sr.getElementById('room-input')?.addEventListener('input', e => { this._inputVal = e.target.value; });
        }
        if (this._editField === 'name') {
          sr.querySelectorAll('[data-type]').forEach(chip => {
            chip.addEventListener('click', () => {
              this._editDevice = { ...this._editDevice, device_type: chip.dataset.type };
              sr.querySelectorAll('[data-type]').forEach(c=>c.classList.remove('sel'));
              chip.classList.add('sel');
            });
          });
          sr.getElementById('name-input')?.addEventListener('input', e => { this._inputVal = e.target.value; });
        }
        sr.getElementById('m-save')?.addEventListener('click', () => {
          const val = (this._inputVal||'').trim();
          if (val && this._editField==='room') this._setRoom(this._editDevice, val.toLowerCase());
          if (val && this._editField==='name') this._rename(this._editDevice, val);
          this._editDevice=null; this._editField=null; this._inputVal='';
          this._render();
        });
        sr.getElementById('m-cancel')?.addEventListener('click', () => {
          this._editDevice=null; this._editField=null; this._inputVal='';
          this._render();
        });
        sr.getElementById('modal-ov')?.addEventListener('click', e => {
          if (e.target.id==='modal-ov') {
            this._editDevice=null; this._editField=null; this._inputVal='';
            this._render();
          }
        });
      }
    }

    static getStubConfig() { return { title: 'NILM Apparaten' }; }
  }



    class CloudemsNilmCardEditor extends HTMLElement {
    setConfig(config) { this._config = config; }
    set hass(h) {}
    connectedCallback() {
      this.innerHTML = `<div style="padding:12px;font-family:monospace;font-size:12px;color:#aaa">
        Geen configuratie nodig — de kaart leest automatisch<br>
        <code>sensor.cloudems_nilm_devices</code></div>`;
    }
  }
  if (!customElements.get('cloudems-nilm-card-editor')) {
    customElements.define('cloudems-nilm-card-editor', CloudemsNilmCardEditor);
  }



  // ═══════════════════════════════════════════════════════════════════════════
  // v4.5.51 — NIEUWE DEV KAARTEN (PriceCard, TopologyCard, OverviewCard)
  // ═══════════════════════════════════════════════════════════════════════════

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-topology-card  ·  Meter-boom met approve/decline
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsTopologyCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass = null;
      this._config = {};
      this._expanded = new Set();
    }

    setConfig(c) { this._config = { title: 'Meter Topologie', ...c }; }
    set hass(h) { this._hass = h; this._render(); }
    getCardSize() { return 5; }

    _svc(svc, data) { this._hass?.callService('cloudems', svc, data); }

    _topoData() {
      if (!this._hass) return { tree: [], stats: {}, suggestions: [] };
      const st = this._hass.states['sensor.cloudems_meter_topology'];
      if (!st) return { tree: [], stats: {}, suggestions: [] };
      return {
        tree:        st.attributes?.tree        || [],
        stats:       st.attributes?.stats       || {},
        suggestions: st.attributes?.suggestions || [],
      };
    }

    _fmt(w) {
      if (w == null) return '—';
      if (Math.abs(w) >= 1000) return (w/1000).toFixed(1) + ' kW';
      return Math.round(w) + ' W';
    }

    _renderNode(node, depth = 0) {
      const hasChildren = node.children && node.children.length > 0;
      const isExp = this._expanded.has(node.entity_id);
      const indent = depth * 20;
      const statusColor = { approved: '#2ecc71', tentative: '#f39c12', declined: '#e74c3c' }[node.status] || '#666';
      const statusLabel = { approved: '✓', tentative: '?', declined: '✗' }[node.status] || '•';

      let html = `
        <div class="node" data-id="${node.entity_id}" style="margin-left:${indent}px">
          <div class="node-row" data-toggle="${node.entity_id}">
            <span class="node-expand">${hasChildren ? (isExp ? '▾' : '▸') : '·'}</span>
            <span class="node-dot" style="background:${statusColor};box-shadow:0 0 6px ${statusColor}"></span>
            <span class="node-name">${node.name}</span>
            <span class="node-power">${this._fmt(node.power_w)}</span>
            <span class="node-status" style="color:${statusColor}">${statusLabel}</span>
            ${node.status === 'tentative' ? `
              <button class="btn-approve" data-up="${node.upstream_id||''}" data-down="${node.entity_id}">✓</button>
              <button class="btn-decline" data-up="${node.upstream_id||''}" data-down="${node.entity_id}">✗</button>
            ` : ''}
          </div>
          ${hasChildren && isExp ? node.children.map(c => {
            c.upstream_id = node.entity_id;
            return this._renderNode(c, depth + 1);
          }).join('') : ''}
        </div>`;
      return html;
    }

    _render() {
      if (!this._hass) return;
      const { tree, stats, suggestions } = this._topoData();

      const noTopology = tree.length === 0 && suggestions.length === 0;

      const CSS = `
        :host { display: block; }
        * { box-sizing: border-box; }
        ha-card {
          background: #0d1117; border: 1px solid rgba(255,255,255,0.07);
          border-radius: 18px; font-family: 'Inter', ui-sans-serif, sans-serif;
          overflow: hidden; color: #e2e8f0;
        }
        .header { padding: 14px 18px 10px; border-bottom: 1px solid rgba(255,255,255,0.06);
          display: flex; align-items: center; gap: 10px; }
        .header-title { flex: 1; font-size: 10px; font-weight: 700;
          letter-spacing: 0.15em; text-transform: uppercase; color: rgba(255,255,255,0.3); }
        .pills { display: flex; gap: 6px; padding: 10px 18px 8px; flex-wrap: wrap; }
        .pill { font-size: 10px; font-weight: 700; padding: 3px 9px; border-radius: 20px; border: 1px solid; }
        .pill-a { color: #2ecc71; border-color: rgba(46,204,113,0.3); background: rgba(46,204,113,0.08); }
        .pill-t { color: #f39c12; border-color: rgba(243,156,18,0.3); background: rgba(243,156,18,0.08); }
        .pill-l { color: #5dade2; border-color: rgba(93,173,226,0.3); background: rgba(93,173,226,0.08); }
        .tree { padding: 4px 14px 14px; }
        .node { margin-bottom: 2px; }
        .node-row {
          display: flex; align-items: center; gap: 7px; padding: 7px 8px;
          border-radius: 8px; cursor: pointer; transition: background 0.1s;
        }
        .node-row:hover { background: rgba(255,255,255,0.04); }
        .node-expand { font-size: 10px; color: rgba(255,255,255,0.25); width: 10px; flex-shrink: 0; }
        .node-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .node-name { flex: 1; font-size: 12px; color: #e2e8f0; }
        .node-power { font-size: 11px; font-weight: 700; color: #5dade2; min-width: 54px; text-align: right; }
        .node-status { font-size: 10px; font-weight: 700; min-width: 12px; }
        .btn-approve { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
          cursor: pointer; border: 1px solid rgba(46,204,113,0.3); background: rgba(46,204,113,0.1);
          color: #2ecc71; transition: background 0.1s; }
        .btn-approve:hover { background: rgba(46,204,113,0.25); }
        .btn-decline { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
          cursor: pointer; border: 1px solid rgba(231,76,60,0.25); background: rgba(231,76,60,0.08);
          color: #e74c3c; transition: background 0.1s; }
        .btn-decline:hover { background: rgba(231,76,60,0.2); }
        .sugg-section { padding: 0 14px 14px; }
        .sugg-title { font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
          text-transform: uppercase; color: rgba(255,255,255,0.3); margin-bottom: 8px; }
        .sugg-row { display: flex; align-items: center; gap: 8px; padding: 8px 10px;
          background: rgba(243,156,18,0.06); border: 1px solid rgba(243,156,18,0.2);
          border-radius: 10px; margin-bottom: 5px; }
        .sugg-text { flex: 1; font-size: 11px; color: rgba(255,255,255,0.7); }
        .sugg-text strong { color: #e2e8f0; }
        .sugg-co { font-size: 10px; color: rgba(255,255,255,0.3); }
        .empty { padding: 32px; text-align: center; color: rgba(255,255,255,0.25); font-size: 12px; line-height: 1.7; }
      `;

      const treeHTML = tree.length > 0
        ? `<div class="tree">${tree.map(n => this._renderNode(n)).join('')}</div>`
        : '';

      const suggHTML = suggestions.length > 0 ? `
        <div class="sugg-section">
          <div class="sugg-title">🔍 Nieuwe suggesties (${suggestions.length})</div>
          ${suggestions.map(s => `
            <div class="sugg-row">
              <div class="sugg-text">
                <strong>${s.upstream_id.split('.').pop()}</strong>
                → <strong>${s.downstream_id.split('.').pop()}</strong>
              </div>
              <span class="sugg-co">${s.co_movements}×</span>
              <button class="btn-approve" data-up="${s.upstream_id}" data-down="${s.downstream_id}">✓</button>
              <button class="btn-decline" data-up="${s.upstream_id}" data-down="${s.downstream_id}">✗</button>
            </div>`).join('')}
        </div>` : '';

      this.shadowRoot.innerHTML = `
        <style>${CSS}</style>
        <ha-card>
          <div class="header">
            <span class="header-title">🔌 ${this._config.title}</span>
          </div>
          <div class="pills">
            ${stats.approved  ? `<span class="pill pill-a">✓ ${stats.approved} bevestigd</span>` : ''}
            ${stats.tentative ? `<span class="pill pill-t">? ${stats.tentative} suggesties</span>` : ''}
            ${stats.learning  ? `<span class="pill pill-l">📡 ${stats.learning} aan het leren</span>` : ''}
          </div>
          ${noTopology
            ? `<div class="empty">📡 Aan het leren…<br><small>CloudEMS observeert vermogensfluctuaties<br>om de meter-hiërarchie te bepalen.</small></div>`
            : treeHTML + suggHTML}
        </ha-card>`;

      // Toggle expand
      this.shadowRoot.querySelectorAll('[data-toggle]').forEach(el => {
        el.addEventListener('click', e => {
          if (e.target.closest('button')) return;
          const id = el.dataset.toggle;
          this._expanded.has(id) ? this._expanded.delete(id) : this._expanded.add(id);
          this._render();
        });
      });

      // Approve / Decline
      this.shadowRoot.querySelectorAll('.btn-approve').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          this._svc('meter_topology_approve', { upstream_id: btn.dataset.up, downstream_id: btn.dataset.down });
        });
      });
      this.shadowRoot.querySelectorAll('.btn-decline').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          this._svc('meter_topology_decline', { upstream_id: btn.dataset.up, downstream_id: btn.dataset.down });
        });
      });
    }

    static getStubConfig() { return { title: 'Meter Topologie' }; }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-overview-card  ·  Compacte hero-kaart voor het DEV overzicht
  // Toont: netimport/export, zon, huis, batterij — alles met live animatie
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsOverviewCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass = null;
      this._config = {};
      this._animId = null;
      this._tick = 0;
    }

    setConfig(c) { this._config = c; this._startAnim(); }
    set hass(h) { this._hass = h; }
    disconnectedCallback() { if (this._animId) { cancelAnimationFrame(this._animId); this._animId = null; } }
    connectedCallback() { this._startAnim(); }
    getCardSize() { return 3; }

    _startAnim() {
      if (this._animId) return;
      const loop = () => {
        this._tick++;
        if (this._tick % 4 === 0) this._render();
        this._animId = requestAnimationFrame(loop);
      };
      this._animId = requestAnimationFrame(loop);
    }

    _val(eid, fallback = 0) {
      if (!this._hass) return fallback;
      const st = this._hass.states[eid];
      if (!st) return fallback;
      let v = parseFloat(st.state) || 0;
      const u = (st.attributes?.unit_of_measurement || '').toLowerCase();
      if (u === 'kw') v *= 1000;
      return v;
    }

    _fmt(w, abs = false) {
      const v = abs ? Math.abs(w) : w;
      if (Math.abs(v) >= 1000) return (v/1000).toFixed(1) + ' kW';
      return Math.round(v) + ' W';
    }

    _render() {
      if (!this._hass) return;
      const e = this._config.entities || {};
      const grid   = this._val(e.grid   || 'sensor.cloudems_grid_net_power');
      const solar  = this._val(e.solar  || 'sensor.cloudems_solar_system_intelligence');
      const house  = this._val(e.house  || 'sensor.cloudems_house_consumption') || (Math.abs(grid) + solar);
      const batSt  = this._hass.states['sensor.cloudems_battery_so_c'];
      const soc    = batSt ? parseFloat(batSt.state) : null;
      const batW   = this._val(e.battery || 'sensor.cloudems_battery_power');

      const importing = grid > 0;
      const exporting = grid < 0;
      const gridCol   = importing ? '#e74c3c' : exporting ? '#2ecc71' : '#5dade2';
      const solarCol  = '#f39c12';
      const houseCol  = '#5dade2';
      const battCol   = batW > 0 ? '#f39c12' : batW < 0 ? '#2ecc71' : '#666';

      // Pulse animatie factor
      const pulse = 0.85 + 0.15 * Math.sin(this._tick * 0.08);

      const CSS = `
        :host { display: block; }
        * { box-sizing: border-box; }
        ha-card {
          background: linear-gradient(135deg, #0d1117 0%, #111827 100%);
          border: 1px solid rgba(255,255,255,0.07); border-radius: 18px;
          font-family: 'Inter', ui-sans-serif, sans-serif; overflow: hidden; color: #e2e8f0;
          padding: 18px;
        }
        .title { font-size: 10px; font-weight: 700; letter-spacing: 0.15em;
          text-transform: uppercase; color: rgba(255,255,255,0.25); margin-bottom: 16px; }
        .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
        .cell { display: flex; flex-direction: column; align-items: center; gap: 4px; }
        .icon { font-size: 22px; line-height: 1; }
        .val { font-size: 15px; font-weight: 800; font-variant-numeric: tabular-nums; }
        .lbl { font-size: 9px; color: rgba(255,255,255,0.3); letter-spacing: 0.08em; text-transform: uppercase; }
        .soc-bar { width: 32px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.1); margin-top: 2px; overflow: hidden; }
        .soc-fill { height: 100%; border-radius: 2px; transition: width 0.5s; }
        .status-row { display: flex; align-items: center; gap: 6px; margin-top: 14px;
          padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.05); }
        .dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .status-txt { font-size: 10px; color: rgba(255,255,255,0.4); flex: 1; }
      `;

      const price = parseFloat(this._hass.states['sensor.cloudems_energy_price_current_hour']?.state);
      const flex  = parseFloat(this._hass.states['sensor.cloudems_flex_score']?.state);

      this.shadowRoot.innerHTML = `
        <style>${CSS}</style>
        <ha-card>
          <div class="title">⚡ CloudEMS — Live</div>
          <div class="grid">
            <div class="cell">
              <div class="icon" style="filter:drop-shadow(0 0 ${6*pulse}px ${gridCol})">
                ${importing ? '🔴' : exporting ? '🟢' : '⚪'}
              </div>
              <div class="val" style="color:${gridCol}">${this._fmt(grid, true)}</div>
              <div class="lbl">${importing ? 'Import' : exporting ? 'Export' : 'Net'}</div>
            </div>
            <div class="cell">
              <div class="icon" style="filter:drop-shadow(0 0 ${solar>100?6*pulse:2}px ${solarCol})">☀️</div>
              <div class="val" style="color:${solarCol}">${this._fmt(solar)}</div>
              <div class="lbl">Zon</div>
            </div>
            <div class="cell">
              <div class="icon">🏠</div>
              <div class="val" style="color:${houseCol}">${this._fmt(house)}</div>
              <div class="lbl">Huis</div>
            </div>
            <div class="cell">
              <div class="icon" style="filter:drop-shadow(0 0 ${Math.abs(batW)>20?4*pulse:2}px ${battCol})">🔋</div>
              <div class="val" style="color:${battCol}">${soc !== null ? Math.round(soc)+'%' : '—'}</div>
              <div class="lbl">${batW > 20 ? 'Laden' : batW < -20 ? 'Ontladen' : 'Batterij'}</div>
              ${soc !== null ? `<div class="soc-bar"><div class="soc-fill" style="width:${soc}%;background:${soc>20?'#2ecc71':'#e74c3c'}"></div></div>` : ''}
            </div>
          </div>
          <div class="status-row">
            <div class="dot" style="background:${importing?'#e74c3c':'#2ecc71'};box-shadow:0 0 4px ${importing?'#e74c3c':'#2ecc71'}"></div>
            <div class="status-txt">
              ${!isNaN(price) ? `€${(price*100).toFixed(2)}ct/kWh` : ''}
              ${!isNaN(flex)  ? ` · Flex ${Math.round(flex)}%` : ''}
              ${exporting     ? ' · Teruglevering actief' : importing ? ' · Stroomafname' : ''}
            </div>
          </div>
        </ha-card>`;
    }

    static getStubConfig() { return {}; }
  }


  // ─────────────────────────────────────────────────────────────────────────
  // REGISTRATIE

// ─────────────────────────────────────────────────────────────────────────
  // cloudems-cost-card  ·  Energie kosten — dag/week/maand animatie
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsCostCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass = null;
      this._config = {};
      this._period = 'day';   // 'day' | 'month' | 'sim'
      this._animId = null;
      this._tick = 0;
    }

    setConfig(c) { this._config = { title: 'Energiekosten', ...c }; this._startAnim(); }
    set hass(h) { this._hass = h; }
    disconnectedCallback() { if (this._animId) { cancelAnimationFrame(this._animId); this._animId = null; } }
    connectedCallback() { this._startAnim(); }
    getCardSize() { return 5; }

    _startAnim() {
      if (this._animId) return;
      const loop = () => { this._tick++; if (this._tick % 6 === 0) this._render(); this._animId = requestAnimationFrame(loop); };
      this._animId = requestAnimationFrame(loop);
    }

    _val(eid, attr = null) {
      if (!this._hass) return null;
      const st = this._hass.states[eid];
      if (!st) return null;
      if (attr) return st.attributes?.[attr] ?? null;
      return parseFloat(st.state) || null;
    }

    _render() {
      if (!this._hass) return;

      const costToday  = this._val('sensor.cloudems_energy_cost') || 0;
      const costMonth  = this._val('sensor.cloudems_energy_cost', 'cost_month_eur') || 0;
      const forecast   = this._val('sensor.cloudems_energie_kosten_verwachting') || 0;
      const simSt      = this._hass.states['sensor.cloudems_bill_simulator'];
      const dynCost    = simSt?.attributes?.dynamic_cost_eur || 0;
      const fixedCost  = simSt?.attributes?.fixed_cost_eur || 0;
      const saving     = simSt?.attributes?.saving_vs_fixed_eur || 0;
      const savingPct  = simSt?.attributes?.saving_vs_fixed_pct || 0;
      const months     = simSt?.attributes?.months_data || 0;
      const bestMonth  = simSt?.attributes?.best_month || null;

      // Verbruik categorieën voor taartdiagram
      const cats = this._val('sensor.cloudems_verbruik_categorien', 'pie_data') || [];
      const totalKwh = this._val('sensor.cloudems_verbruik_categorien', 'total_kwh_today') || 0;

      // Kleurenpalet
      const CAT_COLORS = ['#00b140','#5dade2','#f39c12','#e74c3c','#9b59b6','#1abc9c','#e67e22'];

      // Donut SVG
      const donutSVG = (() => {
        if (!cats.length) return '';
        const total = cats.reduce((s, c) => s + (c.kwh || 0), 0) || 1;
        const cx = 50, cy = 50, r = 38, stroke = 14;
        let offset = 0;
        const circ = 2 * Math.PI * r;
        const slices = cats.map((c, i) => {
          const frac = (c.kwh || 0) / total;
          const dash = frac * circ;
          const gap  = circ - dash;
          const sl = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
            stroke="${CAT_COLORS[i % CAT_COLORS.length]}"
            stroke-width="${stroke}"
            stroke-dasharray="${dash.toFixed(1)} ${gap.toFixed(1)}"
            stroke-dashoffset="${(-offset * circ / (2 * Math.PI * r)).toFixed(1)}"
            transform="rotate(-90 ${cx} ${cy})"
            opacity="0.85"/>`;
          offset += frac * 2 * Math.PI;
          return sl;
        }).join('');
        return `<svg viewBox="0 0 100 100" width="120" height="120">
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="${stroke}"/>
          ${slices}
          <text x="${cx}" y="${cy - 4}" text-anchor="middle" fill="#e2e8f0" font-size="11" font-weight="700">${totalKwh.toFixed(1)}</text>
          <text x="${cx}" y="${cy + 9}" text-anchor="middle" fill="rgba(255,255,255,0.4)" font-size="7">kWh</text>
        </svg>`;
      })();

      // Besparing animatie pulse
      const pulse = 0.7 + 0.3 * Math.abs(Math.sin(this._tick * 0.05));

      const CSS = `
        :host { display: block; }
        * { box-sizing: border-box; }
        ha-card {
          background: #0d1117; border: 1px solid rgba(255,255,255,0.07);
          border-radius: 18px; font-family: 'Inter', ui-sans-serif, sans-serif;
          overflow: hidden; color: #e2e8f0;
        }
        .top { padding: 16px 18px 8px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .title { flex: 1; font-size: 10px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; color: rgba(255,255,255,0.3); }
        .tabs { display: flex; gap: 4px; }
        .tab { font-size: 10px; font-weight: 700; padding: 4px 10px; border-radius: 20px; cursor: pointer;
          border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.4); transition: all 0.12s; }
        .tab.active { background: rgba(0,177,64,0.15); color: #00b140; border-color: rgba(0,177,64,0.35); }
        .main { padding: 16px 18px; display: flex; gap: 16px; align-items: center; }
        .big-num { font-size: 42px; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; }
        .big-sub { font-size: 11px; color: rgba(255,255,255,0.35); margin-top: 4px; }
        .cats { flex: 1; }
        .cat-row { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
        .cat-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .cat-name { font-size: 11px; color: rgba(255,255,255,0.6); flex: 1; }
        .cat-val { font-size: 11px; font-weight: 700; color: #e2e8f0; }
        .cat-bar-wrap { height: 3px; background: rgba(255,255,255,0.06); border-radius: 2px; margin-bottom: 8px; }
        .cat-bar { height: 3px; border-radius: 2px; transition: width 0.5s; }
        .sim-section { padding: 0 18px 16px; }
        .sim-row { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
          background: rgba(255,255,255,0.03); border-radius: 10px; margin-bottom: 6px; border: 1px solid rgba(255,255,255,0.06); }
        .sim-label { font-size: 11px; color: rgba(255,255,255,0.5); flex: 1; }
        .sim-val { font-size: 13px; font-weight: 700; }
        .saving-banner {
          margin: 0 18px 14px; padding: 12px 16px; border-radius: 12px;
          background: rgba(0,177,64,0.1); border: 1px solid rgba(0,177,64,0.3);
          display: flex; align-items: center; gap: 12px;
        }
        .saving-val { font-size: 22px; font-weight: 800; color: #00b140; }
        .saving-txt { font-size: 11px; color: rgba(255,255,255,0.5); }
        .forecast-row { display: flex; align-items: center; gap: 10px; padding: 10px 18px 14px; }
        .fc-icon { font-size: 18px; }
        .fc-txt { font-size: 12px; color: rgba(255,255,255,0.5); flex: 1; }
        .fc-val { font-size: 14px; font-weight: 700; color: #f39c12; }
      `;

      const periodContent = this._period === 'sim' ? `
        ${saving > 0 ? `
        <div class="saving-banner">
          <div style="font-size:${20*pulse}px;transition:font-size 0.1s">💚</div>
          <div>
            <div class="saving-val">€${saving.toFixed(2)} bespaard</div>
            <div class="saving-txt">${savingPct.toFixed(1)}% goedkoper dan vast tarief · ${months} maand(en) data</div>
          </div>
        </div>` : ''}
        <div class="sim-section">
          <div class="sim-row">
            <span class="sim-label">⚡ Dynamisch (EPEX)</span>
            <span class="sim-val" style="color:#5dade2">€${dynCost.toFixed(2)}</span>
          </div>
          <div class="sim-row">
            <span class="sim-label">📌 Vast tarief equivalent</span>
            <span class="sim-val" style="color:#f39c12">€${fixedCost.toFixed(2)}</span>
          </div>
          ${bestMonth ? `<div class="sim-row">
            <span class="sim-label">🏆 Beste maand</span>
            <span class="sim-val" style="color:#2ecc71">${bestMonth}</span>
          </div>` : ''}
        </div>` : `
        <div class="main">
          <div>
            <div class="big-num" style="color:${this._period==='day'?'#5dade2':'#f39c12'}">
              €${(this._period === 'day' ? costToday : costMonth).toFixed(2)}
            </div>
            <div class="big-sub">${this._period === 'day' ? 'vandaag' : 'deze maand'}</div>
            ${donutSVG}
          </div>
          <div class="cats">
            ${cats.slice(0, 5).map((c, i) => {
              const maxKwh = cats[0]?.kwh || 1;
              const pct = ((c.kwh || 0) / maxKwh * 100).toFixed(0);
              return `<div class="cat-row">
                <div class="cat-dot" style="background:${CAT_COLORS[i % CAT_COLORS.length]}"></div>
                <div class="cat-name">${c.name || c.category || 'Overig'}</div>
                <div class="cat-val">${(c.kwh || 0).toFixed(1)} kWh</div>
              </div>
              <div class="cat-bar-wrap">
                <div class="cat-bar" style="width:${pct}%;background:${CAT_COLORS[i % CAT_COLORS.length]}"></div>
              </div>`;
            }).join('')}
          </div>
        </div>
        <div class="forecast-row">
          <div class="fc-icon">📈</div>
          <div class="fc-txt">Verwachte kosten vandaag</div>
          <div class="fc-val">€${forecast.toFixed(2)}</div>
        </div>`;

      this.shadowRoot.innerHTML = `
        <style>${CSS}</style>
        <ha-card>
          <div class="top">
            <div class="title">💶 ${this._config.title}</div>
            <div class="tabs">
              <span class="tab ${this._period==='day'?'active':''}" data-p="day">Dag</span>
              <span class="tab ${this._period==='month'?'active':''}" data-p="month">Maand</span>
              <span class="tab ${this._period==='sim'?'active':''}" data-p="sim">Simulator</span>
            </div>
          </div>
          ${periodContent}
        </ha-card>`;

      this.shadowRoot.querySelectorAll('[data-p]').forEach(el => {
        el.addEventListener('click', () => { this._period = el.dataset.p; this._render(); });
      });
    }

    static getStubConfig() { return { title: 'Energiekosten' }; }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // cloudems-schedule-card  ·  Goedkope-uren schema beheer
  // ─────────────────────────────────────────────────────────────────────────
  class CloudemsScheduleCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass = null;
      this._config = {};
      this._animId = null;
      this._tick = 0;
    }

    setConfig(c) { this._config = { title: 'Schema Beheer', ...c }; this._startAnim(); }
    set hass(h) { this._hass = h; }
    disconnectedCallback() { if (this._animId) { cancelAnimationFrame(this._animId); this._animId = null; } }
    connectedCallback() { this._startAnim(); }
    getCardSize() { return 5; }

    _startAnim() {
      if (this._animId) return;
      const loop = () => { this._tick++; if (this._tick % 6 === 0) this._render(); this._animId = requestAnimationFrame(loop); };
      this._animId = requestAnimationFrame(loop);
    }

    _render() {
      if (!this._hass) return;

      const curH    = new Date().getHours();
      const epexSt  = this._hass.states['sensor.cloudems_energy_epex_today'];
      const today   = epexSt?.attributes?.today_prices || [];
      const min     = today.length ? Math.min(...today.map(p => p.price)) : 0;
      const max     = today.length ? Math.max(...today.map(p => p.price)) : 1;
      const avg     = today.length ? today.reduce((s,p) => s+p.price,0)/today.length : 0;

      // Schakelaar schema's
      const cheapSt = this._hass.states['sensor.cloudems_goedkope_uren_schakelaars'];
      const switches = cheapSt?.attributes?.switches || [];

      // Batterij schema
      const batSt = this._hass.states['sensor.cloudems_batterij_epex_schema'];
      const batSchedule = batSt?.attributes?.schedule || [];

      // 24-uurs tijdlijn blokken
      const timeline = Array.from({length: 24}, (_, h) => {
        const priceEntry = today.find(p => p.hour === h);
        const price = priceEntry?.price ?? null;
        const isCur = h === curH;
        const isPast = h < curH;
        const isCharge = batSchedule.some(s => s.hour === h && s.action === 'charge');
        const isDischarge = batSchedule.some(s => s.hour === h && s.action === 'discharge');
        const activeSwitches = switches.filter(s => s.active_hours?.includes(h));

        let bgColor = 'rgba(255,255,255,0.04)';
        let barColor = '#5dade2';
        if (price !== null) {
          const t = (price - min) / (max - min || 1);
          if (t < 0.33) barColor = '#2ecc71';
          else if (t < 0.66) barColor = '#f39c12';
          else barColor = '#e74c3c';
        }
        if (isCharge) bgColor = 'rgba(46,204,113,0.1)';
        if (isDischarge) bgColor = 'rgba(93,173,226,0.1)';

        const h_fmt = `${String(h).padStart(2,'0')}`;
        const barH = price !== null ? Math.max(4, ((price - min)/(max - min || 1)) * 36 + 4) : 8;

        return `<div class="tl-cell ${isCur?'cur':''} ${isPast?'past':''}" title="${h_fmt}:00${price !== null ? ` · €${(price*100).toFixed(1)}ct` : ''}${isCharge?' · 🔋 laden':''}${isDischarge?' · ⚡ ontladen':''}${activeSwitches.length?' · 🔌 '+activeSwitches.map(s=>s.name).join(', '):''}">
          <div class="tl-bar" style="height:${barH}px;background:${isPast?'rgba(255,255,255,0.1)':barColor}40;border-color:${isPast?'rgba(255,255,255,0.15)':barColor}">
            ${isCharge ? '<div class="tl-icon">🔋</div>' : ''}
            ${isDischarge ? '<div class="tl-icon" style="color:#5dade2">⚡</div>' : ''}
            ${activeSwitches.length ? '<div class="tl-icon">🔌</div>' : ''}
          </div>
          <div class="tl-label">${h_fmt}</div>
        </div>`;
      }).join('');

      const CSS = `
        :host { display: block; }
        * { box-sizing: border-box; }
        ha-card {
          background: #0d1117; border: 1px solid rgba(255,255,255,0.07);
          border-radius: 18px; font-family: 'Inter', ui-sans-serif, sans-serif;
          overflow: hidden; color: #e2e8f0;
        }
        .header { padding: 14px 18px 10px; border-bottom: 1px solid rgba(255,255,255,0.05);
          display: flex; align-items: center; }
        .title { font-size: 10px; font-weight: 700; letter-spacing: 0.15em;
          text-transform: uppercase; color: rgba(255,255,255,0.3); flex: 1; }
        .legend { display: flex; gap: 10px; font-size: 9px; color: rgba(255,255,255,0.3); }
        .leg { display: flex; align-items: center; gap: 3px; }
        .tl-wrap { display: flex; align-items: flex-end; gap: 2px; padding: 12px 14px 0; height: 72px; }
        .tl-cell { flex: 1; display: flex; flex-direction: column; align-items: center;
          cursor: pointer; position: relative; min-width: 0; }
        .tl-cell:hover .tl-bar { filter: brightness(1.5); }
        .tl-cell.cur .tl-bar { outline: 1px solid rgba(255,255,255,0.5); z-index: 2; }
        .tl-cell.past { opacity: 0.4; }
        .tl-bar { width: 100%; border-radius: 2px 2px 0 0; border-bottom: 2px solid;
          display: flex; align-items: flex-start; justify-content: center; transition: filter 0.1s; min-height: 4px; }
        .tl-icon { font-size: 7px; margin-top: 2px; }
        .tl-label { font-size: 7px; color: rgba(255,255,255,0.2); margin-top: 2px;
          white-space: nowrap; overflow: hidden; }
        .tl-labels { height: 14px; }
        .section { padding: 12px 18px; border-top: 1px solid rgba(255,255,255,0.05); }
        .section-title { font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
          text-transform: uppercase; color: rgba(255,255,255,0.25); margin-bottom: 8px; }
        .sw-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px;
          background: rgba(255,255,255,0.03); border-radius: 8px; margin-bottom: 4px;
          border: 1px solid rgba(255,255,255,0.06); }
        .sw-icon { font-size: 16px; flex-shrink: 0; }
        .sw-name { flex: 1; font-size: 12px; color: #e2e8f0; }
        .sw-hours { font-size: 10px; color: rgba(255,255,255,0.35); }
        .sw-status { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .avg-line { font-size: 10px; color: rgba(255,255,255,0.3); padding: 4px 14px 10px;
          display: flex; gap: 12px; }
        .empty { padding: 20px; text-align: center; color: rgba(255,255,255,0.2); font-size: 11px; }
      `;

      this.shadowRoot.innerHTML = `
        <style>${CSS}</style>
        <ha-card>
          <div class="header">
            <div class="title">📅 ${this._config.title}</div>
            <div class="legend">
              <div class="leg"><div style="width:8px;height:8px;background:#2ecc71;border-radius:1px"></div> goedkoop</div>
              <div class="leg"><div style="width:8px;height:8px;background:#f39c12;border-radius:1px"></div> gemiddeld</div>
              <div class="leg"><div style="width:8px;height:8px;background:#e74c3c;border-radius:1px"></div> duur</div>
            </div>
          </div>

          <div class="tl-wrap">${timeline}</div>
          <div class="tl-labels"></div>

          ${today.length ? `<div class="avg-line">
            <span>gem. ${(avg*100).toFixed(1)}ct/kWh</span>
            <span>min ${(min*100).toFixed(1)}ct</span>
            <span>max ${(max*100).toFixed(1)}ct</span>
          </div>` : ''}

          ${switches.length ? `
          <div class="section">
            <div class="section-title">🔌 Schakelaar schema's</div>
            ${switches.map(sw => `
              <div class="sw-row">
                <div class="sw-icon">${sw.icon || '🔌'}</div>
                <div class="sw-name">${sw.name || sw.entity_id?.split('.').pop() || 'Schakelaar'}</div>
                <div class="sw-hours">${(sw.active_hours||[]).map(h=>String(h).padStart(2,'0')+'u').join(' ')}</div>
                <div class="sw-status" style="background:${sw.currently_on?'#2ecc71':'rgba(255,255,255,0.15)'};
                  box-shadow:${sw.currently_on?'0 0 4px #2ecc71':'none'}"></div>
              </div>`).join('')}
          </div>` : ''}

          ${batSchedule.length ? `
          <div class="section">
            <div class="section-title">🔋 Batterij planning</div>
            ${batSchedule.slice(0,6).map(s => `
              <div class="sw-row">
                <div class="sw-icon">${s.action==='charge'?'🔋':'⚡'}</div>
                <div class="sw-name">${String(s.hour).padStart(2,'0')}:00 — ${s.action==='charge'?'Laden':'Ontladen'}</div>
                <div class="sw-hours" style="color:${s.action==='charge'?'#2ecc71':'#5dade2'}">${s.price?'€'+(s.price*100).toFixed(1)+'ct':''}</div>
              </div>`).join('')}
          </div>` : ''}

          ${!switches.length && !batSchedule.length ? `
          <div class="empty">📅 Geen actieve schema's gevonden<br>
            <small>Configureer goedkope-uren schakelaars in de CloudEMS instellingen</small>
          </div>` : ''}
        </ha-card>`;
    }

    static getStubConfig() { return { title: 'Schema Beheer' }; }
  }

  const CARDS = [
    ['cloudems-chip-card',      CloudemsChipCard],
    ['cloudems-cost-card',      CloudemsCostCard],
    ['cloudems-schedule-card',  CloudemsScheduleCard],
    ['cloudems-graph-card',     CloudemsGraphCard],
    ['cloudems-flow-card',      CloudemsFlowCard],
    ['cloudems-stack-card',     CloudemsStackCard],
    ['cloudems-entity-list',    CloudemsEntityList],
    ['cloudems-nilm-card',      CloudemsNilmCard],
    ['cloudems-topology-card',  CloudemsTopologyCard],
    ['cloudems-overview-card',  CloudemsOverviewCard],
  ];

  CARDS.forEach(([name, cls]) => {
    if (!customElements.get(name)) customElements.define(name, cls);
  });

  window.customCards = window.customCards || [];
  window.customCards.push(
    { type: 'cloudems-chip-card',      name: 'CloudEMS Chip',           description: 'Status chip met template rendering' },
    { type: 'cloudems-graph-card',     name: 'CloudEMS Grafiek',         description: 'Lijngrafieken uit HA history' },
    { type: 'cloudems-flow-card',      name: 'CloudEMS Energiestroom',   description: 'Energie-flow diagram' },
    { type: 'cloudems-stack-card',     name: 'CloudEMS Stack',           description: 'Kaarten naadloos stapelen' },
    { type: 'cloudems-entity-list',    name: 'CloudEMS Entiteitslijst',  description: 'Dynamische entiteitslijst' },
    { type: 'cloudems-nilm-card',      name: 'CloudEMS NILM Beheer',     description: 'NILM apparaten per kamer beheren' },
    { type: 'cloudems-cost-card',      name: 'CloudEMS Kosten',          description: 'Dag/maand kosten met donut + simulator' },
    { type: 'cloudems-schedule-card',  name: 'CloudEMS Schema Beheer',   description: '24u tijdlijn met batterij- en schakelaarplanning' },
    { type: 'cloudems-topology-card',  name: 'CloudEMS Meter Topologie', description: 'Meter-boom met upstream learning' },
    { type: 'cloudems-overview-card',  name: 'CloudEMS Live Overzicht',  description: 'Hero-kaart met live energie-animatie' },
  );

  console.info('%c CloudEMS Cards 2.2.1 %c geladen ',
    'background:#00b140;color:#fff;font-weight:700;border-radius:4px 0 0 4px;padding:2px 6px',
    'background:#222;color:#00b140;font-weight:600;border-radius:0 4px 4px 0;padding:2px 6px'
  );

})();
