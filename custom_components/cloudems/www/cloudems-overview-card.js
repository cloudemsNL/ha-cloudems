// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Control Card  v2.0.0  — alles-in-één interactieve beheerkaart

const CTRL_VER = "2.0.0";

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host{
    --bg:#0e1520;--surf:#141c2b;--surf2:#1a2235;--bdr:rgba(255,255,255,0.06);
    --grn:#4ade80;--amb:#fb923c;--red:#f87171;--sky:#7dd3fc;
    --ind:#818cf8;--ylw:#facc15;--pur:#c084fc;
    --mut:#374151;--sub:#6b7280;--txt:#f1f5f9;
    --mono:'JetBrains Mono',monospace;--sans:'Syne',sans-serif;--r:14px;
    display:block;width:100%;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--bg);border-radius:var(--r);border:1px solid var(--bdr);overflow:hidden;font-family:var(--sans);width:100%;box-sizing:border-box;}

  /* NAV — zelfde stijl als solar card */
  .nav{display:flex;gap:6px;padding:10px 12px 0;background:rgba(0,0,0,.3);border-bottom:2px solid rgba(255,255,255,.06);overflow-x:auto;scrollbar-width:none;}
  .nav::-webkit-scrollbar{display:none;}
  .nav-btn{flex:none;padding:9px 10px 10px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;
    color:var(--sub);background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);
    border-bottom:3px solid transparent;border-radius:8px 8px 0 0;cursor:pointer;
    transition:all .15s;white-space:nowrap;font-family:var(--sans);}
  .nav-btn:hover{color:var(--txt);background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.15);}
  .nav-btn.active{color:var(--ind);background:rgba(129,140,248,.1);border-color:rgba(129,140,248,.25);border-bottom-color:var(--ind);font-size:12px;}

  /* HEADER */
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid var(--bdr);
    background:linear-gradient(135deg,rgba(129,140,248,.1),transparent 60%);}
  .hdr-logo{width:36px;height:36px;background:linear-gradient(135deg,var(--ind),var(--sky));border-radius:10px;
    display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
  .hdr-info{flex:1;}
  .hdr-title{font-size:14px;font-weight:800;color:var(--txt);}
  .hdr-sub{font-size:10px;color:var(--sub);margin-top:1px;font-family:var(--mono);}
  .hdr-badge{font-family:var(--mono);font-size:9px;padding:2px 8px;border-radius:8px;
    background:rgba(129,140,248,.12);color:var(--ind);border:1px solid rgba(129,140,248,.2);}

  /* ENERGY STRIP */
  .estrip{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--bdr);}
  .ecell{padding:10px 12px;border-right:1px solid var(--bdr);display:flex;flex-direction:column;gap:2px;}
  .ecell:last-child{border-right:none;}
  .el{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);}
  /* GAS STRIP */
  .gasstrip{display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid var(--bdr);background:rgba(251,146,60,.04);}
  .gasstrip .gs-icon{font-size:16px;line-height:1;}
  .gasstrip .gs-rate{font-size:18px;font-weight:700;color:var(--amb);font-family:var(--mono);}
  .gasstrip .gs-unit{font-size:10px;color:var(--mut);margin-left:2px;}
  .gasstrip .gs-dag{font-size:10px;color:var(--sub);margin-left:8px;}
  .gasstrip .gs-bar-wrap{flex:1;height:4px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;min-width:40px;}
  .gasstrip .gs-bar-fill{height:100%;border-radius:2px;background:var(--amb);transition:width .4s;}
  .gasstrip .gs-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);}
  .ev{font-family:var(--mono);font-size:16px;font-weight:700;}
  .eu{font-family:var(--mono);font-size:9px;color:var(--sub);}

  /* SECTION */
  .sec{padding:12px 16px;border-bottom:1px solid var(--bdr);}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);margin-bottom:8px;}

  /* FLOW BAR */
  .flow-row{display:flex;align-items:center;gap:6px;margin-bottom:6px;}
  .flow-node{display:flex;flex-direction:column;align-items:center;gap:3px;min-width:44px;}
  .ficon{width:32px;height:32px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;}
  .flbl{font-size:8px;text-transform:uppercase;letter-spacing:.08em;color:var(--sub);font-weight:600;}
  .fpw{font-family:var(--mono);font-size:10px;font-weight:700;}
  .fline{flex:1;height:3px;border-radius:2px;background:rgba(255,255,255,.06);overflow:hidden;}
  .fline-fill{height:100%;border-radius:2px;transition:width .8s ease;}

  /* MODULE GRID */
  .mod-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:5px;}
  .mod{background:var(--surf);border-radius:9px;border:1px solid var(--bdr);padding:9px 10px;
    display:flex;flex-direction:column;gap:3px;cursor:pointer;transition:all .15s;user-select:none;}
  .mod:hover{transform:translateY(-1px);border-color:rgba(255,255,255,.12);}
  .mod:active{transform:scale(.97);}
  .mod.on{border-color:rgba(74,222,128,.2);}
  .mod.off{opacity:.5;}
  .mod-top{display:flex;align-items:center;gap:6px;}
  .micon{font-size:13px;flex-shrink:0;}
  .mname{font-size:10px;font-weight:700;color:var(--txt);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .mbadge{font-family:var(--mono);font-size:7px;padding:2px 5px;border-radius:6px;font-weight:700;flex-shrink:0;}
  .mbadge.on{background:rgba(74,222,128,.12);color:var(--grn);border:1px solid rgba(74,222,128,.2);}
  .mbadge.off{background:rgba(248,113,113,.08);color:var(--red);border:1px solid rgba(248,113,113,.15);}
  .mdetail{font-family:var(--mono);font-size:8px;color:var(--sub);padding-left:19px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

  /* SHUTTER ROWS */
  .sh-row{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.03);}
  .sh-row:last-child{border-bottom:none;}
  .sh-name{font-size:11px;font-weight:600;color:var(--txt);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .sh-pos{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--sky);width:32px;text-align:right;}
  .sh-bar{width:60px;height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;flex-shrink:0;}
  .sh-fill{height:100%;border-radius:2px;background:var(--sky);}
  .sh-btns{display:flex;gap:4px;flex-shrink:0;}
  .btn-sm{padding:4px 8px;border-radius:6px;font-size:9px;font-weight:700;cursor:pointer;border:1px solid;
    font-family:var(--mono);transition:all .15s;background:transparent;}
  .btn-sm:hover{filter:brightness(1.2);}
  .btn-sm:active{transform:scale(.95);}
  .btn-up{color:var(--grn);border-color:rgba(74,222,128,.3);}
  .btn-up:hover{background:rgba(74,222,128,.1);}
  .btn-dn{color:var(--sky);border-color:rgba(125,211,252,.3);}
  .btn-dn:hover{background:rgba(125,211,252,.1);}
  .btn-stop{color:var(--amb);border-color:rgba(251,146,60,.3);}
  .btn-stop:hover{background:rgba(251,146,60,.1);}
  .btn-auto{color:var(--ind);border-color:rgba(129,140,248,.3);font-size:8px;}
  .btn-auto:hover{background:rgba(129,140,248,.1);}
  .btn-auto.active{background:rgba(129,140,248,.15);}

  /* BOILER ROWS */
  .bl-row{background:var(--surf);border-radius:10px;border:1px solid var(--bdr);padding:10px 12px;margin-bottom:6px;}
  .bl-row:last-child{margin-bottom:0;}
  .bl-top{display:flex;align-items:center;gap:8px;margin-bottom:8px;}
  .bl-name{font-size:12px;font-weight:700;color:var(--txt);flex:1;}
  .bl-temp{font-family:var(--mono);font-size:16px;font-weight:700;color:var(--sky);}
  .bl-modes{display:flex;gap:4px;flex-wrap:wrap;}
  .mode-btn{padding:4px 10px;border-radius:7px;font-size:9px;font-weight:700;cursor:pointer;
    border:1px solid var(--bdr);background:var(--surf2);color:var(--sub);font-family:var(--mono);transition:all .15s;}
  .mode-btn:hover{border-color:rgba(255,255,255,.2);color:var(--txt);}
  .mode-btn:active{transform:scale(.95);}
  .mode-btn.active{background:rgba(129,140,248,.15);border-color:rgba(129,140,248,.4);color:var(--ind);}
  .sp-row{display:flex;align-items:center;gap:8px;margin-top:8px;}
  .sp-lbl{font-size:9px;color:var(--sub);flex-shrink:0;}
  .sp-input{flex:1;background:var(--surf2);border:1px solid var(--bdr);border-radius:6px;
    color:var(--txt);font-family:var(--mono);font-size:12px;padding:4px 8px;text-align:center;}
  .sp-input:focus{outline:none;border-color:rgba(129,140,248,.4);}
  .btn-set{padding:4px 12px;border-radius:6px;font-size:9px;font-weight:700;cursor:pointer;
    background:rgba(129,140,248,.15);border:1px solid rgba(129,140,248,.3);color:var(--ind);font-family:var(--mono);}
  .btn-set:hover{background:rgba(129,140,248,.25);}

  /* BATTERY */
  .bat-row{display:flex;align-items:center;gap:12px;}
  .bat-arc-wrap{position:relative;flex-shrink:0;}
  .bat-info{flex:1;}
  .bat-soc{font-family:var(--mono);font-size:28px;font-weight:700;}
  .bat-sub{font-size:10px;color:var(--sub);margin-top:2px;}
  .bat-dec{font-size:10px;color:var(--sub);margin-top:6px;font-style:italic;}
  .bat-btns{display:flex;gap:6px;margin-top:8px;}
  .bat-btn{flex:1;padding:7px;border-radius:8px;font-size:10px;font-weight:700;cursor:pointer;
    border:1px solid;text-align:center;font-family:var(--sans);transition:all .15s;}
  .bat-btn:hover{filter:brightness(1.15);}
  .bat-btn:active{transform:scale(.97);}

  /* NILM */
  .nilm-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.03);}
  .nilm-row:last-child{border-bottom:none;}
  .nilm-name{font-size:11px;color:var(--txt);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .nilm-bar-wrap{width:60px;height:3px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;flex-shrink:0;}
  .nilm-bar{height:100%;background:var(--ylw);}
  .nilm-w{font-family:var(--mono);font-size:10px;color:var(--ylw);font-weight:700;width:44px;text-align:right;flex-shrink:0;}

  /* DECISIONS */
  .dec-row{display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.03);}
  .dec-row:last-child{border-bottom:none;}
  .dec-icon{font-size:12px;flex-shrink:0;width:18px;text-align:center;padding-top:1px;}
  .dec-body{flex:1;min-width:0;}
  .dec-main{font-size:10px;font-weight:700;color:var(--txt);}
  .dec-sub{font-size:9px;color:var(--sub);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .dec-time{font-family:var(--mono);font-size:8px;color:var(--mut);flex-shrink:0;}

  /* ALERTS */
  .alert-row{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.03);}
  .alert-row:last-child{border-bottom:none;}
  .adot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
  .alert-body{flex:1;}
  .alert-title{font-size:11px;font-weight:700;color:var(--txt);}
  .alert-msg{font-size:9px;color:var(--sub);margin-top:1px;}

  /* TOAST */
  .toast{position:absolute;bottom:12px;left:50%;transform:translateX(-50%);
    background:rgba(129,140,248,.9);color:#fff;padding:6px 16px;border-radius:20px;
    font-size:11px;font-weight:600;font-family:var(--sans);pointer-events:none;
    opacity:0;transition:opacity .3s;white-space:nowrap;z-index:10;}
  .toast.show{opacity:1;}

  .wrap{position:relative;}
  .page{display:none;}.page.active{display:block;}

  @keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
  .fadein{animation:fadeUp .25s ease both;}
  @keyframes spin{to{transform:rotate(360deg)}}
  .spin{animation:spin 1s linear infinite;display:inline-block;}
`;

const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const W = w => w == null ? "—" : Math.abs(w) < 1000 ? `${Math.round(w)} W` : `${(w/1000).toFixed(2)} kW`;
const pct = (v,t) => t > 0 ? Math.min(100, Math.max(0, Math.round(v/t*100))) : 0;

class CloudemsControlCard extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:"open"});
    this._prev = "";
    this._tab = "overzicht";
    this._toastTimer = null;
  }

  setConfig(c){
    this._cfg = {title: c.title ?? "CloudEMS", ...c};
    this._render();
  }

  set hass(h){
    this._hass = h;
    const st  = h.states["sensor.cloudems_status"];
    const wd  = h.states["sensor.cloudems_watchdog"];
    const bp  = h.states["sensor.cloudems_battery_power"];
    const epx = h.states["sensor.cloudems_batterij_epex_schema"];
    const gn  = h.states["sensor.cloudems_grid_net_power"];
    const al  = h.states["sensor.cloudems_actieve_meldingen"];
    const nd  = h.states["sensor.cloudems_nilm_running_devices"];
    const sol = h.states["sensor.cloudems_solar_system"];
    const j = JSON.stringify([
      st?.last_updated, bp?.state, gn?.state, al?.state, nd?.state,
      epx?.attributes?.soc_pct, sol?.state, wd?.state
    ]);
    if(j !== this._prev){ this._prev = j; this._render(); }
  }

  _sw(id){ return this._hass?.states[id]?.state === "on"; }
  _st(id){ return this._hass?.states[id]?.state ?? "unavailable"; }
  _fa(id, a){ return this._hass?.states[id]?.attributes?.[a]; }
  _fn(id, fb=0){ const v = parseFloat(this._st(id)); return isNaN(v) ? fb : v; }

  _callService(domain, service, data={}){
    this._hass.callService(domain, service, data);
    this._toast(`${service.replace(/_/g," ")} ✓`);
  }

  _toggleSwitch(entityId){
    const on = this._sw(entityId);
    this._hass.callService("switch", on ? "turn_off" : "turn_on", {entity_id: entityId});
    this._toast(on ? "Module uitgeschakeld" : "Module ingeschakeld");
  }

  _toast(msg){
    const sh = this.shadowRoot;
    if(!sh) return;
    const t = sh.querySelector(".toast");
    if(!t) return;
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => t.classList.remove("show"), 2000);
  }

  _setTab(name){
    this._tab = name;
    const sh = this.shadowRoot;
    if(!sh) return;
    sh.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    sh.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.dataset.page === name));
  }

  _render(){
    const sh = this.shadowRoot; if(!sh) return;
    const h = this._hass, c = this._cfg ?? {};
    if(!h){ sh.innerHTML = `<style>${CSS}</style><div class="card" style="padding:32px;text-align:center;color:var(--sub)">⚡ Laden...</div>`; return; }

    // ── Correct sensor mapping ──────────────────────────────────────────
    // sensor.cloudems_status has: system, guardian, watchdog, shutters ONLY
    // Everything else comes from dedicated sensors
    const statusAttr = h.states["sensor.cloudems_status"]?.attributes ?? {};
    const version = this._fa("sensor.cloudems_watchdog","cloudems_version")
                 ?? statusAttr.system?.version
                 ?? "?";

    // Power — all from dedicated sensors
    const gridW   = this._fn("sensor.cloudems_grid_net_power");
    const solarW  = this._fn("sensor.cloudems_solar_system") || this._fn("sensor.cloudems_flexibel_vermogen");
    const batW    = this._fn("sensor.cloudems_battery_power");
    const homeW   = this._fn("sensor.cloudems_home_rest");
    const price   = this._fn("sensor.cloudems_energy_price_current_hour") || this._fn("sensor.cloudems_price_current_hour");
    const costDay = this._fn("sensor.cloudems_energy_cost");

    // Gas — lees van sensor.cloudems_gasstand
    const gasAttr    = this._hass?.states["sensor.cloudems_gasstand"]?.attributes ?? {};
    const gasDagM3   = parseFloat(gasAttr.dag_m3) || 0;
    const gasFib     = Array.isArray(gasAttr.gas_fib_hours) ? gasAttr.gas_fib_hours : [];
    const gasFib1h   = gasFib.find(f => f.hours === 1);
    const gasRateM3h = (gasFib1h && gasFib1h.rate_m3h != null) ? gasFib1h.rate_m3h : null;
    const hasGas     = this._hass?.states["sensor.cloudems_gasstand"] != null;

    // Battery SoC — with Zonneplan fallback chain
    const socDirect = parseFloat(this._st("sensor.cloudems_battery_so_c"));
    const epexAttr  = h.states["sensor.cloudems_batterij_epex_schema"]?.attributes ?? {};
    const soc = !isNaN(socDirect) && this._st("sensor.cloudems_battery_so_c") !== "unavailable"
      ? socDirect
      : (epexAttr.soc_pct ?? epexAttr.batteries?.[0]?.soc_pct ?? 0);

    const pCol = price > 0.25 ? "var(--red)" : price < 0 ? "var(--grn)" : price < 0.12 ? "var(--sky)" : "var(--amb)";
    const maxPow = Math.max(1, Math.abs(gridW), solarW, Math.abs(batW), homeW) * 1.1;

    // Collections from correct sensors
    const alerts   = this._fa("sensor.cloudems_actieve_meldingen","active_alerts") ?? [];
    const running  = this._fa("sensor.cloudems_nilm_running_devices","devices") ?? [];
    const nilmW    = this._fn("sensor.cloudems_nilm_running_devices_power");
    const shutters = (statusAttr.shutters ?? {}).shutters ?? [];    // shutters IS in status
    const boilers  = (h.states["sensor.cloudems_boiler_status"]?.attributes?.boilers ?? []);
    const decAttr  = h.states["sensor.cloudems_watchdog"]?.attributes ?? {};
    const decLog   = (decAttr.last_10 ?? []).slice(0,8);            // decision_log in watchdog.last_10
    const batDec   = epexAttr.battery_decision ?? {};
    const batPwrAttr = h.states["sensor.cloudems_battery_power"]?.attributes ?? {};

    // ── TAB: OVERZICHT ───────────────────────────────────────────────
    const flowNode = (icon, bg, lbl, watt, col) =>
      `<div class="flow-node">
        <div class="ficon" style="background:${bg}">${icon}</div>
        <div class="flbl">${esc(lbl)}</div>
        <div class="fpw" style="color:${col}">${W(watt)}</div>
      </div>`;

    const flowLine = (w, col) =>
      `<div class="fline"><div class="fline-fill" style="width:${pct(Math.abs(w),maxPow)}%;background:${col}"></div></div>`;

    const tabOverzicht = `
      <div class="sec">
        <div class="sec-title">⚡ Energiestroom</div>
        <div class="flow-row">
          ${flowNode("☀️","rgba(250,204,21,.18)","Solar",solarW,"var(--ylw)")}
          ${flowLine(solarW,"var(--ylw)")}
          ${flowNode("🏠","rgba(129,140,248,.18)","Huis",homeW,"var(--ind)")}
          ${flowLine(Math.abs(gridW),gridW>=0?"var(--red)":"var(--grn)")}
          ${flowNode("🔌",gridW>=0?"rgba(248,113,113,.18)":"rgba(74,222,128,.18)",gridW>=0?"Import":"Export",Math.abs(gridW),gridW>=0?"var(--red)":"var(--grn)")}
          ${Math.abs(batW) > 20 ? flowLine(Math.abs(batW),"var(--sky)") + flowNode("🔋","rgba(125,211,252,.18)",batW>0?"Laden":"Ontlad.",Math.abs(batW),"var(--sky)") : ""}
        </div>
      </div>
      ${alerts.length ? `<div class="sec">
        <div class="sec-title">🔔 Meldingen (${alerts.length})</div>
        ${alerts.slice(0,3).map(a => {
          const col = a.priority==="critical"?"var(--red)":a.priority==="warning"?"var(--amb)":"var(--sky)";
          return `<div class="alert-row"><div class="adot" style="background:${col}"></div>
            <div class="alert-body"><div class="alert-title">${esc(a.title)}</div><div class="alert-msg">${esc(a.message)}</div></div>
          </div>`;
        }).join("")}
      </div>` : ""}
      <div class="sec">
        <div class="sec-title">🧠 Recente beslissingen</div>
        ${decLog.slice(0,6).map((d,i) => {
          const ts = d.ts ? new Date(d.ts*1000).toLocaleTimeString("nl",{hour:"2-digit",minute:"2-digit"}) : "";
          const icons = {battery:"🔋",shutter:"🪟",boiler:"🌡️",ev:"🚗",switch:"💡",climate:"❄️",nilm:"🔍"};
          return `<div class="dec-row fadein" style="animation-delay:${i*30}ms">
            <div class="dec-icon">${icons[d.type]??"⚡"}</div>
            <div class="dec-body">
              <div class="dec-main">${esc(d.action??d.msg??"—")}</div>
              ${(d.reason||d.payload?.reason)?`<div class="dec-sub">${esc(d.reason??d.payload?.reason)}</div>`:""}
            </div>
            <div class="dec-time">${esc(ts)}</div>
          </div>`;
        }).join("") || `<div style="font-size:10px;color:var(--sub)">Geen recente beslissingen</div>`}
      </div>`;

    // ── TAB: MODULES ──────────────────────────────────────────────────
    const modules = [
      {sw:"switch.cloudems_module_nilm",          icon:"🔍", name:"NILM AI",         d:()=>running.length?`${running.length} actief`:"Idle"},
      {sw:"switch.cloudems_module_batterij",      icon:"🔋", name:"Batterij",         d:()=>soc>0?`SoC ${soc.toFixed(0)}%`:"Geen data"},
      {sw:"switch.cloudems_module_pv_forecast",   icon:"☀️", name:"Solar Forecast",   d:()=>{const v=this._fn("sensor.cloudems_pv_forecast_today",null);return v!=null?`${v.toFixed(1)} kWh`:"—";}},
      {sw:"switch.cloudems_module_piekbeperking", icon:"📊", name:"Piekbeperking",    d:()=>{const v=this._fn("sensor.cloudems_kwartier_piek",null);return v!=null?`${v.toFixed(2)} kW`:"—";}},
      {sw:"switch.cloudems_module_ketel",         icon:"🌡️", name:"Warm Water",       d:()=>boilers.length?`${boilers.length} boiler${boilers.length>1?"s":""}`:  "Geen boiler"},
      {sw:"switch.cloudems_module_rolluiken",     icon:"🪟", name:"Rolluiken",        d:()=>shutters.length?`${shutters.length} rolluik${shutters.length>1?"en":""}`:  "Geen"},
      {sw:"switch.cloudems_module_klimaat",       icon:"❄️", name:"Klimaat",          d:()=>{const v=this._fn("sensor.cloudems_warmtepomp_cop",null);return v!=null?`COP ${v.toFixed(1)}`:"—";}},
      {sw:"switch.cloudems_module_ev_lader",      icon:"🚗", name:"EV Lader",         d:()=>{const s=this._st("sensor.cloudems_ev_sessie_leermodel");return s!=="unavailable"?s:"—";}},
      {sw:"switch.cloudems_module_goedkope_uren", icon:"💶", name:"Goedkope Uren",    d:()=>{const v=this._fa("sensor.cloudems_goedkope_uren_schakelaars","active_count");return v!=null?`${v} actief`:"—";}},
      {sw:"switch.cloudems_module_faseverdeling", icon:"⚡", name:"Faseverdeling",    d:()=>{const v=this._fn("sensor.cloudems_grid_phase_imbalance",null);return v!=null?`${v.toFixed(0)} W`:"—";}},
      {sw:"switch.cloudems_module_zwembad",       icon:"🏊", name:"Zwembad",          d:()=>{const t=this._fa("sensor.cloudems_zwembad_status","temp_c");return t!=null?`${parseFloat(t).toFixed(1)}°C`:"—";}},
      {sw:"switch.cloudems_module_notificaties",  icon:"🔔", name:"Meldingen",        d:()=>alerts.length?`${alerts.length} actief`:"Geen"},
      {sw:"switch.cloudems_module_ere",           icon:"🏆", name:"ERE",              d:()=>"—"},
      {sw:"switch.cloudems_module_ebike",         icon:"🚲", name:"E-bike",           d:()=>"—"},
      {sw:"switch.cloudems_module_inzichten",     icon:"💡", name:"AI Inzichten",     d:()=>{const m=this._fa("sensor.cloudems_ai_status","model");return m??"—";}},
    ];

    const onCount = modules.filter(m => this._sw(m.sw)).length;
    const tabModules = `<div class="sec">
      <div class="sec-title">🧩 Modules — ${onCount}/${modules.length} aan · klik om te schakelen</div>
      <div class="mod-grid">
        ${modules.map(m => {
          const on = this._sw(m.sw);
          const _TTM=window.CloudEMSTooltip;
          const _ttMod=_TTM?_TTM.html('ov-mod-'+m.sw.replace(/[^a-z0-9]/gi,'_'),m.name,[
            {label:'Module',  value:m.sw},
            {label:'Status',  value:on?'✅ Aan':'❌ Uit'},
            {label:'Status',  value:esc(m.d())},
          ],{footer:'Klik om module aan/uit te zetten'}):{wrap:'',tip:''};
          return `<div class="mod ${on?"on":"off"}" data-sw="${esc(m.sw)}" style="position:relative" ${_ttMod.wrap}>
            <div class="mod-top">
              <span class="micon">${m.icon}</span>
              <span class="mname">${esc(m.name)}</span>
              <span class="mbadge ${on?"on":"off"}">${on?"AAN":"UIT"}</span>
            </div>
            <div class="mdetail">${esc(m.d())}</div>
            ${_ttMod.tip}
          </div>`;
        }).join("")}
      </div>
    </div>`;

    // ── TAB: ROLLUIKEN ────────────────────────────────────────────────
    const tabRolluiken = shutters.length ? `<div class="sec">
      <div class="sec-title">🪟 ${shutters.length} rolluik${shutters.length>1?"en":""}  ·  klik om te bedienen</div>
      ${shutters.map(s => {
        const pos = s.position ?? -1;
        const auto = s.auto_enabled !== false;
        const ov = s.override_active === true;
        const eid = s.entity_id;
        const autoCol = !auto?"var(--red)":ov?"var(--amb)":"var(--grn)";
        return `<div class="sh-row fadein">
          <span style="font-size:14px">${s.last_action==="open"?"🔼":s.last_action==="close"?"🔽":"⏸"}</span>
          <div class="sh-name">${esc(s.label??eid)}</div>
          <div class="sh-bar"><div class="sh-fill" style="width:${pos>=0?pos:0}%"></div></div>
          <div class="sh-pos">${pos>=0?pos+"%":"—"}</div>
          <div class="sh-btns">
            <button class="btn-sm btn-up" data-action="open_cover" data-eid="${esc(eid)}" title="Openen">▲</button>
            <button class="btn-sm btn-stop" data-action="stop_cover" data-eid="${esc(eid)}" title="Stop">■</button>
            <button class="btn-sm btn-dn" data-action="close_cover" data-eid="${esc(eid)}" title="Sluiten">▼</button>
            <button class="btn-sm btn-auto ${auto?"active":""}" data-action="toggle_auto" data-sw="switch.cloudems_rolluik_${esc(eid.split(".")[1])}_auto" title="${auto?"Automaat aan":"Automaat uit"}">🤖</button>
          </div>
        </div>`;
      }).join("")}
    </div>` : `<div class="sec" style="color:var(--sub);font-size:11px">Geen rolluiken geconfigureerd via CloudEMS.</div>`;

    // ── TAB: WARM WATER ───────────────────────────────────────────────
    const tabBoiler = boilers.length ? `<div class="sec">
      <div class="sec-title">🌡️ Warm Water</div>
      ${boilers.map(b => {
        const eid = b.entity_id ?? b.water_heater_entity ?? "";
        const wheid = eid.startsWith("water_heater.") ? eid : `water_heater.cloudems_${(b.label??"boiler1").toLowerCase().replace(/\s+/g,"_")}`;
        const temp = b.current_temp_c ?? b.temperature ?? null;
        const sp   = b.active_setpoint_c ?? b.setpoint ?? 60;
        const mode = b.actual_mode ?? b.mode ?? b.control_mode ?? "auto";
        const curOp = this._fa(wheid, "current_operation") ?? mode;
        return `<div class="bl-row fadein">
          <div class="bl-top">
            <span style="font-size:16px">🌡️</span>
            <div class="bl-name">${esc(b.label??wheid)}</div>
            <div class="bl-temp">${temp!=null?temp.toFixed(1)+"°C":"—"}</div>
          </div>
          <div class="bl-modes">
            ${["auto","manual","eco","boost","legionella"].map(op =>
              `<button class="mode-btn ${curOp===op?"active":""}" data-action="set_op" data-eid="${esc(wheid)}" data-mode="${op}">${op}</button>`
            ).join("")}
          </div>
          <div class="sp-row">
            <span class="sp-lbl">Setpoint</span>
            <input class="sp-input" type="number" min="20" max="75" step="1" value="${Math.round(sp)}" data-wheid="${esc(wheid)}" style="width:64px">
            <button class="btn-set" data-action="set_sp" data-eid="${esc(wheid)}">Instellen</button>
          </div>
        </div>`;
      }).join("")}
    </div>` : `<div class="sec" style="color:var(--sub);font-size:11px">Geen boilers geconfigureerd.</div>`;

    // ── TAB: BATTERIJ ─────────────────────────────────────────────────
    const socColor = soc >= 60 ? "var(--grn)" : soc >= 25 ? "var(--amb)" : "var(--red)";
    const chargeKwh = batPwrAttr.charge_kwh_today ?? 0;
    const disKwh = batPwrAttr.discharge_kwh_today ?? 0;
    const batAction = batDec.action ?? "idle";
    const batReason = batDec.reason ?? "—";
    const hasZP = this._fa("sensor.cloudems_batterij_epex_schema","zonneplan") != null;

    const tabBatterij = `<div class="sec">
      <div class="bat-row">
        <svg width="80" height="80" viewBox="0 0 80 80">
          <circle cx="40" cy="40" r="32" fill="none" stroke="rgba(255,255,255,.06)" stroke-width="6"/>
          <circle cx="40" cy="40" r="32" fill="none" stroke="${socColor}" stroke-width="6"
            stroke-dasharray="${2*Math.PI*32}" stroke-dashoffset="${2*Math.PI*32*(1-soc/100)}"
            stroke-linecap="round" transform="rotate(-90 40 40)" style="transition:stroke-dashoffset .8s ease"/>
          <text x="40" y="43" text-anchor="middle" font-family="JetBrains Mono,monospace" font-size="16" font-weight="700" fill="${socColor}">${soc.toFixed(0)}%</text>
        </svg>
        <div class="bat-info">
          <div style="font-size:10px;color:var(--sub)">Vermogen</div>
          <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:${batW>20?"var(--sky)":batW<-20?"var(--grn)":"var(--sub)"}">${W(batW)}</div>
          <div class="bat-dec">💡 ${esc(batReason.length>60?batReason.slice(0,60)+"…":batReason)}</div>
          <div style="display:flex;gap:12px;margin-top:6px">
            <span style="font-size:9px;color:var(--sub)">⚡ ${chargeKwh.toFixed(2)} kWh geladen</span>
            <span style="font-size:9px;color:var(--sub)">⬇ ${disKwh.toFixed(2)} kWh ontladen</span>
          </div>
        </div>
      </div>
      ${hasZP ? `<div class="bat-btns">
        <button class="bat-btn" data-action="bat_charge" style="color:var(--sky);border-color:rgba(125,211,252,.3);background:rgba(125,211,252,.08)">⚡ Laden</button>
        <button class="bat-btn" data-action="bat_discharge" style="color:var(--grn);border-color:rgba(74,222,128,.3);background:rgba(74,222,128,.08)">⬇ Ontladen</button>
        <button class="bat-btn" data-action="bat_auto" style="color:var(--ind);border-color:rgba(129,140,248,.3);background:rgba(129,140,248,.08)">🤖 Auto</button>
      </div>` : ""}
    </div>
    ${running.length ? `<div class="sec">
      <div class="sec-title">🔍 Actieve NILM apparaten · ${W(nilmW)} totaal</div>
      ${running.slice(0,8).map(d => {
        const dw = d.power_w ?? d.watt ?? 0;
        return `<div class="nilm-row">
          <div class="nilm-name">${esc(d.label??d.name??"Apparaat")}</div>
          <div class="nilm-bar-wrap"><div class="nilm-bar" style="width:${pct(dw,nilmW||1)}%"></div></div>
          <div class="nilm-w">${dw.toFixed(0)} W</div>
        </div>`;
      }).join("")}
      ${running.length>8?`<div style="font-size:9px;color:var(--sub);margin-top:4px">...en ${running.length-8} meer</div>`:""}
    </div>` : ""}`;

    // ── FULL HTML ─────────────────────────────────────────────────────
    const tabs = [
      {id:"overzicht", label:"📊 Overzicht"},
      {id:"modules",   label:"🧩 Modules"},
      {id:"rolluiken", label:"🪟 Rolluiken"},
      {id:"boiler",    label:"🌡️ Boiler"},
      {id:"batterij",  label:"🔋 Batterij"},
    ];

    const html = `<style>${CSS}</style>
<div class="card wrap">
  <div class="hdr">
    <div class="hdr-logo">⚡</div>
    <div class="hdr-info">
      <div class="hdr-title">${esc(c.title)}</div>
      <div class="hdr-sub">v${esc(version)}</div>
    </div>
    <div class="hdr-badge">v${esc(version)}</div>
  </div>
  <div class="estrip">
    ${(()=>{const _TTO=window.CloudEMSTooltip;
      const _ttSol=_TTO?_TTO.html('ov-sol','Zonne-energie',[
        {label:'Sensor',  value:'cloudems_solar_system'},
        {label:'Nu',      value:solarW.toFixed(0)+' W'},
        {label:'Forecast',value:this._fn('sensor.cloudems_pv_forecast_today',null)!=null?this._fn('sensor.cloudems_pv_forecast_today',null).toFixed(1)+' kWh vandaag':'—'},
      ],{trusted:solarW>0}):{wrap:'',tip:''};
      const _ttGrid=_TTO?_TTO.html('ov-grid',gridW>=0?'Import':'Export',[
        {label:'Sensor', value:'cloudems_grid_net_power'},
        {label:'Nu',     value:(gridW>=0?'▼ Import ':'▲ Export ')+Math.abs(gridW).toFixed(0)+' W'},
        {label:'Prijs',  value:'€'+price.toFixed(4)+'/kWh'},
      ],{trusted:true}):{wrap:'',tip:''};
      const _ttBat=_TTO?_TTO.html('ov-bat',batW>=0?'Batterij laden':'Batterij ontladen',[
        {label:'Sensor', value:'cloudems_battery_so_c'},
        {label:'Nu',     value:(batW>=0?'▲ Laden ':'▼ Ontladen ')+Math.abs(batW).toFixed(0)+' W'},
        {label:'SoC',    value:soc.toFixed(0)+'%'},
      ],{trusted:soc>0}):{wrap:'',tip:''};
      const _ttHuis=_TTO?_TTO.html('ov-huis','Huisverbruik',[
        {label:'Sensor',       value:'cloudems_home_rest'},
        {label:'Nu',           value:homeW.toFixed(0)+' W'},
        {label:'Kosten vandaag',value:'€'+costDay.toFixed(2)},
      ],{trusted:homeW>0}):{wrap:'',tip:''};
      return`
    <div class="ecell" style="position:relative;cursor:default" ${_ttSol.wrap}><div class="el">☀️ Solar</div><div class="ev" style="color:var(--ylw)">${solarW>0?solarW.toFixed(0):"0"}</div><div class="eu">W</div>${_ttSol.tip}</div>
    <div class="ecell" style="position:relative;cursor:default" ${_ttGrid.wrap}><div class="el">${gridW>=0?"⬇ Import":"⬆ Export"}</div><div class="ev" style="color:${gridW>=0?"var(--red)":"var(--grn)"}">${Math.abs(gridW).toFixed(0)}</div><div class="eu" style="color:${pCol}">€${price.toFixed(3)}</div>${_ttGrid.tip}</div>
    <div class="ecell" style="position:relative;cursor:default" ${_ttBat.wrap}><div class="el">🔋 ${batW>=0?"Laden":"Ontladen"}</div><div class="ev" style="color:${batW>=0?"var(--sky)":"var(--grn)"}">${Math.abs(batW).toFixed(0)}</div><div class="eu">W · ${soc>0?soc.toFixed(0):"—"}%</div>${_ttBat.tip}</div>
    <div class="ecell" style="position:relative;cursor:default" ${_ttHuis.wrap}><div class="el">🏠 Huis</div><div class="ev">${homeW>0?homeW.toFixed(0):"—"}</div><div class="eu">W · €${costDay.toFixed(2)}</div>${_ttHuis.tip}</div>`;
    })()}
  </div>
  ${hasGas ? (()=>{const _TTG=window.CloudEMSTooltip;
    const _ttGas=_TTG?_TTG.html('ov-gas','Gasverbruik',[
      {label:'Sensor',    value:'cloudems_gasstand'},
      {label:'Stroom',    value:gasRateM3h!=null?gasRateM3h.toFixed(3)+' m³/u':'—'},
      {label:'Vandaag',   value:gasDagM3.toFixed(3)+' m³'},
      {label:'Max geleerd',value:gasAttr.gas_rate_max_m3h?parseFloat(gasAttr.gas_rate_max_m3h).toFixed(3)+' m³/u (EMA)':'—',dim:true},
      {label:'Bron',      value:gasRateM3h!=null?'● P1 DSMR realtime':'○ Berekend uit dagstand',dim:true},
    ],{footer:'Balk = huidig t.o.v. geleerd maximum verbruik'}):{wrap:'',tip:''};
    return`<div class="gasstrip" style="position:relative;cursor:default" ${_ttGas.wrap}>
    <span class="gs-icon">🔥</span>
    <span class="gs-label">Gas</span>
    <span class="gs-rate">${gasRateM3h != null ? gasRateM3h.toFixed(3) : "—"}</span><span class="gs-unit">m³/u</span>
    <div class="gs-bar-wrap"><div class="gs-bar-fill" style="width:${gasRateM3h != null ? Math.min(100, (gasRateM3h / Math.max(gasAttr.gas_rate_max_m3h || 1, gasRateM3h)) * 100).toFixed(1) : 0}%"></div></div>
    <span class="gs-dag">vandaag ${gasDagM3.toFixed(3)} m³</span>
    ${_ttGas.tip}
  </div>`;})() : ""}
  <div class="nav">
    ${tabs.map(t => `<button class="nav-btn${t.id===this._tab?" active":""}" data-tab="${t.id}">${t.label}</button>`).join("")}
  </div>
  ${tabs.map(t => `<div class="page${t.id===this._tab?" active":""}" data-page="${t.id}">${
    t.id==="overzicht"?tabOverzicht:
    t.id==="modules"?tabModules:
    t.id==="rolluiken"?tabRolluiken:
    t.id==="boiler"?tabBoiler:
    tabBatterij
  }</div>`).join("")}
  <div class="toast"></div>
</div>`;

    sh.innerHTML = html;
    this._bindEvents();
  }

  _bindEvents(){
    const sh = this.shadowRoot; if(!sh) return;

    // Nav tabs
    sh.querySelectorAll(".nav-btn").forEach(btn => {
      btn.addEventListener("click", () => this._setTab(btn.dataset.tab));
    });

    // Module toggles
    sh.querySelectorAll(".mod[data-sw]").forEach(el => {
      el.addEventListener("click", () => this._toggleSwitch(el.dataset.sw));
    });

    // Cover buttons
    sh.querySelectorAll("[data-action='open_cover']").forEach(btn => {
      btn.addEventListener("click", e => { e.stopPropagation();
        this._callService("cover","open_cover",{entity_id: btn.dataset.eid}); });
    });
    sh.querySelectorAll("[data-action='stop_cover']").forEach(btn => {
      btn.addEventListener("click", e => { e.stopPropagation();
        this._callService("cover","stop_cover",{entity_id: btn.dataset.eid}); });
    });
    sh.querySelectorAll("[data-action='close_cover']").forEach(btn => {
      btn.addEventListener("click", e => { e.stopPropagation();
        this._callService("cover","close_cover",{entity_id: btn.dataset.eid}); });
    });
    sh.querySelectorAll("[data-action='toggle_auto']").forEach(btn => {
      btn.addEventListener("click", e => { e.stopPropagation();
        const swId = btn.dataset.sw;
        if(swId && this._hass.states[swId]){
          this._toggleSwitch(swId);
        }
      });
    });

    // Boiler mode buttons
    sh.querySelectorAll("[data-action='set_op']").forEach(btn => {
      btn.addEventListener("click", e => { e.stopPropagation();
        this._callService("water_heater","set_operation_mode",{
          entity_id: btn.dataset.eid, operation_mode: btn.dataset.mode});
      });
    });

    // Boiler setpoint
    sh.querySelectorAll("[data-action='set_sp']").forEach(btn => {
      btn.addEventListener("click", e => { e.stopPropagation();
        const eid = btn.dataset.eid;
        const input = sh.querySelector(`.sp-input[data-wheid="${eid}"]`);
        if(input){
          const temp = parseFloat(input.value);
          if(!isNaN(temp)){
            this._callService("water_heater","set_temperature",{entity_id: eid, temperature: temp});
          }
        }
      });
    });

    // Battery actions (Zonneplan)
    sh.querySelector("[data-action='bat_charge']")?.addEventListener("click", () =>
      this._callService("cloudems","zonneplan_battery_charge",{}));
    sh.querySelector("[data-action='bat_discharge']")?.addEventListener("click", () =>
      this._callService("cloudems","zonneplan_battery_discharge",{}));
    sh.querySelector("[data-action='bat_auto']")?.addEventListener("click", () =>
      this._callService("cloudems","zonneplan_battery_auto",{}));
  }

  getCardSize(){ return 12; }
  getLayoutOptions(){ return { grid_columns: 4, grid_rows: 8 }; }

  static getConfigElement(){ return document.createElement("cloudems-beheer-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-beheer-card"}; }
}



class CloudemsBeheerCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){
    this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true}));
  }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>
.wrap{padding:8px;}
.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}
.row:last-child{border-bottom:none;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input[type=text],input[type=number]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;box-sizing:border-box;}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary-color,#03a9f4);cursor:pointer;}
</style>
<div class="wrap">
        <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??"CloudEMS"}"></div>
        <div class="row"><label class="lbl">Max beslissingen</label><input type="number" name="max_decisions" value="${cfg.max_decisions??6}"></div>
</div>`;
    this.shadowRoot.querySelectorAll("input").forEach(el=>{
      el.addEventListener("change",()=>{
        const n=el.name, nc={...this._cfg};
        if(n==="title") nc[n]=el.value;
        if(n==="max_decisions") nc[n]=parseFloat(el.value)||6;
        this._cfg=nc; this._fire();
      });
    });
  }
}
if (!customElements.get("cloudems-beheer-card-editor")) {
  customElements.define("cloudems-beheer-card-editor", CloudemsBeheerCardEditor);
}
if (!customElements.get("cloudems-beheer-card")) {
  customElements.define("cloudems-beheer-card", CloudemsControlCard);
}
if (!customElements.get("cloudems-control-card")) {
  class CloudemsControlCardAlias extends CloudemsControlCard {}
  customElements.define("cloudems-control-card", CloudemsControlCardAlias);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "cloudems-beheer-card",
  name: "CloudEMS Control",
  description: "Alles-in-één interactieve beheerkaart — overzicht, modules, rolluiken, boiler, batterij"
});
