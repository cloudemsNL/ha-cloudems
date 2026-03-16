/**
 * CloudEMS NILM Card — cloudems-nilm-card
 * Version: 1.0.0
 * Tabs: Actief nu | Beoordelen | Alle apparaten | Topologie | Diagnostiek
 */
class CloudEMSNilmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._tab = 'actief';
    this._search = '';
    this._prev = '';
  }

  setConfig(c) { this._config = c || {}; }

  set hass(h) {
    this._hass = h;
    const j = JSON.stringify([
      h.states['sensor.cloudems_nilm_devices']?.last_changed,
      h.states['sensor.cloudems_nilm_running_devices']?.last_changed,
      h.states['sensor.cloudems_nilm_review_current']?.last_changed,
      h.states['sensor.cloudems_nilm_topology']?.last_changed,
    ]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _s(e) { return this._hass?.states?.[e] || null; }
  _a(e, k, d = null) { return this._s(e)?.attributes?.[k] ?? d; }
  _v(e, d = 0) {
    const s = this._s(e);
    if (!s || s.state === 'unavailable' || s.state === 'unknown') return d;
    return parseFloat(s.state) || d;
  }

  _callService(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _render() {
    if (!this._hass) return;

    const running = this._a('sensor.cloudems_nilm_running_devices', 'device_list') || [];
    const allDevs = this._a('sensor.cloudems_nilm_devices', 'device_list') || [];
    const review = this._s('sensor.cloudems_nilm_review_current');
    const reviewPending = this._a('sensor.cloudems_nilm_review_current', 'pending_count') || 0;
    const totalDevs = allDevs.length;
    const activeCount = running.length;
    const totalPower = running.reduce((s, d) => s + (d.power_w || 0), 0);

    const sig = [this._tab, this._search, this._v('sensor.cloudems_nilm_running_devices'), reviewPending, totalDevs].join('|');
    if (sig === this._prev) return;
    this._prev = sig;

    const TABS = [
      { id: 'actief',   label: 'Actief nu' },
      { id: 'review',   label: `Beoordelen${reviewPending > 0 ? ` (${reviewPending})` : ''}` },
      { id: 'alle',     label: 'Alle apparaten' },
      { id: 'topo',     label: 'Topologie' },
      { id: 'diag',     label: 'Diagnostiek' },
    ];

    const tabBar = TABS.map(t => `
      <button class="tab${this._tab === t.id ? ' active' : ''}" data-tab="${t.id}">${t.label}</button>
    `).join('');

    // Phase balance
    const l1w = running.filter(d => d.phase === 'L1').reduce((s, d) => s + (d.power_w || 0), 0);
    const l2w = running.filter(d => d.phase === 'L2').reduce((s, d) => s + (d.power_w || 0), 0);
    const l3w = running.filter(d => d.phase === 'L3').reduce((s, d) => s + (d.power_w || 0), 0);
    const maxPhase = Math.max(l1w, l2w, l3w, 1);

    const phaseBar = (label, w, color) => `
      <div class="pb-row">
        <span class="pb-lbl">${label}</span>
        <div class="pb-track"><div class="pb-fill" style="width:${Math.round(w/maxPhase*100)}%;background:${color}"></div></div>
        <span class="pb-val">${Math.round(w)} W</span>
      </div>`;

    const phaseSection = `<div class="phase-bar">
      ${phaseBar('L1', l1w, '#06b6d4')}
      ${phaseBar('L2', l2w, '#f59e0b')}
      ${phaseBar('L3', l3w, '#34d399')}
    </div>`;

    // ── Tab content ──────────────────────────────────────────────────────────
    let content = '';

    if (this._tab === 'actief') {
      const rows = running.sort((a, b) => (b.power_w || 0) - (a.power_w || 0)).map(d => {
        const conf = d.confidence || 0;
        const confColor = conf >= 70 ? '#34d399' : conf >= 50 ? '#f59e0b' : '#ef4444';
        const phaseColor = d.phase === 'L1' ? '#06b6d4' : d.phase === 'L2' ? '#f59e0b' : '#34d399';
        const src = (d.source_type === 'smart_plug' || d.source_type === 'injected') ? 'plug' : 'nilm';
        return `<div class="dev-row">
          <div class="dev-dot" style="background:${d.confirmed ? '#34d399' : '#f59e0b'}"></div>
          <span class="dev-name" data-did="${d.device_id||''}" data-dname="${(d.name||d.type||'?').replace(/"/g,'')}"">${d.name || d.type || '?'}</span>
          <span class="dev-w">${Math.round(d.power_w || 0)} W</span>
          <span class="badge" style="background:${phaseColor}22;color:${phaseColor}">${d.phase_label || d.phase || '?'}</span>
          <span class="src-lbl">${src}</span>
          <div class="conf-wrap">
            <div class="conf-bar"><div class="conf-fill" style="width:${Math.min(100,conf)}%;background:${confColor}"></div></div>
            <span class="conf-val" style="color:${confColor}">${src === 'plug' ? '100%' : conf + '%'}</span>
          </div>
        </div>`;
      }).join('');

      const unknownW = this._a('sensor.cloudems_nilm_devices', 'undefined_power_w') || 0;
      content = `
        ${phaseSection}
        <div class="list-header">
          <span class="lh-name">Apparaat</span>
          <span class="lh-w">Vermogen</span>
          <span class="lh-phase">Fase</span>
          <span class="lh-src">Bron</span>
          <span class="lh-conf">Conf.</span>
        </div>
        <div class="dev-list">${rows || '<div class="empty">Geen actieve apparaten</div>'}</div>
        ${unknownW > 50 ? `<div class="unknown-row">Onverklaard vermogen: ${Math.round(unknownW)} W</div>` : ''}`;
    }

    else if (this._tab === 'review') {
      const state = review?.state;
      if (!state || state === 'none') {
        content = `<div class="empty-big">✓ Alle apparaten beoordeeld</div>`;
      } else {
        // Get all pending devices from allDevs
        const pending = allDevs.filter(d => !d.confirmed && d.device_id && !d.device_id.startsWith('__'));
        const curName = this._a('sensor.cloudems_nilm_review_current', 'name') || state;
        // Current device highlighted
        const curId = state;
        const rows = pending.map(d => {
          const isCur = (d.name === curName || d.device_id === curId);
          const conf = Math.round((d.confidence || 0) * 100);
          const confColor = conf >= 70 ? '#34d399' : conf >= 50 ? '#f59e0b' : '#ef4444';
          const phaseColor = d.phase === 'L1' ? '#06b6d4' : d.phase === 'L2' ? '#f59e0b' : '#34d399';
          return `<div class="rev-row${isCur ? ' rev-cur' : ''}" data-rid="${d.device_id||''}">
            <div class="dev-dot" style="background:${isCur?'#06b6d4':'rgba(255,255,255,0.15)'}"></div>
            <span class="dev-name">${d.name || d.type || '?'}</span>
            <span class="dev-w">${Math.round(d.power_w || 0)} W</span>
            <span class="badge" style="background:${phaseColor}22;color:${phaseColor}">${d.phase||'?'}</span>
            <span class="conf-val" style="color:${confColor}">${conf}%</span>
            <div class="rev-acts">
              <button class="ra-btn ra-y" title="Bevestigen" data-svc="button/cloudems_nilm_review_confirm" data-cur="${isCur}">✓</button>
              <button class="ra-btn ra-n" title="Afwijzen"  data-svc="button/cloudems_nilm_review_dismiss" data-cur="${isCur}">✗</button>
              <button class="ra-btn ra-m" title="Weet ik niet" data-svc="button/cloudems_nilm_review_maybe" data-cur="${isCur}">?</button>
            </div>
          </div>`;
        }).join('');
        content = `
          <div class="rev-hint">Klik op een rij om die als actief in te stellen, dan de actieknop.</div>
          <div class="list-header" style="grid-template-columns:12px 1fr 60px 44px 44px 90px">
            <span></span><span class="lh-name">Apparaat</span><span class="lh-w">W</span>
            <span class="lh-phase">Fase</span><span class="lh-conf">Conf</span><span style="text-align:right">Actie</span>
          </div>
          <div class="dev-list">${rows || '<div class="empty">Geen apparaten te beoordelen</div>'}</div>`;
      }
    }

    else if (this._tab === 'alle') {
      const q = this._search.toLowerCase();
      const filtered = allDevs.filter(d =>
        !q || (d.name || d.type || '').toLowerCase().includes(q)
      );
      const rows = filtered.map(d => {
        const isOn = d.is_on || d.running || d.state === 'on';
        const conf = Math.round((d.confidence || 0) * 100);
        const confColor = conf >= 70 ? '#34d399' : conf >= 50 ? '#f59e0b' : '#ef4444';
        return `<div class="dev-row ${isOn ? 'dev-on' : 'dev-off'}">
          <div class="dev-dot" style="background:${isOn ? '#34d399' : 'rgba(255,255,255,0.15)'}"></div>
          <span class="dev-name" data-did="${d.device_id||''}" data-dname="${(d.name||d.type||'?').replace(/"/g,'')}"">${d.name || d.type || '?'}</span>
          <span class="dev-w" style="color:${isOn ? '#fff' : 'rgba(255,255,255,0.4)'}">${isOn ? Math.round(d.power_w || d.current_power || 0) + ' W' : '—'}</span>
          <span class="badge" style="background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.5)">${d.phase || '?'}</span>
          <span class="src-lbl">${d.confirmed ? '✓' : '~'}</span>
          <span class="conf-val" style="color:${confColor}">${conf}%</span>
        </div>`;
      }).join('');
      content = `
        <div class="search-wrap">
          <input class="search-input" type="text" placeholder="Zoek apparaat…" value="${this._search}">
          <span class="search-count">${filtered.length}/${totalDevs}</span>
        </div>
        <div class="list-header">
          <span class="lh-name">Apparaat</span>
          <span class="lh-w">Vermogen</span>
          <span class="lh-phase">Fase</span>
          <span class="lh-src">Conf.</span>
          <span class="lh-conf">%</span>
        </div>
        <div class="dev-list">${rows || '<div class="empty">Geen apparaten gevonden</div>'}</div>`;
    }

    else if (this._tab === 'topo') {
      const tree = this._a('sensor.cloudems_meter_topology', 'tree') || [];
      const stats = this._a('sensor.cloudems_meter_topology', 'stats') || {};
      const suggestions = this._a('sensor.cloudems_meter_topology', 'suggestions') || [];

      const renderNode = (node, depth = 0) => {
        if (!node) return '';
        const indent = depth * 16;
        const children = (node.children || []).map(c => renderNode(c, depth + 1)).join('');
        const color = node.status === 'approved' ? '#34d399' : node.status === 'tentative' ? '#f59e0b' : 'rgba(255,255,255,0.3)';
        return `<div class="topo-node" style="margin-left:${indent}px">
          <div class="topo-dot" style="background:${color}"></div>
          <span class="topo-name">${node.name || node.entity_id || '?'}</span>
          <span class="topo-status" style="color:${color}">${node.status || ''}</span>
        </div>${children}`;
      };

      const treeHtml = Array.isArray(tree) ? tree.map(n => renderNode(n)).join('') : renderNode(tree);
      const suggestHtml = suggestions.slice(0, 5).map(s =>
        `<div class="sugg-row">? ${s.child_name || s.child || '?'} → ${s.parent_name || s.parent || '?'} <span style="color:#f59e0b">${Math.round((s.confidence || 0) * 100)}%</span></div>`
      ).join('');

      // Manual add form
      const manualHtml = `
        <div class="section-lbl">Handmatig koppelen</div>
        <div class="topo-manual">
          <input class="topo-inp" id="topo-up" placeholder="Upstream entity_id (bijv. sensor.p1_power)" />
          <span style="color:rgba(255,255,255,0.4);font-size:12px">→</span>
          <input class="topo-inp" id="topo-dn" placeholder="Downstream entity_id (bijv. sensor.wcd_garage_1)" />
          <button class="topo-add-btn" id="topo-add-btn">Bevestig koppeling</button>
        </div>`;

      content = `
        <div class="topo-stats">
          <div class="stat-pill">Bevestigd: ${stats.approved || 0}</div>
          <div class="stat-pill">Tentatief: ${stats.tentative || 0}</div>
          <div class="stat-pill">Kandidaat: ${stats.candidate || 0}</div>
        </div>
        <div class="section-lbl">Topologie boom</div>
        <div class="topo-tree">${treeHtml || '<div class="empty">Nog geen data — CloudEMS leert automatisch na 8+ co-bewegingen (MIN_DELTA=50W)</div>'}</div>
        ${suggestHtml ? `<div class="section-lbl">Suggesties</div><div class="sugg-list">${suggestHtml}</div>` : ''}
        ${manualHtml}`;
    }

    else if (this._tab === 'diag') {
      const threshold = this._a('sensor.cloudems_nilm_diagnostics', 'power_threshold_w') || 0;
      const ramp = this._a('sensor.cloudems_nilm_diagnostics', 'batt_ramp_mask_active') || false;
      const rampS = this._a('sensor.cloudems_nilm_diagnostics', 'batt_ramp_mask_remaining_s') || 0;
      const inputs = this._a('sensor.cloudems_nilm_diagnostics', 'sensor_inputs') || {};
      const evTotal = this._a('sensor.cloudems_nilm_diagnostics', 'events_total') || 0;
      const evClass = this._a('sensor.cloudems_nilm_diagnostics', 'events_classified') || 0;
      const classRate = evTotal > 0 ? Math.round(evClass / evTotal * 100) : 0;

      const schedules = this._a('sensor.cloudems_nilm_apparaat_schemas', 'schedules') || [];
      const schRows = schedules.slice(0, 10).map(s =>
        `<div class="sch-row">
          <span class="dev-name">${s.label || s.device_type || '?'}</span>
          <span class="sch-day">${['Ma','Di','Wo','Do','Vr','Za','Zo'][s.peak_weekday] || '?'}</span>
          <span class="sch-hr">${s.peak_hour !== undefined ? s.peak_hour + ':00' : '?'}</span>
        </div>`
      ).join('');

      content = `
        <div class="diag-grid">
          <div class="diag-item"><div class="diag-lbl">Detectiedrempel</div><div class="diag-val">${Math.round(threshold)} W</div></div>
          <div class="diag-item"><div class="diag-lbl">Batterij masker</div><div class="diag-val" style="color:${ramp ? '#ef4444' : '#34d399'}">${ramp ? `Actief ${Math.round(rampS)}s` : 'Inactief'}</div></div>
          <div class="diag-item"><div class="diag-lbl">Events totaal</div><div class="diag-val">${evTotal}</div></div>
          <div class="diag-item"><div class="diag-lbl">Classificatiegraad</div><div class="diag-val" style="color:${classRate > 70 ? '#34d399' : '#f59e0b'}">${classRate}%</div></div>
          <div class="diag-item"><div class="diag-lbl">Sensor L1</div><div class="diag-val">${inputs.L1 || '—'}</div></div>
          <div class="diag-item"><div class="diag-lbl">Sensor L2</div><div class="diag-val">${inputs.L2 || '—'}</div></div>
          <div class="diag-item"><div class="diag-lbl">Sensor L3</div><div class="diag-val">${inputs.L3 || '—'}</div></div>
        </div>
        ${schRows ? `<div class="section-lbl">Geleerde schema's</div>
        <div class="list-header" style="grid-template-columns:1fr 60px 60px">
          <span class="lh-name">Apparaat</span><span class="lh-w">Dag</span><span class="lh-w">Uur</span>
        </div>
        <div class="dev-list">${schRows}</div>` : ''}`;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; font-family:var(--primary-font-family,sans-serif); height:100%; }
        .card { background:rgb(24,24,24); border-radius:16px; overflow:hidden; display:flex; flex-direction:column; min-height:600px; }
        /* Header */
        .header { padding:12px 16px 0; border-bottom:1px solid rgba(255,255,255,0.07); }
        .header-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
        .title { font-size:12px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:rgba(255,255,255,0.5); }
        .badges { display:flex; gap:6px; }
        .badge { font-size:10px; padding:2px 7px; border-radius:99px; }
        .badge-g { background:rgba(52,211,153,0.15); color:#34d399; }
        .badge-b { background:rgba(6,182,212,0.15); color:#06b6d4; }
        .badge-o { background:rgba(245,158,11,0.15); color:#f59e0b; }
        .total-w { font-size:11px; color:rgba(255,255,255,0.35); }
        /* Tabs */
        .tabs { display:flex; gap:0; overflow-x:auto; }
        .tab { padding:8px 14px; font-size:12px; font-weight:500; color:rgba(255,255,255,0.45); border:none; background:none; cursor:pointer; border-bottom:2px solid transparent; white-space:nowrap; }
        .tab.active { color:#06b6d4; border-bottom-color:#06b6d4; }
        .tab:hover:not(.active) { color:rgba(255,255,255,0.7); }
        /* Phase bar */
        .phase-bar { padding:8px 16px; background:rgba(255,255,255,0.03); border-bottom:1px solid rgba(255,255,255,0.05); display:flex; flex-direction:column; gap:4px; }
        .pb-row { display:flex; align-items:center; gap:8px; }
        .pb-lbl { font-size:10px; color:rgba(255,255,255,0.35); min-width:16px; }
        .pb-track { flex:1; height:4px; background:rgba(255,255,255,0.08); border-radius:2px; overflow:hidden; }
        .pb-fill { height:100%; border-radius:2px; transition:width .3s; }
        .pb-val { font-size:11px; color:rgba(255,255,255,0.55); min-width:50px; text-align:right; }
        /* Content */
        .content { flex:1; overflow-y:auto; }
        /* List header */
        .list-header { display:grid; grid-template-columns:1fr 70px 48px 40px 70px; gap:0; padding:6px 16px 4px; font-size:10px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:rgba(255,255,255,0.25); border-bottom:1px solid rgba(255,255,255,0.05); }
        .lh-name {}
        .lh-w { text-align:right; }
        .lh-phase { text-align:center; }
        .lh-src { text-align:center; }
        .lh-conf { text-align:right; }
        /* Device rows */
        .dev-list { }
        .dev-row { display:grid; grid-template-columns:12px 1fr 70px 48px 40px 70px; gap:0 6px; padding:8px 16px; align-items:center; border-bottom:1px solid rgba(255,255,255,0.04); transition:background .1s; }
        .dev-row:hover { background:rgba(255,255,255,0.03); }
        .dev-off { opacity:.45; }
        .dev-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
        .dev-name { font-size:13px; color:rgba(255,255,255,0.85); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .dev-w { font-size:12px; font-weight:600; color:#fff; text-align:right; }
        .badge { font-size:10px; padding:2px 5px; border-radius:4px; text-align:center; }
        .src-lbl { font-size:10px; color:rgba(255,255,255,0.3); text-align:center; }
        .conf-wrap { display:flex; align-items:center; gap:4px; justify-content:flex-end; }
        .conf-bar { width:28px; height:4px; background:rgba(255,255,255,0.08); border-radius:2px; overflow:hidden; }
        .conf-fill { height:100%; border-radius:2px; }
        .conf-val { font-size:10px; min-width:30px; text-align:right; }
        /* Review */
        .review-card { margin:16px; padding:20px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:12px; }
        .review-name { font-size:18px; font-weight:600; color:#fff; margin-bottom:10px; }
        .review-meta { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
        .review-meta span { font-size:12px; color:rgba(255,255,255,0.55); background:rgba(255,255,255,0.06); padding:3px 8px; border-radius:99px; }
        .review-pending { color:#f59e0b !important; background:rgba(245,158,11,0.1) !important; }
        .review-btns { display:flex; gap:8px; flex-wrap:wrap; }
        .rbtn { flex:1; min-width:80px; padding:8px 12px; border-radius:8px; border:none; font-size:12px; font-weight:600; cursor:pointer; }
        .rbtn-yes { background:rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3); }
        .rbtn-no { background:rgba(239,68,68,0.12); color:#ef4444; border:1px solid rgba(239,68,68,0.25); }
        .rbtn-maybe { background:rgba(245,158,11,0.12); color:#f59e0b; border:1px solid rgba(245,158,11,0.25); }
        .rbtn-nav { background:rgba(255,255,255,0.06); color:rgba(255,255,255,0.5); border:1px solid rgba(255,255,255,0.1); }
        /* Search */
        .search-wrap { display:flex; align-items:center; gap:8px; padding:10px 16px; border-bottom:1px solid rgba(255,255,255,0.05); }
        .search-input { flex:1; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:6px 10px; color:#fff; font-size:13px; outline:none; }
        .search-count { font-size:11px; color:rgba(255,255,255,0.35); }
        /* Topology */
        .topo-stats { display:flex; gap:8px; padding:12px 16px 8px; flex-wrap:wrap; }
        .stat-pill { font-size:11px; color:rgba(255,255,255,0.6); background:rgba(255,255,255,0.06); padding:3px 10px; border-radius:99px; }
        .topo-tree { padding:8px 16px; }
        .topo-node { display:flex; align-items:center; gap:6px; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.03); }
        .topo-dot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
        .topo-name { font-size:12px; color:rgba(255,255,255,0.8); flex:1; }
        .topo-status { font-size:10px; }
        .sugg-list { padding:0 16px 12px; }
        .sugg-row { font-size:12px; color:rgba(255,255,255,0.5); padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.03); }
        /* Diagnostics */
        .diag-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:12px 16px; }
        .diag-item { background:rgba(255,255,255,0.04); border-radius:8px; padding:10px 12px; }
        .diag-lbl { font-size:10px; color:rgba(255,255,255,0.4); text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px; }
        .diag-val { font-size:14px; font-weight:600; color:#fff; }
        /* Schedule */
        .sch-row { display:grid; grid-template-columns:1fr 60px 60px; gap:0; padding:7px 16px; border-bottom:1px solid rgba(255,255,255,0.04); font-size:12px; color:rgba(255,255,255,0.7); }
        .sch-day, .sch-hr { color:rgba(255,255,255,0.45); text-align:right; }
        /* Misc */
        .section-lbl { font-size:10px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:rgba(255,255,255,0.3); padding:12px 16px 4px; }
        .empty { padding:24px 16px; font-size:13px; color:rgba(255,255,255,0.3); text-align:center; }
        .empty-big { padding:60px 16px; font-size:16px; color:rgba(255,255,255,0.3); text-align:center; }
        .rev-row { display:grid; grid-template-columns:12px 1fr 60px 44px 44px 90px; gap:0 6px; padding:7px 16px; border-bottom:1px solid rgba(255,255,255,0.04); align-items:center; cursor:pointer; }
        .rev-row:hover { background:rgba(255,255,255,0.03); }
        .rev-cur { background:rgba(6,182,212,0.07) !important; border-left:2px solid #06b6d4; }
        .rev-acts { display:flex; gap:4px; justify-content:flex-end; }
        .ra-btn { width:24px; height:24px; border-radius:6px; border:none; font-size:12px; font-weight:700; cursor:pointer; }
        .ra-y { background:rgba(52,211,153,0.15); color:#34d399; }
        .ra-n { background:rgba(239,68,68,0.12); color:#ef4444; }
        .ra-m { background:rgba(245,158,11,0.12); color:#f59e0b; }
        .rev-hint { font-size:10px; color:rgba(255,255,255,0.3); padding:6px 16px 2px; }
        .topo-manual { display:flex; gap:6px; align-items:center; padding:8px 16px 12px; flex-wrap:wrap; }
        .topo-inp { flex:1; min-width:160px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.12); border-radius:6px; padding:6px 8px; color:#fff; font-size:11px; outline:none; }
        .topo-add-btn { background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.3); color:#34d399; border-radius:6px; padding:6px 10px; font-size:11px; cursor:pointer; white-space:nowrap; }
        .unknown-row { font-size:11px; color:rgba(245,158,11,0.8); padding:6px 16px; background:rgba(245,158,11,0.06); }
      </style>

      <div class="card">
        <div class="header">
          <div class="header-top">
            <span class="title">NILM Apparaten</span>
            <div class="badges">
              <span class="badge badge-g">${totalDevs} gevonden</span>
              <span class="badge badge-b">${activeCount} actief</span>
              ${reviewPending > 0 ? `<span class="badge badge-o">${reviewPending} te beoordelen</span>` : ''}
            </div>
            <span class="total-w">${Math.round(totalPower)} W</span>
          </div>
          <div class="tabs">${tabBar}</div>
        </div>
        <div class="content">${content}</div>
      </div>`;

    // Events
    // Review row click → navigate to that device (next/prev until match)
    this.shadowRoot.querySelectorAll('.rev-row').forEach(row => {
      row.addEventListener('click', e => {
        if (e.target.classList.contains('ra-btn')) return; // handled below
      });
    });
    // Review action buttons
    this.shadowRoot.querySelectorAll('.ra-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const [domain, entity] = btn.dataset.svc.split('/');
        this._hass.callService(domain, 'press', { entity_id: `button.${entity}` });
        setTimeout(() => { this._prev = ''; this._render(); }, 600);
      });
    });
    // Topology manual add
    const topoBtn = this.shadowRoot.querySelector('#topo-add-btn');
    if (topoBtn) {
      topoBtn.addEventListener('click', () => {
        const up = this.shadowRoot.querySelector('#topo-up')?.value?.trim();
        const dn = this.shadowRoot.querySelector('#topo-dn')?.value?.trim();
        if (up && dn) {
          this._hass.callService('cloudems', 'topology_approve', { upstream_id: up, downstream_id: dn });
          this.shadowRoot.querySelector('#topo-up').value = '';
          this.shadowRoot.querySelector('#topo-dn').value = '';
          setTimeout(() => { this._prev = ''; this._render(); }, 600);
        }
      });
    }
    this.shadowRoot.querySelectorAll('[data-did]').forEach(el=>{
      el.addEventListener('dblclick',e=>{
        e.stopPropagation();
        const did=el.dataset.did; const cur=el.dataset.dname||el.textContent;
        if(!did)return;
        const inp=document.createElement('input');
        inp.value=cur;
        inp.style.cssText='background:rgba(255,255,255,0.1);border:1px solid rgba(6,182,212,0.5);border-radius:4px;color:#fff;font-size:13px;padding:2px 6px;width:140px;outline:none';
        el.replaceWith(inp); inp.focus(); inp.select();
        const save=()=>{
          const n=inp.value.trim();
          if(n&&n!==cur)this._hass.callService('cloudems','rename_nilm_device',{device_id:did,name:n});
          this._prev=''; setTimeout(()=>this._render(),400);
        };
        inp.addEventListener('keydown',e=>{if(e.key==='Enter')save();if(e.key==='Escape'){this._prev='';this._render();}});
        inp.addEventListener('blur',save);
      });
    });
    this.shadowRoot.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        this._tab = btn.dataset.tab;
        this._prev = '';
        this._render();
      });
    });

    this.shadowRoot.querySelectorAll('.rbtn[data-svc]').forEach(btn => {
      btn.addEventListener('click', () => {
        const [domain, entity] = btn.dataset.svc.split('/');
        this._hass.callService(domain, 'press', { entity_id: `button.${entity}` });
        setTimeout(() => { this._prev = ''; this._render(); }, 500);
      });
    });

    const searchInput = this.shadowRoot.querySelector('.search-input');
    if (searchInput) {
      searchInput.addEventListener('input', e => {
        this._search = e.target.value;
        this._prev = '';
        this._render();
      });
    }
  }

  getCardSize() { return 12; }
  static getConfigElement() { return document.createElement('cloudems-nilm-card-editor'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-nilm-card')) {
  customElements.define('cloudems-nilm-card', CloudEMSNilmCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-nilm-card')) {
  window.customCards.push({ type: 'cloudems-nilm-card', name: 'CloudEMS NILM Card', description: 'NILM apparaten, beoordelen, topologie, diagnostiek' });
}

if (!customElements.get('cloudems-nilm-card-editor')) {
  class _cloudems_nilm_card_editor extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});}
    setConfig(c){this._cfg=c;this._render();}
    _fire(key,val){
      this._cfg={...this._cfg,[key]:val};
      this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));
    }
    _render(){
      const cfg=this._cfg||{};
      this.shadowRoot.innerHTML=`<style>
        .row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:0.5px solid rgba(255,255,255,0.08)}
        label{font-size:12px;color:rgba(255,255,255,0.6)}
        input{background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.15);border-radius:6px;color:#fff;padding:4px 8px;font-size:12px;width:180px}
      </style>
      <div style="padding:8px"></div>`;
    }
  }
  customElements.define('cloudems-nilm-card-editor', _cloudems_nilm_card_editor);
}
