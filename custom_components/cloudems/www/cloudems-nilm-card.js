/**
 * CloudEMS NILM Card  v2.0.0
 * Één overzicht — per kamer, per categorie, snelfilter, inline beoordelen
 */

// ── Categorie → icoon + kleur ────────────────────────────────────────────────
const CARD_NILM_VERSION = '5.4.96';
const CAT = {
  verlichting:    { i:'💡', c:'#fde047' },
  entertainment:  { i:'📺', c:'#a78bfa' },
  koeling:        { i:'❄️', c:'#67e8f9' },
  wasgoed:        { i:'🧺', c:'#38bdf8' },
  koken:          { i:'🍳', c:'#fb923c' },
  verwarming:     { i:'🔥', c:'#f87171' },
  transport:      { i:'🚗', c:'#4ade80' },
  computer:       { i:'💻', c:'#818cf8' },
  gereedschap:    { i:'🔧', c:'#94a3b8' },
  smart_plug:     { i:'🔌', c:'#34d399' },
  boiler:         { i:'🛁', c:'#fb923c' },
  overig:         { i:'⚡', c:'#6b7280' },
};

// Normaliseer device_type → categorie
function devCat(type) {
  const t = (type || '').toLowerCase();
  if (/light|lamp|verlichting|led/.test(t))                  return 'verlichting';
  if (/tv|television|media|audio|speaker|entertain/.test(t)) return 'entertainment';
  if (/fridge|freezer|koeling|koel|vriezer/.test(t))         return 'koeling';
  if (/washer|wash|dryer|wasmach|was|droog/.test(t))         return 'wasgoed';
  if (/oven|micro|cook|kook|keuken|stove|grill/.test(t))     return 'koken';
  if (/heat|verwar|boiler|cv|water_heat/.test(t))            return 'boiler';
  if (/ev|car|vehicle|charge|laad|transport/.test(t))        return 'transport';
  if (/pc|computer|laptop|monitor|printer|server/.test(t))   return 'computer';
  if (/drill|zaag|tool|gereed/.test(t))                      return 'gereedschap';
  if (/smart_plug|plug|stopcontact/.test(t))                 return 'smart_plug';
  return 'overig';
}

// Confidence balk — 10 blokjes
function confBar(pct, size = 10) {
  const filled = Math.round((pct / 100) * size);
  const col = pct >= 70 ? '#4ade80' : pct >= 45 ? '#fb923c' : '#f87171';
  return `<span class="cbar">${Array.from({length: size}, (_, i) =>
    `<span class="cb${i < filled ? ' on' : ''}" style="${i < filled ? `background:${col}` : ''}"></span>`
  ).join('')}</span><span class="cpct" style="color:${col}">${Math.round(pct)}%</span>`;
}

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// ── CSS ──────────────────────────────────────────────────────────────────────
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host{display:block}
  *{box-sizing:border-box;margin:0;padding:0}
  .card{background:#0e1520;border-radius:16px;border:1px solid rgba(255,255,255,0.06);font-family:'Syne',sans-serif;overflow:hidden}

  /* ── Header ── */
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 10px;border-bottom:1px solid rgba(255,255,255,0.06)}
  .hdr-icon{font-size:20px}
  .hdr-title{font-size:13px;font-weight:700;color:#f1f5f9;letter-spacing:.04em;text-transform:uppercase}
  .hdr-sub{font-size:11px;color:#6b7280;margin-top:2px}
  .hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px}
  .total-pill{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:#fde047;background:rgba(253,224,71,0.08);border:1px solid rgba(253,224,71,0.2);border-radius:10px;padding:3px 10px}

  /* ── Zoekbalk ── */
  .search-row{display:flex;align-items:center;gap:8px;padding:8px 18px;border-bottom:1px solid rgba(255,255,255,0.05)}
  .search-inp{flex:1;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:6px 10px;color:#fff;font-size:12px;outline:none;font-family:'Syne',sans-serif}
  .search-inp:focus{border-color:rgba(96,165,250,0.4);background:rgba(96,165,250,0.06)}
  .search-clr{font-size:14px;cursor:pointer;color:#4b5563;padding:2px 4px}
  .search-count{font-size:10px;color:#374151;white-space:nowrap}

  /* ── Filter tabs ── */
  .filters{display:flex;gap:0;overflow-x:auto;padding:0 18px;border-bottom:1px solid rgba(255,255,255,0.05);scrollbar-width:none}
  .filters::-webkit-scrollbar{display:none}
  .ftab{padding:8px 12px;font-size:11px;font-weight:700;color:#4b5563;cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent;letter-spacing:.03em}
  .ftab.active{color:#7dd3fc;border-bottom-color:#7dd3fc}
  .ftab .badge{display:inline-block;background:rgba(248,113,113,0.2);color:#f87171;border-radius:8px;padding:0 5px;font-size:9px;margin-left:4px}

  /* ── Beoordelen banner ── */
  .review-banner{margin:12px 18px 0;border-radius:12px;overflow:hidden;background:rgba(96,165,250,0.07);border:1px solid rgba(96,165,250,0.2)}
  .rev-hdr{display:flex;align-items:center;gap:8px;padding:10px 14px 0}
  .rev-hdr-title{font-size:12px;font-weight:700;color:#7dd3fc;flex:1}
  .rev-count{font-size:10px;color:#4b5563}
  .rev-device{padding:8px 14px 4px}
  .rev-name{font-size:15px;font-weight:700;color:#f1f5f9;margin-bottom:4px}
  .rev-meta{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
  .rev-btns{display:flex;gap:8px;padding:0 0 12px;flex-wrap:wrap}
  .rbtn{flex:1;min-width:90px;padding:8px 10px;border-radius:10px;border:1px solid;font-size:12px;font-weight:700;cursor:pointer;font-family:'Syne',sans-serif;letter-spacing:.02em;transition:opacity .15s}
  .rbtn:active{opacity:.7}
  .rbtn-yes{background:rgba(74,222,128,0.12);border-color:rgba(74,222,128,0.35);color:#4ade80}
  .rbtn-no{background:rgba(248,113,113,0.10);border-color:rgba(248,113,113,0.3);color:#f87171}
  .rbtn-skip{background:rgba(255,255,255,0.04);border-color:rgba(255,255,255,0.1);color:#6b7280}
  .rev-queue{padding:0 14px 10px;display:flex;gap:5px;flex-wrap:wrap}
  .rev-q-chip{font-size:10px;padding:2px 8px;border-radius:8px;background:rgba(255,255,255,0.05);color:#4b5563;cursor:pointer}
  .rev-q-chip.cur{background:rgba(96,165,250,0.15);color:#7dd3fc;border:1px solid rgba(96,165,250,0.25)}

  /* ── Kamer sectie ── */
  .room-sec{margin:10px 0 0}
  .room-hdr{display:flex;align-items:center;gap:8px;padding:8px 18px 5px;cursor:pointer;user-select:none}
  .room-hdr:hover .room-name{color:#e2e8f0}
  .room-chevron{font-size:10px;color:#374151;transition:transform .2s;flex-shrink:0}
  .room-chevron.open{transform:rotate(90deg)}
  .room-name{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#4b5563;flex:1}
  .room-stats{display:flex;gap:8px;align-items:center}
  .room-pwr{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:#fde047}
  .room-cnt{font-size:10px;color:#374151}
  .room-body{padding:0 18px 6px}

  /* ── Apparaatrij ── */
  .dev-row{display:grid;grid-template-columns:18px 1fr auto auto;gap:0 8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.03);align-items:center;cursor:default}
  .dev-row:last-child{border-bottom:none}
  .dev-dot{width:8px;height:8px;border-radius:50%;justify-self:center}
  .dev-main{min-width:0}
  .dev-name{font-size:12px;font-weight:600;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
  .dev-name:hover{color:#7dd3fc}
  .dev-name.editing{outline:none;background:rgba(96,165,250,0.1);border:1px solid rgba(96,165,250,0.4);border-radius:4px;color:#fff;padding:1px 5px;font-family:'Syne',sans-serif;font-size:12px;font-weight:600;min-width:80px}
  .dev-sub{display:flex;align-items:center;gap:5px;margin-top:2px;flex-wrap:wrap}
  .dev-type{font-size:10px;color:#374151}
  .dev-phase{font-size:9px;padding:1px 5px;border-radius:5px;font-weight:700;letter-spacing:.04em}
  .dev-src{font-size:9px;color:#374151}
  .tag-new{font-size:9px;padding:1px 6px;border-radius:5px;background:rgba(167,139,250,0.15);color:#a78bfa;border:1px solid rgba(167,139,250,0.3);font-weight:700}
  .tag-plug{font-size:9px;padding:1px 6px;border-radius:5px;background:rgba(52,211,153,0.12);color:#34d399;font-weight:700}
  .tag-pend{font-size:9px;padding:1px 6px;border-radius:5px;background:rgba(96,165,250,0.12);color:#60a5fa;font-weight:700}
  .dev-conf{text-align:right;min-width:90px}
  .dev-pwr{text-align:right;min-width:50px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700}

  /* ── Confidence balk ── */
  .cbar{display:inline-flex;gap:2px;vertical-align:middle}
  .cb{width:5px;height:8px;border-radius:2px;background:rgba(255,255,255,0.07)}
  .cb.on{opacity:1}
  .cpct{font-size:10px;margin-left:5px;vertical-align:middle;font-family:'JetBrains Mono',monospace}

  /* ── Onverklaard vermogen ── */
  .unknown-row{display:flex;align-items:center;gap:8px;padding:8px 18px;margin:8px 18px;border-radius:8px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2)}
  .unknown-icon{font-size:16px}
  .unknown-text{flex:1;font-size:11px;color:#fbbf24}
  .unknown-w{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:#f59e0b}

  /* ── Diagnostiek paneel ── */
  .diag-toggle{display:flex;align-items:center;gap:6px;padding:10px 18px;cursor:pointer;border-top:1px solid rgba(255,255,255,0.05);font-size:11px;color:#374151}
  .diag-toggle:hover{color:#6b7280}
  .diag-body{padding:10px 18px 14px;border-top:1px solid rgba(255,255,255,0.04)}
  .diag-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px}
  .diag-tile{background:rgba(255,255,255,0.03);border-radius:8px;padding:8px 10px}
  .diag-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#374151;margin-bottom:3px}
  .diag-val{font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#9ca3af}

  /* ── Leeg ── */
  .empty{padding:28px 18px;text-align:center;color:#374151;font-size:12px}

  /* ── Stat strip ── */
  .stat-strip{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid rgba(255,255,255,0.05)}
  .stat-tile{padding:8px 4px;display:flex;flex-direction:column;align-items:center;gap:2px;border-right:1px solid rgba(255,255,255,0.05)}
  .stat-tile:last-child{border-right:none}
  .stat-lbl{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#374151;text-align:center}
  .stat-val{font-size:14px;font-weight:800;font-family:'JetBrains Mono',monospace}
  .c-green{color:#4ade80}.c-amber{color:#fb923c}.c-muted{color:#4b5563}.c-yellow{color:#fde047}.c-red{color:#f87171}.c-blue{color:#7dd3fc}
`;

// ── Hoofdkaart ────────────────────────────────────────────────────────────────
class CloudEMSNilmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._filter   = 'all';   // all | active | pending | cat:X | room:X
    this._search   = '';
    this._diagOpen = false;
    this._openRooms= new Set(['']);   // alle kamers standaard open
    this._revIdx   = 0;               // welke pending-device actief in review
    this._prev     = '';
  }

  setConfig(c) { this._cfg = { title: 'NILM Apparaten', ...c }; }

  set hass(h) {
    this._hass = h;
    const sig = [
      h.states['sensor.cloudems_nilm_devices']?.last_changed,
      h.states['sensor.cloudems_nilm_review_current']?.last_changed,
      this._filter, this._search, this._diagOpen,
      JSON.stringify([...this._openRooms]),
      this._revIdx,
    ].join('|');
    if (sig !== this._prev) { this._prev = sig; this._render(); }
  }

  _a(e, k, d = null) { return this._hass?.states?.[e]?.attributes?.[k] ?? d; }
  _s(e)              { return this._hass?.states?.[e] || null; }
  _svc(d, s, data)   { this._hass?.callService(d, s, data); }

  _render() {
    const sh = this.shadowRoot; if (!sh || !this._hass) return;

    // ── Data ────────────────────────────────────────────────────────────────
    const allDevs    = this._a('sensor.cloudems_nilm_devices', 'device_list') || [];
    const totalPowerW= this._a('sensor.cloudems_nilm_devices', 'total_power_w') || 0;
    const unknownW   = this._a('sensor.cloudems_nilm_devices', 'undefined_power_w') || 0;
    const pending    = allDevs.filter(d => !d.confirmed && !d.dismissed && d.device_id && !d.device_id.startsWith('__'));
    const active     = allDevs.filter(d => d.is_on || d.running);
    const confirmed  = allDevs.filter(d => d.confirmed);

    // Diagnostics
    const diagThr    = this._a('sensor.cloudems_nilm_diagnostics', 'power_threshold_w') || 0;
    const diagRamp   = this._a('sensor.cloudems_nilm_diagnostics', 'batt_ramp_mask_active') || false;
    const diagEvTot  = this._a('sensor.cloudems_nilm_diagnostics', 'events_total') || 0;
    const diagEvCls  = this._a('sensor.cloudems_nilm_diagnostics', 'events_classified') || 0;
    const diagRate   = diagEvTot > 0 ? Math.round(diagEvCls / diagEvTot * 100) : 0;

    // ── Zoek + filter ────────────────────────────────────────────────────────
    const q = this._search.toLowerCase();
    let shown = allDevs.filter(d => !d.dismissed);
    if (q) shown = shown.filter(d => (d.name || d.type || '').toLowerCase().includes(q));
    if (this._filter === 'active')  shown = shown.filter(d => d.is_on || d.running);
    if (this._filter === 'pending') shown = shown.filter(d => !d.confirmed);
    if (this._filter.startsWith('cat:')) {
      const cat = this._filter.slice(4);
      shown = shown.filter(d => devCat(d.type || d.device_type) === cat);
    }
    if (this._filter.startsWith('room:')) {
      const room = this._filter.slice(5);
      shown = shown.filter(d => (d.room || '') === room);
    }

    // ── Groepeer per kamer ───────────────────────────────────────────────────
    const roomMap = {};
    for (const d of shown) {
      const r = d.room || '— Onbekend';
      if (!roomMap[r]) roomMap[r] = [];
      roomMap[r].push(d);
    }
    // Sorteer: kamer met meest actieve apparaten eerst
    const rooms = Object.entries(roomMap).sort(([, a], [, b]) => {
      const aOn = a.filter(d => d.is_on).length;
      const bOn = b.filter(d => d.is_on).length;
      return bOn - aOn || b.length - a.length;
    });

    // ── Stat strip ───────────────────────────────────────────────────────────
    const statHtml = `<div class="stat-strip">
      <div class="stat-tile"><span class="stat-lbl">Totaal</span><span class="stat-val c-blue">${allDevs.length}</span></div>
      <div class="stat-tile"><span class="stat-lbl">Actief</span><span class="stat-val c-yellow">${active.length}</span></div>
      <div class="stat-tile"><span class="stat-lbl">Bevestigd</span><span class="stat-val c-green">${confirmed.length}</span></div>
      <div class="stat-tile"><span class="stat-lbl">Te beoord.</span><span class="stat-val ${pending.length > 0 ? 'c-red' : 'c-muted'}">${pending.length}</span></div>
    </div>`;

    // ── Review banner ────────────────────────────────────────────────────────
    let reviewHtml = '';
    if (pending.length > 0) {
      const idx = Math.min(this._revIdx, pending.length - 1);
      const cur = pending[idx];
      const cat = devCat(cur.type || cur.device_type);
      const ci  = CAT[cat] || CAT.overig;
      const phCol = cur.phase === 'L1' ? '#06b6d4' : cur.phase === 'L2' ? '#f59e0b' : '#34d399';
      const conf  = Math.round(cur.confidence || 0);
      reviewHtml = `<div class="review-banner">
        <div class="rev-hdr">
          <span style="font-size:16px">${ci.i}</span>
          <span class="rev-hdr-title">Nieuw apparaat gevonden</span>
          <span class="rev-count">${idx + 1} / ${pending.length}</span>
        </div>
        <div class="rev-device">
          <div class="rev-name">${esc(cur.name || cur.type || '?')}</div>
          <div class="rev-meta">
            <span style="font-size:11px;color:#9ca3af">${Math.round(cur.power_w || 0)} W</span>
            <span class="dev-phase" style="background:${phCol}22;color:${phCol}">${cur.phase || '?'}</span>
            ${confBar(conf, 8)}
            ${cur.room ? `<span style="font-size:10px;color:#4b5563">📍 ${esc(cur.room)}</span>` : ''}
          </div>
          <div class="rev-btns">
            <button class="rbtn rbtn-yes" data-ra="confirm">✅ Bevestigen</button>
            <button class="rbtn rbtn-no"  data-ra="dismiss">❌ Afwijzen</button>
            <button class="rbtn rbtn-skip" data-ra="skip">⏭ Overslaan</button>
          </div>
        </div>
        ${pending.length > 1 ? `<div class="rev-queue">
          ${pending.map((d, i) => `<span class="rev-q-chip${i === idx ? ' cur' : ''}" data-ridx="${i}">${esc(d.name || d.type || '?')}</span>`).join('')}
        </div>` : ''}
      </div>`;
    }

    // ── Filter tabs ──────────────────────────────────────────────────────────
    const cats = [...new Set(allDevs.map(d => devCat(d.type || d.device_type)))].sort();
    const filterHtml = `<div class="filters">
      <span class="ftab${this._filter==='all'?' active':''}"    data-f="all">Alle (${allDevs.length})</span>
      <span class="ftab${this._filter==='active'?' active':''}" data-f="active">⚡ Actief (${active.length})</span>
      ${pending.length ? `<span class="ftab${this._filter==='pending'?' active':''}" data-f="pending">⏳ Beoordelen <span class="badge">${pending.length}</span></span>` : ''}
      ${cats.map(cat => {
        const ci = CAT[cat] || CAT.overig;
        const n  = allDevs.filter(d => devCat(d.type||d.device_type) === cat).length;
        return `<span class="ftab${this._filter==='cat:'+cat?' active':''}" data-f="cat:${cat}">${ci.i} ${cat} (${n})</span>`;
      }).join('')}
    </div>`;

    // ── Apparaatrij ──────────────────────────────────────────────────────────
    const devRow = d => {
      const isOn  = d.is_on || d.running;
      const conf  = Math.round(d.confidence || 0);
      const cat   = devCat(d.type || d.device_type);
      const ci    = CAT[cat] || CAT.overig;
      const dotCol= isOn ? ci.c : 'rgba(255,255,255,0.12)';
      const phCol = d.phase === 'L1' ? '#06b6d4' : d.phase === 'L2' ? '#f59e0b' : '#34d399';
      const isNew = d.last_seen_days != null && d.last_seen_days < 2 && !d.confirmed;
      const isPlug= d.source_type === 'smart_plug';
      const isPend= !d.confirmed;
      const pwrTxt= isOn ? `${Math.round(d.power_w || 0)} W` : `<span style="color:#374151">—</span>`;
      const _TTN = window.CloudEMSTooltip;
      const _srcLabel = isPlug ? '🔌 Smart plug (direct gemeten)' : conf >= 80 ? '🤖 NILM (hoge betrouwbaarheid)' : conf >= 50 ? '🤖 NILM (matige betrouwbaarheid)' : '🤖 NILM (lage betrouwbaarheid)';
      const _ttNilm = _TTN ? _TTN.html('nilm-'+esc(d.device_id||''), esc(d.name||d.type||'?'), [
        {label:'Betrouwbaarheid', value:(isPlug?'100':conf)+'%'},
        {label:'Detectiemethode', value:_srcLabel},
        {label:'Fase',           value:d.phase_label||d.phase||'?'},
        {label:'Type',           value:d.type||d.device_type||'—', dim:true},
        {label:'Kamer',          value:d.room||'—', dim:true},
        {label:'Bevestigd',      value:d.confirmed?'✅ Ja':'❌ Niet bevestigd', dim:true},
        {label:'Vandaag',        value:d.today_kwh>0?d.today_kwh.toFixed(2)+' kWh':'—', dim:true},
      ], {footer:isPlug?'● Direct gemeten via smart plug':'○ Afgeleid via NILM detectie'}) : {wrap:'',tip:''};
      return `<div class="dev-row" style="position:relative;cursor:default" ${_ttNilm.wrap}>
        <div class="dev-dot" style="background:${dotCol}"></div>
        <div class="dev-main">
          <div class="dev-name" data-rename="${esc(d.device_id||'')}" data-cur="${esc(d.name||d.type||'?')}">${esc(d.name || d.type || '?')}</div>
          <div class="dev-sub">
            <span class="dev-type" style="color:${ci.c}88">${ci.i} ${esc(d.type || d.device_type || '')}</span>
            <span class="dev-phase" style="background:${phCol}22;color:${phCol}">${d.phase_label || d.phase || '?'}</span>
            ${isPlug ? `<span class="tag-plug">🔌 plug</span>` : ''}
            ${isNew  ? `<span class="tag-new">NIEUW</span>` : ''}
            ${isPend && !isNew ? `<span class="tag-pend">? niet bevestigd</span>` : ''}
            ${d.today_kwh > 0 ? `<span class="dev-src">${d.today_kwh.toFixed(2)} kWh</span>` : ''}
          </div>
        </div>
        <div class="dev-conf">${confBar(isPlug ? 100 : conf)}</div>
        <div class="dev-pwr" style="color:${isOn ? '#fde047' : '#374151'}">${pwrTxt}</div>
        ${_ttNilm.tip}
      </div>`;
    };

    // ── Kamerlijst ───────────────────────────────────────────────────────────
    let roomsHtml = '';
    if (rooms.length === 0) {
      roomsHtml = `<div class="empty">Geen apparaten gevonden${q ? ` voor "${esc(q)}"` : ''}</div>`;
    } else {
      roomsHtml = rooms.map(([room, devs]) => {
        const isOpen = this._openRooms.has(room) || this._openRooms.has('');
        const roomPwr= devs.filter(d => d.is_on).reduce((s,d) => s+(d.power_w||0), 0);
        const roomOn = devs.filter(d => d.is_on).length;
        const sortedDevs = devs.slice().sort((a,b) => {
          if ((b.is_on||false) !== (a.is_on||false)) return (b.is_on ? 1 : 0) - (a.is_on ? 1 : 0);
          return (b.power_w||0) - (a.power_w||0);
        });
        return `<div class="room-sec" data-room="${esc(room)}">
          <div class="room-hdr" data-toggle-room="${esc(room)}">
            <span class="room-chevron${isOpen?' open':''}">▶</span>
            <span class="room-name">${esc(room === '— Onbekend' ? '— Onbekend' : room)}</span>
            <div class="room-stats">
              ${roomOn > 0 ? `<span class="room-pwr">${Math.round(roomPwr)} W</span>` : ''}
              <span class="room-cnt">${devs.length} app.</span>
            </div>
          </div>
          ${isOpen ? `<div class="room-body">${sortedDevs.map(devRow).join('')}</div>` : ''}
        </div>`;
      }).join('');
    }

    // ── Onverklaard vermogen ─────────────────────────────────────────────────
    const unknownHtml = unknownW > 50 ? `<div class="unknown-row">
      <span class="unknown-icon">❓</span>
      <span class="unknown-text">Onverklaard vermogen — NILM heeft nog geen match gevonden</span>
      <span class="unknown-w">${Math.round(unknownW)} W</span>
    </div>` : '';

    // ── Diagnostiek ──────────────────────────────────────────────────────────
    const diagHtml = `
      <div class="diag-toggle" data-diag>⚙️ Diagnostiek ${this._diagOpen ? '▲' : '▼'}</div>
      ${this._diagOpen ? `<div class="diag-body">
        <div class="diag-grid">
          <div class="diag-tile"><div class="diag-lbl">Drempel</div><div class="diag-val">${Math.round(diagThr)} W</div></div>
          <div class="diag-tile"><div class="diag-lbl">Classificatie</div><div class="diag-val" style="color:${diagRate>70?'#4ade80':'#fb923c'}">${diagRate}%</div></div>
          <div class="diag-tile"><div class="diag-lbl">Events totaal</div><div class="diag-val">${diagEvTot}</div></div>
          <div class="diag-tile"><div class="diag-lbl">Batterij masker</div><div class="diag-val" style="color:${diagRamp?'#f87171':'#4ade80'}">${diagRamp ? 'Actief' : 'Inactief'}</div></div>
        </div>
      </div>` : ''}`;

    // ── Render ────────────────────────────────────────────────────────────────
    sh.innerHTML = `<style>${CSS}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">🔍</span>
        <div>
          <div class="hdr-title">${esc(this._cfg?.title || 'NILM Apparaten')}</div>
          <div class="hdr-sub">${allDevs.length} apparaten · ${Object.keys(roomMap).length} kamers</div>
        </div>
        ${totalPowerW > 0 ? `<div class="hdr-right"><div class="total-pill">${Math.round(totalPowerW)} W</div></div>` : ''}
      </div>
      ${statHtml}
      <div class="search-row">
        <input class="search-inp" type="text" placeholder="Zoek apparaat, type, kamer…" value="${esc(this._search)}">
        ${this._search ? `<span class="search-clr" data-clr>✕</span>` : ''}
        <span class="search-count">${shown.length}/${allDevs.length}</span>
      </div>
      ${filterHtml}
      ${reviewHtml}
      ${unknownHtml}
      ${roomsHtml}
      ${diagHtml}
    </div>`;

    // ── Events ────────────────────────────────────────────────────────────────

    // Zoeken
    sh.querySelector('.search-inp')?.addEventListener('input', e => {
      this._search = e.target.value;
      this._prev = ''; this._render();
    });
    sh.querySelector('[data-clr]')?.addEventListener('click', () => {
      this._search = ''; this._prev = ''; this._render();
    });

    // Filter tabs
    sh.querySelectorAll('[data-f]').forEach(el => {
      el.addEventListener('click', () => {
        this._filter = el.dataset.f;
        this._prev = ''; this._render();
      });
    });

    // Kamer in-/uitklappen
    sh.querySelectorAll('[data-toggle-room]').forEach(el => {
      el.addEventListener('click', () => {
        const r = el.dataset.toggleRoom;
        // Verwijder de "alles open" marker als eerste klik
        this._openRooms.delete('');
        if (this._openRooms.has(r)) this._openRooms.delete(r);
        else this._openRooms.add(r);
        this._prev = ''; this._render();
      });
    });

    // Review knoppen
    sh.querySelectorAll('[data-ra]').forEach(btn => {
      btn.addEventListener('click', () => {
        const act = btn.dataset.ra;
        if (act === 'confirm') {
          this._svc('button', 'press', { entity_id: 'button.cloudems_nilm_review_confirm' });
          this._revIdx = 0;
        } else if (act === 'dismiss') {
          this._svc('button', 'press', { entity_id: 'button.cloudems_nilm_review_dismiss' });
          this._revIdx = 0;
        } else if (act === 'skip') {
          const idx = Math.min(this._revIdx, pending.length - 1);
          this._revIdx = (idx + 1) % pending.length;
        }
        this._prev = ''; setTimeout(() => { this._prev = ''; this._render(); }, 500);
      });
    });

    // Review wachtrij chips
    sh.querySelectorAll('[data-ridx]').forEach(el => {
      el.addEventListener('click', () => {
        this._revIdx = parseInt(el.dataset.ridx);
        this._prev = ''; this._render();
      });
    });

    // Apparaat hernoemen (dubbelklik)
    sh.querySelectorAll('[data-rename]').forEach(el => {
      el.addEventListener('dblclick', e => {
        e.stopPropagation();
        const did = el.dataset.rename;
        const cur = el.dataset.cur || el.textContent;
        if (!did) return;
        el.contentEditable = 'true';
        el.classList.add('editing');
        el.focus();
        // Selecteer alles
        const range = document.createRange();
        range.selectNodeContents(el);
        const sel = sh.getSelection?.() || window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
        const save = () => {
          const n = el.textContent.trim();
          el.contentEditable = 'false';
          el.classList.remove('editing');
          if (n && n !== cur) {
            this._svc('cloudems', 'rename_nilm_device', { device_id: did, name: n });
          }
          this._prev = ''; setTimeout(() => this._render(), 400);
        };
        el.addEventListener('keydown', ev => {
          if (ev.key === 'Enter') { ev.preventDefault(); save(); }
          if (ev.key === 'Escape') { el.textContent = cur; save(); }
        }, { once: false });
        el.addEventListener('blur', save, { once: true });
      });
    });

    // Diagnostiek toggle
    sh.querySelector('[data-diag]')?.addEventListener('click', () => {
      this._diagOpen = !this._diagOpen;
      this._prev = ''; this._render();
    });
  }

  getCardSize() { return 10; }
  static getConfigElement() { return document.createElement('cloudems-nilm-card-editor'); }
  static getStubConfig() { return { title: 'NILM Apparaten' }; }
}

// ── Editor ────────────────────────────────────────────────────────────────────
class CloudEMSNilmCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); }
  setConfig(c) { this._cfg = { ...c }; this._render(); }
  _fire() { this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._cfg }, bubbles: true, composed: true })); }
  _render() {
    const cfg = this._cfg || {};
    this.shadowRoot.innerHTML = `
      <style>.wrap{padding:8px}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:180px}</style>
      <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" value="${esc(cfg.title||'NILM Apparaten')}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change', e => {
      this._cfg = { ...this._cfg, title: e.target.value }; this._fire();
    });
  }
}

// ── Registratie ───────────────────────────────────────────────────────────────
if (!customElements.get('cloudems-nilm-card')) {
  customElements.define('cloudems-nilm-card', CloudEMSNilmCard);
}
if (!customElements.get('cloudems-nilm-card-editor')) {
  customElements.define('cloudems-nilm-card-editor', CloudEMSNilmCardEditor);
}
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-nilm-card')) {
  window.customCards.push({ type: 'cloudems-nilm-card', name: 'CloudEMS NILM Card', description: 'NILM apparaten per kamer/categorie — beoordelen, zoeken, hernoemen', preview: true });
}
console.info('%c CLOUDEMS-NILM-CARD %c v2.0.0 ', 'background:#a78bfa;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px', 'background:#0e1520;color:#a78bfa;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
