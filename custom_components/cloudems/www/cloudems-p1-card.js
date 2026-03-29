// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS P1 Card  v5.4.96

const P1_VERSION = "5.4.96";
const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function fmt(v, dec=0, unit="") {
  if (v == null || isNaN(v)) return "—";
  return parseFloat(v).toFixed(dec) + (unit ? " "+unit : "");
}
function fmtW(w) {
  if (w == null) return "—";
  const abs = Math.abs(w);
  return abs >= 1000 ? (w/1000).toFixed(2)+" kW" : Math.round(w)+" W";
}
function phaseColor(w) {
  // netto fase: negatief=export(groen), positief=import(blauw), hoog=rood
  if (w == null) return "var(--a-muted)";
  const n = parseFloat(w);
  if (n < -50) return "var(--a-green)";
  if (n > 2000) return "var(--a-red)";
  if (n > 200)  return "var(--a-blue)";
  return "var(--a-text)";
}

const CSS = `
  :host {
    --a-bg:var(--ha-card-background,var(--card-background-color,#1c1c1c));
    --a-surface:rgba(255,255,255,.04);--a-border:rgba(255,255,255,.08);
    --a-text:var(--primary-text-color,#e8eaed);--a-muted:var(--secondary-text-color,#9aa0a6);
    --a-green:#1D9E75;--a-amber:#BA7517;--a-blue:#378ADD;--a-red:#e55;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--a-bg);border-radius:12px;overflow:hidden;font-family:var(--primary-font-family,sans-serif);}
  .hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 12px;border-bottom:0.5px solid var(--a-border);}
  .hdr-title{font-size:13px;font-weight:500;color:var(--a-muted);}
  .hdr-badge{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600;}
  .import{background:rgba(55,138,221,.18);color:#60a5fa;}
  .export{background:rgba(29,158,117,.18);color:#4ade80;}

  /* Netto balans groot */
  .balance{display:flex;align-items:center;justify-content:center;gap:16px;padding:16px;border-bottom:0.5px solid var(--a-border);}
  .bal-val{font-size:32px;font-weight:700;}
  .bal-sub{font-size:12px;color:var(--a-muted);margin-top:2px;text-align:center;}
  .bal-arrow{font-size:24px;}

  /* Mini balken voor import/export */
  .net-bar{display:flex;gap:8px;padding:0 16px 12px;border-bottom:0.5px solid var(--a-border);}
  .nb{flex:1;background:var(--a-surface);border-radius:8px;padding:8px 10px;}
  .nb-lbl{font-size:10px;color:var(--a-muted);text-transform:uppercase;letter-spacing:.04em;}
  .nb-val{font-size:18px;font-weight:700;margin-top:2px;}

  /* Fases grid */
  .phases{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;background:var(--a-border);border-top:0.5px solid var(--a-border);}
  .phase{background:var(--a-bg);padding:10px 12px;}
  .ph-label{font-size:11px;font-weight:700;color:var(--a-muted);margin-bottom:6px;text-transform:uppercase;}
  .ph-row{display:flex;justify-content:space-between;align-items:center;padding:2px 0;font-size:12px;}
  .ph-key{color:var(--a-muted);}
  .ph-val{font-weight:500;}
  .ph-power{font-size:15px;font-weight:700;margin-bottom:4px;}

  /* Onbalans */
  .imbalance{display:flex;align-items:center;gap:8px;padding:8px 16px;border-top:0.5px solid var(--a-border);font-size:12px;}
  .imb-ok{color:var(--a-green);}
  .imb-warn{color:var(--a-amber);}
  .imb-alert{color:var(--a-red);}

  /* Tariefinfo */
  .tariff{display:flex;gap:8px;padding:10px 16px;border-top:0.5px solid var(--a-border);font-size:12px;}
  .tf{flex:1;background:var(--a-surface);border-radius:6px;padding:6px 10px;}
  .tf-lbl{color:var(--a-muted);font-size:10px;text-transform:uppercase;}
  .tf-val{font-weight:600;color:var(--a-text);margin-top:2px;}

  /* Spanning */
  .voltages{display:flex;gap:1px;background:var(--a-border);border-top:0.5px solid var(--a-border);}
  .vl{flex:1;background:var(--a-bg);padding:8px 10px;text-align:center;}
  .vl-lbl{font-size:10px;color:var(--a-muted);}
  .vl-val{font-size:14px;font-weight:600;color:var(--a-text);margin-top:2px;}

  .empty{padding:32px;text-align:center;color:var(--a-muted);font-size:13px;}
`;

class CloudemsP1Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this._prev = "";
  }

  setConfig(c) { this._cfg = {title:"P1 Netbalans",...c}; this._render(); }

  set hass(h) {
    this._hass = h;
    const st  = h.states["sensor.cloudems_p1_power"];
    const pr  = h.states["sensor.cloudems_price_current_hour"];
    const key = JSON.stringify([
      st?.attributes?.p1_data,
      st?.attributes?.phase_balance,
      pr?.state,
    ]);
    if (key !== this._prev) { this._prev = key; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot;
    const h = this._hass, c = this._cfg ?? {};
    if (!h) { sh.innerHTML=`<style>${CSS}</style><div class="card"><div class="empty">Laden…</div></div>`; return; }

    const st    = h.states["sensor.cloudems_p1_power"];
    const p1    = st?.attributes ?? {};
    const bal   = h.states["sensor.cloudems_grid_phase_imbalance"]?.attributes ?? {};
    const pr    = h.states["sensor.cloudems_price_current_hour"];
    const price = pr ? parseFloat(pr.state) : null;

    if (!st || (!p1.net_power_w && !p1.power_import_w && !p1.power_export_w && !p1.source)) {
      const src = p1.source || '';
      const msg = src === 'ha_entity'
        ? 'P1 data actief via DSMR/HomeWizard integratie. Direct TCP niet geconfigureerd — dat is geen probleem.'
        : src && src !== 'none'
          ? `P1 bron: ${src} — data wordt geladen...`
          : 'Geen P1 data beschikbaar.<br>Koppel een P1/DSMR slimme meter via CloudEMS configuratie.';
      sh.innerHTML = `<style>${CSS}</style><div class="card"><div class="empty">${msg}</div></div>`;
      return;
    }

    const net     = parseFloat(p1.net_power_w   ?? 0);
    const imp     = parseFloat(p1.power_import_w ?? 0);
    const exp     = parseFloat(p1.power_export_w ?? 0);
    const isExport = net < -20;
    const isImport = net > 20;

    // Per fase: netto = import - export
    // Netto fase-vermogen uit sensor.cloudems_status attributen (berekend in backend)
    const _st_phases = h.states['sensor.cloudems_status']?.attributes?.phases || {};
    const l1net = _st_phases['L1']?.power_w ?? null;
    const l2net = _st_phases['L2']?.power_w ?? null;
    const l3net = _st_phases['L3']?.power_w ?? null;
    const hasPhases = l1net != null;
    const hasVoltage = parseFloat(p1.voltage_l1 ?? 0) > 0;

    // Onbalans
    const imbalA = parseFloat(bal.imbalance_a ?? 0);
    const imbalClass = imbalA > 16 ? "imb-alert" : imbalA > 8 ? "imb-warn" : "imb-ok";
    const imbalIcon  = imbalA > 16 ? "⚠️" : imbalA > 8 ? "⚡" : "✅";

    // Tarief
    const tariff = p1.tariff;
    const tariffLabel = tariff === 2 ? "Piek (T2)" : tariff === 1 ? "Dal (T1)" : "—";

    // Kosten huidig vermogen
    const costNow = price != null && imp > 0 ? (imp / 1000 * price).toFixed(4) : null;
    const earnNow = price != null && exp > 0 ? (exp / 1000 * price).toFixed(4) : null;

    const phasesHtml = hasPhases ? `
      <div class="phases">
        ${["L1","L2","L3"].map((l, i) => {
          const lnet = [l1net, l2net, l3net][i];
          const limp = [p1.power_l1_import_w, p1.power_l2_import_w, p1.power_l3_import_w][i] ?? 0;
          const lexp = [p1.power_l1_export_w, p1.power_l2_export_w, p1.power_l3_export_w][i] ?? 0;
          const cur  = [p1.current_l1, p1.current_l2, p1.current_l3][i];
          return `<div class="phase">
            <div class="ph-label">${l}</div>
            <div class="ph-power" style="color:${phaseColor(lnet)}">${fmtW(lnet)}</div>
            ${limp > 0 ? `<div class="ph-row"><span class="ph-key">Import</span><span class="ph-val">${fmtW(limp)}</span></div>` : ""}
            ${lexp > 0 ? `<div class="ph-row"><span class="ph-key">Export</span><span class="ph-val" style="color:var(--a-green)">${fmtW(lexp)}</span></div>` : ""}
            ${cur != null ? `<div class="ph-row"><span class="ph-key">Stroom</span><span class="ph-val">${fmt(cur,1,"A")}</span></div>` : ""}
          </div>`;
        }).join("")}
      </div>` : "";

    const voltageHtml = hasVoltage ? `
      <div class="voltages">
        ${["L1","L2","L3"].map((l,i) => {
          const v = [p1.voltage_l1, p1.voltage_l2, p1.voltage_l3][i];
          const col = v && (v < 207 || v > 253) ? "var(--a-amber)" : "var(--a-text)";
          return `<div class="vl">
            <div class="vl-lbl">${l} spanning</div>
            <div class="vl-val" style="color:${col}">${fmt(v,1,"V")}</div>
          </div>`;
        }).join("")}
      </div>` : "";

    sh.innerHTML = `<style>${CSS}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-title">${esc(c.title)}</span>
        <span class="hdr-badge ${isExport?"export":isImport?"import":""}">${
          isExport ? "⬆ Exporteren" : isImport ? "⬇ Importeren" : "⇄ Neutraal"
        }</span>
      </div>

      <div class="balance">
        <div>
          <div class="bal-val" style="color:${isExport?"var(--a-green)":isImport?"var(--a-blue)":"var(--a-text)"}">${fmtW(Math.abs(net))}</div>
          <div class="bal-sub">${isExport?"Netto export":"Netto import"}</div>
        </div>
      </div>

      <div class="net-bar">
        <div class="nb">
          <div class="nb-lbl">Import</div>
          <div class="nb-val" style="color:${imp>0?"var(--a-blue)":"var(--a-muted)"}">${fmtW(imp)}</div>
          ${costNow ? `<div style="font-size:10px;color:var(--a-muted)">€${costNow}/s·€</div>` : ""}
        </div>
        <div class="nb">
          <div class="nb-lbl">Export</div>
          <div class="nb-val" style="color:${exp>0?"var(--a-green)":"var(--a-muted)"}">${fmtW(exp)}</div>
          ${earnNow ? `<div style="font-size:10px;color:var(--a-muted)">€${earnNow}/h opbrengst</div>` : ""}
        </div>
        <div class="nb">
          <div class="nb-lbl">Prijs nu</div>
          <div class="nb-val" style="color:${price!=null&&price<0?"var(--a-green)":price!=null&&price>0.25?"var(--a-amber)":"var(--a-text)"}">${price!=null?(price*100).toFixed(1)+" ct":"—"}</div>
        </div>
      </div>

      ${phasesHtml}
      ${voltageHtml}

      <div class="imbalance">
        <span>${imbalIcon}</span>
        <span class="${imbalClass}">Fase-onbalans: ${fmt(imbalA,1,"A")}</span>
        ${imbalA > 8 ? `<span style="color:var(--a-muted)"> — overweeg lasten te herverdelen</span>` : ""}
      </div>

      <div class="tariff">
        <div class="tf">
          <div class="tf-lbl">Tarief</div>
          <div class="tf-val">${esc(tariffLabel)}</div>
        </div>
        <div class="tf">
          <div class="tf-lbl">Import totaal</div>
          <div class="tf-val">${fmt(p1.energy_import_kwh,1,"kWh")}</div>
        </div>
        <div class="tf">
          <div class="tf-lbl">Export totaal</div>
          <div class="tf-val">${fmt(p1.energy_export_kwh,1,"kWh")}</div>
        </div>
      </div>
    </div>`;
  }

  static getConfigElement() { return document.createElement("cloudems-p1-card-editor"); }
  static getStubConfig()    { return {title:"P1 Netbalans"}; }
  getCardSize() { return 5; }
}

class CloudemsP1CardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:"open"}); this._cfg={}; }
  setConfig(c)  { this._cfg={...c}; this._render(); }
  set hass(h)   { this._hass=h; }
  _fire() { this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render() {
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>.wrap{padding:8px;}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input{background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:180px;}</style>
<div class="wrap">
  <div class="row"><label class="lbl">Titel</label><input name="title" value="${esc(cfg.title??"P1 Netbalans")}"></div>
</div>`;
    this.shadowRoot.querySelector("input[name=title]")?.addEventListener("change",e=>{
      this._cfg={...this._cfg,title:e.target.value}; this._fire();
    });
  }
}

if (!customElements.get('cloudems-p1-card-editor')) customElements.define("cloudems-p1-card-editor", CloudemsP1CardEditor);
if (!customElements.get('cloudems-p1-card')) customElements.define("cloudems-p1-card", CloudemsP1Card);
window.customCards=window.customCards??[];
window.customCards.push({type:"cloudems-p1-card",name:"CloudEMS P1 Card",description:"P1 netbalans — fasevermogen, spanning, onbalans"});
console.info(`%c CLOUDEMS-P1-CARD %c v${P1_VERSION} `,"background:#1D9E75;color:#fff;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0e1520;color:#1D9E75;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
