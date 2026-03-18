// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Klimaat Card  v1.0.0

const KLIM_VERSION = '1.0.0';

const KLIM_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host{display:block;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:#0e1520;border-radius:16px;border:1px solid rgba(255,255,255,0.06);overflow:hidden;font-family:'Syne',sans-serif;}
  .card:hover{border-color:rgba(128,203,196,0.15);box-shadow:0 8px 40px rgba(0,0,0,0.7);}

  /* Header */
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid rgba(255,255,255,0.06);position:relative;overflow:hidden;}
  .hdr::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(128,203,196,0.07) 0%,transparent 60%);pointer-events:none;}
  .hdr-icon{font-size:18px;flex-shrink:0;}
  .hdr-texts{flex:1;}
  .hdr-title{font-size:13px;font-weight:700;color:#f1f5f9;letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:11px;color:#6b7280;margin-top:2px;}
  .mod-off{padding:10px 18px;background:rgba(251,146,60,0.08);border-bottom:1px solid rgba(251,146,60,0.2);font-size:11px;font-weight:600;color:#fb923c;}

  /* Boiler strip */
  .boiler-strip{display:flex;align-items:center;gap:10px;padding:10px 18px;border-bottom:1px solid rgba(255,255,255,0.06);}
  .boiler-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
  .boiler-dot.on{background:#f87171;box-shadow:0 0 6px rgba(248,113,113,0.5);}
  .boiler-dot.off{background:#374151;}
  .boiler-text{font-size:12px;color:#9ca3af;}
  .boiler-text b{color:#f1f5f9;}

  /* Zone cards */
  .zones{padding:10px 18px 4px;}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#374151;margin-bottom:8px;}
  .zone-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px 14px;margin-bottom:8px;}
  .zone-card.heating{border-color:rgba(248,113,113,0.25);background:rgba(248,113,113,0.04);}
  .zone-card.cooling{border-color:rgba(125,211,252,0.2);background:rgba(125,211,252,0.03);}
  .zone-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
  .zone-name{font-size:13px;font-weight:700;color:#e2e8f0;}
  .zone-chips{display:flex;gap:5px;flex-wrap:wrap;}
  .chip{font-family:'JetBrains Mono',monospace;font-size:9px;padding:2px 7px;border-radius:10px;font-weight:600;letter-spacing:.04em;}
  .chip-preset-comfort{background:rgba(74,222,128,0.12);color:#4ade80;border:1px solid rgba(74,222,128,0.2);}
  .chip-preset-eco{background:rgba(125,211,252,0.10);color:#7dd3fc;border:1px solid rgba(125,211,252,0.2);}
  .chip-preset-boost{background:rgba(248,113,113,0.12);color:#f87171;border:1px solid rgba(248,113,113,0.25);}
  .chip-preset-sleep{background:rgba(167,139,250,0.12);color:#a78bfa;border:1px solid rgba(167,139,250,0.2);}
  .chip-preset-away{background:rgba(107,114,128,0.15);color:#9ca3af;border:1px solid rgba(107,114,128,0.2);}
  .chip-preset-other{background:rgba(255,255,255,0.06);color:#6b7280;border:1px solid rgba(255,255,255,0.1);}
  .chip-demand{background:rgba(248,113,113,0.12);color:#f87171;border:1px solid rgba(248,113,113,0.25);animation:pulse 2s infinite;}
  .chip-cool{background:rgba(125,211,252,0.12);color:#7dd3fc;border:1px solid rgba(125,211,252,0.2);animation:pulse 2s infinite;}
  .chip-window{background:rgba(253,224,71,0.10);color:#fde047;border:1px solid rgba(253,224,71,0.2);}
  .zone-temps{display:flex;gap:16px;margin-bottom:6px;}
  .temp-item{display:flex;flex-direction:column;gap:1px;}
  .temp-val{font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:700;color:#f1f5f9;}
  .temp-val.heating{color:#fca5a5;}
  .temp-val.cooling{color:#7dd3fc;}
  .temp-lbl{font-size:9px;color:#4b5563;text-transform:uppercase;letter-spacing:.06em;}
  .zone-reason{font-size:10px;color:#6b7280;font-style:italic;margin-top:2px;}
  .zone-stats{display:flex;gap:12px;margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05);}
  .zone-stat{font-size:10px;color:#4b5563;}
  .zone-stat span{color:#9ca3af;}

  /* Devices section */
  .devices-section{padding:10px 18px 4px;border-top:1px solid rgba(255,255,255,0.06);}
  .dev-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
  .dev-row:last-child{border-bottom:none;}
  .dev-name{flex:1;font-size:12px;color:#9ca3af;}
  .dev-type{font-size:9px;color:#4b5563;text-transform:uppercase;}
  .dev-temp{font-family:'JetBrains Mono',monospace;font-size:11px;color:#6b7280;}
  .dev-managed{font-size:9px;padding:2px 6px;border-radius:6px;background:rgba(74,222,128,0.08);color:#4ade80;border:1px solid rgba(74,222,128,0.15);}
  .dev-readonly{font-size:9px;padding:2px 6px;border-radius:6px;background:rgba(255,255,255,0.04);color:#4b5563;border:1px solid rgba(255,255,255,0.07);}

  /* Empty */
  .empty{padding:20px 18px;text-align:center;color:#374151;font-size:12px;}

  /* Heatmap */
  .heatmap-section{padding:10px 18px 12px;border-top:1px solid rgba(255,255,255,0.06);}
  .hm-table{width:100%;border-collapse:collapse;font-size:9px;}
  .hm-table th{color:#4b5563;padding:2px 3px;text-align:center;font-weight:600;}
  .hm-table td{padding:2px 3px;text-align:center;font-size:10px;}

  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
`;

const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

const PRESET_ICON = {comfort:'🏠',eco:'🌿',boost:'🔥',sleep:'😴',away:'🚗',solar:'☀️',houtfire:'🪵',eco_window:'🪟'};
const PRESET_CLS  = {comfort:'chip-preset-comfort',eco:'chip-preset-eco',boost:'chip-preset-boost',sleep:'chip-preset-sleep',away:'chip-preset-away'};

class CloudEMSKlimaatCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); this._prev=''; }

  setConfig(c){ this._cfg = {title: c.title||'Klimaatbeheer', ...c}; }

  set hass(h){
    this._hass = h;
    const sw = h.states['switch.cloudems_module_klimaat'];
    // Collect zone sensor states
    const zoneSensors = Object.values(h.states).filter(s =>
      s.entity_id.startsWith('sensor.cloudems_zone_') &&
      !s.entity_id.includes('kosten') &&
      s.state !== 'unavailable' && s.state !== 'unknown'
    );
    const boilerSt = h.states['sensor.cloudems_zone_klimaat_kosten_vandaag'];
    const sig = [sw?.state, zoneSensors.map(s=>s.state+JSON.stringify(s.attributes?.preset||'')).join('|'), boilerSt?.attributes?.boiler?.boiler_on].join('|');
    if(sig !== this._prev){ this._prev = sig; this._render(); }
  }

  _render(){
    const sh = this.shadowRoot; if(!sh) return;
    const h = this._hass, c = this._cfg||{};
    if(!h){ sh.innerHTML=`<style>${KLIM_CSS}</style><div class="card"><div class="empty">🌡️</div></div>`; return; }

    const sw    = h.states['switch.cloudems_module_klimaat'];
    const modOn = sw?.state === 'on';

    // Zone sensors (dynamic per configured zone)
    const zoneSensors = Object.values(h.states).filter(s =>
      s.entity_id.startsWith('sensor.cloudems_zone_') &&
      !s.entity_id.includes('kosten') &&
      s.state !== 'unavailable' && s.state !== 'unknown'
    );

    // Boiler status from costs sensor attributes
    const boilerAttr = h.states['sensor.cloudems_zone_klimaat_kosten_vandaag']?.attributes?.boiler || {};
    const boilerOn   = !!boilerAttr.boiler_on;
    const boilerZones = boilerAttr.zones_calling || 0;
    const boilerReason= boilerAttr.reason || '';

    // Climate entities from epex status for "found devices" section
    const epexDevices = h.states['sensor.cloudems_climate_epex_status']?.attributes?.devices || [];

    // ── Boiler strip ─────────────────────────────────────────────────────
    const boilerHtml = `<div class="boiler-strip">
      <div class="boiler-dot ${boilerOn?'on':'off'}"></div>
      <span class="boiler-text">${boilerOn
        ? `<b>🔥 CV-Brander AAN</b> — ${boilerZones} zone${boilerZones!==1?'s':''} vragen warmte`
        : `<b>CV-Brander uit</b>${boilerReason?' — '+esc(boilerReason):''}`}
      </span>
    </div>`;

    // ── Zone cards ────────────────────────────────────────────────────────
    let zonesHtml = '';
    if(zoneSensors.length === 0){
      zonesHtml = `<div class="zones"><div class="empty">Geen actieve zones geconfigureerd.<br>Activeer apparaten via CloudEMS wizard → Klimaatbeheer.</div></div>`;
    } else {
      const zoneCards = zoneSensors.map(s => {
        const a = s.attributes || {};
        const cur     = parseFloat(s.state) || null;
        const doel    = a.doeltemperatuur;
        const preset  = a.preset || 'comfort';
        const presetNl= a.preset_nl || preset;
        const warmte  = !!a.warmtevraag;
        const koeling = !!a.koelingsvraag;
        const raam    = !!a.raam_open;
        const reden   = a.reden || '';
        const bron    = a.beste_bron || '';
        const kostenVandaag = a.kosten_vandaag;
        const voorstook = a.voorstook_min || 0;
        const zoneName = a.area || s.entity_id.replace('sensor.cloudems_zone_','').replace(/_/g,' ');

        const cardCls = warmte ? 'zone-card heating' : koeling ? 'zone-card cooling' : 'zone-card';
        const presetCls = PRESET_CLS[preset] || 'chip-preset-other';
        const presetIcon = PRESET_ICON[preset] || '🌡️';
        const curCls = warmte ? 'temp-val heating' : koeling ? 'temp-val cooling' : 'temp-val';

        const chips = [
          `<span class="chip ${presetCls}">${presetIcon} ${esc(presetNl)}</span>`,
          warmte ? `<span class="chip chip-demand">🔥 Warmte</span>` : '',
          koeling ? `<span class="chip chip-cool">❄️ Koeling</span>` : '',
          raam ? `<span class="chip chip-window">🪟 Raam open</span>` : '',
        ].filter(Boolean).join('');

        return `<div class="${cardCls}">
          <div class="zone-header">
            <span class="zone-name">${esc(zoneName)}</span>
            <div class="zone-chips">${chips}</div>
          </div>
          <div class="zone-temps">
            <div class="temp-item">
              <span class="${curCls}">${cur!=null?cur.toFixed(1)+'°':'—'}</span>
              <span class="temp-lbl">Huidig</span>
            </div>
            <div class="temp-item">
              <span class="temp-val">${doel!=null?doel.toFixed(1)+'°':'—'}</span>
              <span class="temp-lbl">Doel</span>
            </div>
            ${voorstook>0?`<div class="temp-item"><span class="temp-val" style="color:#fb923c">${voorstook}m</span><span class="temp-lbl">Voorstook</span></div>`:''}
          </div>
          ${reden?`<div class="zone-reason">${esc(reden.length>80?reden.slice(0,80)+'…':reden)}</div>`:''}
          <div class="zone-stats">
            ${bron?`<span class="zone-stat">Bron: <span>${esc(bron)}</span></span>`:''}
            ${kostenVandaag!=null?`<span class="zone-stat">Kosten: <span>€${parseFloat(kostenVandaag).toFixed(2)}</span></span>`:''}
          </div>
        </div>`;
      }).join('');
      zonesHtml = `<div class="zones"><div class="sec-title">🌡️ Zones (${zoneSensors.length})</div>${zoneCards}</div>`;
    }

    // ── Gevonden apparaten (climate entities via NILM/scan) ───────────────
    // Scan alle climate.* entities
    const allClimate = Object.values(h.states).filter(s =>
      s.entity_id.startsWith('climate.') &&
      s.state !== 'unavailable' && s.state !== 'unknown'
    ).slice(0, 12);

    let devHtml = '';
    if(allClimate.length > 0){
      const managedIds = new Set(zoneSensors.flatMap(s => s.attributes?.entiteiten || []));
      const rows = allClimate.map(s => {
        const a = s.attributes || {};
        const cur = a.current_temperature;
        const tgt = a.temperature;
        const name = a.friendly_name || s.entity_id.split('.')[1].replace(/_/g,' ');
        const managed = managedIds.has(s.entity_id);
        const typeGuess = s.entity_id.includes('trv')||s.entity_id.includes('radiator')?'TRV':
                          s.entity_id.includes('airco')||s.entity_id.includes('aircon')?'Airco':'Thermostaat';
        return `<div class="dev-row">
          <div style="flex:1">
            <div class="dev-name">${esc(name)}</div>
            <div class="dev-type">${typeGuess}</div>
          </div>
          <span class="dev-temp">${cur!=null?cur.toFixed(1)+'°':''} ${tgt!=null?'→ '+tgt.toFixed(1)+'°':''}</span>
          <span class="${managed?'dev-managed':'dev-readonly'}">${managed?'✅ beheerd':'👁 lees'}</span>
        </div>`;
      }).join('');
      devHtml = `<div class="devices-section">
        <div class="sec-title" style="margin-bottom:6px">🔍 Klimaatapparaten (${allClimate.length} gevonden)</div>
        ${rows}
        <div style="font-size:10px;color:#4b5563;margin-top:6px;font-style:italic">Activeer apparaten via CloudEMS wizard → Klimaatbeheer om ze te laten aansturen.</div>
      </div>`;
    }

    // ── Subheader ─────────────────────────────────────────────────────────
    const activeCount = zoneSensors.filter(s => !!s.attributes?.warmtevraag || !!s.attributes?.koelingsvraag).length;
    const sub = zoneSensors.length === 0 ? 'Geen actieve zones — configureer via wizard'
      : `${zoneSensors.length} zone${zoneSensors.length!==1?'s':''} · ${boilerOn?'brander aan':'brander uit'}${activeCount>0?' · '+activeCount+' vragen warmte/koeling':''}`;

    sh.innerHTML = `<style>${KLIM_CSS}</style>
    <div class="card">
      ${!modOn ? `<div class="mod-off">⚠️ Klimaat module staat uit — schakel in via Configuratie.</div>` : ''}
      <div class="hdr">
        <span class="hdr-icon">🌡️</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub">${esc(sub)}</div>
        </div>
      </div>
      ${boilerHtml}
      ${zonesHtml}
      ${devHtml}
    </div>`;
  }

  getCardSize(){ return 6; }
  static getConfigElement(){ return document.createElement('cloudems-klimaat-card-editor'); }
  static getStubConfig(){ return {title:'Klimaatbeheer'}; }
}

class CloudEMSKlimaatCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>.wrap{padding:8px;}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06);}.row:last-child{border-bottom:none;}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}input[type=text]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px;}</style>
<div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${esc(cfg.title||'Klimaatbeheer')}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change', e => {
      this._cfg={...this._cfg, title:e.target.value}; this._fire();
    });
  }
}

customElements.define('cloudems-klimaat-card', CloudEMSKlimaatCard);
customElements.define('cloudems-klimaat-card-editor', CloudEMSKlimaatCardEditor);
window.customCards = window.customCards||[];
window.customCards.push({type:'cloudems-klimaat-card', name:'CloudEMS Klimaat Card', description:'Zones, CV-ketel, thermostaten en klimaatbeheer', preview:true});
console.info('%c CLOUDEMS-KLIMAAT-CARD %c v'+KLIM_VERSION+' ','background:#80cbc4;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#80cbc4;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
