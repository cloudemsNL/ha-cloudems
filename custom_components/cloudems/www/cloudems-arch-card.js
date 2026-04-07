// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Architecture Card v5.4.96

const ARCH_VERSION = '5.5.318';

class CloudEMSArchCard extends HTMLElement {
  constructor() {
    super();
    this._activeTab = 'diagram';
  }

  set hass(h) {
    this._hass = h;
    const j = JSON.stringify([
      h?.states['sensor.cloudems_status']?.last_changed,
      h?.states['sensor.cloudems_decisions_history']?.last_changed,
      h?.states['sensor.cloudems_ai_status']?.last_changed,
    ]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  setConfig(c) { this._cfg = c; }
  getCardSize() { return 14; }
  static getConfigElement() { return document.createElement('cloudems-arch-card-editor'); }
  static getStubConfig() { return {}; }

  _render() {
    const h = this._hass;
    if (!h) return;
    const status    = h.states['sensor.cloudems_status']?.attributes || {};
    const decisions = h.states['sensor.cloudems_decisions_history']?.attributes?.decisions || [];
    const ai        = h.states['sensor.cloudems_ai_status']?.attributes || {};
    const now       = Date.now() / 1000;

    const activeCount = status.active_modules || '?';
    const nTrained  = ai.n_trained || 0;
    const nSince    = ai.n_since_train || 0;
    const retrainAt = ai.retrain_at || 48;
    const aiReady   = ai.ready;
    const aiColor   = aiReady ? '#3fb950' : '#d29922';
    const aiLabel   = aiReady ? `✅ ${nTrained} samples` : `⏳ ${nSince}/${retrainAt}`;

    const bdeAction = status.bde_action || (decisions.find(d => d.cat === 'battery')?.action || 'idle');
    const bdeColor  = bdeAction === 'charge' ? '#3fb950' : bdeAction === 'discharge' ? '#f85149' : '#58a6ff';

    const agoStr = (ts) => {
      if (!ts) return '';
      const a = now - ts;
      if (a < 60)   return `${Math.round(a)}s`;
      if (a < 3600) return `${Math.round(a/60)}m`;
      return `${Math.round(a/3600)}u`;
    };

    const recentRows = decisions.slice(0, 8).map(d => {
      const a = now - (d.ts || 0);
      const ago = a < 60 ? `${Math.round(a)}s` : a < 3600 ? `${Math.round(a/60)}m` : `${Math.round(a/3600)}u`;
      const col = d.cat==='battery'?'#58a6ff':d.cat==='boiler'?'#f97316':d.cat==='solar'?'#d29922':d.cat==='ev'?'#3fb950':'#bc8cff';
      return `<div class="dec-row">
        <span class="dec-cat" style="color:${col}">${(d.cat||'?').toUpperCase()}</span>
        <span class="dec-act">${d.action||'—'}</span>
        <span class="dec-reason">${(d.reason||'').slice(0,60)}</span>
        <span class="dec-ago">${ago}</span>
      </div>`;
    }).join('');

    const tab = this._activeTab;

    const tabContent = {
      diagram: this._renderDiagram(),
      tabel:   this._renderTable(),
    };

    this.innerHTML = `
    <ha-card>
      <style>
        ha-card { background:#0d1117; border-radius:12px; padding:16px; color:#f0f6fc;
          font-family:'Syne',system-ui,sans-serif; }
        .arch-hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
        .arch-title { font-size:14px; font-weight:800; letter-spacing:.04em; color:#58a6ff; }
        .arch-sub { font-size:10px; color:rgba(255,255,255,.35); }
        .bde-banner { border-radius:8px; padding:8px 14px; margin-bottom:10px;
          border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.03);
          display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
        .bde-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; animation:pulse 1.5s infinite; }
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(1.4)} }
        .bde-action { font-size:13px; font-weight:700; }
        .bde-reason { font-size:10px; color:rgba(255,255,255,.4); flex:1; }
        .ai-badge { font-size:10px; font-weight:700; padding:2px 8px; border-radius:10px; }

        /* Universal tabs */
        .tab-bar { display:flex; gap:4px; margin-bottom:12px;
          border-bottom:1px solid rgba(255,255,255,.08); }
        .tab-btn { flex:1; padding:8px 4px 9px; font-size:10px; font-weight:700; text-transform:uppercase;
          letter-spacing:.06em; background:transparent; border:none; border-bottom:2px solid transparent;
          color:rgba(255,255,255,.3); cursor:pointer; transition:color .15s,border-color .15s; }
        .tab-btn:hover { color:rgba(255,255,255,.6); }
        .tab-btn.active { color:#e6edf3; border-bottom-color:#e6edf3; }

        /* Diagram SVG */
        .arch-svg { width:100%; overflow:visible; min-height:400px; }

        /* Tabel */
        .arch-table { width:100%; border-collapse:collapse; font-size:10px; }
        .arch-table th { text-align:left; padding:6px 10px;
          background:rgba(255,255,255,.04); color:rgba(255,255,255,.4);
          font-weight:600; font-size:9px; text-transform:uppercase; letter-spacing:.06em;
          border-bottom:1px solid rgba(255,255,255,.06); }
        .arch-table td { padding:6px 10px; border-bottom:1px solid rgba(255,255,255,.03);
          color:rgba(255,255,255,.7); vertical-align:top; line-height:1.4; }
        .arch-table tr:hover td { background:rgba(255,255,255,.02); }
        .arch-table .sec-row td { background:rgba(255,255,255,.04); font-weight:700;
          font-size:9px; letter-spacing:.08em; padding:5px 10px; }
        .tag { display:inline-block; padding:1px 6px; border-radius:3px;
          font-size:8px; font-weight:700; }
        .freq { color:rgba(255,255,255,.35); font-size:9px; white-space:nowrap; }

        /* Beslissingen */
        .sec-hdr { font-size:9px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
          color:rgba(255,255,255,.25); margin:10px 0 5px; }
        .dec-row { display:flex; gap:8px; align-items:center; padding:3px 0;
          border-bottom:1px solid rgba(255,255,255,.04); font-size:10px; }
        .dec-cat { font-weight:700; min-width:52px; font-size:9px; }
        .dec-act { font-weight:600; color:rgba(255,255,255,.7); min-width:68px; }
        .dec-reason { color:rgba(255,255,255,.35); flex:1; }
        .dec-ago { color:rgba(255,255,255,.2); font-size:9px; white-space:nowrap; }
      </style>

      <div class="arch-hdr">
        <span class="arch-title">🏗️ CloudEMS Architectuur</span>
        <span class="arch-sub">${activeCount} modules actief · v${ARCH_VERSION}</span>
      </div>

      <div class="bde-banner">
        <div class="bde-dot" style="background:${bdeColor}"></div>
        <span class="bde-action" style="color:${bdeColor}">Batterij: ${bdeAction||'idle'}</span>
        <span class="bde-reason">${(status.bde_reason||'').slice(0,70)||'—'}</span>
        <span class="ai-badge" style="background:${aiColor}22;color:${aiColor}">${aiLabel}</span>
      </div>

      <div class="tab-bar">
        <button class="tab-btn ${tab==='diagram'?'active':''}" data-tab="diagram">📊 Diagram</button>
        <button class="tab-btn ${tab==='tabel'?'active':''}"   data-tab="tabel">📋 Modules</button>
      </div>

      <div id="arch-content">
        ${tabContent[tab] || ''}
      </div>

      <div class="sec-hdr" style="margin-top:12px">Recente beslissingen</div>
      ${recentRows || '<div style="color:rgba(255,255,255,.25);font-size:10px">Nog geen beslissingen</div>'}
    </ha-card>`;

    this.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeTab = btn.dataset.tab;
        this._render();
      });
    });
  }

  _renderDiagram() {
    return `
    <svg class="arch-svg" viewBox="0 0 1100 620" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arr"   markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="rgba(255,255,255,.3)"/></marker>
        <marker id="arr-b" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#58a6ff"/></marker>
        <marker id="arr-p" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#bc8cff"/></marker>
        <marker id="arr-o" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#f97316"/></marker>
        <marker id="arr-g" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#3fb950"/></marker>
        <marker id="arr-y" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#d29922"/></marker>
      </defs>

      <!-- Kolom headers -->
      <rect x="4"   y="4" width="196" height="22" rx="4" fill="rgba(88,166,255,.12)"/>
      <text x="102" y="19" text-anchor="middle" font-size="12" font-weight="700" fill="#58a6ff" letter-spacing="1">📡 DATA IN</text>

      <rect x="210" y="4" width="196" height="22" rx="4" fill="rgba(188,140,255,.12)"/>
      <text x="308" y="19" text-anchor="middle" font-size="12" font-weight="700" fill="#bc8cff" letter-spacing="1">🧠 INTELLIGENCE</text>

      <rect x="416" y="4" width="196" height="22" rx="4" fill="rgba(249,115,22,.12)"/>
      <text x="514" y="19" text-anchor="middle" font-size="12" font-weight="700" fill="#f97316" letter-spacing="1">⚡ BESLISSINGEN</text>

      <rect x="622" y="4" width="196" height="22" rx="4" fill="rgba(63,185,80,.12)"/>
      <text x="720" y="19" text-anchor="middle" font-size="12" font-weight="700" fill="#3fb950" letter-spacing="1">🔧 ACTUATOREN</text>

      <rect x="828" y="4" width="268" height="22" rx="4" fill="rgba(210,153,34,.12)"/>
      <text x="962" y="19" text-anchor="middle" font-size="12" font-weight="700" fill="#d29922" letter-spacing="1">📊 RAPPORTAGE</text>

      <!-- ── DATA blokken ── -->
      ${this._blk(4,  36,196,52,'data', 'P1/DSMR Reader','Grid L1/L2/L3 · LKG-cache','1s')}
      ${this._blk(4, 98,196,52,'data', 'Omvormer Manager','Growatt · GoodWe · SMA · fase','1s')}
      ${this._blk(4, 160,196,52,'data','Battery Provider','Nexus · SoC · vermogen · lag','1s')}
      ${this._blk(4, 222,196,52,'data','EPEX + Prijzen','Spotprijzen · tariefgroep · TTF','1u')}
      ${this._blk(4, 284,196,52,'data','PV Forecast','Forecast.Solar · Solcast · Ecowitt','15m')}
      ${this._blk(4, 346,196,52,'data','Weersensoren','Temp · cloud cover · wind','1m')}
      ${this._blk(4, 408,196,52,'data','FrozenWatchdog','Bevroren sensoren detectie','1s')}

      <!-- ── INTELLIGENCE blokken ── -->
      ${this._blk(210, 36,196,52,'brain','Lokale k-NN AI',`${this._hass?.states['sensor.cloudems_ai_status']?.attributes?.n_trained||0} samples · ThresholdLearner`,'2m')}
      ${this._blk(210, 98,196,52,'brain','NILM Detector','Apparaatherkenning · fase · profiel','1s')}
      ${this._blk(210,160,196,52,'brain','BatteryOptimizer','48u plan · 96 slots · PV p10/50/90','10s')}
      ${this._blk(210,222,196,52,'brain','HouseLoadOptimizer','Bat + boiler + EV · deadline','10s')}
      ${this._blk(210,284,196,52,'brain','Zelf-Lerende Modules','Shutter · Solar · Boiler · EV','continu')}
      ${this._blk(210,346,196,52,'brain','CostForecaster','Maandfactuur · ROI · CO₂','10s')}

      <!-- ── BESLISSINGEN blokken ── -->
      ${this._blk(416, 36,196,52,'decide','BatteryDecision','5-laags · anti-cycling · AI-hint','1s')}
      ${this._blk(416, 98,196,52,'decide','BoilerController','GREEN/BOOST · Legionella · COP','10s')}
      ${this._blk(416,160,196,52,'decide','ShutterController','Zon · temp · thermisch · patroon','10s')}
      ${this._blk(416,222,196,52,'decide','SmartClimate+EPEX','Pre-heat · pre-cool · setpoint','10s')}
      ${this._blk(416,284,196,52,'decide','EV Trip Planner','Goedkoopste uur · deadline','10s')}
      ${this._blk(416,346,196,52,'decide','TariffOptimizer','Negatieve prijs · SmartDelay','1s')}
      ${this._blk(416,408,196,52,'decide','PoolController','Filter · warmtepomp · surplus','10s')}

      <!-- ── ACTUATOREN blokken ── -->
      ${this._blk(622, 36,196,52,'act','Zonneplan Bridge','Nexus API · override detectie','wijziging')}
      ${this._blk(622, 98,196,52,'act','Solar Dimmer','Omvormer begrenzen · spanning','wijziging')}
      ${this._blk(622,160,196,52,'act','Boiler API','Ariston Lydos · verify/retry','wijziging')}
      ${this._blk(622,222,196,52,'act','HA Services','Stekkers · EV · thermostaat','wijziging')}
      ${this._blk(622,284,196,52,'act','ActuatorWatchdog','Verificatie actuatoren 60s','60s')}

      <!-- ── RAPPORTAGE blokken ── -->
      ${this._blk(828, 36,268,52,'report','Dashboard (20+ kaarten)','Flow · Solar · NILM · AI · Besliss.','realtime')}
      ${this._blk(828, 98,268,52,'report','190+ HA Sensoren','Energiestroom · fase · AI · plan','1-10s')}
      ${this._blk(828,160,268,52,'report','Dagrapport','Besparing · ROI · CO₂','dagelijks')}
      ${this._blk(828,222,268,52,'report','AdaptiveHome Cloud','Benchmarking · community','periodiek')}

      <!-- ── PIJLEN Data → Intelligence ── -->
      <line x1="200" y1="62"  x2="210" y2="62"  stroke="#58a6ff" stroke-width="2" marker-end="url(#arr-b)"/>
      <line x1="200" y1="124" x2="210" y2="124" stroke="#58a6ff" stroke-width="2" marker-end="url(#arr-b)"/>
      <line x1="200" y1="186" x2="210" y2="186" stroke="#58a6ff" stroke-width="2" marker-end="url(#arr-b)"/>
      <line x1="200" y1="248" x2="210" y2="62"  stroke="#58a6ff" stroke-width="1.5" marker-end="url(#arr-b)" stroke-dasharray="4,2"/>
      <line x1="200" y1="310" x2="210" y2="186" stroke="#58a6ff" stroke-width="1.5" marker-end="url(#arr-b)" stroke-dasharray="4,2"/>
      <line x1="200" y1="372" x2="210" y2="310" stroke="#58a6ff" stroke-width="1.5" marker-end="url(#arr-b)" stroke-dasharray="4,2"/>

      <!-- ── PIJLEN Intelligence → Beslissingen ── -->
      <line x1="406" y1="62"  x2="416" y2="62"  stroke="#bc8cff" stroke-width="2" marker-end="url(#arr-p)"/>
      <line x1="406" y1="124" x2="416" y2="124" stroke="#bc8cff" stroke-width="1.5" marker-end="url(#arr-p)" stroke-dasharray="4,2"/>
      <line x1="406" y1="186" x2="416" y2="62"  stroke="#bc8cff" stroke-width="1.5" marker-end="url(#arr-p)" stroke-dasharray="4,2"/>
      <line x1="406" y1="248" x2="416" y2="248" stroke="#bc8cff" stroke-width="1.5" marker-end="url(#arr-p)" stroke-dasharray="4,2"/>
      <line x1="406" y1="310" x2="416" y2="310" stroke="#bc8cff" stroke-width="1.5" marker-end="url(#arr-p)" stroke-dasharray="4,2"/>

      <!-- ── PIJLEN Beslissingen → Actuatoren ── -->
      <line x1="612" y1="62"  x2="622" y2="62"  stroke="#f97316" stroke-width="2" marker-end="url(#arr-o)"/>
      <line x1="612" y1="124" x2="622" y2="186" stroke="#f97316" stroke-width="2" marker-end="url(#arr-o)"/>
      <line x1="612" y1="186" x2="622" y2="248" stroke="#f97316" stroke-width="2" marker-end="url(#arr-o)"/>
      <line x1="612" y1="248" x2="622" y2="248" stroke="#f97316" stroke-width="1.5" marker-end="url(#arr-o)" stroke-dasharray="4,2"/>
      <line x1="612" y1="310" x2="622" y2="248" stroke="#f97316" stroke-width="1.5" marker-end="url(#arr-o)" stroke-dasharray="4,2"/>
      <line x1="612" y1="62"  x2="622" y2="98"  stroke="#f97316" stroke-width="1.5" marker-end="url(#arr-o)" stroke-dasharray="4,2"/>

      <!-- ── PIJLEN Actuatoren → Rapportage ── -->
      <line x1="818" y1="62"  x2="828" y2="62"  stroke="#3fb950" stroke-width="1.5" marker-end="url(#arr-g)" stroke-dasharray="4,2"/>
      <line x1="818" y1="186" x2="828" y2="98"  stroke="#3fb950" stroke-width="1.5" marker-end="url(#arr-g)" stroke-dasharray="4,2"/>

      <!-- ── Data direct → Rapportage ── -->
      <line x1="200" y1="434" x2="828" y2="160" stroke="rgba(255,255,255,.1)" stroke-width="1" stroke-dasharray="6,4" marker-end="url(#arr)"/>

      <!-- ── Feedback lus ── -->
      <path d="M 828 248 C 780 520 280 520 280 400" stroke="rgba(210,153,34,.35)"
        stroke-width="1.5" fill="none" stroke-dasharray="6,3" marker-end="url(#arr-y)"/>
      <text x="554" y="540" text-anchor="middle" font-size="9" fill="rgba(210,153,34,.55)">← feedback lus (RL · AI learning · OutcomeTracker)</text>
    </svg>`;
  }

  _blk(x, y, w, h, type, title, body, freq) {
    const colors = {
      data:   {bg:'rgba(88,166,255,.08)',  border:'rgba(88,166,255,.28)',  title:'#58a6ff'},
      brain:  {bg:'rgba(188,140,255,.08)', border:'rgba(188,140,255,.28)', title:'#bc8cff'},
      decide: {bg:'rgba(249,115,22,.08)',  border:'rgba(249,115,22,.28)',  title:'#f97316'},
      act:    {bg:'rgba(63,185,80,.08)',   border:'rgba(63,185,80,.28)',   title:'#3fb950'},
      report: {bg:'rgba(210,153,34,.08)',  border:'rgba(210,153,34,.28)',  title:'#d29922'},
    };
    const c = colors[type] || colors.data;
    return `
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6"
        fill="${c.bg}" stroke="${c.border}" stroke-width="1"/>
      <text x="${x+8}" y="${y+18}" font-size="12" font-weight="700" fill="${c.title}">${title}</text>
      <text x="${x+8}" y="${y+33}" font-size="10" fill="rgba(255,255,255,.55)">${body}</text>
      <text x="${x+w-4}" y="${y+h-5}" text-anchor="end" font-size="9" fill="rgba(255,255,255,.25)">${freq}</text>`;
  }

  _renderTable() {
    const rows = [
      {sec:'📡 DATA IN', col:'data'},
      {tag:'data', mod:'P1/DSMR Reader',         wat:'Grid import/export + L1/L2/L3 stroom/spanning. LKG-cache voorkomt 0-waarden.',         freq:'1s'},
      {tag:'data', mod:'Multi-Inverter Manager',  wat:'Growatt · GoodWe · SMA · Huawei. Auto-detectie fase en calib-factor.',               freq:'1s'},
      {tag:'data', mod:'Battery Provider',        wat:'SoC · vermogen · SoH van Nexus/SMA/Victron. Nexus latency-leren.',                    freq:'1s'},
      {tag:'data', mod:'EPEX + Prijzen',          wat:'EPEX spotprijzen vandaag/morgen. Tariefgroep. TTF gasprijs.',                          freq:'elk uur'},
      {tag:'data', mod:'PV Forecast',             wat:'Forecast.Solar + Solcast + Ecowitt bewolking. p10/p50/p90. PVAccuracy calibratie.',   freq:'15 min'},
      {tag:'data', mod:'FrozenSensorWatchdog',    wat:'Detecteert bevriezen van grid+battery op 0W. Triggert coordinator refresh.',           freq:'1s'},
      {sec:'🧠 INTELLIGENCE', col:'brain'},
      {tag:'brain',mod:'Lokale k-NN AI',          wat:'Traint op jouw installatie. Voorspelt optimale actie. ThresholdLearner past drempels aan.',freq:'2 min'},
      {tag:'brain',mod:'NILM Detector',           wat:'Herkent apparaten op vermogenswijzigingen. Leert fase, profiel en tijdpatroon.',        freq:'1s'},
      {tag:'brain',mod:'BatteryOptimizer',        wat:'48u kostenoptimalisatie. 96 halfuur-slots. PV p10/50/90. Slijtage meerekenen.',        freq:'10s'},
      {tag:'brain',mod:'HouseLoadOptimizer',      wat:'Coördineert bat + boiler + EV. Deadline-safety. PV-surplus eerlijk verdelen.',         freq:'10s'},
      {tag:'brain',mod:'Zelf-Lerende Modules',    wat:'ShutterThermal · SolarLearner · BoilerCOP · EVSession · FaseDetector · HomeBaseline.', freq:'continu'},
      {tag:'brain',mod:'CostForecaster',          wat:'Maandfactuur voorspelling. ROI batterij. CO₂ voetafdruk. Salderings-countdown.',      freq:'10s'},
      {sec:'⚡ BESLISSINGEN', col:'decide'},
      {tag:'decide',mod:'BatteryDecisionEngine',  wat:'5-laags: Safety→PeakShaving→Tariefgroep→Optimizer→EPEX→AI→Surplus. Anti-cycling.',   freq:'1s'},
      {tag:'decide',mod:'BoilerController',       wat:'GREEN/BOOST/COMFORT. Legionella op goedkoopste uur. COP-leren. Verify/retry.',        freq:'10s'},
      {tag:'decide',mod:'ShutterController',      wat:'Rolluiken op zon, temp, tijd, patroon. Thermisch buffer. Open-raam detectie.',         freq:'10s'},
      {tag:'decide',mod:'SmartClimate + EPEX',    wat:'Multi-zone. Pre-heat/pre-cool op goedkoop uur. EPEX-compensatie setpoint.',           freq:'10s'},
      {tag:'decide',mod:'EV Trip Planner',        wat:'Laad op goedkoopste uur vóór vertrek. Required SoC per rit. Deadline safety.',        freq:'10s'},
      {tag:'decide',mod:'TariffOptimizer',        wat:'Negatieve prijs dump. SmartDelay. Micro-cycle prevention.',                            freq:'1s'},
      {tag:'decide',mod:'PoolController',         wat:'Filter + warmtepomp op PV-surplus. Temperatuur bewaking.',                            freq:'10s'},
      {sec:'🔧 ACTUATOREN', col:'act'},
      {tag:'act',mod:'Zonneplan Bridge',          wat:'Nexus via API: laden/ontladen/idle. Manual override detectie. ActuatorWatchdog 60s.', freq:'wijziging'},
      {tag:'act',mod:'Solar Dimmer',              wat:'Omvormer begrenzen bij negatieve EPEX of spanning >248V. VoltageRise prevention.',    freq:'wijziging'},
      {tag:'act',mod:'Boiler API',                wat:'Ariston Lydos via cloud API. Command verify met backoff. ActuatorWatchdog 60s.',       freq:'wijziging'},
      {tag:'act',mod:'HA Services',               wat:'turn_on/off stekkers · set_value EV-laders · climate.set_temperature thermostaten.',  freq:'wijziging'},
      {sec:'📊 RAPPORTAGE', col:'report'},
      {tag:'report',mod:'Dashboard (20+ kaarten)',wat:'Flow · Solar · NILM · AI-status · Batterij · P1 · Beslissingen · Diagnose · ISO.',   freq:'realtime'},
      {tag:'report',mod:'190+ HA Sensoren',       wat:'Energiestroom · fase · AI · optimizer plan · beslissingsuitleg — allemaal in HA.',    freq:'1-10s'},
      {tag:'report',mod:'Dagrapport',             wat:'Besparing · ROI batterij · CO₂ voetafdruk · saldering countdown.',                   freq:'dagelijks'},
      {tag:'report',mod:'AdaptiveHome Cloud',     wat:'Leest data voor benchmarking. Toekomst: cloud intelligence module-voor-module.',      freq:'periodiek'},
    ];

    const tagColors = {
      data:'#58a6ff', brain:'#bc8cff', decide:'#f97316', act:'#3fb950', report:'#d29922'
    };
    const tagBg = {
      data:'rgba(88,166,255,.18)', brain:'rgba(188,140,255,.18)',
      decide:'rgba(249,115,22,.18)', act:'rgba(63,185,80,.18)', report:'rgba(210,153,34,.18)'
    };

    const rowsHtml = rows.map(r => {
      if (r.sec) {
        const c = tagColors[r.col];
        return `<tr class="sec-row"><td colspan="4" style="color:${c};background:${tagBg[r.col]}">${r.sec}</td></tr>`;
      }
      return `<tr>
        <td><span class="tag" style="background:${tagBg[r.tag]};color:${tagColors[r.tag]}">${r.tag}</span></td>
        <td style="font-weight:600;color:#e6edf3">${r.mod}</td>
        <td>${r.wat}</td>
        <td class="freq">${r.freq}</td>
      </tr>`;
    }).join('');

    return `<table class="arch-table">
      <tr><th>Laag</th><th>Module</th><th>Wat het doet</th><th>Freq.</th></tr>
      ${rowsHtml}
    </table>`;
  }
}

if (!customElements.get('cloudems-arch-card'))
  customElements.define('cloudems-arch-card', CloudEMSArchCard);

class CloudEMSArchCardEditor extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `<p style="padding:8px;color:#aaa;font-size:12px">Geen configuratie vereist.</p>`;
  }
}
if (!customElements.get('cloudems-arch-card-editor'))
  customElements.define('cloudems-arch-card-editor', CloudEMSArchCardEditor);
