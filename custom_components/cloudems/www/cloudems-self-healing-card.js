// CloudEMS Self-Healing Dashboard Card v3.0.0

const SHC_VERSION = '5.4.8';

const SHC_STYLES = `
  :host { display:block; }
  * { box-sizing:border-box; margin:0; padding:0; }

  .card {
    background: #0f1117;
    border-radius: 12px;
    border: 1px solid #1e2130;
    font-family: 'DM Sans', 'Helvetica Neue', sans-serif;
    overflow: hidden;
    position: relative;
  }

  /* Smalle kleurstreep linksboven als enige kleur-accent */
  .card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent, #2d6a4f);
    transition: background .4s ease;
  }

  .top {
    display: flex;
    align-items: center;
    padding: 14px 16px 12px;
    gap: 12px;
    border-bottom: 1px solid #1e2130;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent, #2d6a4f);
    flex-shrink: 0;
    transition: background .4s ease;
  }

  .label {
    flex: 1;
    font-size: 13px;
    font-weight: 600;
    color: #d4d8e2;
    letter-spacing: -.01em;
  }

  .sub {
    font-size: 11px;
    color: #52566a;
    margin-top: 1px;
  }

  .status-tag {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 4px;
    background: var(--tag-bg, #1a2e25);
    color: var(--accent, #52b788);
    border: 1px solid var(--tag-border, #2d6a4f44);
    flex-shrink: 0;
    transition: all .4s ease;
  }

  .metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
  }

  .m {
    padding: 11px 14px;
    border-right: 1px solid #1e2130;
  }
  .m:last-child { border-right: none; }

  .m-key {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #3a3e52;
    margin-bottom: 4px;
  }

  .m-val {
    font-size: 16px;
    font-weight: 700;
    color: #d4d8e2;
    font-variant-numeric: tabular-nums;
    letter-spacing: -.02em;
  }
  .m-val.dim { color: #52566a; }
  .m-val.pos { color: #52b788; }
  .m-val.neg { color: #e07070; }
  .m-val.neu { color: #7eb3d8; }

  .m-sub {
    font-size: 9px;
    color: #3a3e52;
    margin-top: 2px;
  }

  .pills {
    padding: 8px 14px 10px;
    border-top: 1px solid #1e2130;
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }

  .pill {
    font-size: 10px;
    font-weight: 500;
    padding: 3px 8px;
    border-radius: 3px;
    background: #1a1d29;
    border: 1px solid #252839;
    color: #52566a;
    letter-spacing: .01em;
  }
  .pill.on   { background:#1a2e25; border-color:#2d6a4f44; color:#52b788; }
  .pill.warn { background:#2a1e14; border-color:#8b4513aa; color:#c87941; }
  .pill.bad  { background:#2a1414; border-color:#8b141444; color:#e07070; }
  .pill.info { background:#141a2a; border-color:#144488aa; color:#7eb3d8; }
`;

// Situatie-kleuren — één accent per situatie, rest is neutraal
const THEMES = {
  maintenance: { accent:'#e07070', tagBg:'#2a1414', tagBorder:'#8b141444' },
  negative:    { accent:'#52b788', tagBg:'#1a2e25', tagBorder:'#2d6a4f44' },
  supercool:   { accent:'#7eb3d8', tagBg:'#141a2a', tagBorder:'#144488aa' },
  surplus:     { accent:'#c8a227', tagBg:'#221e0f', tagBorder:'#8b6914aa' },
  peak:        { accent:'#e07070', tagBg:'#2a1414', tagBorder:'#8b141444' },
  boost:       { accent:'#c87941', tagBg:'#2a1e14', tagBorder:'#8b4513aa' },
  expensive:   { accent:'#c87941', tagBg:'#2a1e14', tagBorder:'#8b4513aa' },
  charging:    { accent:'#7eb3d8', tagBg:'#141a2a', tagBorder:'#144488aa' },
  discharging: { accent:'#52b788', tagBg:'#1a2e25', tagBorder:'#2d6a4f44' },
  wash:        { accent:'#9a8fcf', tagBg:'#1e1a2e', tagBorder:'#44348baa' },
  sleeping:    { accent:'#4a5068', tagBg:'#14151e', tagBorder:'#2a2d4488' },
  away:        { accent:'#9a8fcf', tagBg:'#1e1a2e', tagBorder:'#44348baa' },
  normal:      { accent:'#2d6a4f', tagBg:'#1a2e25', tagBorder:'#2d6a4f44' },
};

function getData(h) {
  const st  = h.states['sensor.cloudems_status']?.attributes || {};
  const epx = (h.states['sensor.cloudems_batterij_epex_schema']
            || h.states['sensor.cloudems_battery_schedule'])?.attributes || {};
  const dol = h.states['sensor.cloudems_decision_learner']?.attributes || {};
  const occ = st.occupancy || {};
  const peak = st.peak_shaving || st.capacity_peak || {};
  const wash = st.appliance_cycles?.appliances || [];
  const vcs  = st.virtual_cold_storage || [];
  const efp  = st.electrical_fingerprint || [];
  const cocc = st.contextual_occupancy || {};
  const ghost = st.ghost_tv_sim || {};
  const boiler = st.boiler || {};
  const nilm = (st.nilm_devices || []).filter(d => d.power_w > 10);

  const gridW  = parseFloat(h.states['sensor.cloudems_grid_net_power']?.state || st.grid_power_w || 0);
  const solarW = parseFloat(h.states['sensor.cloudems_zon_vermogen']?.state || h.states['sensor.cloudems_solar_system']?.state || 0);
  const battW  = parseFloat(
    h.states['sensor.thuisbatterij_power']?.state ||
    h.states['sensor.cloudems_battery_power']?.state ||
    st.battery_power_w || 0);
  const soc    = Math.round(parseFloat(
    h.states['sensor.thuisbatterij_percentage']?.state ||
    h.states['sensor.cloudems_battery_soc']?.state ||
    epx.soc_pct || 0));

  const _huisSt = h.states['sensor.cloudems_huisverbruik'];
  const homeW = (parseFloat(_huisSt?.state) > 5 && !isNaN(parseFloat(_huisSt?.state)))
    ? parseFloat(_huisSt.state)
    : Math.max(0, solarW + gridW - battW);

  const priceSt  = h.states['sensor.cloudems_price_current_hour'];
  const epexSt   = h.states['sensor.cloudems_energy_epex_today'];
  const _priceState = parseFloat(priceSt?.state);
  const _priceAttr  = parseFloat(priceSt?.attributes?.price_incl_tax || priceSt?.attributes?.price_all_in || 0);
  const _epexPrice  = parseFloat(epexSt?.attributes?.current_price_display || epexSt?.attributes?.price_incl_tax || 0);
  const price = (_priceState > 0) ? _priceState : (_priceAttr > 0 ? _priceAttr : (_epexPrice > 0 ? _epexPrice : 0));
  const surplus = Math.max(0, solarW - homeW + (battW < 0 ? Math.abs(battW) : 0));

  const isAway     = ['away','extended_away'].includes(occ.state || '');
  const isSleeping = occ.state === 'sleeping';
  const peakActive = !!(peak.active || peak.peak_active);
  const savedTotal = parseFloat(dol.total_value_eur || 0);

  const vcsSuperCool = vcs.some(v => v.mode === 'super_cool');
  const vcsOffPeak   = vcs.some(v => v.mode === 'off_peak');
  const efpWarn = efp.find(f => f.warning_count > 0 && (Date.now()/1000 - (f.last_warning_ts||0)) < 86400);
  const washActive = wash.find(a => a.fase && a.fase !== 'idle' && a.fase !== 'klaar');
  const boilerBoost = boiler.mode === 'boost' || boiler.boost_active;
  const ghostTvOn = ghost.running === true;
  const intent = cocc.last_intent || '';
  const freshIntent = intent && (Date.now()/1000 - (cocc.last_intent_ts||0)) < 600;

  return { gridW, solarW, battW, homeW, soc, price, surplus,
           isAway, isSleeping, peakActive, savedTotal,
           vcsSuperCool, vcsOffPeak, efpWarn, washActive,
           boilerBoost, boilerTemp: parseFloat(boiler.temp_c||0),
           boilerOn: parseFloat(boiler.power_w||0) > 100,
           ghostTvOn, freshIntent, intent,
           nilmCount: nilm.length };
}

const SITUATIONS = [
  {
    id: 'maintenance',
    check: d => !!d.efpWarn,
    theme: 'maintenance',
    label: d => `${d.efpWarn.label} — afwijkend inschakelpatroon`,
    sub:   d => `${d.efpWarn.last_deviation_pct?.toFixed(0)}% afwijking · controleer het apparaat`,
    tag:   () => 'onderhoud',
    pills: d => [
      { t: d.efpWarn.label,                     c: 'bad'  },
      { t: `${d.efpWarn.last_deviation_pct?.toFixed(0)}% afwijking`, c: 'bad' },
    ],
  },
  {
    id: 'negative',
    check: d => d.price < 0,
    theme: 'negative',
    label: d => `Negatieve prijs — ${(d.price*100).toFixed(1)} ct/kWh`,
    sub:   () => 'alles wat kan laden, laadt nu',
    tag:   () => 'gratis stroom',
    pills: d => [
      { t: 'batterij laden',    c: 'on' },
      { t: 'boiler boost',      c: 'on' },
      ...(d.vcsSuperCool ? [{t:'vriezer koud',c:'info'}] : []),
    ],
  },
  {
    id: 'supercool',
    check: d => d.vcsSuperCool && d.surplus > 800,
    theme: 'supercool',
    label: d => `Vriezer super-cool — ${(d.surplus/1000).toFixed(1)} kW surplus`,
    sub:   () => 'overtollige zonne-energie opgeslagen als koude',
    tag:   () => 'thermisch laden',
    pills: () => [{ t:'vriezer koud', c:'info' }, { t:'surplus benut', c:'on' }],
  },
  {
    id: 'surplus',
    check: d => d.surplus > 1500,
    theme: 'surplus',
    label: d => `${(d.surplus/1000).toFixed(1)} kW surplus`,
    sub:   () => 'meer opwek dan verbruik',
    tag:   () => 'pv-surplus',
    pills: d => [
      { t: 'surplus actief', c: 'on' },
      ...(d.boilerBoost ? [{t:`boiler ${d.boilerTemp.toFixed(0)}°C`,c:'warn'}] : []),
      ...(d.vcsSuperCool ? [{t:'vriezer koud',c:'info'}] : []),
      ...(d.washActive ? [{t: d.washActive.label || 'wasmachine', c:'on'}] : []),
    ],
  },
  {
    id: 'peak',
    check: d => d.peakActive,
    theme: 'peak',
    label: d => `Piekschaving — ${(Math.abs(d.gridW)/1000).toFixed(1)} kW`,
    sub:   () => 'grote verbruikers worden gespreid',
    tag:   () => 'piekbeperking',
    pills: () => [{ t:'piekbeperking actief', c:'bad' }],
  },
  {
    id: 'boost',
    check: d => d.boilerBoost,
    theme: 'boost',
    label: d => `Boiler boost${d.boilerTemp > 0 ? ` — ${d.boilerTemp.toFixed(0)}°C` : ''}`,
    sub:   () => 'laden op goedkoop moment',
    tag:   d => `${d.boilerTemp.toFixed(0)}°C`,
    pills: () => [{ t:'boiler boost', c:'warn' }],
  },
  {
    id: 'expensive',
    check: d => d.price > 0.25,
    theme: 'expensive',
    label: d => `${(d.price*100).toFixed(0)} ct/kWh`,
    sub:   () => 'verbruik verschoven naar goedkoper uur',
    tag:   d => `${(d.price*100).toFixed(0)} ct`,
    pills: d => [
      { t: 'verbruik uitgesteld', c: 'warn' },
      ...(d.battW < -200 ? [{t:'batterij ontlaadt',c:'on'}] : []),
      ...(d.vcsOffPeak ? [{t:'vriezer buffert',c:'info'}] : []),
    ],
  },
  {
    id: 'charging',
    check: d => d.battW > 500,
    theme: 'charging',
    label: d => `Batterij laadt — ${(d.battW/1000).toFixed(1)} kW`,
    sub:   d => `${d.soc}% — slim geladen op goedkoop moment`,
    tag:   d => `${d.soc}%`,
    pills: () => [{ t:'slim laden', c:'info' }],
  },
  {
    id: 'discharging',
    check: d => d.battW < -300,
    theme: 'discharging',
    label: d => `Batterij levert — ${(Math.abs(d.battW)/1000).toFixed(1)} kW`,
    sub:   () => 'netkosten worden verlaagd',
    tag:   d => `${d.soc}%`,
    pills: () => [{ t:'ontladen actief', c:'on' }],
  },
  {
    id: 'neg_price_dump',
    check: d => (d.battSource||'') === 'negative_price_dump',
    theme: 'charging',
    label: d => `Negatieve prijs dump — batterij ontlaadt`,
    sub:   () => 'ruimte vrijmaken voor betaald laden',
    tag:   () => 'arbitrage',
    pills: () => [{ t:'ontladen voor negatief uur', c:'info' }, { t:'max laadruimte', c:'on' }],
  },
  {
    id: 'micro_cycle',
    check: d => (d.battSource||'') === 'anti_cycling',
    theme: 'normal',
    label: () => `Micro-cycle preventie actief`,
    sub:   () => 'batterij beschermd tegen snelle wisselingen',
    tag:   () => 'beschermd',
    pills: () => [{ t:'anti-cycling', c:'warn' }],
  },
  {
    id: 'window_open',
    check: d => !!d.windowOpen,
    theme: 'peak',
    label: d => `Raam open — verwarming gepauzeerd`,
    sub:   () => 'temperatuurval gedetecteerd, ECO-stand actief',
    tag:   () => 'raam open',
    pills: () => [{ t:'ECO-window', c:'warn' }, { t:'verwarming uit', c:'bad' }],
  },
  {
    id: 'voltage_rise',
    check: d => (d.voltageAction||'ok') !== 'ok',
    theme: 'expensive',
    label: d => `Spanning ${d.voltageV||'—'}V — export verlaagd`,
    sub:   () => 'netspanning te hoog door teruglevering',
    tag:   d => `${d.voltageV||'—'}V`,
    pills: d => [
      { t: `${d.voltageV||'—'}V`, c: 'bad' },
      { t: `export -${d.voltageReducePct||0}%`, c: 'warn' },
    ],
  },
  {
    id: 'wash',
    check: d => !!d.washActive,
    theme: 'wash',
    label: d => `${d.washActive.label || 'Wasmachine'} — ${d.washActive.fase || 'actief'}`,
    sub:   d => d.washActive.remaining_min > 0
      ? `nog ~${Math.round(d.washActive.remaining_min)} min · droger-advies volgt`
      : 'droger-advies beschikbaar na aflopen',
    tag:   d => d.washActive.remaining_min > 0 ? `~${Math.round(d.washActive.remaining_min)}m` : 'bezig',
    pills: () => [],
  },
  {
    id: 'sleeping',
    check: d => d.isSleeping,
    theme: 'sleeping',
    label: () => 'Nachtmodus',
    sub:   () => 'minimaal verbruik',
    tag:   () => 'nacht',
    pills: d => d.battW > 200 ? [{ t:'nacht-laden', c:'info' }] : [],
  },
  {
    id: 'away',
    check: d => d.isAway,
    theme: 'away',
    label: () => 'Niemand thuis',
    sub:   () => 'lamp-circulatie actief',
    tag:   () => 'away',
    pills: d => [
      { t: 'lamp-circulatie', c: 'on' },
      ...(d.ghostTvOn ? [{t:'tv-simulatie',c:'on'}] : []),
    ],
  },
  {
    id: 'normal',
    check: () => true,
    theme: 'normal',
    label: d => `${(d.price*100).toFixed(0)} ct/kWh`,
    sub:   d => d.freshIntent
      ? ({ slaap:'slaap herkend — nachtmodus wordt klaargemaakt',
           opstaan:'opstaan herkend',
           vertrek:'vertrek herkend — away-modus wordt geactiveerd',
         }[d.intent] || d.intent)
      : 'bewaking actief',
    tag:   d => d.savedTotal > 0 ? `+€${d.savedTotal.toFixed(0)}` : 'ok',
    pills: d => [
      ...(d.nilmCount > 0 ? [{t:`${d.nilmCount} apparaten`,c:''}] : []),
      ...(d.savedTotal > 1 ? [{t:`€${d.savedTotal.toFixed(2)} geleerd`,c:'on'}] : []),
      ...(d.boilerOn ? [{t:`boiler ${d.boilerTemp.toFixed(0)}°C`,c:'warn'}] : []),
    ],
  },
];

function fmtW(w) {
  const abs = Math.abs(w);
  return abs >= 1000 ? `${(abs/1000).toFixed(1)}kW` : `${Math.round(abs)}W`;
}

class CloudEMSSelfHealingCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode:'open' });
    this._prev = '';
  }

  setConfig(c) { this._config = c || {}; }

  set hass(h) {
    this._hass = h;
    const st  = h.states['sensor.cloudems_status']?.attributes || {};
    const sig = JSON.stringify([
      st.grid_power_w, h.states['sensor.cloudems_zon_vermogen']?.state, st.battery_power_w,
      h.states['sensor.cloudems_price_current_hour']?.state || h.states['sensor.cloudems_energy_epex_today']?.attributes?.current_price_display,
      h.states['sensor.cloudems_huisverbruik']?.state,
      st.occupancy?.state, st.ghost_tv_sim?.running,
      (st.appliance_cycles?.appliances||[]).map(a=>a.fase).join(','),
    ]);
    if (sig !== this._prev) { this._prev = sig; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot;
    if (!this._hass) return;

    const d   = getData(this._hass);
    const sit = SITUATIONS.find(s => s.check(d));
    const th  = THEMES[sit.theme];

    const label = sit.label(d);
    const sub   = sit.sub(d);
    const tag   = sit.tag(d);
    const pills = sit.pills(d);

    const pillsHtml = pills.length
      ? `<div class="pills">${pills.map(p=>`<div class="pill ${p.c||''}">${p.t}</div>`).join('')}</div>`
      : '';

    const battDir = d.battW > 50 ? 'neu' : d.battW < -50 ? 'pos' : 'dim';
    const gridDir = d.gridW > 50 ? 'neg' : d.gridW < -50 ? 'pos' : 'dim';

    sh.innerHTML = `<style>${SHC_STYLES}</style>
<div class="card" style="--accent:${th.accent};--tag-bg:${th.tagBg};--tag-border:${th.tagBorder}">
  <div class="top">
    <div class="dot"></div>
    <div style="flex:1;min-width:0">
      <div class="label">${label}</div>
      <div class="sub">${sub}</div>
    </div>
    <div class="status-tag">${tag}</div>
  </div>
  <div class="metrics">
    <div class="m">
      <div class="m-key">solar</div>
      <div class="m-val ${d.solarW > 50 ? 'pos' : 'dim'}">${fmtW(d.solarW)}</div>
      ${d.surplus > 100 ? `<div class="m-sub">+${fmtW(d.surplus)} surplus</div>` : '<div class="m-sub">&nbsp;</div>'}
    </div>
    <div class="m">
      <div class="m-key">${d.gridW >= 0 ? 'import' : 'export'}</div>
      <div class="m-val ${gridDir}">${fmtW(d.gridW)}</div>
      <div class="m-sub">${(d.price*100).toFixed(1)} ct</div>
    </div>
    <div class="m">
      <div class="m-key">batterij</div>
      <div class="m-val ${battDir}">${d.soc}%</div>
      <div class="m-sub">${Math.abs(d.battW) > 50 ? (d.battW>0?'+':'')+fmtW(d.battW) : '&nbsp;'}</div>
    </div>
    <div class="m">
      <div class="m-key">huis</div>
      <div class="m-val">${fmtW(d.homeW)}</div>
      <div class="m-sub">${d.nilmCount > 0 ? `${d.nilmCount} apparaten` : '&nbsp;'}</div>
    </div>
  </div>
  ${pillsHtml}
</div>`;
  }

  getCardSize() { return 3; }
  static getConfigElement() { return document.createElement('cloudems-self-healing-card-editor'); }
  static getStubConfig()    { return {}; }
}

class CloudEMSSelfHealingCardEditor extends HTMLElement {
  setConfig(c) {}
  connectedCallback() {
    if (!this.innerHTML)
      this.innerHTML = `<p style="font-size:12px;color:#666;padding:8px">Geen configuratie vereist.</p>`;
  }
}

if (!customElements.get('cloudems-self-healing-card'))
  customElements.define('cloudems-self-healing-card', CloudEMSSelfHealingCard);
if (!customElements.get('cloudems-self-healing-card-editor'))
  customElements.define('cloudems-self-healing-card-editor', CloudEMSSelfHealingCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'cloudems-self-healing-card',
  name: 'CloudEMS Status',
  description: 'Systeemstatus',
  preview: true,
});
