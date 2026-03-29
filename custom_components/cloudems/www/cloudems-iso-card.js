// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Isometric Energy Card v5.4.96

const ISO_VERSION = '4.0.0';
const ISO_BASE = '/local/cloudems/iso-assets/';

const HOUSE_TYPES = {
  modern:    'house_modern.png',
  villa:     'house_villa.png',
  terraced:  'house_terraced.png',
  apartment: 'house_apartment.png',
  farmhouse: 'house_farmhouse.png',
};

// Standaard element layouts per huistype
// Alle waarden in % van de kaartbreedte/hoogte
const LAYOUTS = {
  modern:    { hx:22,hy:5,hw:56,  bx:-6,by:38,bw:30,  ex:62,ey:37,ew:36,  gx:68,gy:-6,gw:26,  px:-2,py:60,pw:24,  ox:68,oy:37,ow:15,  ax:68,ay:49,aw:14 },
  villa:     { hx:18,hy:5,hw:60,  bx:-8,by:40,bw:30,  ex:64,ey:36,ew:36,  gx:70,gy:-6,gw:24,  px:-4,py:62,pw:26,  ox:68,oy:40,ow:14,  ax:68,ay:52,aw:13 },
  terraced:  { hx:22,hy:3,hw:54,  bx:-5,by:42,bw:28,  ex:62,ey:40,ew:34,  gx:70,gy:-4,gw:24,  px:-2,py:64,pw:22,  ox:68,oy:42,ow:13,  ax:68,ay:54,aw:12 },
  apartment: { hx:20,hy:4,hw:58,  bx:-6,by:38,bw:28,  ex:64,ey:36,ew:34,  gx:70,gy:-4,gw:24,  px:-2,py:62,pw:22,  ox:68,oy:38,ow:13,  ax:68,ay:50,aw:12 },
  farmhouse: { hx:15,hy:6,hw:62,  bx:-8,by:42,bw:32,  ex:60,ey:40,ew:36,  gx:68,gy:-4,gw:26,  px:-4,py:64,pw:26,  ox:66,oy:42,ow:15,  ax:66,ay:54,aw:14 },
};

class FlowParticle {
  constructor(path, color, speed, size) {
    this.path   = path;
    this.length = path.getTotalLength();
    this.color  = color;
    this.speed  = speed;
    this.size   = size || 4;
    this.t      = Math.random();
  }
  tick(dt) {
    this.t = (this.t + (this.speed * dt) / this.length) % 1;
    return this.path.getPointAtLength(this.t * this.length);
  }
}

class CloudEMSIsoCard extends HTMLElement {
  constructor() {
    super();
    this._particles = [];
    this._flowSig   = null;
    this._rafId     = null;
    this._lastTs    = null;
    this._ready     = false;
    this._houseType = 'modern';
    this._customUrl = null;
    this._layout    = LAYOUTS.modern;
    this._aiLayout  = null;
    this._aiRunning = false;
  }

  set hass(h) {
    this._hass = h;
    // Lees huistype uit sensor als niet via config gezet
    if (!this._cfgHouseType) {
      const ht = h?.states['sensor.cloudems_iso_settings']?.attributes?.house_type;
      if (ht && ht !== this._houseType) {
        this._houseType = ht;
        this._layout = LAYOUTS[ht] || LAYOUTS.modern;
        this._ready = false;
      }
      const cu = h?.states['sensor.cloudems_iso_settings']?.attributes?.custom_image_url;
      if (cu && cu !== this._customUrl) {
        this._customUrl = cu;
        this._houseType = 'custom';
        this._ready = false;
        this._runAI(cu);
      }
    }
    const j = JSON.stringify([
      h?.states['sensor.cloudems_solar_system']?.state,
      h?.states['sensor.cloudems_battery_power']?.state,
      h?.states['sensor.cloudems_battery_so_c']?.state,
      h?.states['sensor.cloudems_status']?.attributes?.grid_power_w,
      h?.states['sensor.cloudems_home_rest']?.state,
      h?.states['sensor.cloudems_pool_status']?.state,
      h?.states['sensor.cloudems_climate_epex_status']?.attributes?.total_power_w,
      h?.states['sensor.cloudems_lamp_circulation_status']?.attributes?.lamps_active,
      h?.states['sensor.cloudems_ev_laad_power']?.state,
    ]);
    if (j !== this._prev) { this._prev = j; this._update(); }
  }

  setConfig(c) {
    this._cfg = c;
    if (c.house_type) {
      this._cfgHouseType = c.house_type;
      this._houseType = c.house_type;
      this._layout = LAYOUTS[c.house_type] || LAYOUTS.modern;
    }
    if (c.custom_image_url) {
      this._customUrl = c.custom_image_url;
      this._houseType = 'custom';
      this._runAI(c.custom_image_url);
    }
  }

  getCardSize() { return 10; }

  static getConfigElement() {
    return document.createElement('cloudems-iso-card-editor');
  }

  static getStubConfig() {
    return { house_type: 'modern' };
  }

  connectedCallback()    { if (this._ready) this._startAnim(); }
  disconnectedCallback() { this._stopAnim(); }

  // ── AI positie-analyse ────────────────────────────────────────────────────
  async _runAI(imageUrl) {
    if (this._aiRunning) return;
    this._aiRunning = true;
    try {
      const resp = await fetch(imageUrl);
      const blob = await resp.blob();
      const b64  = await new Promise(res => {
        const r = new FileReader();
        r.onload = () => res(r.result.split(',')[1]);
        r.readAsDataURL(blob);
      });

      const apiResp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 300,
          messages: [{
            role: 'user',
            content: [
              { type: 'image', source: { type: 'base64', media_type: blob.type || 'image/jpeg', data: b64 } },
              { type: 'text', text: `Analyze this house photo for an energy dashboard overlay.
Return ONLY a JSON object with percentage positions (0-100) for overlaying energy elements.
The card is 100% wide, house should be centered.
{"hx":20,"hy":5,"hw":55,"bx":-5,"by":38,"bw":28,"ex":62,"ey":36,"ew":32,"gx":70,"gy":-4,"gw":22,"px":-2,"py":60,"pw":20,"ox":68,"oy":38,"ow":12,"ax":68,"ay":50,"aw":11}
hx/hy/hw=house x/y/width, bx/by/bw=battery, ex/ey/ew=EV, gx/gy/gw=grid pole, px/py/pw=pool, ox/oy/ow=boiler, ax/ay/aw=airco` }
            ]
          }]
        })
      });

      const data = await apiResp.json();
      const text = data.content?.find(b => b.type === 'text')?.text || '';
      const m = text.match(/\{[\s\S]*?\}/);
      if (m) {
        const j = JSON.parse(m[0]);
        if (j.hx !== undefined) {
          this._aiLayout = j;
          this._layout = j;
          this._ready = false;
          this._update();
        }
      }
    } catch(e) {
      console.warn('CloudEMS ISO: AI layout mislukt, gebruik standaard', e);
      this._layout = LAYOUTS.modern;
    }
    this._aiRunning = false;
  }

  _getData() {
    const h = this._hass;
    if (!h) return null;
    const st = h.states;
    const solarW   = parseFloat(st['sensor.cloudems_solar_system']?.state || 0);
    const gridW    = parseFloat(st['sensor.cloudems_status']?.attributes?.grid_power_w || 0);
    const houseW   = parseFloat(st['sensor.cloudems_home_rest']?.state || 0);
    const batW     = parseFloat(st['sensor.cloudems_battery_power']?.state || 0);
    const batSoc   = parseFloat(st['sensor.cloudems_battery_so_c']?.state || 0);
    const price    = parseFloat(st['sensor.cloudems_price_current_hour']?.state || 0);
    const boilers  = st['sensor.cloudems_boiler_status']?.attributes?.boilers || [];
    const boilerW  = boilers.reduce((s, b) => s + parseFloat(b.power_w || b.current_w || 0), 0);
    const boilerConf = !!st['sensor.cloudems_boiler_status'];
    const evW      = parseFloat(st['sensor.cloudems_ev_laad_power']?.state || 0);
    const evConf   = !!st['sensor.cloudems_ev_laad_power'];
    const poolAttr = st['sensor.cloudems_pool_status']?.attributes || {};
    const poolW    = parseFloat(poolAttr.filter_power_w || 0) + parseFloat(poolAttr.heat_power_w || 0);
    const poolOn   = !!(poolAttr.filter_is_on || poolAttr.heat_is_on);
    const poolConf = !!st['sensor.cloudems_pool_status'];
    const aircoAttr= st['sensor.cloudems_climate_epex_status']?.attributes || {};
    const aircoW   = parseFloat(aircoAttr.total_power_w || 0);
    const aircoConf= !!st['sensor.cloudems_climate_epex_status'];
    const lampAttr = st['sensor.cloudems_lamp_circulation_status']?.attributes || {};
    const lampsOn  = parseInt(lampAttr.lamps_active || 0);
    const lampLabels = lampAttr.lamps_on_labels || [];
    return { solarW, gridW, houseW, batW, batSoc, boilerW, boilerConf,
             evW, evConf, poolW, poolOn, poolConf, aircoW, aircoConf,
             lampsOn, lampLabels, price };
  }

  _fmt(w) {
    const abs = Math.abs(w);
    if (abs >= 1000) return `${(abs/1000).toFixed(1)} kW`;
    return `${Math.round(abs)} W`;
  }

  _houseImgUrl() {
    if (this._houseType === 'custom' && this._customUrl) return this._customUrl;
    return `${ISO_BASE}${HOUSE_TYPES[this._houseType] || HOUSE_TYPES.modern}`;
  }

  _update() {
    const d = this._getData();
    if (!d) return;
    if (!this._ready) { this._build(d); this._ready = true; this._startAnim(); return; }
    this._updateLabels(d);
    this._updateFlows(d);
  }

  _build(d) {
    const l = this._layout;
    const houseUrl = this._houseImgUrl();

    this.innerHTML = `
    <ha-card>
      <style>
        ha-card {
          background: #010508;
          border-radius: 16px;
          border: 1px solid rgba(0,160,255,.15);
          overflow: hidden;
          padding: 0;
          font-family: 'Syne', system-ui, sans-serif;
          box-shadow: 0 0 60px rgba(0,120,255,.08);
        }
        .iso-wrap { position:relative; width:100%; aspect-ratio:10/6; }
        svg.iso-svg { position:absolute; inset:0; width:100%; height:100%; }

        /* PNG lagen — mix-blend-mode:screen maakt zwart transparant */
        .il {
          position: absolute;
          mix-blend-mode: screen;
          pointer-events: none;
          transition: opacity .5s;
        }

        /* Data labels */
        .lb {
          position: absolute;
          background: rgba(0,0,0,.18);
          border: 1px solid rgba(0,180,255,.12);
          border-radius: 8px;
          padding: 5px 10px;
          pointer-events: none;
          backdrop-filter: blur(6px);
          -webkit-backdrop-filter: blur(6px);
          min-width: 76px;
          box-shadow: none;
          z-index: 10;
        }
        .lb-name {
          font-size: 7px; font-weight: 700; letter-spacing: .1em;
          text-transform: uppercase; color: rgba(0,210,255,.7);
          margin-bottom: 2px;
          text-shadow: 0 0 8px rgba(0,0,0,1), 0 1px 3px rgba(0,0,0,1);
        }
        .lb-val { font-size: 15px; font-weight: 700; color: #fff; line-height:1.1;
          text-shadow: 0 0 10px rgba(0,0,0,1), 0 1px 4px rgba(0,0,0,1), 0 0 20px rgba(0,0,0,.8); }
        .lb-sub { font-size: 9px; color: rgba(100,210,255,.7); margin-top:1px;
          text-shadow: 0 0 6px rgba(0,0,0,1), 0 1px 3px rgba(0,0,0,1); }

        /* Posities */
        #lb-solar  { left:1%; top:3%; }
        #lb-bat    { left:1%; top:56%; }
        #lb-grid   { right:1%; top:3%; text-align:right; }
        #lb-ev     { right:1%; top:52%; text-align:right; }
        #lb-house  { left:50%; transform:translateX(-50%); bottom:1%; text-align:center; }
        #lb-boiler { right:1%; top:30%; text-align:right; }
        #lb-airco  { right:1%; top:42%; text-align:right; }
        #lb-pool   { left:1%; top:76%; }
        #lb-lamps  { left:1%; top:40%; }

        /* Huistype selector chip */
        .ht-chips {
          position:absolute; bottom:4px; right:6px;
          display:flex; gap:4px; z-index:20; align-items:center;
        }
        .ht-chip {
          font-size:8px; font-weight:700; letter-spacing:.05em;
          padding:2px 7px; border-radius:8px; cursor:pointer;
          background:rgba(0,20,40,.7); border:1px solid rgba(0,160,255,.2);
          color:rgba(0,200,255,.5); transition:all .2s;
        }
        .ht-chip:hover { border-color:rgba(0,200,255,.5); color:#00c8ff; }
        .ht-chip.active { background:rgba(0,80,160,.4); border-color:#00c8ff; color:#00c8ff; }
        .ht-upload {
          font-size:8px; font-weight:700; padding:2px 8px; border-radius:8px;
          cursor:pointer; background:rgba(0,60,20,.7); border:1px solid rgba(0,200,80,.25);
          color:rgba(0,220,80,.5); transition:all .2s; white-space:nowrap;
        }
        .ht-upload:hover { border-color:rgba(0,220,80,.6); color:#00ff88; }
        .ht-upload.loading { opacity:.5; pointer-events:none; }
        #iso-upload-inp { display:none; }
        .ht-upload-status {
          position:absolute; bottom:24px; right:6px; z-index:20;
          font-size:9px; color:rgba(0,220,80,.7); background:rgba(0,10,20,.8);
          padding:2px 8px; border-radius:6px; display:none;
        }
      </style>

      <div class="iso-wrap">

        <!-- Huis PNG -->
        <img class="il" id="img-house"
          src="${houseUrl}"
          style="left:${l.hx}%;top:${l.hy}%;width:${l.hw}%;opacity:.95"
          onerror="this.style.opacity='.1'"/>

        <!-- Batterij -->
        <img class="il" id="img-battery"
          src="${ISO_BASE}battery.png"
          style="left:${l.bx}%;top:${l.by}%;width:${l.bw}%;opacity:.88"/>

        <!-- EV -->
        <img class="il" id="img-ev"
          src="${ISO_BASE}ev.png"
          style="left:${l.ex}%;top:${l.ey}%;width:${l.ew}%;opacity:0"
          onerror="this.style.display='none'"/>

        <!-- Net paal -->
        <img class="il" id="img-grid"
          src="${ISO_BASE}grid.png"
          style="left:${l.gx}%;top:${l.gy}%;width:${l.gw}%;opacity:.82"
          onerror="this.style.display='none'"/>

        <!-- Pool -->
        <img class="il" id="img-pool"
          src="${ISO_BASE}pool.png"
          style="left:${l.px}%;top:${l.py}%;width:${l.pw}%;opacity:0"
          onerror="this.style.display='none'"/>

        <!-- Boiler -->
        <img class="il" id="img-boiler"
          src="${ISO_BASE}boiler.png"
          style="left:${l.ox}%;top:${l.oy}%;width:${l.ow}%;opacity:0"
          onerror="this.style.display='none'"/>

        <!-- Airco -->
        <img class="il" id="img-airco"
          src="${ISO_BASE}airco.png"
          style="left:${l.ax}%;top:${l.ay}%;width:${l.aw}%;opacity:0"
          onerror="this.style.display='none'"/>

        <!-- SVG overlay: particles + flow lijnen -->
        <svg class="iso-svg" viewBox="0 0 1000 600" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <filter id="glow-p" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="5" result="b1"/>
              <feGaussianBlur stdDeviation="10" result="b2"/>
              <feMerge><feMergeNode in="b2"/><feMergeNode in="b1"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>

          <!-- Flow paden -->
          <path id="fp-sh"   d="M 330,205 C 400,250 450,285 500,315" fill="none" stroke="none"/>
          <path id="fp-sb"   d="M 295,245 C 255,285 205,330 175,370" fill="none" stroke="none"/>
          <path id="fp-bh"   d="M 200,378 C 310,348 410,328 492,318" fill="none" stroke="none"/>
          <path id="fp-gh"   d="M 820,205 C 755,248 672,288 565,315" fill="none" stroke="none"/>
          <path id="fp-hg"   d="M 565,298 C 672,268 755,235 820,198" fill="none" stroke="none"/>
          <path id="fp-sg"   d="M 420,168 C 580,152 700,160 818,175" fill="none" stroke="none"/>
          <path id="fp-bo"   d="M 595,328 C 648,328 695,332 725,335" fill="none" stroke="none"/>
          <path id="fp-ac"   d="M 595,345 C 645,358 692,368 722,372" fill="none" stroke="none"/>
          <path id="fp-ev"   d="M 608,362 C 695,392 772,415 820,438" fill="none" stroke="none"/>
          <path id="fp-pool" d="M 468,388 C 375,415 272,442 202,468" fill="none" stroke="none"/>
          <path id="fp-lamp" d="M 485,365 C 432,382 372,394 322,402" fill="none" stroke="none"/>

          <!-- Flow lijnen -->
          <path d="M 330,205 C 400,250 450,285 500,315" fill="none" stroke="#ffd700" stroke-width="1.5" stroke-dasharray="5,10" opacity=".1" id="fl-sh"/>
          <path d="M 295,245 C 255,285 205,330 175,370" fill="none" stroke="#00ff88" stroke-width="1.5" stroke-dasharray="5,10" opacity=".1" id="fl-sb"/>
          <path d="M 200,378 C 310,348 410,328 492,318" fill="none" stroke="#00ff88" stroke-width="1.5" stroke-dasharray="5,10" opacity=".1" id="fl-bh"/>
          <path d="M 820,205 C 755,248 672,288 565,315" fill="none" stroke="#ff4444" stroke-width="1.5" stroke-dasharray="5,10" opacity=".1" id="fl-gh"/>
          <path d="M 565,298 C 672,268 755,235 820,198" fill="none" stroke="#00ff88" stroke-width="1.5" stroke-dasharray="5,10" opacity=".1" id="fl-hg"/>
          <path d="M 420,168 C 580,152 700,160 818,175" fill="none" stroke="#ffd700" stroke-width="1.5" stroke-dasharray="5,10" opacity=".1" id="fl-sg"/>
          <path d="M 595,328 C 648,328 695,332 725,335" fill="none" stroke="#ff8800" stroke-width="1"   stroke-dasharray="4,8"  opacity=".1" id="fl-bo"/>
          <path d="M 595,345 C 645,358 692,368 722,372" fill="none" stroke="#00aaff" stroke-width="1"   stroke-dasharray="4,8"  opacity=".1" id="fl-ac"/>
          <path d="M 608,362 C 695,392 772,415 820,438" fill="none" stroke="#00aaff" stroke-width="1"   stroke-dasharray="4,8"  opacity=".1" id="fl-ev"/>
          <path d="M 468,388 C 375,415 272,442 202,468" fill="none" stroke="#00c8ff" stroke-width="1"   stroke-dasharray="4,8"  opacity=".1" id="fl-pool"/>
          <path d="M 485,365 C 432,382 372,394 322,402" fill="none" stroke="#ffc800" stroke-width="1"   stroke-dasharray="4,8"  opacity=".1" id="fl-lamp"/>

          <g id="iso-particles"/>
          <text x="996" y="596" text-anchor="end" font-size="7"
            fill="rgba(0,140,255,.12)" font-family="monospace">iso v${ISO_VERSION}</text>
        </svg>

        <!-- Labels -->
        <div class="lb" id="lb-solar">
          <div class="lb-name">☀ Solar</div>
          <div class="lb-val" id="lv-solar">—</div>
          <div class="lb-sub" id="ls-solar"></div>
        </div>
        <div class="lb" id="lb-bat">
          <div class="lb-name">⚡ Batterij</div>
          <div class="lb-val" id="lv-bat">—</div>
          <div class="lb-sub" id="ls-bat"></div>
        </div>
        <div class="lb" id="lb-grid">
          <div class="lb-name">🔌 Net</div>
          <div class="lb-val" id="lv-grid">—</div>
          <div class="lb-sub" id="ls-grid"></div>
        </div>
        <div class="lb" id="lb-ev" style="display:none">
          <div class="lb-name">🚗 EV</div>
          <div class="lb-val" id="lv-ev">—</div>
          <div class="lb-sub" id="ls-ev"></div>
        </div>
        <div class="lb" id="lb-house">
          <div class="lb-name">🏠 Huis</div>
          <div class="lb-val" id="lv-house">—</div>
          <div class="lb-sub" id="ls-house"></div>
        </div>
        <div class="lb" id="lb-boiler" style="display:none">
          <div class="lb-name">🌡 Boiler</div>
          <div class="lb-val" id="lv-boiler">—</div>
          <div class="lb-sub" id="ls-boiler">Uit</div>
        </div>
        <div class="lb" id="lb-airco" style="display:none">
          <div class="lb-name">❄ Airco</div>
          <div class="lb-val" id="lv-airco">—</div>
          <div class="lb-sub" id="ls-airco">Uit</div>
        </div>
        <div class="lb" id="lb-pool" style="display:none">
          <div class="lb-name">🏊 Zwembad</div>
          <div class="lb-val" id="lv-pool">—</div>
          <div class="lb-sub" id="ls-pool">Standby</div>
        </div>
        <div class="lb" id="lb-lamps">
          <div class="lb-name">💡 Lampen</div>
          <div class="lb-val" id="lv-lamps">—</div>
          <div class="lb-sub" id="ls-lamps">Uit</div>
        </div>

        <!-- Huistype selector -->
        <input type="file" id="iso-upload-inp" accept="image/*" style="display:none"/>
        <div class="ht-upload-status" id="iso-upload-status"></div>
        <div class="ht-chips">
          <div class="ht-chip ${this._houseType==='modern'?'active':''}"    data-ht="modern">Modern</div>
          <div class="ht-chip ${this._houseType==='villa'?'active':''}"     data-ht="villa">Villa</div>
          <div class="ht-chip ${this._houseType==='terraced'?'active':''}"  data-ht="terraced">Rij</div>
          <div class="ht-chip ${this._houseType==='apartment'?'active':''}" data-ht="apartment">Flat</div>
          <div class="ht-chip ${this._houseType==='farmhouse'?'active':''}" data-ht="farmhouse">Boerderij</div>
          <div class="ht-upload" id="iso-upload-btn">📷 Eigen foto</div>
        </div>
      </div>
    </ha-card>`;

    // Chip click handlers
    this.querySelectorAll('.ht-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const ht = chip.dataset.ht;
        this._houseType = ht;
        this._layout = LAYOUTS[ht] || LAYOUTS.modern;
        this._ready = false;
        const d = this._getData();
        if (d) { this._build(d); this._ready = true; }
        this._saveHouseType(ht);
      });
    });

    // Upload knop
    const uploadBtn = this.querySelector('#iso-upload-btn');
    const uploadInp = this.querySelector('#iso-upload-inp');
    if (uploadBtn && uploadInp) {
      uploadBtn.addEventListener('click', () => uploadInp.click());
      uploadInp.addEventListener('change', async e => {
        const file = e.target.files?.[0];
        if (!file) return;
        await this._uploadPhoto(file);
      });
    }

    this._updateLabels(d);
    this._updateFlows(d);
    this._updatePaths();
  }

  async _uploadPhoto(file) {
    const btn    = this.querySelector('#iso-upload-btn');
    const status = this.querySelector('#iso-upload-status');
    if (btn) { btn.classList.add('loading'); btn.textContent = '⏳ Uploaden...'; }
    if (status) { status.textContent = ''; status.style.display = 'none'; }

    try {
      // Stap 1: upload naar HA via /api/image/upload of direct naar /config/www/cloudems/
      const fname    = `iso_house_${Date.now()}.${file.name.split('.').pop()}`;
      const formData = new FormData();
      formData.append('file', file, fname);

      // Probeer HA file upload API
      let fileUrl = null;
      try {
        const uploadResp = await fetch('/api/cloudems/upload_iso_image', {
          method: 'POST',
          headers: { Authorization: `Bearer ${this._hass?.auth?.data?.access_token || ''}` },
          body: formData,
        });
        if (uploadResp.ok) {
          const uploadData = await uploadResp.json();
          fileUrl = uploadData.url;
        }
      } catch(_) {}

      // Fallback: base64 data URL voor directe AI analyse
      if (!fileUrl) {
        fileUrl = await new Promise(res => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.readAsDataURL(file);
        });
      }

      if (status) { status.textContent = '🧠 AI analyseert...'; status.style.display = 'block'; }

      // Stap 2: AI positie analyse
      const b64 = fileUrl.startsWith('data:')
        ? fileUrl.split(',')[1]
        : await fetch(fileUrl).then(r=>r.blob()).then(b=>new Promise(res=>{const rd=new FileReader();rd.onload=()=>res(rd.result.split(',')[1]);rd.readAsDataURL(b);}));

      const apiResp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 300,
          messages: [{
            role: 'user',
            content: [
              { type: 'image', source: { type: 'base64', media_type: file.type || 'image/jpeg', data: b64 } },
              { type: 'text', text: `Analyze this house photo. Return ONLY JSON with percentage positions for energy dashboard overlay elements. Card is 100% wide.
{"hx":22,"hy":5,"hw":55,"bx":-5,"by":38,"bw":28,"ex":62,"ey":36,"ew":32,"gx":70,"gy":-4,"gw":22,"px":-2,"py":60,"pw":20,"ox":68,"oy":38,"ow":12,"ax":68,"ay":50,"aw":11}
hx/hy/hw=house center x/y/width%, bx/by/bw=battery left, ex/ey/ew=EV right, gx/gy/gw=grid pole top-right, px/py/pw=pool bottom-left, ox/oy/ow=boiler right-mid, ax/ay/aw=airco right-mid-low` }
            ]
          }]
        })
      });

      const data = await apiResp.json();
      const text = data.content?.find(b => b.type === 'text')?.text || '';
      const m    = text.match(/\{[\s\S]*?\}/);

      if (m) {
        const j = JSON.parse(m[0]);
        if (j.hx !== undefined) {
          this._layout    = j;
          this._houseType = 'custom';
          this._customUrl = fileUrl;
          this._ready     = false;
          localStorage.setItem('cloudems_iso_custom_url', fileUrl.startsWith('data:') ? '' : fileUrl);
          localStorage.setItem('cloudems_iso_layout', JSON.stringify(j));
          const d = this._getData();
          if (d) { this._build(d); this._ready = true; }
          if (status) { status.textContent = '✅ Klaar!'; setTimeout(()=>{ if(status) status.style.display='none'; }, 3000); }
        }
      } else {
        throw new Error('Geen layout ontvangen');
      }
    } catch(err) {
      console.warn('CloudEMS ISO upload:', err);
      if (status) { status.textContent = '⚠️ Upload mislukt — sla foto op in /config/www/ en voer de URL in via Instellingen → CloudEMS → Dashboard'; status.style.display = 'block'; setTimeout(()=>{ if(status) status.style.display='none'; }, 6000); }
    } finally {
      if (btn) { btn.classList.remove('loading'); btn.textContent = '📷 Eigen foto'; }
    }
  }

  _saveHouseType(ht) {
    // Sla huistype op via HA storage (input_select of persistent notification als fallback)
    try {
      if (this._hass && this._hass.callService) {
        // Gebruik CloudEMS service als die bestaat, anders localStorage als fallback
        localStorage.setItem('cloudems_iso_house_type', ht);
      }
    } catch(e) {}
  }

  _updatePaths() {
    const l = this._layout;
    if (!l) return;
    const svg = this.querySelector('svg.iso-svg');
    if (!svg) return;

    // % → SVG viewBox pixels (1000×600)
    const px = p => p * 10;
    const py = p => p * 6;

    // Middelpunten per element
    const hCx = px(l.hx + l.hw/2), hCy = py(l.hy + 15);  // dak
    const hMx = px(l.hx + l.hw/2), hMy = py(l.hy + 38);  // midden huis
    const bCx = px(Math.max(0, l.bx) + l.bw/2), bCy = py(l.by + l.bw/3);
    const eCx = px(Math.min(100, l.ex) + l.ew/2), eCy = py(l.ey + l.ew/3);
    const gCx = px(Math.min(95, l.gx) + l.gw/2), gCy = py(l.gy + l.gw/2);
    const pCx = px(Math.max(0, l.px) + l.pw/2), pCy = py(l.py + l.pw/3);
    const oCx = px(Math.min(95, l.ox) + l.ow/2), oCy = py(l.oy + l.ow/2);
    const aCx = px(Math.min(95, l.ax) + l.aw/2), aCy = py(l.ay + l.aw/2);

    // Cubic bezier A → B
    const cbez = (x1,y1,x2,y2) => {
      const cx = (x1+x2)/2;
      return `M ${x1.toFixed(0)},${y1.toFixed(0)} C ${cx.toFixed(0)},${y1.toFixed(0)} ${cx.toFixed(0)},${y2.toFixed(0)} ${x2.toFixed(0)},${y2.toFixed(0)}`;
    };

    const newPaths = {
      'fp-sh':   cbez(hCx, hCy, hMx, hMy),
      'fp-sb':   cbez(hCx, hCy, bCx, bCy),
      'fp-bh':   cbez(bCx, bCy, hMx, hMy),
      'fp-gh':   cbez(gCx, gCy, hMx, hMy),
      'fp-hg':   cbez(hMx, hMy, gCx, gCy),
      'fp-sg':   cbez(hCx, hCy-5, gCx, gCy-5),
      'fp-bo':   cbez(hMx, hMy, oCx, oCy),
      'fp-ac':   cbez(hMx, hMy+8, aCx, aCy),
      'fp-ev':   cbez(hMx, hMy+16, eCx, eCy),
      'fp-pool': cbez(hMx, hMy+24, pCx, pCy),
      'fp-lamp': cbez(hMx-15, hMy+5, hMx-35, hMy+25),
    };
    const flMap = {
      'fp-sh':'fl-sh','fp-sb':'fl-sb','fp-bh':'fl-bh',
      'fp-gh':'fl-gh','fp-hg':'fl-hg','fp-sg':'fl-sg',
      'fp-bo':'fl-bo','fp-ac':'fl-ac','fp-ev':'fl-ev',
      'fp-pool':'fl-pool','fp-lamp':'fl-lamp',
    };
    for (const [fpId, d] of Object.entries(newPaths)) {
      const fp = svg.querySelector(`#${fpId}`);
      if (fp) fp.setAttribute('d', d);
      const fl = svg.querySelector(`#${flMap[fpId]}`);
      if (fl) fl.setAttribute('d', d);
    }
    this._flowSig = null; // Particles opnieuw aanmaken
  }

  _updateLabels(d) {
    const q = id => this.querySelector(`#${id}`);
    if (!q('lv-solar')) return;

    // Solar
    q('lv-solar').textContent = this._fmt(d.solarW);
    q('lv-solar').style.color = d.solarW > 50 ? '#ffd700' : 'rgba(180,210,255,.35)';
    q('ls-solar').textContent  = d.solarW > 50 ? 'Opwek actief' : 'Geen opwek';

    // Batterij
    const socPct = Math.round(d.batSoc);
    const batDir = d.batW > 10 ? '↑ laden' : d.batW < -10 ? '↓ ontladen' : 'idle';
    q('lv-bat').textContent = `${socPct}%`;
    q('lv-bat').style.color = d.batSoc < 20 ? '#ff4444' : '#00ff88';
    q('ls-bat').textContent  = `${this._fmt(d.batW)} · ${batDir}`;

    // Grid
    q('lv-grid').textContent = this._fmt(d.gridW);
    q('lv-grid').style.color = d.gridW > 50 ? '#ff4444' : d.gridW < -50 ? '#00ff88' : 'rgba(180,210,255,.35)';
    q('ls-grid').textContent  = d.gridW > 50 ? '↓ import' : d.gridW < -50 ? '↑ export' : 'idle';

    // Huis
    q('lv-house').textContent = this._fmt(d.houseW);
    q('lv-house').style.color = '#dceeff';
    q('ls-house').textContent  = d.price ? `${(d.price*100).toFixed(1)} ct/kWh` : '';

    // EV — alleen tonen als geconfigureerd
    const lbEv = this.querySelector('#lb-ev');
    const imgEv = this.querySelector('#img-ev');
    if (d.evConf) {
      if (lbEv) lbEv.style.display = '';
      q('lv-ev').textContent = d.evW > 5 ? this._fmt(d.evW) : '—';
      q('lv-ev').style.color = d.evW > 5 ? '#00aaff' : 'rgba(180,210,255,.3)';
      q('ls-ev').textContent  = d.evW > 5 ? 'Laden' : 'Verbonden';
      if (imgEv) imgEv.style.opacity = d.evW > 5 ? '0.92' : '0.45';
    } else {
      if (lbEv) lbEv.style.display = 'none';
      if (imgEv) imgEv.style.opacity = '0';
    }

    // Boiler — alleen tonen als geconfigureerd
    const lbBo = this.querySelector('#lb-boiler');
    const imgBo = this.querySelector('#img-boiler');
    if (d.boilerConf) {
      if (lbBo) lbBo.style.display = '';
      q('lv-boiler').textContent = d.boilerW > 20 ? this._fmt(d.boilerW) : '—';
      q('lv-boiler').style.color = d.boilerW > 20 ? '#ff8800' : 'rgba(180,210,255,.3)';
      q('ls-boiler').textContent  = d.boilerW > 20 ? 'Actief' : 'Uit';
      if (imgBo) imgBo.style.opacity = d.boilerW > 50 ? '0.88' : '0.35';
    } else {
      if (lbBo) lbBo.style.display = 'none';
      if (imgBo) imgBo.style.opacity = '0';
    }

    // Airco
    const lbAc = this.querySelector('#lb-airco');
    const imgAc = this.querySelector('#img-airco');
    if (d.aircoConf) {
      if (lbAc) lbAc.style.display = '';
      q('lv-airco').textContent = d.aircoW > 20 ? this._fmt(d.aircoW) : '—';
      q('lv-airco').style.color = d.aircoW > 20 ? '#00aaff' : 'rgba(180,210,255,.3)';
      q('ls-airco').textContent  = d.aircoW > 20 ? 'Actief' : 'Uit';
      if (imgAc) imgAc.style.opacity = d.aircoW > 50 ? '0.88' : '0.3';
    } else {
      if (lbAc) lbAc.style.display = 'none';
      if (imgAc) imgAc.style.opacity = '0';
    }

    // Pool
    const lbPo = this.querySelector('#lb-pool');
    const imgPo = this.querySelector('#img-pool');
    if (d.poolConf) {
      if (lbPo) lbPo.style.display = '';
      q('lv-pool').textContent = d.poolW > 20 ? this._fmt(d.poolW) : '—';
      q('lv-pool').style.color = d.poolOn ? '#00c8ff' : 'rgba(180,210,255,.3)';
      q('ls-pool').textContent  = d.poolOn ? 'Actief' : 'Standby';
      if (imgPo) imgPo.style.opacity = d.poolOn ? '0.88' : '0.25';
    } else {
      if (lbPo) lbPo.style.display = 'none';
      if (imgPo) imgPo.style.opacity = '0';
    }

    // Lampen
    q('lv-lamps').textContent = d.lampsOn > 0 ? `${d.lampsOn}` : '—';
    q('lv-lamps').style.color = d.lampsOn > 0 ? '#ffc800' : 'rgba(180,210,255,.3)';
    q('ls-lamps').textContent  = d.lampsOn > 0
      ? (d.lampLabels.slice(0,2).join(', ') || `${d.lampsOn} aan`) : 'Uit';
  }

  _updateFlows(d) {
    const active = {
      'fp-sh':   d.solarW > 100,
      'fp-sb':   d.solarW > 100 && d.batW > 10,
      'fp-bh':   d.batW < -10,
      'fp-gh':   d.gridW > 100,
      'fp-hg':   d.gridW < -100,
      'fp-sg':   d.solarW > 200 && d.gridW < -100,
      'fp-bo':   d.boilerConf && d.boilerW > 80,
      'fp-ac':   d.aircoConf  && d.aircoW  > 80,
      'fp-ev':   d.evConf     && d.evW     > 5,
      'fp-pool': d.poolConf   && d.poolOn,
      'fp-lamp': d.lampsOn > 0,
    };
    const colors = {
      'fp-sh':'#ffd700','fp-sb':'#00ff88','fp-bh':'#00ff88',
      'fp-gh':'#ff4444','fp-hg':'#00ff88','fp-sg':'#ffd700',
      'fp-bo':'#ff8800','fp-ac':'#00aaff','fp-ev':'#00aaff',
      'fp-pool':'#00c8ff','fp-lamp':'#ffc800',
    };
    const flMap = {
      'fp-sh':'fl-sh','fp-sb':'fl-sb','fp-bh':'fl-bh',
      'fp-gh':'fl-gh','fp-hg':'fl-hg','fp-sg':'fl-sg',
      'fp-bo':'fl-bo','fp-ac':'fl-ac','fp-ev':'fl-ev',
      'fp-pool':'fl-pool','fp-lamp':'fl-lamp',
    };
    const speeds = {
      'fp-sh': Math.min(280, 80 + d.solarW/6),
      'fp-sb': Math.min(200, 60 + d.batW/5),
      'fp-bh': Math.min(220, 60 + Math.abs(d.batW)/5),
      'fp-gh': Math.min(280, 80 + d.gridW/6),
      'fp-hg': Math.min(240, 70 + Math.abs(d.gridW)/6),
      'fp-sg': Math.min(240, 70 + d.solarW/8),
      'fp-bo': 110, 'fp-ac': 130,
      'fp-ev': Math.min(200, 80 + d.evW/5),
      'fp-pool': 90, 'fp-lamp': 70,
    };

    for (const [fp, fl] of Object.entries(flMap)) {
      const el = this.querySelector(`#${fl}`);
      if (el) el.setAttribute('opacity', active[fp] ? '0.45' : '0.07');
    }

    const sig = JSON.stringify(active);
    if (sig === this._flowSig) return;
    this._flowSig = sig;

    this._particles = [];
    const svg = this.querySelector('svg.iso-svg');
    if (!svg) return;

    for (const [fpId, on] of Object.entries(active)) {
      if (!on) continue;
      const el = svg.querySelector(`#${fpId}`);
      if (!el) continue;
      const n  = fpId === 'fp-sh' ? 7 : fpId === 'fp-lamp' ? 2 : 4;
      const sz = fpId === 'fp-sh' ? 5 : 4;
      for (let i = 0; i < n; i++)
        this._particles.push(new FlowParticle(el, colors[fpId], speeds[fpId], sz));
    }
  }

  _startAnim() {
    if (this._rafId) return;
    const tick = ts => {
      if (!this._lastTs) this._lastTs = ts;
      const dt = Math.min((ts - this._lastTs) / 1000, 0.1);
      this._lastTs = ts;
      this._animTick(dt);
      this._rafId = requestAnimationFrame(tick);
    };
    this._rafId = requestAnimationFrame(tick);
  }

  _stopAnim() {
    if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }
    this._lastTs = null;
  }

  _animTick(dt) {
    const g = this.querySelector('#iso-particles');
    if (!g) return;
    const n = this._particles.length;
    while (g.children.length < n) {
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      g.appendChild(c);
    }
    while (g.children.length > n) g.removeChild(g.lastChild);
    for (let i = 0; i < n; i++) {
      const p  = this._particles[i];
      const pt = p.tick(dt);
      const c  = g.children[i];
      c.setAttribute('cx', pt.x.toFixed(1));
      c.setAttribute('cy', pt.y.toFixed(1));
      c.setAttribute('r',  p.size);
      c.setAttribute('fill', p.color);
      c.setAttribute('filter', 'url(#glow-p)');
      c.setAttribute('opacity', '0.95');
    }
  }
}

if (!customElements.get('cloudems-iso-card'))
  customElements.define('cloudems-iso-card', CloudEMSIsoCard);

// ── GUI Editor ───────────────────────────────────────────────────────────────
class CloudEMSIsoCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }

  _render() {
    const ht = this._config?.house_type || 'modern';
    const cu = this._config?.custom_image_url || '';
    this.innerHTML = `
      <div style="padding:12px;font-family:system-ui;font-size:13px">
        <label style="display:block;margin-bottom:6px;font-weight:600">Huistype</label>
        <select id="ht-sel" style="width:100%;padding:6px;border-radius:6px;background:#1a1a2e;color:#dceeff;border:1px solid rgba(0,160,255,.3);margin-bottom:10px">
          <option value="modern"    ${ht==='modern'   ?'selected':''}>Modern (glas/flat)</option>
          <option value="villa"     ${ht==='villa'    ?'selected':''}>Villa</option>
          <option value="terraced"  ${ht==='terraced' ?'selected':''}>Rijtjeshuis</option>
          <option value="apartment" ${ht==='apartment'?'selected':''}>Appartement</option>
          <option value="farmhouse" ${ht==='farmhouse'?'selected':''}>Boerderij</option>
          <option value="custom"    ${ht==='custom'   ?'selected':''}>Eigen foto (URL)</option>
        </select>
        <div id="custom-row" style="display:${ht==='custom'?'block':'none'}">
          <label style="display:block;margin-bottom:4px;font-weight:600">Foto URL</label>
          <input id="cu-inp" type="text" value="${cu}"
            placeholder="https://... of /local/mijnhuis.jpg"
            style="width:100%;padding:6px;border-radius:6px;background:#1a1a2e;color:#dceeff;border:1px solid rgba(0,160,255,.3);box-sizing:border-box"/>
          <div style="font-size:10px;color:rgba(0,180,255,.5);margin-top:4px">
            CloudEMS AI analyseert de foto automatisch voor elementposities.
          </div>
        </div>
      </div>`;

    this.querySelector('#ht-sel').addEventListener('change', e => {
      const val = e.target.value;
      this.querySelector('#custom-row').style.display = val === 'custom' ? 'block' : 'none';
      this._emit({ house_type: val, custom_image_url: this.querySelector('#cu-inp')?.value || '' });
    });
    this.querySelector('#cu-inp')?.addEventListener('change', e => {
      this._emit({ house_type: 'custom', custom_image_url: e.target.value });
    });
  }

  _emit(patch) {
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config: { ...this._config, ...patch } }, bubbles: true, composed: true
    }));
  }
}

if (!customElements.get('cloudems-iso-card-editor'))
  customElements.define('cloudems-iso-card-editor', CloudEMSIsoCardEditor);
