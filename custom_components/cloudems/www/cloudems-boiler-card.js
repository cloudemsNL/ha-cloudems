// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Boiler Card  v5.5.465

const BOILER_CARD_VERSION = "5.5.465";

const S = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
  :host{display:block;--gap:16px;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:#111318;border:1px solid rgba(255,255,255,0.07);border-radius:20px;overflow:hidden;font-family:'Syne',sans-serif;position:relative;}
  .card::before{content:'';position:absolute;inset:-60px;background:radial-gradient(ellipse 60% 40% at 20% 0%,rgba(255,100,40,0.08) 0%,transparent 60%),radial-gradient(ellipse 50% 35% at 80% 100%,rgba(52,140,220,0.06) 0%,transparent 60%);pointer-events:none;z-index:0;}
  .inner{position:relative;z-index:1;}

  /* ── Boiler selector tabs (multi-boiler) ── */
  .boiler-tabs{display:flex;gap:1px;background:rgba(255,255,255,0.04);border-bottom:1px solid rgba(255,255,255,0.06);}
  .boiler-tab{flex:1;padding:9px 4px;text-align:center;font-size:11px;font-weight:600;letter-spacing:.04em;color:#444;cursor:pointer;border:none;background:#111318;transition:all .15s;}
  .boiler-tab:hover{color:#888;}
  .boiler-tab.active{color:#ff8040;border-bottom:2px solid #ff8040;background:rgba(255,128,64,0.04);}

  /* ── Header ── */
  .hdr{display:flex;align-items:center;gap:12px;padding:16px 20px 12px;border-bottom:1px solid rgba(255,255,255,0.06);}
  .hdr-icon{width:38px;height:38px;background:linear-gradient(135deg,rgba(255,100,40,0.25),rgba(255,160,80,0.1));border:1px solid rgba(255,120,50,0.3);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
  .hdr-title{font-size:15px;font-weight:700;color:#f0f0f0;letter-spacing:.02em;}
  .hdr-sub{font-size:11px;color:#5a6070;margin-top:1px;font-family:'JetBrains Mono',monospace;}
  .hdr-badge{margin-left:auto;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:.05em;font-family:'JetBrains Mono',monospace;}
  .badge-on{background:rgba(0,220,100,0.12);border:1px solid rgba(0,220,100,0.3);color:#00dc64;}
  .badge-off{background:rgba(120,120,120,0.12);border:1px solid rgba(120,120,120,0.2);color:#666;}
  .badge-boost{background:rgba(255,100,40,0.15);border:1px solid rgba(255,100,40,0.4);color:#ff6428;}
  .badge-green{background:rgba(0,200,120,0.12);border:1px solid rgba(0,200,120,0.3);color:#00c878;}

  /* ── Content tabs ── */
  .ctabs{display:flex;border-bottom:1px solid rgba(255,255,255,0.06);}
  .ctab{flex:1;padding:8px 4px;text-align:center;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#444;cursor:pointer;border:none;background:transparent;transition:all .15s;}
  .ctab:hover{color:#777;}
  .ctab.active{color:#ff8040;border-bottom:2px solid #ff8040;}

  /* ── Tab content panels ── */
  .tab-panel{display:none;} .tab-panel.active{display:block;}

  /* ── LIVE tab ── */
  .hero{display:grid;grid-template-columns:auto 1fr;padding:18px 20px 0;align-items:start;}
  .tank-wrap{display:flex;flex-direction:column;align-items:center;gap:6px;padding-right:18px;}
  .tank-label{font-size:10px;color:#444;letter-spacing:.1em;text-transform:uppercase;}
  .stats-col{display:flex;flex-direction:column;gap:10px;}
  .temp-big{display:flex;align-items:baseline;gap:4px;}
  .temp-val{font-size:48px;font-weight:800;color:#f0f0f0;line-height:1;letter-spacing:-2px;}
  .temp-unit{font-size:20px;font-weight:600;color:#555;}
  .temp-label{font-size:11px;color:#5a6070;letter-spacing:.06em;text-transform:uppercase;}
  .sp-row{display:flex;align-items:center;gap:8px;padding:7px 10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:10px;}
  .sp-text{font-size:12px;color:#888;}
  .sp-val{font-size:13px;font-weight:700;color:#e0e0e0;margin-left:auto;font-family:'JetBrains Mono',monospace;}
  .sp-bar-wrap{height:3px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;margin-top:4px;}
  .sp-bar{height:100%;border-radius:2px;transition:width 1.2s cubic-bezier(.4,0,.2,1);}
  .metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:14px 0 0;background:rgba(255,255,255,0.05);border-top:1px solid rgba(255,255,255,0.05);border-bottom:1px solid rgba(255,255,255,0.05);}
  .metric{padding:13px 10px;background:#111318;display:flex;flex-direction:column;align-items:center;gap:4px;}
  .metric-icon{font-size:17px;}
  .metric-val{font-size:21px;font-weight:800;color:#f0f0f0;font-family:'JetBrains Mono',monospace;letter-spacing:-0.5px;line-height:1;}
  .metric-val.accent{color:#ff8040;} .metric-val.blue{color:#52a8ff;} .metric-val.green{color:#00dc64;}
  .metric-label{font-size:10px;color:#444;letter-spacing:.08em;text-transform:uppercase;text-align:center;}
  .graphs{padding:14px 20px 18px;}
  .graph-title{font-size:11px;color:#444;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:8px;}
  .graph-title::after{content:'';flex:1;height:1px;background:rgba(255,255,255,0.05);}
  .dual-graph{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
  .donut-row{display:flex;align-items:center;gap:18px;margin-top:16px;}
  .donut-wrap{position:relative;width:78px;height:78px;flex-shrink:0;}
  .donut-wrap svg{width:78px;height:78px;}
  .donut-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;}
  .donut-big{font-size:17px;font-weight:800;color:#f0f0f0;font-family:'JetBrains Mono',monospace;line-height:1;}
  .donut-small{font-size:9px;color:#444;letter-spacing:.06em;}
  .donut-info{flex:1;}
  .donut-row-item{display:flex;justify-content:space-between;font-size:12px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
  .donut-row-item:last-child{border:none;}
  .donut-key{color:#666;} .donut-v{color:#e0e0e0;font-weight:600;font-family:'JetBrains Mono',monospace;}
  .vtherm-ctrl{margin:6px 20px;padding:10px 14px;background:rgba(255,255,255,.04);border-radius:10px;border:1px solid rgba(255,255,255,.08);}
  .action-section{padding:12px 16px 14px;border-top:1px solid rgba(255,255,255,0.07);}
  .action-section-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.25);margin-bottom:10px;padding-left:2px;}
  .action-row{display:flex;gap:8px;}
  .action-btn{
    flex:1;padding:11px 6px 9px;border-radius:11px;
    font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
    cursor:pointer;border:1px solid;transition:all .15s;text-align:center;
    display:flex;flex-direction:column;align-items:center;gap:3px;
  }
  .action-btn .btn-icon{font-size:16px;line-height:1;}
  .action-btn .btn-lbl{font-size:10px;font-weight:600;letter-spacing:.03em;}
  .action-btn .btn-sub{font-size:9px;font-weight:400;opacity:.7;letter-spacing:.02em;}
  .action-btn:hover{filter:brightness(1.15);transform:translateY(-1px);}
  .action-btn:active{opacity:.7;transform:translateY(0);}
  .action-btn:disabled{opacity:.3;cursor:default;transform:none;filter:none;}
  .btn-send{background:rgba(0,200,100,0.15);border-color:rgba(0,200,100,0.45);color:#00c878;}
  .btn-send:hover{background:rgba(0,200,100,0.25);border-color:#00c878;}
  .btn-green{background:rgba(52,211,153,0.15);border-color:rgba(52,211,153,0.45);color:#34d399;}
  .btn-green:hover{background:rgba(52,211,153,0.25);border-color:#34d399;}
  .btn-pause{background:rgba(255,160,0,0.12);border-color:rgba(255,160,0,0.38);color:#ffa000;}
  .btn-pause:hover{background:rgba(255,160,0,0.22);border-color:#ffa000;}
  .btn-resume{background:rgba(100,180,255,0.15);border-color:rgba(100,180,255,0.40);color:#64b4ff;}
  .btn-resume:hover{background:rgba(100,180,255,0.25);border-color:#64b4ff;}
  .pause-group{display:flex;gap:6px;flex:2;}
  .footer-chips{padding:10px 20px;border-top:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
  .chip{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;display:flex;align-items:center;gap:5px;letter-spacing:.04em;}
  .chip-boost{background:rgba(255,100,40,0.12);border:1px solid rgba(255,100,40,0.3);color:#ff6428;}
  .chip-green{background:rgba(0,200,100,0.1);border:1px solid rgba(0,200,100,0.25);color:#00c878;}
  .chip-off{background:rgba(120,120,120,0.1);border:1px solid rgba(120,120,120,0.2);color:#666;}
  .chip-power{background:rgba(255,214,0,0.08);border:1px solid rgba(255,214,0,0.2);color:#ffd600;}
  .chip-cop{background:rgba(100,200,255,0.08);border:1px solid rgba(100,200,255,0.2);color:#64c8ff;}
  .chip-warn{background:rgba(255,200,0,0.1);border:1px solid rgba(255,200,0,0.3);color:#ffc800;}
  .chip-verify{background:rgba(255,160,0,0.1);border:1px solid rgba(255,160,0,0.3);color:#ffa000;animation:pulse 2s infinite;}
  .chip-ramp{background:rgba(167,139,250,0.10);border:1px solid rgba(167,139,250,0.2);color:#a78bfa;}

  /* ── LEREN tab ── */
  .learn-section{padding:14px 20px;}
  .learn-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#374151;margin-bottom:10px;margin-top:14px;}
  .learn-title:first-child{margin-top:0;}
  .kv-grid{display:grid;grid-template-columns:1fr auto;gap:4px 12px;}
  .kv-key{font-size:12px;color:#6b7280;}
  .kv-val{font-size:12px;font-weight:700;color:#e2e8f0;font-family:'JetBrains Mono',monospace;text-align:right;}
  .kv-val.good{color:#4ade80;} .kv-val.warn{color:#fb923c;} .kv-val.info{color:#7dd3fc;} .kv-val.purple{color:#a78bfa;}
  .progress-bar{height:6px;background:rgba(255,255,255,0.07);border-radius:4px;overflow:hidden;margin-top:4px;grid-column:1/-1;}
  .progress-fill{height:100%;border-radius:4px;transition:width .8s ease;}
  .divider{height:1px;background:rgba(255,255,255,0.05);margin:10px 0;grid-column:1/-1;}
  .ramp-viz{display:flex;align-items:center;gap:3px;margin-top:8px;padding:8px 10px;background:rgba(255,255,255,0.03);border-radius:8px;border:1px solid rgba(255,255,255,0.06);}
  .ramp-step{flex:1;height:18px;border-radius:3px;background:rgba(255,255,255,0.05);position:relative;overflow:hidden;}
  .ramp-step.active{background:rgba(167,139,250,0.2);border:1px solid rgba(167,139,250,0.3);}
  .ramp-step.done{background:rgba(74,222,128,0.15);}
  .ramp-label{font-size:8px;color:#4b5563;text-align:center;line-height:18px;}
  .stat-pill{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;margin:3px 3px 0 0;}
  .stat-good{background:rgba(74,222,128,0.1);color:#4ade80;border:1px solid rgba(74,222,128,0.2);}
  .stat-bad{background:rgba(248,113,113,0.1);color:#f87171;border:1px solid rgba(248,113,113,0.2);}
  .stat-neutral{background:rgba(255,255,255,0.05);color:#6b7280;border:1px solid rgba(255,255,255,0.08);}
  .ratio-bar{display:flex;height:8px;border-radius:4px;overflow:hidden;margin-top:6px;grid-column:1/-1;}
  .ratio-good{background:#4ade80;}
  .ratio-bad{background:#f87171;}

  /* ── GEZONDHEID tab ── */
  .health-section{padding:14px 20px;}
  .health-item{display:flex;align-items:center;gap:12px;padding:10px 12px;background:rgba(255,255,255,0.03);border-radius:10px;border:1px solid rgba(255,255,255,0.06);margin-bottom:8px;}
  .health-icon{font-size:22px;flex-shrink:0;}
  .health-body{flex:1;}
  .health-label{font-size:12px;font-weight:700;color:#e2e8f0;}
  .health-sub{font-size:11px;color:#6b7280;margin-top:1px;}
  .health-val{font-size:16px;font-weight:800;font-family:'JetBrains Mono',monospace;flex-shrink:0;}
  .health-bar{height:4px;background:rgba(255,255,255,0.07);border-radius:3px;overflow:hidden;margin-top:4px;}
  .health-bar-fill{height:100%;border-radius:3px;transition:width .8s ease;}
  .leg-status{padding:10px 12px;border-radius:10px;margin-bottom:8px;display:flex;align-items:center;gap:10px;}
  .leg-ok{background:rgba(74,222,128,0.08);border:1px solid rgba(74,222,128,0.2);}
  .leg-warn{background:rgba(251,146,60,0.08);border:1px solid rgba(251,146,60,0.2);}
  .leg-danger{background:rgba(248,113,113,0.10);border:1px solid rgba(248,113,113,0.25);}

  /* ── LOG tab ── */
  .log-section{padding:14px 20px 18px;}
  .dec-list{display:flex;flex-direction:column;gap:5px;}
  .dec-row{display:flex;align-items:baseline;gap:8px;padding:5px 8px;border-radius:8px;background:rgba(255,255,255,0.02);font-size:12px;line-height:1.4;}
  .dec-row:first-child{background:rgba(255,255,255,0.04);}
  .dec-time{font-family:'JetBrains Mono',monospace;font-size:11px;color:#555;flex-shrink:0;}
  .dec-icon{font-size:12px;flex-shrink:0;}
  .dec-msg{color:#888;flex:1;}
  .dec-cnt{font-size:10px;color:#444;font-family:'JetBrains Mono',monospace;flex-shrink:0;}
  .dec-empty{font-size:12px;color:#333;padding:6px 8px;font-style:italic;}

  /* ── Warmtebron ── */
  .warmtebron{margin:6px 20px 0;padding:8px 12px;background:rgba(255,255,255,0.04);border-radius:10px;border:1px solid rgba(255,255,255,0.06);}

  /* ── Empty / spinner ── */
  .empty{padding:40px 20px;text-align:center;color:#333;font-size:13px;}
  .empty-icon{font-size:36px;display:block;margin-bottom:12px;}
  .spinner{display:inline-block;width:20px;height:20px;border:2px solid rgba(255,255,255,0.1);border-top-color:#ff8040;border-radius:50%;animation:spin .8s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
`;

// ── Helpers ───────────────────────────────────────────────────────────────────
const esc = s => { const d = document.createElement('div'); d.textContent = String(s??''); return d.innerHTML; };
const clamp = (v,lo,hi) => Math.max(lo,Math.min(hi,v));
const fmtC = v => v!=null ? (v*100).toFixed(1)+' ct' : '—';

function tempToColor(t) {
  if(t>=65) return '#ff3020'; if(t>=55) return '#ff6428';
  if(t>=45) return '#ff9030'; if(t>=38) return '#ffb830'; return '#52a8ff';
}
function animateCounter(el,from,to,dur=800,dec=0){
  const start=performance.now(),diff=to-from;
  const step=now=>{const t=Math.min(1,(now-start)/dur),e=1-Math.pow(1-t,3);el.textContent=(from+diff*e).toFixed(dec);if(t<1)requestAnimationFrame(step);};
  requestAnimationFrame(step);
}
function buildDonut(pct,color,bg='rgba(255,255,255,0.05)'){
  const r=30,cx=40,cy=40,sw=7,circ=2*Math.PI*r,dash=circ*clamp(pct,0,1);
  return `<svg viewBox="0 0 80 80"><circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${bg}" stroke-width="${sw}"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="${sw}" stroke-dasharray="${dash} ${circ}" stroke-dashoffset="${circ*.25}" stroke-linecap="round" style="transition:stroke-dasharray 1.2s cubic-bezier(.4,0,.2,1)"/></svg>`;
}
function calcUsableWater(tb,tt,tc,vol){if(tb<=tt)return 0;if(tt<=tc)return vol;return Math.round(vol*(1+(tb-tt)/(tt-tc)));}
function calcShowers(ul,dur,flow){const lps=dur*flow;return lps>0?Math.floor(ul/lps):0;}

function buildTankSVG(fillPct,tempC){
  const W=52,H=90,R=8,color=tempToColor(tempC??30);
  const fillH=Math.round((H-8)*clamp(fillPct,0,1));
  const fillY=H-4-fillH;
  const wp=`M4,${fillY} Q${W/4},${fillY-3} ${W/2},${fillY} Q${W*3/4},${fillY+3} ${W-4},${fillY} L${W-4},${H-4} L4,${H-4} Z`;
  return `<svg width="${W}" height="${H+20}" viewBox="0 0 ${W} ${H+20}">
    <defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity=".9"/><stop offset="100%" stop-color="${color}" stop-opacity=".4"/></linearGradient><clipPath id="tc"><rect x="4" y="4" width="${W-8}" height="${H-8}" rx="${R-2}"/></clipPath></defs>
    <rect x="2" y="2" width="${W-4}" height="${H-4}" rx="${R}" fill="rgba(255,255,255,.03)" stroke="rgba(255,255,255,.1)" stroke-width="1.5"/>
    <g clip-path="url(#tc)"><path d="${wp}" fill="url(#tg)" opacity=".85"/>
    <circle cx="${W*.35}" cy="${fillY+fillH*.3}" r="2.5" fill="${color}" opacity=".3"><animate attributeName="cy" values="${fillY+fillH*.3};${fillY+fillH*.15};${fillY+fillH*.3}" dur="3s" repeatCount="indefinite"/></circle></g>
    ${[.25,.5,.75].map(p=>`<line x1="${W-8}" y1="${H-4-(H-8)*p}" x2="${W-4}" y2="${H-4-(H-8)*p}" stroke="rgba(255,255,255,.12)" stroke-width="1"/>`).join('')}
    <text x="${W/2}" y="${H*.6}" text-anchor="middle" font-family="'JetBrains Mono',monospace" font-size="11" font-weight="600" fill="${fillPct>.3?'rgba(255,255,255,.9)':'rgba(255,255,255,.3)'}">${tempC?tempC.toFixed(0)+'°':'—'}</text>
    <rect x="${W/2-4}" y="${H-2}" width="8" height="10" rx="2" fill="rgba(255,255,255,.07)" stroke="rgba(255,255,255,.08)" stroke-width="1"/>
  </svg>`;
}
function buildLine(pts,color,label,W=280,H=52){
  if(!pts||!pts.length) return `<div style="text-align:center;padding:8px;color:#333;font-size:10px">Wacht op data…</div>`;
  const vals=pts.map(p=>p.v),mx=Math.max(...vals,1),mn=Math.max(0,Math.min(...vals)-2),rng=mx-mn||1,pad=4;
  const xs=pts.map((_,i)=>pad+(i/Math.max(pts.length-1,1))*(W-pad*2));
  const ys=pts.map(p=>H-pad-((p.v-mn)/rng)*(H-pad*2));
  const line=xs.map((x,i)=>`${i?'L':'M'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const fill=line+` L${xs[xs.length-1].toFixed(1)},${H} L${xs[0].toFixed(1)},${H} Z`;
  const lx=xs[xs.length-1],ly=ys[ys.length-1],lv=pts[pts.length-1].v;
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="display:block;overflow:visible">
    <defs><linearGradient id="lg${label}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity=".3"/><stop offset="100%" stop-color="${color}" stop-opacity=".02"/></linearGradient></defs>
    <path d="${fill}" fill="url(#lg${label})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round"/>
    <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3" fill="${color}"/>
    <text x="${lx.toFixed(1)}" y="${(ly-6).toFixed(1)}" text-anchor="middle" fill="${color}" font-size="9" font-weight="600">${typeof lv==='number'?lv.toFixed(lv<100?1:0):lv}</text>
  </svg>`;
}
function buildDecisionsHtml(log,label,entityId){
  if(!log||!log.length) return '<div class="dec-empty">Nog geen beslissingen gelogd.</div>';
  const lo=(label||'').toLowerCase(),elo=(entityId||'').toLowerCase();
  const mine=log.filter(e=>{const m=(e[1]||'').toString().toLowerCase();return m.includes(lo)||m.includes(elo);});
  if(!mine.length) return `<div class="dec-empty">Geen beslissingen voor ${esc(label)}.</div>`;
  const rows=[];let lastMsg='',cnt=0;
  for(const e of mine){
    const ts=e[0]||'';
    const raw=(e[1]||'').toString().replace('hold_on','aan gehouden').replace('hold_off','uit gehouden').replace('turn_on','aangezet').replace('turn_off','uitgezet');
    const rl=raw.toLowerCase();
    const icon=rl.includes('aangezet')?'▶️':rl.includes('uitgezet')?'⏹️':rl.includes('aan gehouden')?'🟢':'⚫';
    let ts2='—';try{const d=new Date(ts);if(!isNaN(d))ts2=d.toLocaleTimeString('nl-NL',{hour:'2-digit',minute:'2-digit'});}catch(_){}
    const msg=raw.replace(new RegExp(`boiler ?\\d*:?\\s*`,'i'),'').replace(new RegExp((label||'').replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+':?\\s*','i'),'').trim();
    const mt=msg.length>72?msg.slice(0,70)+'…':msg;
    if(mt===lastMsg){cnt++;if(rows.length)rows[rows.length-1].cnt=cnt;}
    else{if(rows.length>=8)break;lastMsg=mt;cnt=1;rows.push({ts2,icon,msg:mt,cnt:1});}
  }
  return `<div class="dec-list">${rows.map(r=>`<div class="dec-row"><span class="dec-time">${r.ts2}</span><span class="dec-icon">${r.icon}</span><span class="dec-msg">${esc(r.msg)}</span>${r.cnt>1?`<span class="dec-cnt">${r.cnt}×</span>`:''}</div>`).join('')}</div>`;
}

// ── Main card ─────────────────────────────────────────────────────────────────
class CloudemsBoilerCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._prevJson='';this._boilerTab=0;this._contentTab='live';this._history={};this._historyPower={};this._historyLoading={};this._histLastFetch=0;}

  connectedCallback(){if(!this._fetchTimer)this._fetchTimer=setInterval(()=>this._fetchHistory(),300000);}
  disconnectedCallback(){clearInterval(this._fetchTimer);this._fetchTimer=null;}
  setConfig(cfg){
    this._cfg={tank_liters:0,cold_water_temp:10,shower_temp:38,shower_liters_per_min:8,shower_duration_min:8,title:'Warm water',...cfg};
    this._render();
  }

  set hass(hass){
    this._hass=hass;
    // Clear optimistic setpoint als HA de nieuwe waarde al doorgestuurd heeft
    if(this._optimisticSp){
      Object.keys(this._optimisticSp).forEach(eid=>{
        const st=hass.states[eid];if(!st)return;
        const real=parseFloat(st.attributes?.temperature);
        if(Math.abs(real-this._optimisticSp[eid])<0.5)delete this._optimisticSp[eid];
      });
    }
    const st=hass.states['sensor.cloudems_boiler_status'];
    const boilers=st?.attributes?.boilers??[];
    const json=JSON.stringify([st?.last_updated,st?.state,boilers.map(b=>[b.temp_c,b.current_power_w,b.is_on,b.active_setpoint_c,b.tank_liters_learned,b.ramp_setpoint_c])]);
    // Sample power values for in-memory graph fallback (recorder may not store 0W states)
    if(boilers.length){
      if(!this._powerSamples) this._powerSamples={};
      const d=new Date(),tLabel=d.getHours()+':'+String(d.getMinutes()).padStart(2,'0');
      for(const b of boilers){
        const pw=parseFloat(b.current_power_w??b.power_w??0);
        if(!this._powerSamples[b.entity_id]) this._powerSamples[b.entity_id]=[];
        const samps=this._powerSamples[b.entity_id];
        const last=samps[samps.length-1];
        if(!last||last.t!==tLabel) samps.push({t:tLabel,v:pw});
        if(samps.length>48) samps.splice(0,samps.length-48);
      }
    }
    if(json!==this._prevJson){
      this._prevJson=json;this._render();
      const now=Date.now(),thr=this._histLastFetch===0?5000:300000;
      if(now-this._histLastFetch>thr){this._histLastFetch=now;this._fetchHistory();}
    }
  }

  async _fetchHistory(){
    if(!this._hass) return;
    const st=this._hass.states['sensor.cloudems_boiler_status'];
    const boilers=st?.attributes?.boilers??[];
    for(const b of boilers){
      const eid=b.entity_id;
      if(this._historyLoading[eid]) continue;
      this._historyLoading[eid]=true;
      try{
        const end=new Date(),start=new Date(end-4*3600000);
        const slug=(b.label||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'');
        const tEid=`sensor.cloudems_boiler_${slug}_temp`;
        const pEid=`sensor.cloudems_boiler_${slug}_power`;
        const parse=arr=>{if(!arr?.[0]?.length)return[];const raw=arr[0].filter(s=>!isNaN(parseFloat(s.s??s.state??'')));const step=Math.max(1,Math.floor(raw.length/24));return raw.filter((_,i)=>i%step===0).slice(-24).map(s=>{const d=new Date(s.lc??s.last_changed??0);return{t:d.getHours()+':'+String(d.getMinutes()).padStart(2,'0'),v:parseFloat(s.s??s.state)};});};
        const url=e=>`history/period/${start.toISOString()}?filter_entity_id=${e}&minimal_response=true&no_attributes=true&end_time=${end.toISOString()}`;
        const [rt,rp]=await Promise.all([this._hass.callApi('GET',url(tEid)).catch(()=>null),this._hass.callApi('GET',url(pEid)).catch(()=>null)]);
        if(rt?.[0]?.length)this._history[eid]=parse(rt);
        if(rp?.[0]?.length){
          this._historyPower[eid]=parse(rp);
        } else {
          // Power sensor has no recorder history yet (all zeros = state unchanged = not recorded)
          // Build synthetic history from in-memory samples collected by the card
          if(!this._powerSamples) this._powerSamples={};
          if(!this._powerSamples[eid]) this._powerSamples[eid]=[];
          // Samples are added in _samplePower() — just use whatever we have
          if(this._powerSamples[eid].length>1) this._historyPower[eid]=[...this._powerSamples[eid]];
        }
        this._render();
      }catch(_){}
      this._historyLoading[eid]=false;
    }
  }

  _setBoostThreshold(entityId, minutes){
    if(!this._hass||!minutes) return;
    const mins = parseInt(minutes);
    if(isNaN(mins)||mins<10||mins>300) return;
    // Sla op als cloudems config update via HA input_number fallback
    const inputId = `number.cloudems_boiler_boost_threshold`;
    if(this._hass.states[inputId]){
      this._hass.callService('number','set_value',{entity_id:inputId,value:mins}).catch(()=>{});
    } else {
      // Persistent notification als fallback
      this._hass.callService('persistent_notification','create',{
        title:'CloudEMS Boost-drempel',
        message:`Boost-drempel ingesteld op ${mins} min voor ${entityId}. Herstart CloudEMS om te activeren.`,
        notification_id:'cloudems_boost_threshold',
      }).catch(()=>{});
    }
  }
  _adjustSetpoint(eid,delta){if(!this._hass||!eid)return;const st=this._hass.states[eid];const cur=this._optimisticSp?.[eid]??parseFloat(st?.attributes?.temperature??53);const t=Math.max(35,Math.min(80,cur+delta));if(!this._optimisticSp)this._optimisticSp={};this._optimisticSp[eid]=t;this._render();this._hass.callService('cloudems','boiler_send_now',{entity_id:eid,on:true,setpoint_c:t}).catch(()=>this._hass.callService('water_heater','set_temperature',{entity_id:eid,temperature:t}));}
  _setSetpoint(eid,temp){if(!this._hass||!eid)return;if(!this._optimisticSp)this._optimisticSp={};this._optimisticSp[eid]=temp;this._render();this._hass.callService('cloudems','boiler_send_now',{entity_id:eid,on:true,setpoint_c:temp}).catch(()=>this._hass.callService('water_heater','set_temperature',{entity_id:eid,temperature:temp}));}

  _renderLiveTab(b,cfg,hass,statusSensor){
    const labelSlug=(b.label||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/,'');
    const eidSlug=(b.entity_id||'').split('.').pop().replace(/-/g,'_');
    const recT=hass.states[`sensor.cloudems_boiler_${labelSlug}_temp`];
    const recP=hass.states[`sensor.cloudems_boiler_${labelSlug}_power`];
    const tempC=b.temp_c??(isNaN(parseFloat(recT?.state))?null:parseFloat(recT?.state));
    const vbSt=hass.states[`water_heater.cloudems_boiler_${labelSlug}`]??hass.states[`water_heater.cloudems_boiler_${eidSlug}`];
    const vbSp=this._optimisticSp?.[b.entity_id]??vbSt?.attributes?.temperature??null;
    const setpoint=vbSp??b.active_setpoint_c??b.setpoint_c??60;
    const maxSp=b.hardware_max_c||b.max_setpoint_boost_c||Math.max(b.max_setpoint_green_c||0,b.setpoint_c||60,75);
    const recPow=recP&&recP.state!=='unavailable'&&recP.state!=='unknown'?parseFloat(recP.state):null;
    const powerW=b.current_power_w??(isNaN(recPow)?null:recPow)??0;
    // v5.5.465: gebruik geleerde waarden indien beschikbaar, anders config-defaults
    const _learned = b?.shower_learned || {};
    const _learnedFlow = b?.shower_flow_learned;
    const _learnedDur  = b?.shower_duration_learned;
    const _learnedL    = b?.shower_liters_learned;
    const coldT   = cfg.cold_water_temp;
    const showerT = cfg.shower_temp;
    const flowLpm = _learnedFlow ?? cfg.shower_liters_per_min;
    const durMin  = _learnedDur  ?? cfg.shower_duration_min;
    const _isLearned = !!(_learnedFlow || _learnedDur);
    // Use learned or configured tank liters
    const tankL=cfg.tank_liters>0?cfg.tank_liters:(b.tank_liters_active||80);
    const safeT=tempC??setpoint;
    const usableL=calcUsableWater(safeT,showerT,coldT,tankL);
    const showers=calcShowers(usableL,durMin,flowLpm);
    // Beschikbare thermische energie in kWh
    const storedKwh = tempC!=null ? Math.max(0, (tankL*(tempC-coldT)*1.163)/1000) : null;
    const usableKwh = storedKwh!=null ? Math.max(0, (usableL*(Math.max(0,safeT-coldT))*1.163)/1000) : null;
    const fillPct=tempC!=null?clamp((tempC-coldT)/(maxSp-coldT),.05,1):.5;
    const spPct=clamp((setpoint-coldT)/(maxSp-coldT),0,1);
    const usablePct=clamp(usableL/(tankL*2),0,1);
    const spColor=tempToColor(setpoint);
    const cop=b.cop_at_current_temp;
    // Gebruik history direct van sensor attributen ipv HA recorder API
    const _buildHist = (arr) => arr.length >= 2
      ? arr.map(pt => { const d = new Date(pt.t*1000); return {t:d.getHours()+':'+String(d.getMinutes()).padStart(2,'0'),v:pt.v}; })
      : null;
    const hist  = _buildHist(b.temp_history  || []) || this._history[b.entity_id]         || null;
    const histP = _buildHist(b.power_history || []) || (this._historyPower||{})[b.entity_id] || (this._powerSamples?.[b.entity_id]?.length > 1 ? this._powerSamples[b.entity_id] : null);

    // Warmtebron
    const wbSt=hass.states['sensor.cloudems_goedkoopste_warmtebron'];
    const wbHtml=wbSt?`<div class="warmtebron"><div style="display:flex;align-items:center;gap:6px;margin-bottom:5px">
      <span>${wbSt.state==='gas'?'🔥':'⚡'}</span>
      <span style="font-size:11px;font-weight:700;color:${wbSt.state==='gas'?'#ff8040':'#4ade80'}">${wbSt.state==='gas'?'Gas goedkoper':'Stroom goedkoper'}</span></div>
      <div style="display:grid;grid-template-columns:1fr auto;gap:2px 10px;font-size:11px;color:#6b7280">
        <span>🔥 Gas/kWh warmte</span><span style="font-family:monospace">${fmtC(wbSt.attributes?.gas_per_kwh_heat)}</span>
        <span>⚡ Stroom/kWh warmte</span><span style="font-family:monospace">${fmtC(wbSt.attributes?.elec_boiler_per_kwh_heat)}</span>
      </div></div>`:'';

    // Virtual thermostat control
    const vtHtml=vbSt?`<div class="vtherm-ctrl">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span style="font-size:11px;font-weight:600;color:rgba(255,255,255,.6)">🌡️ Virtuele thermostaat</span>
        <span style="font-size:10px;color:rgba(255,255,255,.35)">${vbSt.attributes?.hvac_action||vbSt.state||'—'}</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <button onclick="this.getRootNode().host._adjustSetpoint('${b.entity_id}', -1)" style="width:28px;height:28px;border-radius:50%;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);color:#fff;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center">−</button>
        <div style="flex:1;text-align:center">
          <div style="font-size:20px;font-weight:700;color:#ffd600;font-family:monospace">${vbSp!=null?vbSp.toFixed(0)+'°C':'—'}</div>
          <div style="font-size:9px;color:rgba(255,255,255,.35);margin-top:1px">Setpoint · Nu: ${tempC!=null?tempC.toFixed(1)+'°C':'—'}</div>
        </div>
        <button onclick="this.getRootNode().host._adjustSetpoint('${b.entity_id}', +1)" style="width:28px;height:28px;border-radius:50%;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);color:#fff;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center">+</button>
      </div>
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
        ${[{l:'Nacht',v:45},{l:'Normaal',v:b.max_setpoint_green_c||53},{l:'PV-boost',v:Math.round(maxSp)}].map(p=>`<button onclick="this.getRootNode().host._setSetpoint('${b.entity_id}',${p.v})" style="flex:1;padding:4px 6px;border-radius:6px;border:1px solid rgba(255,255,255,.12);background:${vbSp!=null&&Math.round(vbSp)===p.v?'rgba(255,214,0,.15)':'rgba(255,255,255,.04)'};color:${vbSp!=null&&Math.round(vbSp)===p.v?'#ffd600':'rgba(255,255,255,.5)'};font-size:10px;cursor:pointer">${p.l}<br><span style="font-size:9px;opacity:.7">${p.v}°</span></button>`).join('')}
      </div></div>`:'';

    return `
      <div class="hero">
        <div class="tank-wrap">${buildTankSVG(fillPct,tempC)}<span class="tank-label">${tankL}L</span>${storedKwh!=null?`<span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:rgba(255,255,255,.45);">${storedKwh.toFixed(2)} kWh</span>`:''}</div>
        <div class="stats-col">
          <div><div class="temp-label">Huidige temperatuur</div>
            <div class="temp-big"><span class="temp-val" id="tv">${tempC!=null?tempC.toFixed(1):'—'}</span>${tempC!=null?'<span class="temp-unit">°C</span>':''}</div></div>
          ${(()=>{const _TTB=window.CloudEMSTooltip;
            const _ttSp=_TTB?_TTB.html('bl-sp','Setpoint',[
              {label:'Huidig',     value:setpoint.toFixed(0)+'°C'},
              {label:'Max (hw)',   value:maxSp?maxSp.toFixed(0)+'°C':'—'},
              {label:'Modus',      value:b.actual_mode||b.control_mode||'—'},
              {label:'Ramp',       value:b.ramp_setpoint_c?b.ramp_setpoint_c.toFixed(0)+'°C':'—',dim:true},
            ],{footer:'Setpoint aangepast door PV-surplus, prijs en modus'}):{wrap:'',tip:''};
            const _ttPow=_TTB?_TTB.html('bl-pow','Vermogen',[
              {label:'Vermogen nu', value:powerW.toFixed(0)+' W'},
              {label:'Nominaal',    value:b.power_w?b.power_w.toFixed(0)+' W':'—'},
              {label:'Is aan',      value:b.is_on?'✅ Ja':'❌ Nee'},
            ],{trusted:!!b.energy_sensor}):{wrap:'',tip:''};
            return`
          <div class="sp-row" style="position:relative;cursor:default" ${_ttSp.wrap}><span>🎯</span><div style="flex:1">
            <div style="display:flex;justify-content:space-between"><span class="sp-text">Setpoint</span><span class="sp-val">${setpoint.toFixed(0)}°C</span></div>
            <div class="sp-bar-wrap"><div class="sp-bar" style="width:${spPct*100}%;background:${spColor}"></div></div></div>${_ttSp.tip}</div>
          <div class="sp-row" style="border-color:rgba(255,180,0,.2);position:relative;cursor:default" ${_ttPow.wrap}><span>⚡</span><div style="flex:1">
            <div style="display:flex;justify-content:space-between"><span class="sp-text">Vermogen</span><span class="sp-val" style="color:${powerW>50?'#ffd600':'rgba(255,255,255,.4)'}">${powerW.toFixed(0)} W</span></div>
            <div class="sp-bar-wrap"><div class="sp-bar" style="width:${powerW>50?clamp(powerW/(b.power_w||1500)*100,2,100):0}%;background:linear-gradient(90deg,#ff8040,#ffd600)"></div></div></div>${_ttPow.tip}</div>`;
          })()}
        </div>
      </div>
      ${wbHtml}
      ${vtHtml}
      <div class="metrics">
        ${(()=>{const _TTB=window.CloudEMSTooltip;
          const _ttShw=_TTB?_TTB.html('bl-shw','Beschikbare douches',[
            {label:'Berekend',  value:showers+' douches'},
            {label:'Tankinhoud',value:tankL+' L ('+( cfg.tank_liters>0?'config':b.tank_liters_learned?'geleerd':'standaard')+')'},
            {label:'Per douche',value:(_learnedL?_learnedL.toFixed(0):(durMin*flowLpm).toFixed(0))+' L'+(_isLearned?' ✓':'')+'  ('+durMin.toFixed(1)+'min × '+flowLpm.toFixed(1)+' L/min)'},
            {label:'Douchetem.',value:showerT+'°C'},
            {label:'Koud water',value:coldT+'°C'},
          ],{footer:'Berekend op basis van beschikbaar warm water boven douchetemperatuur'}):{wrap:'',tip:''};
          const _ttLit=_TTB?_TTB.html('bl-lit','Beschikbare liters',[
            {label:'Liters',    value:usableL+' L @ '+showerT+'°C'},
            {label:'Tanktemp.', value:tempC!=null?tempC.toFixed(1)+'°C':'—'},
            {label:'Setpoint',  value:setpoint.toFixed(0)+'°C'},
            {label:'Formule',   value:'Tank × (T−T_douche) / (T_setpoint−T_koud)',dim:true},
          ]):{wrap:'',tip:''};
          const _ttCop=_TTB?_TTB.html('bl-cop',cop?'COP nu':'Geladen %',[
            cop?{label:'COP',value:cop.toFixed(2)}:{label:'Geladen %',value:tempC!=null?clamp(Math.round((tempC-coldT)/(setpoint-coldT)*100),0,100)+'%':'—'},
            {label:'Tanktemp.',value:tempC!=null?tempC.toFixed(1)+'°C':'—'},
            {label:'Setpoint', value:setpoint.toFixed(0)+'°C'},
            {label:'Uitleg',   value:cop?'Warmte output / elektrisch vermogen':'(T_huidig−T_koud) / (T_setpoint−T_koud)',dim:true},
          ]):{wrap:'',tip:''};
          return`
        <div class="metric" style="position:relative;cursor:default" ${_ttShw.wrap}><span class="metric-icon">🚿</span><span class="metric-val accent" id="sv">${showers}</span><span class="metric-label">Douches</span>${_ttShw.tip}</div>
        <div class="metric" style="position:relative;cursor:default" ${_ttLit.wrap}><span class="metric-icon">💧</span><span class="metric-val blue" id="lv">${usableL}</span><span class="metric-label">Liter @ ${showerT}°C</span>${_ttLit.tip}</div>
        <div class="metric" style="position:relative;cursor:default" ${_ttCop.wrap}><span class="metric-icon">${cop?'🌡️':'⏱️'}</span><span class="metric-val green">${cop?cop.toFixed(1):(tempC!=null?clamp(Math.round((tempC-coldT)/(setpoint-coldT)*100),0,100):'—')}</span><span class="metric-label">${cop?'COP':'Geladen %'}</span>${_ttCop.tip}</div>`; })()}
      </div>
      <div class="graphs">
        <div class="dual-graph">
          <div><div class="graph-title">🌡️ Temperatuur (4u)</div>${buildLine(hist?[...hist,{t:'nu',v:tempC??safeT}]:null,tempToColor(safeT),'T')}</div>
          <div><div class="graph-title">⚡ Vermogen (4u)</div>${buildLine(histP?[...histP,{t:'nu',v:powerW}]:null,'#ffd600','P')}</div>
        </div>
        <div class="donut-row" style="margin-top:16px">
          <div class="donut-wrap">${buildDonut(usablePct,tempToColor(safeT))}<div class="donut-center"><span class="donut-big" id="dv">${usableL}</span><span class="donut-small">liter</span></div></div>
          <div class="donut-info">
            <div class="donut-row-item"><span class="donut-key">🚿 Per douche</span><span class="donut-v">${(_learnedL?_learnedL.toFixed(0):(durMin*flowLpm).toFixed(0))} L${_isLearned?' ✓':''}</span></div>
            <div class="donut-row-item"><span class="donut-key">⏱️ Douchetijd</span><span class="donut-v">${durMin.toFixed(1)} min${_isLearned?' ✓':''}</span></div>
            <div class="donut-row-item"><span class="donut-key">🌡️ Koud water</span><span class="donut-v">${coldT}°C</span></div>
            <div class="donut-row-item"><span class="donut-key">🧮 Tankvolume</span><span class="donut-v">${tankL} L ${cfg.tank_liters>0?'(config)':b.tank_liters_learned?'(geleerd)':'(standaard)'}</span></div>
          </div>
        </div>
      </div>`;
  }

  _renderLerenTab(b,groups){
    // Find group data for this boiler
    const grp=groups?.find(g=>g.boilers?.some(gb=>gb.entity_id===b.entity_id));
    const gb=grp?.boilers?.find(gb=>gb.entity_id===b.entity_id)||{};
    const tankL=b.tank_liters_active||80;
    const tankLearned=b.tank_liters_learned;
    const tankConfig=b.tank_liters_config;
    const rampSp=b.ramp_setpoint_c;
    const rampMax=b.ramp_max_c||65;
    const rampGreen=b.max_setpoint_green_c||53;
    const heatRate=gb.heat_rate_c_h;
    const mtsLearned=gb.minutes_to_heat;
    const mtsCalc=b.minutes_to_setpoint;
    const ds=gb.demand_boost_stats;

    // Ramp visualization
    const rampSteps=[];
    const stepC=b.cheap_ramp_step_c||5;
    for(let sp=rampGreen;sp<=rampMax+0.5;sp+=stepC){rampSteps.push(sp);}
    const rampViz=rampSteps.length>1?`<div class="ramp-viz">
      ${rampSteps.map(sp=>{const done=rampSp!=null&&sp<rampSp-0.5;const act=rampSp!=null&&Math.abs(sp-rampSp)<0.5+stepC*0.1;return `<div class="ramp-step ${done?'done':act?'active':''}"><div class="ramp-label" style="font-size:7px;color:${act?'#a78bfa':done?'#4ade80':'#4b5563'}">${sp.toFixed(0)}°</div></div>`}).join('')}</div>`:'';

    // Demand boost ratio bar
    let dsHtml='';
    if(ds&&ds.total>0){
      const gPct=Math.round(ds.ratio*100);
      dsHtml=`<div class="kv-grid" style="margin-top:8px">
        <span class="kv-key">✅ Correct</span><span class="kv-val good">${ds.correct}×</span>
        <span class="kv-key">❌ Overbodig</span><span class="kv-val warn">${ds.incorrect}×</span>
        <span class="kv-key">Nauwkeurigheid</span><span class="kv-val ${gPct>=70?'good':gPct>=50?'info':'warn'}">${gPct}%</span>
        <span class="kv-key">Geleerde drempel</span><span class="kv-val info">${ds.threshold_min?.toFixed(0)||90} min</span>
        <div class="ratio-bar"><div class="ratio-good" style="width:${gPct}%"></div><div class="ratio-bad" style="width:${100-gPct}%"></div></div>
        ${ds.total<10?`<span style="font-size:10px;color:#6b7280;grid-column:1/-1;font-style:italic">📊 ${ds.total}/10 metingen — nog aan het leren</span>`:''}
      </div>`;
    } else {
      dsHtml=`<p style="font-size:11px;color:#4b5563;font-style:italic;margin-top:6px">Nog geen demand-boost metingen.</p>`;
    }

    return `<div class="learn-section">
      <div class="learn-title">💧 Tankvolume</div>
      <div class="kv-grid">
        <span class="kv-key">Actief gebruikt</span><span class="kv-val info">${tankL.toFixed(0)} L ${tankConfig?'(config)':tankLearned?'(geleerd)':'(standaard 80L)'}</span>
        ${tankConfig?`<span class="kv-key">Geconfigureerd</span><span class="kv-val">${tankConfig.toFixed(0)} L</span>`:''}
        ${tankLearned?`<span class="kv-key">Geleerd via EMA</span><span class="kv-val good">${tankLearned.toFixed(0)} L</span>`:`<span class="kv-key">Geleerd via EMA</span><span class="kv-val" style="color:#4b5563">nog niet</span>`}
        <span class="kv-key">Hoe te leren</span><span class="kv-val" style="color:#4b5563;font-size:10px">kWh ÷ (COP × 0.001163 × ΔT)</span>
      </div>

      <div class="learn-title" style="margin-top:14px">⚡ Opwarmsnelheid WP</div>
      <div class="kv-grid">
        ${heatRate?`<span class="kv-key">Geleerd °C/uur</span><span class="kv-val good">${heatRate.toFixed(1)} °C/h</span>`:`<span class="kv-key">Geleerd °C/uur</span><span class="kv-val" style="color:#4b5563">nog niet</span>`}
        ${mtsLearned!=null?`<span class="kv-key">Minuten tot setpoint</span><span class="kv-val ${mtsLearned>90?'warn':'good'}">${mtsLearned.toFixed(0)} min (geleerd)</span>`:''}
        ${mtsCalc!=null?`<span class="kv-key">ETA (berekend)</span><span class="kv-val">${mtsCalc.toFixed(0)} min</span>`:''}
      </div>

      ${b.boiler_type==='hybrid'?`
      <div class="learn-title" style="margin-top:14px">📈 Gradueel setpoint (ramp)</div>
      <div class="kv-grid">
        <span class="kv-key">Huidig ramp-setpoint</span><span class="kv-val purple">${rampSp!=null?rampSp.toFixed(0)+'°C':'53°C (GREEN basis)'}</span>
        <span class="kv-key">GREEN basis</span><span class="kv-val">${rampGreen}°C</span>
        <span class="kv-key">Ramp maximum</span><span class="kv-val">${rampMax}°C</span>
        <span class="kv-key">Stap</span><span class="kv-val">${stepC}°C per 30 min AAN</span>
      </div>
      ${rampViz}
      <p style="font-size:10px;color:#4b5563;margin-top:6px;line-height:1.5">Bij HA/internet-uitval blijft de boiler op het ramp-setpoint staan (niet op 75°C).</p>`:''}

      <div class="learn-title" style="margin-top:14px">🔮 Demand-boost leren</div>
      <p style="font-size:11px;color:#6b7280;line-height:1.5">CloudEMS boost alleen als WP te traag is én warm water verwacht wordt. Na elke boost leert het of de beslissing correct was (temperatuurdip gedetecteerd).</p>
      ${dsHtml}

      <div class="learn-title" style="margin-top:14px">⚙️ Boost-drempel instellen</div>
      <p style="font-size:11px;color:#6b7280;line-height:1.5">Minimale minuten tot setpoint voordat CloudEMS een demand-boost activeert. Lager = eerder boosten, hoger = conservatiever.</p>
      <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
        <input type="range" min="30" max="180" step="5"
          value="${ds?.threshold_min?.toFixed(0)||90}"
          style="flex:1"
          id="boost-thresh-${b.entity_id.replace(/[^a-z0-9]/gi,'_')}"
          oninput="this.nextElementSibling.textContent=this.value+' min'">
        <span style="font-size:12px;color:#a78bfa;min-width:52px;text-align:right">${ds?.threshold_min?.toFixed(0)||90} min</span>
      </div>
      <button onclick="this.getRootNode().host._setBoostThreshold('${b.entity_id}',document.getElementById('boost-thresh-${b.entity_id.replace(/[^a-z0-9]/gi,'_')}')?.value)"
        style="margin-top:6px;font-size:11px;padding:4px 12px;border-radius:6px;border:1px solid rgba(167,139,250,0.3);background:rgba(167,139,250,0.1);color:#a78bfa;cursor:pointer">
        Instellen
      </button>
    </div>`;
  }

  _renderGezondheidTab(b,groups){
    const grp=groups?.find(g=>g.boilers?.some(gb=>gb.entity_id===b.entity_id));
    const gb=grp?.boilers?.find(gb=>gb.entity_id===b.entity_id)||{};
    const leg=gb.legionella||{};
    const scalePct=gb.scale_score_pct||0;
    const anodePct=gb.anode_wear_pct||0;
    const anodeKwh=gb.anode_kwh||0;
    const cop=b.cop_at_current_temp;
    const legDays=leg.days_since;
    const legNeeded=leg.needed;
    const legDeadline=leg.deadline;
    const legPlanned=leg.planned_hour>=0?`${leg.planned_hour}:00`:'—';
    const legConfPct=leg.confirm_pct||0;

    const legCls=legDeadline?'leg-danger':legNeeded?'leg-warn':'leg-ok';
    const legIcon=legDeadline?'🚨':legNeeded?'⚠️':'✅';
    const legViaBoost=leg.via_boost??false;
    const legTxt=legDeadline?'Legionella DRINGEND nodig!':legNeeded?`Gepland om ${legPlanned}`:`${legDays?.toFixed(0)||'?'} dagen geleden${legViaBoost?' · via BOOST ⚡':''}`;  // FIX 6

    // v4.6.438: Bereken de volgende geplande datum voor legionella
    const LEGIONELLA_INTERVAL = 14; // dagen
    const legNextDate = (() => {
      if (!legDays && legDays !== 0) return null;
      const daysLeft = Math.max(0, LEGIONELLA_INTERVAL - legDays);
      if (daysLeft === 0) return 'Vandaag';
      const d = new Date(); d.setDate(d.getDate() + daysLeft);
      return d.toLocaleDateString('nl-NL', {weekday:'short', day:'numeric', month:'short'});
    })();
    const legNextHourTxt = legPlanned !== '—' && (legNeeded || legDeadline)
      ? ` om ${legPlanned}` : '';

    return `<div class="health-section">
      <div class="leg-status ${legCls}">
        <span style="font-size:22px">${legIcon}</span>
        <div style="flex:1">
          <div style="font-size:12px;font-weight:700;color:#e2e8f0">Legionella preventie</div>
          <div style="font-size:11px;color:#6b7280">${legTxt}</div>
          ${!legNeeded && !legDeadline && legNextDate ? `<div style="font-size:10px;color:#4b5563;margin-top:2px">📅 Volgende cyclus: <strong style="color:#7dd3fc">${legNextDate}${legNextHourTxt}</strong></div>` : ''}
          ${legNeeded && legPlanned !== '—' ? `<div style="font-size:10px;color:#fbbf24;margin-top:2px">⏰ Gepland vandaag om <strong>${legPlanned}</strong> (goedkoopste uur)</div>` : ''}
          ${legConfPct>0?`<div style="margin-top:4px"><div class="health-bar" style="width:100%"><div class="health-bar-fill" style="width:${legConfPct}%;background:#7dd3fc"></div></div><div style="font-size:9px;color:#4b5563;margin-top:2px">${legConfPct.toFixed(0)}% bevestigd (${leg.confirm_ticks||0}s)</div></div>`:''}
        </div>
      </div>

      <!-- Legionella weekschema -->
      ${(()=>{
        const DAYS=['Ma','Di','Wo','Do','Vr','Za','Zo'];
        const interval=14;
        const daysSince=legDays??interval;
        const today=new Date().getDay();
        const todayIdx=today===0?6:today-1;
        const lastIdx=((todayIdx-Math.round(daysSince))%7+7)%7;
        const daysLeft=Math.max(0,interval-Math.round(daysSince||0));
        const nextIdx=((todayIdx+daysLeft)%7);
        const cells=DAYS.map((d,i)=>{
          const isToday=i===todayIdx, isLast=i===lastIdx&&daysSince!=null&&!legNeeded;
          const isNext=i===nextIdx&&daysLeft>0&&!legNeeded;
          const isCurrent=legNeeded&&i===todayIdx;
          const bg=isCurrent?'rgba(251,191,36,0.25)':isNext?'rgba(125,211,252,0.15)':isLast?'rgba(74,222,128,0.12)':isToday?'rgba(255,255,255,0.06)':'rgba(255,255,255,0.02)';
          const col=isCurrent?'#fbbf24':isNext?'#7dd3fc':isLast?'#4ade80':isToday?'#e2e8f0':'#4b5563';
          const icon=isCurrent?'⚠️':isNext?'🎯':isLast?'✅':'';
          return `<div style="flex:1;text-align:center;padding:6px 2px;border-radius:6px;background:${bg}"><div style="font-size:9px;font-weight:700;color:${col}">${d}</div><div style="font-size:10px;margin-top:1px">${icon||(isToday?'●':'·')}</div></div>`;
        }).join('');
        return `<div style="margin:8px 0 12px;padding:10px 12px;background:rgba(125,211,252,0.05);border-radius:10px;border:1px solid rgba(125,211,252,0.1)"><div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#374151;margin-bottom:6px">📅 Weekschema legionella</div><div style="display:flex;gap:3px">${cells}</div><div style="font-size:10px;color:#4b5563;margin-top:6px;display:flex;gap:10px;flex-wrap:wrap"><span>✅ Laatste</span><span>🎯 Gepland</span><span>⚠️ Vandaag</span></div></div>`;
      })()}

      <div class="health-item">
        <span class="health-icon">🦠</span>
        <div class="health-body">
          <div class="health-label">Kalkindex</div>
          <div class="health-sub">Gebaseerd op opwarmsnelheid vs baseline · ${b.water_hardness_dh||14}°dH</div>
          <div class="health-bar"><div class="health-bar-fill" style="width:${Math.min(scalePct,100)}%;background:${scalePct>70?'#f87171':scalePct>40?'#fb923c':'#4ade80'}"></div></div>
        </div>
        <span class="health-val" style="color:${scalePct>70?'#f87171':scalePct>40?'#fb923c':'#4ade80'}">${scalePct.toFixed(0)}%</span>
      </div>

      <div class="health-item">
        <span class="health-icon">🔋</span>
        <div class="health-body">
          <div class="health-label">Anode-slijtage</div>
          <div class="health-sub">${anodeKwh.toFixed(0)} kWh verwarmd · drempel ${gb.anode_kwh_threshold||4000} kWh</div>
          <div class="health-bar"><div class="health-bar-fill" style="width:${Math.min(anodePct,100)}%;background:${anodePct>80?'#f87171':anodePct>60?'#fb923c':'#4ade80'}"></div></div>
        </div>
        <span class="health-val" style="color:${anodePct>80?'#f87171':anodePct>60?'#fb923c':'#4ade80'}">${anodePct.toFixed(0)}%</span>
      </div>

      ${cop?`<div class="health-item">
        <span class="health-icon">🌡️</span>
        <div class="health-body">
          <div class="health-label">COP nu</div>
          <div class="health-sub">Op buitentemperatuur ${b.outside_temp_c!=null?b.outside_temp_c.toFixed(0)+'°C':'?'}</div>
        </div>
        <span class="health-val" style="color:#7dd3fc">${cop.toFixed(2)}</span>
      </div>`:''}

      <div class="health-item">
        <span class="health-icon">💧</span>
        <div class="health-body">
          <div class="health-label">Cycle kWh</div>
          <div class="health-sub">Elektriciteit verbruikt deze verwarmingscyclus</div>
        </div>
        <span class="health-val" style="color:#fde047">${b.cycle_kwh?.toFixed(2)||'0.00'} kWh</span>
      </div>

      <!-- v4.6.438: Legionella weekschema — wanneer is de cyclus gedaan per dag -->
      <div style="margin-top:14px">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#374151;margin-bottom:8px">📅 Legionella schema (7 weken)</div>
        ${(() => {
          const hist = leg.history || [];
          const DAYS = ['Ma','Di','Wo','Do','Vr','Za','Zo'];
          const now = Date.now();
          // Bouw een 7×7 grid: 7 weken terug, 7 dagen per week
          const grid = Array.from({length:7}, (_,wi) =>
            Array.from({length:7}, (_,di) => {
              const daysAgo = (6-wi)*7 + (6-di);
              const ts = now - daysAgo * 86400000;
              const dateStr = new Date(ts).toISOString().slice(0,10);
              const done = hist.some(h => h.date === dateStr);
              return {done, daysAgo};
            })
          );
          const rows = grid.map((week, wi) => {
            const cells = week.map(({done, daysAgo}) => {
              const col = done ? '#1D9E75' : daysAgo < 7 && legNeeded ? '#fbbf24' : 'rgba(255,255,255,0.06)';
              const title = done ? '✓ Cyclus voltooid' : daysAgo === 0 ? 'Vandaag' : `${daysAgo}d geleden`;
              return `<div title="${title}" style="width:14px;height:14px;border-radius:2px;background:${col};cursor:default"></div>`;
            }).join('');
            return `<div style="display:flex;gap:3px">${cells}</div>`;
          }).join('');
          const dayLabels = DAYS.map(d => `<div style="width:14px;text-align:center;font-size:7px;color:#374151">${d}</div>`).join('');
          return `<div style="display:flex;gap:3px;margin-bottom:4px">${dayLabels}</div>
                  <div style="display:flex;flex-direction:column-reverse;gap:3px">${rows}</div>
                  <div style="display:flex;gap:12px;margin-top:6px;font-size:9px;color:#4b5563">
                    <span><span style="display:inline-block;width:8px;height:8px;border-radius:1px;background:#1D9E75;margin-right:3px"></span>Voltooid</span>
                    <span><span style="display:inline-block;width:8px;height:8px;border-radius:1px;background:#fbbf24;margin-right:3px"></span>Nodig</span>
                    <span><span style="display:inline-block;width:8px;height:8px;border-radius:1px;background:rgba(255,255,255,0.06);margin-right:3px"></span>Niet gedaan</span>
                  </div>`;
        })()}
      </div>
    </div>`;
  }

  _renderDoucheTab(b, showerStatus){
    const eid = b.entity_id||'';
    const ss  = showerStatus?.[eid]||{};
    const active  = ss.active||{};
    const last    = ss.last||null;
    const stats   = ss.stats||{};
    const hist    = ss.history||[];
    const lff     = ss.last_fun_fact||null;
    const fmtMin  = m=>m!=null?m.toFixed(1)+' min':'—';
    const fmtL    = l=>l!=null?l.toFixed(0)+' L':'—';
    const fmtEur  = e=>e!=null?'€'+e.toFixed(2):'—';
    const fmtCO2  = c=>c!=null?c.toFixed(0)+' g':'—';
    const fmtFlow = f=>f!=null?f.toFixed(1)+' L/min':'—';

    // Actieve sessie banner
    const activeBanner = active.running ? `
      <div style="background:rgba(96,165,250,.12);border:1px solid rgba(96,165,250,.3);border-radius:8px;padding:10px 14px;margin-bottom:10px;display:flex;align-items:center;gap:10px">
        <span style="font-size:18px;animation:pulse 1s infinite alternate">🚿</span>
        <div>
          <div style="font-size:12px;font-weight:700;color:#60a5fa">Douche bezig</div>
          <div style="font-size:11px;color:#94a3b8">${fmtMin(active.duration_min)} · ${fmtL(active.liters_so_far)} · ${fmtFlow(active.flow_l_min)}</div>
        </div>
      </div>` : '';

    // Laatste sessie
    const lastHtml = last ? `
      <div style="margin-bottom:12px">
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#64748b;margin-bottom:8px">Laatste douche</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
          ${[
            ['⏱ Duur',       fmtMin(last.duration_min)],
            ['💧 Liters',     fmtL(last.liters)],
            ['⚡ kWh',        last.energy_kwh?.toFixed(3)||'—'],
            ['💶 Kosten',     fmtEur(last.cost_eur)],
            ['🌱 CO₂',        fmtCO2(last.co2_gram)],
            ['🚿 Flow',       fmtFlow(last.flow_l_min)],
          ].map(([lbl,val])=>`
            <div style="background:rgba(255,255,255,0.04);border-radius:7px;padding:8px 10px;border:1px solid rgba(255,255,255,0.06)">
              <div style="font-size:10px;color:#64748b;margin-bottom:3px">${lbl}</div>
              <div style="font-size:13px;font-weight:700;color:#e2e8f0;font-family:monospace">${val}</div>
            </div>`).join('')}
        </div>
        ${lff ? `<div style="margin-top:8px;background:rgba(255,255,255,0.03);border-radius:8px;padding:10px 12px;border:1px solid rgba(255,255,255,0.06)">
          <div style="font-size:13px">${lff.rating}</div>
          <div style="font-size:11px;color:#94a3b8;margin-top:3px">${lff.message}</div>
        </div>` : ''}
      </div>` : '<div style="font-size:12px;color:#475569;margin-bottom:12px">Nog geen douche-sessies geregistreerd.</div>';

    // Statistieken
    const statsHtml = stats.sessions_total > 0 ? `
      <div style="margin-bottom:12px">
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#64748b;margin-bottom:8px">Gemiddelden (${stats.sessions_total} sessies)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">
          ${[
            ['⏱ Gem. duur', fmtMin(stats.avg_min)],
            ['💧 Gem. liters', fmtL(stats.avg_liters)],
            ['💶 Gem. kosten', fmtEur(stats.avg_cost_eur)],
          ].map(([lbl,val])=>`
            <div style="background:rgba(255,255,255,0.04);border-radius:7px;padding:8px 10px;border:1px solid rgba(255,255,255,0.06);text-align:center">
              <div style="font-size:10px;color:#64748b;margin-bottom:3px">${lbl}</div>
              <div style="font-size:12px;font-weight:700;color:#e2e8f0;font-family:monospace">${val}</div>
            </div>`).join('')}
        </div>
        ${stats.total_liters>0?`<div style="margin-top:8px;font-size:11px;color:#475569;text-align:center">Totaal ${stats.total_liters.toFixed(0)}L · ${stats.olympic_pool_pct?.toFixed(4)||0}% van een olympisch zwembad</div>`:''}
      </div>` : '';

    // Geschiedenis grafiek (bars)
    const histHtml = hist.length>1 ? `
      <div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#64748b;margin-bottom:8px">Geschiedenis</div>
        <div style="display:flex;align-items:flex-end;gap:3px;height:48px">
          ${hist.slice(-20).map(s=>{
            const maxM=Math.max(...hist.map(x=>x.duration_min));
            const pct=maxM>0?s.duration_min/maxM:0;
            const col=s.duration_min>15?'#f87171':s.duration_min>10?'#fb923c':'#4ade80';
            return `<div title="${s.duration_min.toFixed(1)} min · ${s.liters?.toFixed(0)||'?'}L · €${s.cost_eur?.toFixed(2)||'?'}" style="flex:1;height:${Math.max(4,pct*100)}%;background:${col};border-radius:2px 2px 0 0;min-width:4px;cursor:default"></div>`;
          }).join('')}
        </div>
        <div style="display:flex;justify-content:space-between;font-size:9px;color:#475569;margin-top:2px"><span>oudst</span><span>nieuwst</span></div>
      </div>` : '';

    return `<style>@keyframes pulse{from{opacity:.6}to{opacity:1}}</style>
      <div style="padding:2px 0">
        ${activeBanner}${lastHtml}${statsHtml}${histHtml}
      </div>`;
  }

  _renderThermischTab(b, groups){
    // Thermisch verlies, seizoen, gebruikspatroon per uur
    const grp = groups?.find(g=>g.boilers?.some(gb=>gb.entity_id===b.entity_id));
    const gb  = grp?.boilers?.find(gb=>gb.entity_id===b.entity_id)||{};
    const ls  = grp?.learn_status||{};

    // ── Thermisch verlies ──────────────────────────────────────────────
    const minCold   = gb.minutes_to_cold;
    const reheatMin = gb.reheat_eta_min;
    const heatRate  = gb.heat_rate_c_h||0;
    const lossRate  = gb.thermal_loss_c_h||0;

    const fmtMin = m => m==null?'—': m<120?(Math.round(m)+' min'):((m/60).toFixed(1)+' u');

    const thermHtml = (minCold!=null||reheatMin!=null||heatRate>0) ? `
      <div class="learn-title">🌡️ Thermisch verlies & voorspelling</div>
      <div class="kv-grid">
        <span class="kv-key">Verliessnelheid</span><span class="kv-val warn">${lossRate.toFixed(1)} °C/u</span>
        <span class="kv-key">Warm water koud over</span><span class="kv-val">${fmtMin(minCold)}</span>
        <span class="kv-key">Reheat ETA</span><span class="kv-val">${fmtMin(reheatMin)}</span>
        <span class="kv-key">Opwarmsnelheid</span><span class="kv-val good">${heatRate>0?heatRate.toFixed(1)+' °C/u':'—'}</span>
      </div>` : `<div class="learn-title">🌡️ Thermisch verlies</div>
      <p style="font-size:11px;color:#4b5563;font-style:italic">Nog geen leerdata. Beschikbaar na enkele verwarmingscycli.</p>`;

    // ── Seizoen & cascade-info ─────────────────────────────────────────
    const seasonIcon = {'summer':'☀️','winter':'❄️'}[grp?.season]||'🍂';
    const seasonHtml = grp ? `
      <div class="learn-title" style="margin-top:14px">🗓️ Seizoen & cascadegroep</div>
      <div class="kv-grid">
        <span class="kv-key">Seizoen</span><span class="kv-val">${seasonIcon} ${grp.season||'—'}</span>
        <span class="kv-key">Modus</span><span class="kv-val info">${grp.mode||'—'}</span>
        <span class="kv-key">Leveringsboiler</span><span class="kv-val ${grp.delivery_learned?'good':'warn'}">${grp.delivery_learned?'✅ geleerd':'⏳ leren ('+((ls.events||0))+' cycli)'}</span>
        ${gb.cycle_kwh?`<span class="kv-key">Cyclus verbruik</span><span class="kv-val">${parseFloat(gb.cycle_kwh).toFixed(2)} kWh</span>`:''}
      </div>` : '';

    // ── Gebruikspatroon per uur ────────────────────────────────────────
    const hourly = ls.hourly_demand;
    let patternHtml = `<div class="learn-title" style="margin-top:14px">📊 Gebruikspatroon per uur</div>`;
    if(hourly && hourly.length===24){
      const maxV = Math.max(...hourly, 0.001);
      const bars = hourly.map((v,h)=>{
        const pct = Math.round(v/maxV*100);
        const col = pct>70?'#f87171':pct>40?'#fb923c':'#4ade80';
        return `<div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
          <div style="width:100%;height:${Math.max(3,Math.round(pct*0.4))}px;background:${col};border-radius:2px 2px 0 0;min-height:3px"></div>
          ${h%6===0?`<span style="font-size:8px;color:#4b5563">${String(h).padStart(2,'0')}</span>`:'<span style="font-size:8px;color:transparent">·</span>'}
        </div>`;
      }).join('');
      patternHtml += `<div style="display:flex;align-items:flex-end;gap:1px;height:56px;padding:4px 0">${bars}</div>
        <p style="font-size:10px;color:#4b5563;margin-top:4px">Warm-watergebruik genormaliseerd per uur van de dag. Rood = piek.</p>`;
    } else {
      patternHtml += `<p style="font-size:11px;color:#4b5563;font-style:italic">Nog geen patroon beschikbaar. Wordt geleerd na ~2 weken gebruik.</p>`;
    }

    return `<div class="learn-section">${thermHtml}${seasonHtml}${patternHtml}</div>`;
  }

  _render(){
    const sh=this.shadowRoot;if(!sh)return;
    const hass=this._hass,cfg=this._cfg??{};
    if(!hass){sh.innerHTML=`<style>${S}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;return;}
    const st=hass.states['sensor.cloudems_boiler_status'];
    if(!st||st.state==='unavailable'){sh.innerHTML=`<style>${S}</style><div class="card"><div class="empty"><span class="empty-icon">🚿</span>Boiler sensor niet beschikbaar.</div></div>`;return;}
    const allB=st.attributes?.boilers??[];
    const groups=st.attributes?.groups??[];
    const showerStatus=st.attributes?.shower_status??{};
    if(!allB.length){sh.innerHTML=`<style>${S}</style><div class="card"><div class="empty"><span class="empty-icon">🚿</span>Geen boilers geconfigureerd.</div></div>`;return;}
    const idx=Math.min(this._boilerTab,allB.length-1);
    const b=allB[idx];
    const mode=(b.actual_mode||'').toLowerCase();
    const isOn=b.is_on??false;
    const powerW=b.current_power_w??0;
    const isHeating=b.is_heating??(powerW>50);
    const cop=b.cop_at_current_temp;
    const legDays=b.legionella_days;
    const rampSp=b.ramp_setpoint_c;

    let badgeCls='badge-off',badgeLbl='⚫ UIT';

    // v4.6.522: pauze-status
    const pausedUntil = b.boost_paused_until || 0;
    const isPaused    = pausedUntil > 0;
    const pauseRemSec = b.boost_paused_remaining_s || 0;
    const pauseRemaining = isPaused
      ? (pauseRemSec > 3600 ? `${(pauseRemSec/3600).toFixed(1)}u` : `${Math.ceil(pauseRemSec/60)}m`)
      : '';

    if(isPaused){badgeCls='badge-off';badgeLbl='⏸ GEPAUZEERD';}
    else if(isHeating&&mode.includes('boost')){badgeCls='badge-boost';badgeLbl='🔥 BOOST';}
    else if(isOn&&mode.includes('green')){
      badgeCls='badge-green';
      // FIX 4: toon ramp-setpoint als het afwijkt van de GREEN-basis
      const rampSp=b.ramp_setpoint_c;
      const greenBase=b.max_setpoint_green_c||53;
      badgeLbl=rampSp&&rampSp>greenBase+0.5?`🌿 GREEN · ${rampSp.toFixed(0)}°C`:'🌿 GREEN';
    }
    else if(isOn){badgeCls='badge-on';badgeLbl='🟢 AAN';}

    const boilerTabsHtml=allB.length>1?`<div class="boiler-tabs">${allB.map((bx,i)=>`<button class="boiler-tab ${i===idx?'active':''}" data-btab="${i}">${esc(bx.label||`Boiler ${i+1}`)}</button>`).join('')}</div>`:'';
    const ctabs=['live','leren','gezondheid','thermisch','douche','log'];
    const ctabLabels={'live':'⚡ Live','leren':'📚 Leren','gezondheid':'🏥 Gezondheid','thermisch':'🌡️ Thermisch','douche':'🚿 Douche','log':'📋 Log'};
    const ct=this._contentTab;

    let contentHtml='';
    if(ct==='live')     contentHtml=this._renderLiveTab(b,cfg,hass,st);
    else if(ct==='leren')    contentHtml=this._renderLerenTab(b,groups);
    else if(ct==='gezondheid') contentHtml=this._renderGezondheidTab(b,groups);
    else if(ct==='thermisch') contentHtml=this._renderThermischTab(b,groups);
    else if(ct==='douche')    contentHtml=this._renderDoucheTab(b,showerStatus);
    else contentHtml=`<div class="log-section">${buildDecisionsHtml(st.attributes?.log??[],b.label,b.entity_id)}</div>`;

    sh.innerHTML=`<style>${S}</style><div class="card"><div class="inner">
      ${boilerTabsHtml}
      <div class="hdr">
        <div class="hdr-icon">🚿</div>
        <div><div class="hdr-title">${esc(cfg.title)} · ${esc(b.label||'Boiler')}</div>
          <div class="hdr-sub">${esc(b.brand_label||b.boiler_type||'')} · ${b.tank_liters_active||cfg.tank_liters||80}L</div></div>
        ${(()=>{const _TTBadge=window.CloudEMSTooltip;
          const _ttBadge=_TTBadge?_TTBadge.html('bl-badge','Boiler status',[
            {label:'Status',    value:badgeLbl},
            {label:'Modus',     value:b.actual_mode||b.control_mode||'—'},
            {label:'Is aan',    value:isOn?'✅ Ja':'❌ Nee'},
            {label:'Verwarmt',  value:isHeating?'✅ Ja':'❌ Nee'},
            {label:'Ramp',      value:rampSp?rampSp.toFixed(0)+'°C':'—',dim:!rampSp},
            {label:'Pauze tot', value:isPaused&&pausedUntil?new Date(pausedUntil*1000).toLocaleTimeString('nl-NL',{hour:'2-digit',minute:'2-digit'}):'—',dim:!isPaused},
          ],{footer:'BOOST=snel laden | GREEN=PV/prijs-gestuurd | UIT=geen vraag'}):{wrap:'',tip:''};
          return`<span class="hdr-badge ${badgeCls}" style="position:relative;cursor:default" ${_ttBadge.wrap}>${badgeLbl}${_ttBadge.tip}</span>`; })()}
      </div>
      <div class="ctabs">${ctabs.map(t=>`<button class="ctab ${t===ct?'active':''}" data-ctab="${t}">${ctabLabels[t]}</button>`).join('')}</div>
      <div class="tab-panel active">${contentHtml}</div>
      ${ct==='live'?`<div class="footer-chips">
        <span class="chip ${mode.includes('boost')?'chip-boost':mode.includes('green')?'chip-green':'chip-off'}">${mode.includes('boost')?'🔥 BOOST':mode.includes('green')?'🌿 GREEN':'💤 '+mode}</span>
        ${powerW>50?`<span class="chip chip-power">⚡ ${powerW.toFixed(0)}W</span>`:''}
        ${cop?`<span class="chip chip-cop">COP ${cop.toFixed(2)}</span>`:''}
        ${rampSp&&rampSp>53?`<span class="chip chip-ramp">📈 Ramp ${rampSp.toFixed(0)}°C</span>`:''}
        ${legDays!=null?`<span class="chip ${legDays<5?'chip-cop':'chip-warn'}">🦠 Leg. ${legDays.toFixed(0)}d</span>`:''}
        ${b.stall_active?`<span class="chip chip-verify">⚠️ Stall</span>`:''}
      </div>
      <div class="action-section">
        <div class="action-section-title">Handmatige sturing</div>
        <div class="action-row">
          <button class="action-btn btn-send" data-action="send_now" data-eid="${b.entity_id}" title="Nu direct warm water aanvragen">
            <span class="btn-icon">🚿</span>
            <span class="btn-lbl">Nu laden</span>
            <span class="btn-sub">direct BOOST</span>
          </button>
          ${isPaused || mode.includes('green')
            ? `<button class="action-btn btn-resume" data-action="resume_boost" data-eid="${b.entity_id}" title="Automatische CloudEMS sturing hervatten">
                <span class="btn-icon">🔄</span>
                <span class="btn-lbl">Hervatten</span>
                <span class="btn-sub">${isPaused?'pauze ('+pauseRemaining+')':'was GREEN'}</span>
               </button>`
            : `<button class="action-btn btn-green" data-action="set_green" data-eid="${b.entity_id}" title="Schakel naar GREEN — laadt alleen op PV-surplus of lage prijs">
                <span class="btn-icon">🌿</span>
                <span class="btn-lbl">GREEN</span>
                <span class="btn-sub">eco modus</span>
               </button>`
          }
          ${!isPaused
            ? `<div class="pause-group">
                 <button class="action-btn btn-pause" data-action="pause_boost" data-eid="${b.entity_id}" data-seconds="3600" title="BOOST pauzeren voor 1 uur">
                   <span class="btn-icon">⏸</span>
                   <span class="btn-lbl">1 uur</span>
                   <span class="btn-sub">pauze</span>
                 </button>
                 <button class="action-btn btn-pause" data-action="pause_boost" data-eid="${b.entity_id}" data-seconds="7200" title="BOOST pauzeren voor 2 uur">
                   <span class="btn-icon">⏸</span>
                   <span class="btn-lbl">2 uur</span>
                   <span class="btn-sub">pauze</span>
                 </button>
                 <button class="action-btn btn-pause" data-action="pause_boost" data-eid="${b.entity_id}" data-seconds="14400" title="BOOST pauzeren voor 4 uur">
                   <span class="btn-icon">⏸</span>
                   <span class="btn-lbl">4 uur</span>
                   <span class="btn-sub">pauze</span>
                 </button>
               </div>`
            : ''
          }
        </div>
      </div>`:''}
    </div></div>`;

    // Animate counters (Live tab only)
    if(ct==='live'){requestAnimationFrame(()=>{
      const tempC=b.temp_c;
      const tankL=cfg.tank_liters>0?cfg.tank_liters:(b.tank_liters_active||80);
      const usableL=calcUsableWater(tempC??b.active_setpoint_c??60,cfg.shower_temp,cfg.cold_water_temp,tankL);
      const showers=calcShowers(usableL,cfg.shower_duration_min,cfg.shower_liters_per_min);
      const tv=sh.getElementById('tv');if(tv&&tempC!=null){const p=parseFloat(tv.textContent)||tempC;if(Math.abs(p-tempC)>.05)animateCounter(tv,p,tempC,600,1);else tv.textContent=tempC.toFixed(1);}
      const sv=sh.getElementById('sv');if(sv){const p=parseInt(sv.textContent)||0;if(p!==showers)animateCounter(sv,p,showers,500,0);}
      const lv=sh.getElementById('lv');if(lv){const p=parseInt(lv.textContent)||0;if(p!==usableL)animateCounter(lv,p,usableL,500,0);}
      const dv=sh.getElementById('dv');if(dv){const p=parseInt(dv.textContent)||0;if(p!==usableL)animateCounter(dv,p,usableL,500,0);}
    });}

    // Event listeners
    sh.querySelectorAll('.boiler-tab').forEach(btn=>btn.addEventListener('click',()=>{this._boilerTab=parseInt(btn.dataset.btab);this._render();}));
    sh.querySelectorAll('.ctab').forEach(btn=>btn.addEventListener('click',()=>{this._contentTab=btn.dataset.ctab;this._render();}));
    sh.querySelectorAll('.action-btn').forEach(btn=>btn.addEventListener('click',()=>{
      const act=btn.dataset.action,eid=btn.dataset.eid;if(!this._hass||!eid)return;
      btn.disabled=true;
      const origText=btn.textContent;
      btn.textContent='⏳';
      setTimeout(()=>{btn.disabled=false;btn.textContent=origText;},3000);
      if(act==='send_now'){
        btn.textContent='🚿 Sturen…';
        this._hass.callService('cloudems','boiler_send_now',{entity_id:eid,on:true}).catch(()=>{});
      } else if(act==='set_green'){
        btn.textContent='🌿 Instellen…';
        this._hass.callService('cloudems','boiler_set_green',{entity_id:eid}).catch(()=>{});
      } else if(act==='pause_boost'){
        const secs=parseInt(btn.dataset.seconds||'3600');
        const label=secs>=7200?`⏸ ${secs/3600}u…`:'⏸ 1u…';
        btn.textContent=label;
        this._hass.callService('cloudems','boiler_pause_boost',{entity_id:eid,seconds:secs}).catch(()=>{});
      } else if(act==='resume_boost'){
        btn.textContent='🔄 Hervatten…';
        this._hass.callService('cloudems','boiler_resume_boost',{entity_id:eid}).catch(()=>{});
      }
    }));
  }

  getCardSize(){return 9;}
  static getConfigElement(){return document.createElement('cloudems-boiler-card-editor');}
  static getStubConfig(){return {title:'Warm water'};}
}

class CloudemsBoilerCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(c){this._cfg={...c};this._render();}
  _fire(){this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));}
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px;}.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}.row:last-child{border-bottom:none;}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:130px;box-sizing:border-box;}</style>
    <div class="wrap">
      <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??'Warm water'}"></div>
      <div class="row"><label class="lbl">Tank inhoud (L) — 0=leren</label><input type="number" name="tank_liters" value="${cfg.tank_liters??0}"></div>
      <div class="row"><label class="lbl">Koud water temp (°C)</label><input type="number" name="cold_water_temp" value="${cfg.cold_water_temp??10}"></div>
      <div class="row"><label class="lbl">Douchetemperatuur (°C)</label><input type="number" name="shower_temp" value="${cfg.shower_temp??38}"></div>
      <div class="row"><label class="lbl">Liter/min douche</label><input type="number" name="shower_liters_per_min" value="${cfg.shower_liters_per_min??8}"></div>
      <div class="row"><label class="lbl">Douchetijd (min)</label><input type="number" name="shower_duration_min" value="${cfg.shower_duration_min??8}"></div>
    </div>`;
    this.shadowRoot.querySelectorAll('input').forEach(el=>el.addEventListener('change',()=>{
      const n=el.name,nc={...this._cfg};
      if(n==='title')nc[n]=el.value;else nc[n]=parseFloat(el.value)||0;
      this._cfg=nc;this._fire();
    }));
  }
}
if (!customElements.get('cloudems-boiler-card-editor')) customElements.define('cloudems-boiler-card-editor',CloudemsBoilerCardEditor);
if (!customElements.get('cloudems-boiler-card')) customElements.define('cloudems-boiler-card',CloudemsBoilerCard);
window.customCards=window.customCards??[];
window.customCards.push({type:'cloudems-boiler-card',name:'CloudEMS Boiler Card',description:'Warm water — live, leren, gezondheid, log'});
console.info('%c CLOUDEMS-BOILER-CARD %c v'+BOILER_CARD_VERSION+' ','background:#ff8040;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#111318;color:#ff8040;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
