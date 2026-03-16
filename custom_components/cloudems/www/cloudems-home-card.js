/**
 * CloudEMS Home Card — cloudems-home-card
 * Version: 1.7.0
 *
 * 15 tabs: Status · Categorieën · Kamers · Apparaten · Zonne · Batterij · Boiler · Rolluiken · EV · E-bike · Zwembad
 */
const HCV = '1.8.7';

const PCOL = ct => ct<=15?'#34d399':ct<=22?'#86efac':ct<=28?'#fbbf24':ct<=33?'#f97316':'#ef4444';
const PLBL = ct => ct<=15?'LAAG':ct<=22?'NORMAAL':ct<=28?'MEDIUM':ct<=33?'HIGH':'PIEK';

class CloudEMSHomeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this._hass=null; this._config={}; this._tab='status';
    this._expanded=new Set(); this._prev='';
    this._swipeX=0; this._lastTap=0; this._devSearch='';
  }
  setConfig(c){this._config=c||{};}
  set hass(h){this._hass=h;this._render();}
  _s(e){return this._hass?.states?.[e]||null;}
  _v(e,d=0){const s=this._s(e);if(!s||s.state==='unavailable'||s.state==='unknown')return d;return parseFloat(s.state)||d;}
  _a(e,k,d=null){return this._s(e)?.attributes?.[k]??d;}
  _fmt(w){if(Math.abs(w)>=1000)return(w/1000).toFixed(2)+' kW';return Math.round(w)+' W';}
  _ago(ts){if(!ts)return'—';const d=(Date.now()-new Date(ts).getTime())/1000;if(d<60)return Math.round(d)+'s';if(d<3600)return Math.round(d/60)+'m';return Math.round(d/3600)+'u';}
  _cap(s){return s?s.charAt(0).toUpperCase()+s.slice(1):'—';}

  _render(){
    if(!this._hass)return;
    const sig=JSON.stringify([this._tab,
      this._v('sensor.cloudems_net_vermogen'),
      this._v('sensor.cloudems_zon_vermogen'),
      this._v('sensor.cloudems_battery_power'),
      this._v('sensor.cloudems_batterij_soc'),
      (this._a('sensor.cloudems_kamers_overzicht','rooms')||[]).length,
    ]);
    if(sig===this._prev)return;
    this._prev=sig;
    try{
      this.shadowRoot.innerHTML=this._css()+this._html();
      this._bind();
    }catch(e){
      console.error('[CloudEMS home-card]',e);
      this._prev='';
      this.shadowRoot.innerHTML='<style>:host{display:block}</style><div style="padding:16px;color:rgba(239,68,68,0.8);font-size:11px;background:rgb(22,22,22);border-radius:14px">⚠ '+e.message+'</div>';
    }
  }

  _css(){return`<style>
*{box-sizing:border-box;margin:0;padding:0}
:host{display:block}
.card{background:rgb(22,22,22);border-radius:14px;border:1px solid rgba(255,255,255,0.07);overflow:hidden;color:#fff;font-family:Inter,sans-serif}
.hdr{padding:11px 16px 9px;border-bottom:1px solid rgba(255,255,255,0.07);display:flex;justify-content:space-between;align-items:center}
.hdr-title{font-size:13px;font-weight:700}
.hdr-sub{font-size:10px;color:rgba(255,255,255,0.35);margin-top:1px}
.hdr-grid{font-size:18px;font-weight:700;text-align:right}
.hdr-lbl{font-size:10px;color:rgba(255,255,255,0.35);text-align:right}
.tabs{display:flex;flex-wrap:wrap;border-bottom:1px solid rgba(255,255,255,0.07)}
.tab{flex:0 0 auto;padding:6px 10px;font-size:10px;font-weight:600;text-align:center;cursor:pointer;color:rgba(255,255,255,0.3);border-bottom:2px solid transparent;transition:all 0.15s;white-space:nowrap}
.tab.active{color:#fff;border-bottom-color:#EF9F27}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(255,255,255,0.06);border-bottom:1px solid rgba(255,255,255,0.06)}
.sc{background:rgb(22,22,22);padding:10px 13px;cursor:pointer;transition:background 0.15s}
.sc:hover{background:rgb(30,30,30)}
.sc-l{font-size:9px;font-weight:700;letter-spacing:0.07em;color:rgba(255,255,255,0.25);text-transform:uppercase;margin-bottom:4px}
.sc-v{font-size:20px;font-weight:700;line-height:1}
.sc-s{font-size:10px;color:rgba(255,255,255,0.35);margin-top:2px}
.sc-b{display:inline-flex;align-items:center;gap:4px;font-size:10px;padding:2px 7px;border-radius:8px;margin-top:4px;font-weight:600;border:1px solid}
.soc-bar{width:60px;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;margin-top:4px}
.soc-f{height:100%;border-radius:2px}
.pblock{padding:9px 13px;border-bottom:1px solid rgba(255,255,255,0.06)}
.blbl{font-size:9px;font-weight:700;letter-spacing:0.07em;color:rgba(255,255,255,0.22);text-transform:uppercase;margin-bottom:7px;display:flex;justify-content:space-between}
.blbl span{font-size:10px;font-weight:400;letter-spacing:0;text-transform:none;color:rgba(255,255,255,0.3)}
.phases{display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;margin-bottom:7px}
.ph{border-radius:7px;padding:7px 9px;text-align:center;border:1px solid rgba(255,255,255,0.06);background:rgba(255,255,255,0.03)}
.ph.over{border-color:rgba(239,68,68,0.5);background:rgba(239,68,68,0.08);animation:pulse 1.2s ease-in-out infinite}
.ph.exp{border-color:rgba(52,211,153,0.3);background:rgba(52,211,153,0.05)}
@keyframes pulse{0%,100%{background:rgba(239,68,68,0.08)}50%{background:rgba(239,68,68,0.2)}}
.ph-n{font-size:9px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:3px}
.ph-a{font-size:16px;font-weight:700;line-height:1}
.ph-d{font-size:9px;margin-top:2px;font-weight:700}
.ph-w{font-size:10px;color:rgba(255,255,255,0.35);margin-top:1px}
.ph-bg{height:3px;background:rgba(255,255,255,0.07);border-radius:2px;overflow:hidden;margin-top:4px}
.ph-fg{height:100%;border-radius:2px}
.imb{display:flex;align-items:center;justify-content:space-between;background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.15);border-radius:7px;padding:5px 9px;margin-bottom:7px}
.imb-l{font-size:11px;color:rgba(255,255,255,0.45)}
.imb-v{font-size:13px;font-weight:700}
.price-rows{padding:0 0 2px}
.pr{display:flex;align-items:center;gap:8px;margin-bottom:5px;padding:0 13px}
.pr:last-child{margin-bottom:0}
.pr-t{font-size:11px;font-weight:700;width:38px;text-align:right;flex-shrink:0}
.pr-bg{flex:1;height:13px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;position:relative}
.pr-bar{height:100%;border-radius:3px}
.pr-p{font-size:11px;font-weight:700;width:42px;text-align:right;flex-shrink:0}
.pr-lbl{font-size:9px;width:48px;text-align:right;flex-shrink:0;font-weight:700}
.boiler-sp-ctrl{display:flex;align-items:center;gap:4px;margin-top:4px;justify-content:center}.sp-btn{background:rgba(239,159,39,0.15);border:1px solid rgba(239,159,39,0.3);color:#EF9F27;border-radius:6px;width:22px;height:22px;font-size:14px;cursor:pointer;line-height:1;padding:0}.sp-val{font-size:11px;color:rgba(255,255,255,0.7);min-width:34px;text-align:center}.insight-strip{font-size:11px;color:rgba(255,255,255,0.65);background:rgba(6,182,212,0.08);border:1px solid rgba(6,182,212,0.2);border-radius:8px;padding:6px 10px;margin:6px 13px;line-height:1.4}.pkblock{padding:8px 13px 6px;border-bottom:1px solid rgba(255,255,255,0.06)}
.pk-row{display:flex;align-items:center;gap:7px;margin-bottom:4px}
.pk-row:last-child{margin-bottom:0}
.pk-l{font-size:11px;color:rgba(255,255,255,0.45);width:85px;flex-shrink:0}
.pk-bg{flex:1;height:7px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;position:relative}
.pk-bar{height:100%;border-radius:4px}
.pk-lim{position:absolute;top:0;bottom:0;width:2px;background:rgba(239,68,68,0.6)}
.pk-v{font-size:11px;font-weight:700;width:44px;text-align:right;flex-shrink:0}
.pk-s{font-size:10px;padding:2px 7px;border-radius:6px;border:1px solid;font-weight:700;flex-shrink:0}
.dimblock{padding:6px 13px 8px}
.dimrow{display:flex;align-items:center;gap:7px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
.dimrow:last-child{border-bottom:none}
.dim-n{font-size:11px;color:rgba(255,255,255,0.65);flex:1}
.dim-bg{width:70px;height:5px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden;flex-shrink:0}
.dim-fg{height:100%;border-radius:3px;background:#34d399}
.dim-p{font-size:11px;font-weight:700;width:34px;text-align:right;flex-shrink:0;color:#34d399}.dim-pwr{font-size:11px;min-width:44px;text-align:right;color:rgba(255,255,255,0.6);flex-shrink:0}.dim-hint{font-size:10px;color:rgba(245,158,11,0.6);padding:1px 0 3px 20px}
.sr{padding:6px 13px;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;align-items:center;justify-content:space-between}
.sr:last-child{border-bottom:none}
.sr-l{display:flex;align-items:center;gap:7px;font-size:12px;color:rgba(255,255,255,0.55)}
.sr-icon{font-size:13px;width:18px;text-align:center}
.sr-r{font-size:12px;font-weight:700;color:rgba(255,255,255,0.85);text-align:right}
.sr-sub{font-size:10px;color:rgba(255,255,255,0.35);font-weight:400}
.dec-block{padding:8px 13px;border-top:1px solid rgba(255,255,255,0.06)}
.dec-hdr{font-size:9px;font-weight:700;letter-spacing:0.07em;color:rgba(255,255,255,0.22);text-transform:uppercase;margin-bottom:6px;display:flex;justify-content:space-between}
.dec-hdr span{font-size:10px;font-weight:400;letter-spacing:0;text-transform:none;color:rgba(255,255,255,0.25)}
.dec-item{background:rgba(255,255,255,0.03);border-radius:7px;padding:7px 9px;border-left:3px solid}
.dec-top{display:flex;justify-content:space-between;margin-bottom:2px}
.dec-cat{font-size:9px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase}
.dec-time{font-size:10px;color:rgba(255,255,255,0.3)}
.dec-msg{font-size:11px;color:rgba(255,255,255,0.7);line-height:1.35;margin-bottom:4px}
.dec-meta{display:flex;gap:8px;font-size:10px;color:rgba(255,255,255,0.3)}
.cat-section{padding:5px 0 3px}
.cat-row{display:grid;grid-template-columns:20px 1fr 54px 56px 32px;align-items:center;gap:0 6px;padding:4px 13px}
.cat-bg{height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;margin:0 13px 4px 39px}
.cat-fg{height:100%;border-radius:2px}
.ins{padding:5px 13px 8px;font-size:10px;color:rgba(255,255,255,0.3);font-style:italic;border-top:1px solid rgba(255,255,255,0.05)}
.sec-lbl{font-size:9px;font-weight:700;letter-spacing:0.07em;color:rgba(255,255,255,0.2);padding:5px 13px 2px;text-transform:uppercase}
.row{display:grid;grid-template-columns:100px 52px 1fr 58px 14px;align-items:center;gap:0 5px;padding:4px 13px;cursor:pointer;transition:background 0.1s}
.row:hover{background:rgba(255,255,255,0.03)}
.row.top{background:rgba(239,159,39,0.04)}
.rname{font-size:12px;color:rgba(255,255,255,0.8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row.top .rname{color:#EF9F27;font-weight:700}
.rpw{font-size:12px;font-weight:700;text-align:right}
.row.top .rpw{color:#EF9F27}
.rbg{height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden}
.rfg{height:100%;border-radius:2px}
.rkwh{font-size:10px;color:rgba(255,255,255,0.3);text-align:right}
.rexp{font-size:9px;color:rgba(255,255,255,0.2);text-align:center}
.sep{height:1px;background:rgba(255,255,255,0.06);margin:2px 13px}
.dvblock{background:rgba(255,255,255,0.02);padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
.dvrow{display:grid;grid-template-columns:10px 1fr 46px 28px 64px;align-items:center;gap:0 5px;padding:3px 13px 3px 25px;font-size:11px}
.dot{width:6px;height:6px;border-radius:50%}
.ph-bar{display:flex;gap:10px;padding:7px 13px;border-bottom:1px solid rgba(255,255,255,0.06);font-size:11px;flex-wrap:wrap}
.ph-chip{display:flex;align-items:center;gap:4px}
.ph-dot{width:7px;height:7px;border-radius:50%}
.dhdr{display:grid;grid-template-columns:24px 1fr 48px 36px 30px 28px;gap:0 5px;padding:4px 13px;font-size:9px;font-weight:700;letter-spacing:0.06em;color:rgba(255,255,255,0.2);text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.05)}
.drow{display:grid;grid-template-columns:24px 1fr 48px 36px 30px 28px;align-items:center;gap:0 5px;padding:4px 13px;transition:background 0.1s}
.drow:hover{background:rgba(255,255,255,0.03)}
.drow.top{background:rgba(239,159,39,0.04)}
.dnr{font-size:11px;color:rgba(255,255,255,0.25);text-align:center}
.drow.top .dnr{color:#EF9F27;font-weight:700}
.dn{font-size:11px;color:rgba(255,255,255,0.8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.drow.top .dn{color:#EF9F27}
.dw{font-size:11px;font-weight:700;text-align:right}
.drow.top .dw{color:#EF9F27}
.dph{text-align:center;font-size:10px;font-weight:700}
.dbr{text-align:center;font-size:12px}
.dpct{font-size:10px;text-align:right;color:rgba(255,255,255,0.35)}
.sol-inv{border-bottom:1px solid rgba(255,255,255,0.05);padding:9px 13px}
.sol-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.sol-name{font-size:12px;font-weight:700}
.sol-w{font-size:17px;font-weight:700}
.sol-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:6px}
.sol-stat{background:rgba(255,255,255,0.04);border-radius:6px;padding:4px 7px}
.ssl{font-size:9px;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.05em}
.ssv{font-size:11px;font-weight:700}
.sbarlbl{display:flex;justify-content:space-between;font-size:10px;color:rgba(255,255,255,0.3);margin-bottom:2px}
.sbarbg{height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;margin-bottom:4px}
.sbarfg{height:100%;border-radius:2px}
.badges{display:flex;gap:5px;flex-wrap:wrap;margin-top:3px}
.badge{font-size:10px;padding:2px 7px;border-radius:7px;border:1px solid}
.bl{color:#a78bfa;border-color:rgba(167,139,250,0.3);background:rgba(167,139,250,0.08)}
.bg{color:#34d399;border-color:rgba(52,211,153,0.3);background:rgba(52,211,153,0.08)}
.bat-top{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;background:rgba(255,255,255,0.06);border-bottom:1px solid rgba(255,255,255,0.06)}
.bc{background:rgb(22,22,22);padding:9px 13px;text-align:center}
.bcv{font-size:18px;font-weight:700}
.bcl{font-size:9px;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;margin-top:2px}
.bat-rows{padding:3px 0}
.bat-row{display:flex;align-items:center;justify-content:space-between;padding:5px 13px;border-bottom:1px solid rgba(255,255,255,0.04);font-size:12px}
.bat-row:last-child{border-bottom:none}
.bat-k{color:rgba(255,255,255,0.5);display:flex;align-items:center;gap:6px}
.bat-v{font-weight:700;color:rgba(255,255,255,0.85)}
.nexus{margin:0 13px 10px;background:rgba(55,138,221,0.08);border:1px solid rgba(55,138,221,0.2);border-radius:8px;padding:8px 11px}
.nx-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px}
.nx-title{font-size:11px;font-weight:700;color:#60a5fa}
.nx-mode{font-size:10px;color:rgba(255,255,255,0.4)}
.nx-row{display:flex;justify-content:space-between;font-size:10px;padding:2px 0;color:rgba(255,255,255,0.45)}
.nx-row span:last-child{color:rgba(255,255,255,0.8);font-weight:600}
.boil-top{display:flex;align-items:center;gap:11px;padding:11px 13px;border-bottom:1px solid rgba(255,255,255,0.06)}
.boil-tank{width:34px;height:50px;border:2px solid rgba(255,255,255,0.15);border-radius:4px;overflow:hidden;position:relative;flex-shrink:0}
.boil-fill{position:absolute;bottom:0;left:0;right:0;background:rgba(239,159,39,0.35)}
.boil-info{flex:1}
.boil-name{font-size:12px;font-weight:700}
.boil-sub{font-size:10px;color:rgba(255,255,255,0.4);margin-top:1px}
.boil-temp{font-size:18px;font-weight:700;margin-top:3px}
.boil-badge{display:inline-flex;padding:2px 7px;border-radius:7px;font-size:10px;font-weight:700;background:rgba(239,64,64,0.12);color:#f87171;border:1px solid rgba(239,64,64,0.28)}
.boil-bars{padding:7px 13px;border-bottom:1px solid rgba(255,255,255,0.06)}
.bbar{margin-bottom:7px}
.bbar:last-child{margin-bottom:0}
.bbarlbl{display:flex;justify-content:space-between;font-size:10px;color:rgba(255,255,255,0.35);margin-bottom:2px}
.bbarbg{height:5px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden}
.bbarfg{height:100%;border-radius:3px}
.boil-stats{display:grid;grid-template-columns:1fr 1fr 1fr;padding:7px 13px;gap:5px;border-bottom:1px solid rgba(255,255,255,0.06)}
.bstat{text-align:center}
.bstatv{font-size:17px;font-weight:700}
.bstatl{font-size:9px;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;margin-top:1px}
.boil-foot{font-size:10px;color:rgba(255,255,255,0.35);padding:6px 13px 8px;text-align:center}
.shut-hdr{padding:6px 13px 4px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(255,255,255,0.05)}
.shut-btns{display:flex;gap:5px}
.shut-btn{font-size:10px;padding:3px 9px;border-radius:7px;background:rgba(255,255,255,0.05);cursor:pointer;color:rgba(255,255,255,0.45);border:1px solid rgba(255,255,255,0.08)}
.shut-btn:hover{background:rgba(255,255,255,0.1)}
.shut-row{display:grid;grid-template-columns:1fr 80px 34px;align-items:center;gap:0 7px;padding:6px 13px;border-bottom:1px solid rgba(255,255,255,0.05);cursor:pointer;transition:background 0.1s}
.shut-row:hover{background:rgba(255,255,255,0.03)}
.shut-row:last-child{border-bottom:none}
.shut-name{font-size:12px;color:rgba(255,255,255,0.82)}
.shut-sub{font-size:10px;color:rgba(255,255,255,0.3)}
.shut-pbg{height:6px;background:rgba(255,255,255,0.07);border-radius:3px;overflow:hidden}
.shut-pfg{height:100%;background:#60a5fa;border-radius:3px}
.shut-pct{font-size:11px;font-weight:700;text-align:right;color:rgba(255,255,255,0.65)}
.shut-info{font-size:10px;color:rgba(255,255,255,0.25);padding:5px 13px 8px;text-align:center}
.tab-block{padding:10px 13px;border-bottom:1px solid rgba(255,255,255,0.06)}
.tab-block:last-child{border-bottom:none}
.tb-hdr{font-size:11px;font-weight:700;margin-bottom:6px;display:flex;align-items:center;justify-content:space-between}
.tb-sub{font-size:10px;color:rgba(255,255,255,0.35);font-weight:400}
.stat-row{display:flex;align-items:center;justify-content:space-between;padding:4px 0;font-size:11px;border-bottom:1px solid rgba(255,255,255,0.04)}
.stat-row:last-child{border-bottom:none}
.stat-k{color:rgba(255,255,255,0.5)}
.stat-v{font-weight:700;color:rgba(255,255,255,0.85)}
.alert{display:flex;align-items:center;gap:8px;border-radius:8px;padding:7px 10px;font-size:11px;margin-bottom:7px;border:1px solid}
.alert-w{border-color:rgba(239,68,68,0.3);background:rgba(239,68,68,0.08);color:#fca5a5}
.alert-g{border-color:rgba(52,211,153,0.3);background:rgba(52,211,153,0.08);color:#6ee7b7}
.alert-y{border-color:rgba(251,191,36,0.3);background:rgba(251,191,36,0.08);color:#fcd34d}
.empty{padding:20px 13px;text-align:center;font-size:12px;color:rgba(255,255,255,0.25)}
.footer{padding:6px 13px 8px;border-top:1px solid rgba(255,255,255,0.06);display:flex;justify-content:space-between;font-size:10px;color:rgba(255,255,255,0.2)}
.alert-box{margin:6px 10px 0;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);border-radius:8px;padding:8px 10px}
.alert-item{display:flex;gap:8px;align-items:flex-start;font-size:11px;color:rgba(255,255,255,0.8);line-height:1.4;margin-bottom:4px}
.alert-item:last-child{margin-bottom:0}
.alert-item strong{color:rgba(255,255,255,0.95)}
.alert-meer{font-size:10px;color:rgba(255,255,255,0.4);margin-top:4px;font-style:italic}
.inzicht-box{margin:6px 10px 0;background:rgba(241,196,15,0.07);border:1px solid rgba(241,196,15,0.2);border-radius:8px;padding:7px 10px;display:flex;gap:8px;align-items:flex-start;font-size:11px;color:rgba(255,255,255,0.75);line-height:1.4}
.inzicht-icon{flex-shrink:0;font-size:13px}
.inzicht-txt{flex:1}
@keyframes pk-pulse{0%,100%{opacity:1}50%{opacity:0.4}}</style>`;
  }

  _html(){
    const t=this._tab;
    const gw=this._v('sensor.cloudems_net_vermogen');
    const sw=this._v('sensor.cloudems_zon_vermogen');
    const bw=this._v('sensor.cloudems_battery_power');
    const hw=this._v('sensor.cloudems_home_rest');
    const soc=this._v('sensor.cloudems_batterij_soc');
    const top=this._a('sensor.cloudems_kamers_overzicht','top_room')||'—';
    const imp=gw>50,exp=gw<-50;
    const gc=imp?'#f87171':exp?'#34d399':'rgba(255,255,255,0.5)';
    const kwh=this._a('sensor.cloudems_verbruik_categorien','total_kwh_today',0);
    const TABS=[['status','Status'],['cats','Categorieën'],['rooms','Kamers'],['devs','Apparaten'],
      ['solar','Zonne'],['bat','Batterij'],['boiler','Boiler'],['shutters','Rolluiken'],
      ['ev','EV 🚗'],['ebike','E-bike 🚲'],['pool','Zwembad 🏊'],
      ['prices','Prijzen 💶'],['history','Historie 📋']];
    return`<div class="card">
<div class="hdr">
  <div><div class="hdr-title">⚡ CloudEMS</div><div class="hdr-sub">🏆 ${this._cap(top)} · ${this._fmt(hw)} huis</div></div>
  <div><div class="hdr-grid" style="color:${gc}">${imp?'↓':exp?'↑':'='} ${this._fmt(Math.abs(gw))}</div><div class="hdr-lbl">${imp?'import':exp?'export':'balans'} grid</div></div>
</div>
<div class="tabs">${TABS.map(([id,l])=>`<div class="tab${t===id?' active':''}" data-tab="${id}">${l}</div>`).join('')}</div>
${this._renderAlerts()}
<div class="tc">
${t==='status'?this._tabStatus(gw,sw,bw,hw,soc):''}
${t==='cats'?this._tabCats():''}
${t==='rooms'?this._tabRooms():''}
${t==='devs'?this._tabDevices():''}
${t==='solar'?this._tabSolar():''}
${t==='bat'?this._tabBat(bw,soc):''}
${t==='boiler'?this._tabBoiler():''}
${t==='shutters'?this._tabShutters():''}
${t==='ev'?this._tabEV():''}
${t==='ebike'?this._tabEbike():''}
${t==='pool'?this._tabPool():''}
${t==='prices'?this._tabPrices():''}
${t==='history'?this._tabHistory():''}
</div>
<div class="footer"><span>Vandaag: ${parseFloat(kwh).toFixed(2)} kWh excl. batterij</span><span>CloudEMS Home v${HCV}</span></div>
</div>`;
  }

  /* ── ALERTS + INZICHT ──────────────────────────────────────────────────── */
  _renderAlerts(){
    const alerts=this._a('sensor.cloudems_actieve_meldingen','active_alerts',[])||[];
    const inzicht=this._s('sensor.cloudems_energy_insights')?.state||'';
    let html='';
    // Meldingen banner (alleen als er meldingen zijn)
    if(alerts.length>0){
      const items=alerts.slice(0,3).map(a=>{
        const icon=a.priority==='critical'?'🔴':a.priority==='warning'?'🟡':'🔵';
        return`<div class="alert-item"><span>${icon}</span><div><strong>${a.title}</strong> — ${a.message}</div></div>`;
      }).join('');
      const meer=alerts.length>3?`<div class="alert-meer">...en ${alerts.length-3} meer</div>`:'';
      html+=`<div class="alert-box">${items}${meer}</div>`;
    }
    // Inzicht & Advies (alleen tonen als geen actieve meldingen en niet generiek)
    if(inzicht&&inzicht!=='unavailable'&&inzicht!=='unknown'){
      const isGeneric=/alles in orde|geen bijzonderheden|no issues/i.test(inzicht);
      if(!isGeneric||alerts.length===0){
        html+=`<div class="inzicht-box"><span class="inzicht-icon">💡</span><span class="inzicht-txt">${inzicht}</span></div>`;
      }
    }
    return html;
  }

  /* ── STATUS ─────────────────────────────────────────────────────────────── */
  _tabStatus(gw,sw,bw,hw,soc){
    const boilers=this._a('sensor.cloudems_boiler_status','boilers')||[];
    const b=boilers[0]||{};
    const btemp=b.temp_c??'—'; const bsp=b.active_setpoint_c??b.setpoint_c??'—';
    const bpow=b.current_power_w??0; const bmode=(b.actual_mode||'').toUpperCase();
    const imp=gw>50; const exp=gw<-50;
    // Price
    const priceSt=this._s('sensor.cloudems_price_current_hour');
    const priceCt=priceSt?parseFloat(priceSt.state)*100:null;
    const nextPrices=this._a('sensor.cloudems_price_current_hour','next_hours',[])||[];
    const nextCt=nextPrices.length>0?nextPrices[0].price_eur_kwh*100:null;
    const maxP=Math.max(priceCt||0,nextCt||0,35);
    const now=new Date(); const nowH=`${String(now.getHours()).padStart(2,'0')}:00`;
    const nextH=`${String((now.getHours()+1)%24).padStart(2,'0')}:00`;
    // Phases
    // v1.5.0: signed current (negatief = export) — valt terug op unsigned met sign van power
    const _signedA=(ph)=>{
      const signed=this._v(`sensor.cloudems_signed_current_${ph.toLowerCase()}`);
      if(signed!==0||this._s(`sensor.cloudems_signed_current_${ph.toLowerCase()}`)?.state==='0')return signed;
      const raw=this._v(`sensor.cloudems_grid_phase_${ph.toLowerCase()}_current`)||this._v(`sensor.cloudems_current_${ph.toLowerCase()}`)||0;
      const pw=this._v(`sensor.cloudems_grid_phase_${ph.toLowerCase()}_power`)||this._v(`sensor.cloudems_power_${ph.toLowerCase()}`)||0;
      return raw*(pw<0?-1:1);
    };
    // v1.8.1: sanity clamp — waarden >100A zijn opstartartefacten
    const _clampA=(a)=>Math.abs(a)>100?0:a;
    const l1a=_clampA(_signedA('L1')); const l2a=_clampA(_signedA('L2')); const l3a=_clampA(_signedA('L3'));
    const phaseSt=this._s('sensor.cloudems_batterij_soc'); // just to get hass
    const phData=this._a('sensor.cloudems_status','phase_data')||{};
    // Try to get per-phase power from phases attribute on battery sensor or net_vermogen
    const l1w=this._v('sensor.cloudems_import_power_l1')||this._v('sensor.cloudems_power_l1');
    const l2w=this._v('sensor.cloudems_import_power_l2')||this._v('sensor.cloudems_power_l2');
    const l3w=this._v('sensor.cloudems_import_power_l3')||this._v('sensor.cloudems_power_l3');
    const maxA=this._config.max_ampere||25;
    const imbalance=Math.max(l1a,l2a,l3a)-Math.min(l1a,l2a,l3a);
    const phColor=(a,w)=>a<0||w<0?'#34d399':Math.abs(a)>maxA?'#ef4444':'#f87171';
    const phDir=(w,a)=>a<0||w<0?'↑ export':w>10?'↓ import':'≈ balans';
    const phDirC=(w,a)=>a<0||w<0?'#34d399':w>10?'#f87171':'rgba(255,255,255,0.4)';
    // Kleur op basis van belastingpercentage: groen→geel→oranje→rood
    const _loadColor=(a)=>{ const r=Math.min(1,Math.abs(a)/maxA); const hue=Math.round(120-r*120); return `hsl(${hue},80%,50%)`; };
    // Peak shaving
    const peakSt=this._s('sensor.cloudems_kwartier_piek');
    const peakW=peakSt?parseFloat(peakSt.state)||0:0;
    const monthPeak=this._a('sensor.cloudems_kwartier_piek','month_peak_w',0);
    const peakWarn=this._a('sensor.cloudems_kwartier_piek','warning_active',false);
    // Dimmer
    const dimSlider=this._a('sensor.cloudems_pv_dimmer','dimmer_pct_growatt')||null;
    const invs=this._a('sensor.cloudems_solar_system','inverters')||[];
    // Last decision
    const decs=this._a('sensor.cloudems_decisions_history','decisions',[])||[];
    const lastDec=decs[0]||null;
    const decColors={boiler:'#a78bfa',battery:'#60a5fa',ev:'#34d399',shutter:'#fbbf24',peak:'#ef4444',solar:'#EF9F27'};
    const catColor=c=>decColors[(c||'').toLowerCase()]||'rgba(255,255,255,0.3)';
    // Budget
    const monthCost=this._a('sensor.cloudems_energie_kosten_verwachting','month_cost_eur',null);
    const budget=this._a('sensor.cloudems_energie_kosten_verwachting','budget_eur',null);
    const batAction=this._a('sensor.cloudems_batterij_epex_schema','battery_decision',{})||{};
    // Live overzicht extra
    const importW=parseFloat(this._s('sensor.cloudems_grid_import_power')?.state||0)||0;
    const exportW=parseFloat(this._s('sensor.cloudems_grid_export_power')?.state||0)||0;
    const flexW=parseFloat(this._s('sensor.cloudems_flexibel_vermogen')?.state||0)||0;
    const aanwezig=this._s('binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom')?.state==='on';
    const zelfcons=parseFloat(this._s('sensor.cloudems_self_consumption')?.state||0)||0;
    const kostenVandaag=this._s('sensor.cloudems_energy_cost')?.state||null;
    const dagtypeRaw=this._s('sensor.cloudems_dag_type_classificatie')?.state||'unknown';
    const dagtypeMap={'work_home':'🏠 Thuis werken','work_away':'🏢 Weg werken','weekend':'🌤️ Weekend','holiday':'🎉 Feestdag','vacation':'✈️ Vakantie','night':'🌙 Nacht','unknown':'❓ Onbekend'};
    const dagtype=dagtypeMap[dagtypeRaw]||dagtypeRaw;

    return`
<!-- 4 grote blokken -->
<div class="sgrid">
  <div class="sc" data-nav="solar">
    <div class="sc-l">☀️ Zonne</div>
    <div class="sc-v" style="color:${sw>100?'#EF9F27':'rgba(255,255,255,0.25)'}"> ${this._fmt(sw)}</div>
    <div class="sc-s">Piek 7d: ${this._fmt(this._a('sensor.cloudems_solar_system','total_peak_w',0))}</div>
    ${sw<50?`<div class="sc-b" style="color:rgba(255,255,255,0.3);border-color:rgba(255,255,255,0.1);background:rgba(255,255,255,0.04)">🌙 Niet actief</div>`:`<div class="sc-b" style="color:#EF9F27;border-color:rgba(239,159,39,0.3);background:rgba(239,159,39,0.08)">⚡ Produceert</div>`}
  </div>
  <div class="sc" data-nav="bat">
    <div class="sc-l">🔋 Batterij</div>
    <div class="sc-v" style="color:#34d399">${Math.round(soc)}%</div>
    <div class="sc-s">${this._fmt(Math.abs(bw))} · ${bw>50?'laden':bw<-50?'ontladen':'idle'}</div>
    <div class="soc-bar"><div class="soc-f" style="width:${soc}%;background:${soc>30?'#34d399':'#f87171'}"></div></div>
  </div>
  <div class="sc" data-nav="prices">
    <div class="sc-l">⚡ Grid</div>
    <div class="sc-v" style="color:${imp?'#f87171':exp?'#34d399':'rgba(255,255,255,0.5)'}"> ${this._fmt(Math.abs(gw))}</div>
    <div class="sc-s">${imp?'import':exp?'export':'balans'}${priceCt!==null?' · €'+((priceCt/100).toFixed(3)):''}</div>
    ${priceCt!==null?`<div class="sc-b" style="color:${PCOL(priceCt)};border-color:${PCOL(priceCt)}33;background:${PCOL(priceCt)}18">${PLBL(priceCt)}</div>`:''}
  </div>
  <div class="sc" data-nav="boiler">
    <div class="sc-l">🚿 Boiler</div>
    <div class="sc-v" style="color:#EF9F27">${btemp}°C</div>
    <div class="sc-s">setpoint ${bsp}°C · ${this._fmt(bpow)}</div>
    ${bmode?`<div class="sc-b" style="color:#f87171;border-color:rgba(239,64,64,0.25);background:rgba(239,64,64,0.1)">${bmode}</div>`:''}
    ${typeof bsp==='number'?`<div class="boiler-sp-ctrl" data-slug="${(b.label||'boiler_1').toLowerCase().replace(/[^a-z0-9]+/g,'_')}">
      <button class="sp-btn sp-dn" data-sp="${bsp-1}">−</button>
      <span class="sp-val">${bsp}°C</span>
      <button class="sp-btn sp-up" data-sp="${bsp+1}">+</button>
    </div>`:''}
  </div>
</div>

${(()=>{const ins=this._a('sensor.cloudems_status','insights')||'';return ins?`<div class="insight-strip">${ins}</div>`:''})()}

<!-- PIEKSCHAVING -->
<div class="pkblock">
  <div class="blbl">Piekschaving <span>limiet ${maxA}A / ${Math.round(maxA*230)} W</span></div>
  ${[['L1',l1a],['L2',l2a],['L3',l3a]].map(([phase,a])=>{
    const isExp=a<0;
    const lbl=phase;
    const abs=Math.abs(a);
    const pct=Math.min(50,Math.round(abs/maxA*50));
    const over=a>maxA;
    const warn=!isExp&&a>maxA*0.8;
    const c=isExp?'#34d399':_loadColor(a);
    const ec='#34d399';
    const pulse=over||warn?'animation:pk-pulse 1s ease-in-out infinite;':'';
    const lblColor=isExp?ec:c;
    return`<div class="pk-row">
      <div class="pk-l" style="color:${lblColor}">${lbl}</div>
      <div class="pk-bg" style="position:relative">
        <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,0.2)"></div>
        ${isExp
          ? `<div style="position:absolute;right:50%;top:0;bottom:0;width:${pct}%;background:#34d399;border-radius:3px 0 0 3px;${pulse}"></div>`
          : `<div style="position:absolute;left:50%;top:0;bottom:0;width:${pct}%;background:${c};border-radius:0 3px 3px 0;${pulse}"></div>`
        }
      </div>
      <div class="pk-v" style="color:${isExp?ec:c}">${isExp?'-':''}${abs.toFixed(2)} A</div>
      <div class="pk-s" style="color:${isExp?ec:c};border-color:${isExp?'rgba(52,211,153,0.3)':c+'44'};background:${isExp?'rgba(52,211,153,0.1)':c+'18'}">${over?'OVER':isExp?'EXPORT':'IMPORT'}</div>
    </div>`;
  }).join('')}
  ${(()=>{
    const vals=[l1a,l2a,l3a]; const mx=Math.max(...vals); const mn=Math.min(...vals); const diff=mx-mn;
    const bc=diff>5?'#ef4444':diff>3?'#f97316':'#34d399';
    const bpct=Math.min(100,Math.round(diff/maxA*100));
    return`<div class="pk-row" style="margin-top:4px;border-top:1px solid rgba(255,255,255,0.07);padding-top:4px">
      <div class="pk-l" style="color:${bc}">Fase onbalans</div>
      <div class="pk-bg"><div style="height:100%;width:${bpct}%;background:${bc};border-radius:3px;opacity:0.7"></div></div>
      <div class="pk-v" style="color:${bc}">${diff.toFixed(2)} A</div>
      <div class="pk-s" style="color:${bc};border-color:${bc+'44'};background:${bc+'18'}">${diff>5?'ALERT':diff>3?'WARN':'OK'}</div>
    </div>`;
  })()}
  ${(()=>{
    const shed=this._a('sensor.cloudems_grid_peak_shaving','shed_devices')||[];
    if(!shed.length)return'';
    return`<div style="margin-top:6px;padding:6px 8px;background:rgba(239,68,68,0.08);border-radius:8px;border:1px solid rgba(239,68,68,0.25)">
      <div style="font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#ef4444;margin-bottom:4px">⚠️ Piekschaving actief</div>
      ${shed.map(e=>`<div style="font-size:11px;color:rgba(255,255,255,0.7);padding:2px 0">🔌 ${e.split('.')[1]?.replace(/_/g,' ')}</div>`).join('')}
    </div>`;
  })()}
  ${monthPeak>0?`<div class="pk-row" style="margin-top:3px">
    <div class="pk-l" style="color:rgba(255,255,255,0.35)">Max deze maand</div>
    <div class="pk-bg"><div class="pk-bar" style="width:${Math.min(100,Math.round(monthPeak/(maxA*230)*100))}%;background:#EF9F27"></div></div>
    <div class="pk-v" style="color:#EF9F27">${this._fmt(monthPeak)}</div>
    <div class="pk-s" style="color:#EF9F27;border-color:rgba(239,159,39,0.3);background:rgba(239,159,39,0.08)">PIEK</div>
  </div>`:''}
</div>

<!-- DIMMER STATUS -->
<div class="dimblock">
  <div class="blbl" style="margin-bottom:5px">Zonnedimmer</div>
  ${invs.map(inv=>{
    const curW=Math.round(inv.current_w||0);
    const peakW=Math.round(inv.peak_w_7d||inv.peak_w||0);
    const util=Math.round(inv.utilisation_pct||0);
    const isDimmed=util>0&&util<98;
    const maxW=peakW>0?peakW:curW>0?curW:1;
    const barW=Math.min(100,Math.round(curW/maxW*100));
    const barColor=isDimmed?'#f59e0b':'#34d399';
    const dimEid=`switch.cloudems_pv_dimmer_${(inv.label||'').toLowerCase().replace(/[^a-z0-9]/g,'_')}`;
    const dimOn=this._s(dimEid)?.state==='on';
    const wouldBeW=isDimmed&&peakW>0?Math.round(peakW*(util/100)):null;
    return`<div class="dimrow">
      <span style="font-size:12px">☀️</span>
      <div class="dim-n">${inv.label||'Omvormer'}</div>
      <div class="dim-bg"><div class="dim-fg" style="width:${barW}%;background:${barColor}"></div></div>
      <div class="dim-pwr" style="color:${barColor}">${curW>0?curW+' W':'0 W'}</div>
      <div class="dim-p" style="color:${isDimmed?'#f59e0b':'#34d399'}">${util}%</div>
    </div>${isDimmed&&wouldBeW?`<div class="dim-hint">zonder dimmer ~${wouldBeW} W</div>`:''}`;
  }).join('')||'<div style="font-size:11px;color:rgba(255,255,255,0.3);padding:4px 0">Geen omvormers geconfigureerd</div>'}
</div>

<!-- STATUSINFORMATIE RIJEN -->
${(()=>{
  const _maxPwr=Math.max(importW,exportW,hw,500);
  const _bar=(w,color)=>`<div style="flex:1;height:3px;background:rgba(255,255,255,0.07);border-radius:2px;overflow:hidden;margin:0 8px"><div style="width:${Math.min(100,Math.round(w/_maxPwr*100))}%;height:100%;background:${color};border-radius:2px"></div></div>`;
  return`
<div class="sr"><div class="sr-l"><span class="sr-icon">🔌</span>Afname grid</div>${_bar(importW,'#f87171')}<div class="sr-r" style="color:${importW>100?'#f87171':'rgba(255,255,255,0.5)'}">${this._fmt(importW)}</div></div>
<div class="sr"><div class="sr-l"><span class="sr-icon">⬆️</span>Teruglevering</div>${_bar(exportW,'#34d399')}<div class="sr-r" style="color:${exportW>100?'#34d399':'rgba(255,255,255,0.5)'}">${this._fmt(exportW)}</div></div>
<div class="sr"><div class="sr-l"><span class="sr-icon">🏠</span>Huisverbruik</div>${_bar(hw,'#818cf8')}<div class="sr-r">${this._fmt(hw)} <span class="sr-sub">nu</span></div></div>`;
})()}
<div class="sr"><div class="sr-l"><span class="sr-icon">🏆</span>Hoogste verbruiker</div><div class="sr-r">${this._cap(this._a('sensor.cloudems_kamers_overzicht','top_room')||'—')}</div></div>
${(()=>{const uw=this._v('sensor.cloudems_onverklaard_vermogen')||this._a('sensor.cloudems_status','undefined_power_w',0)||0;const un=this._a('sensor.cloudems_status','undefined_power_name','Onverklaard vermogen')||'Onverklaard vermogen';return uw>50?`<div class="sr"><div class="sr-l"><span class="sr-icon">❓</span>${un}</div><div class="sr-r" style="color:#fbbf24">${this._fmt(uw)}</div></div>`:'';})()}
<div class="sr"><div class="sr-l"><span class="sr-icon">📅</span>Dagtype</div><div class="sr-r" style="color:rgba(255,255,255,0.7)">${dagtype}</div></div>
<div class="sr"><div class="sr-l"><span class="sr-icon">⚡</span>Flex vermogen</div><div class="sr-r">${this._fmt(flexW)}</div></div>
<div class="sr"><div class="sr-l"><span class="sr-icon">🏡</span>Aanwezig</div><div class="sr-r" style="color:${aanwezig?'#34d399':'rgba(255,255,255,0.4)'}">${aanwezig?'✅ Ja':'❌ Nee'}</div></div>
<div class="sr"><div class="sr-l"><span class="sr-icon">🔁</span>Zelfconsumptie</div><div class="sr-r">${zelfcons.toFixed(1)}%</div></div>
${kostenVandaag!==null&&kostenVandaag!=='unavailable'?`<div class="sr"><div class="sr-l"><span class="sr-icon">💰</span>Kosten vandaag</div><div class="sr-r">${kostenVandaag}</div></div>`:''}
${batAction.action?`<div class="sr"><div class="sr-l"><span class="sr-icon">🔋</span>Batterij beslissing</div><div class="sr-r" style="color:#60a5fa">${batAction.action==='charge'?'Laden':batAction.action==='discharge'?'Ontladen':'Idle'}</div></div>`:''}
${monthCost!==null&&budget!==null?`<div class="sr"><div class="sr-l"><span class="sr-icon">📊</span>Maandbudget</div><div class="sr-r" style="color:${monthCost>budget*0.85?'#f97316':'rgba(255,255,255,0.85)'}">€${parseFloat(monthCost).toFixed(0)} / €${parseFloat(budget).toFixed(0)}</div></div>`:''}

<!-- LAATSTE BESLISSING -->
${lastDec?`<div class="dec-block">
  <div class="dec-hdr">Laatste beslissing <span>${this._ago(lastDec.ts)}</span></div>
  <div class="dec-item" style="border-left-color:${catColor(lastDec.category)}">
    <div class="dec-top">
      <div class="dec-cat" style="color:${catColor(lastDec.category)}">${lastDec.category||'—'}</div>
    </div>
    <div class="dec-msg">${lastDec.message||lastDec.reason||'—'}</div>
    <div class="dec-meta">
      ${lastDec.solar_w!=null?`<span>☀️ ${this._fmt(lastDec.solar_w)}</span>`:''}
      ${lastDec.soc_pct!=null?`<span>🔋 ${Math.round(lastDec.soc_pct)}%</span>`:''}
      ${lastDec.price_all_in_eur_kwh!=null?`<span>€ ${Math.round(lastDec.price_all_in_eur_kwh*100)}ct</span>`:''}
    </div>
  </div>
</div>`:''}`;
  }

  /* ── CATEGORIEËN ─────────────────────────────────────────────────────────── */
  _tabCats(){
    const pie=this._a('sensor.cloudems_verbruik_categorien','pie_data',[])||[];
    const ins=this._a('sensor.cloudems_verbruik_categorien','dominant_insight','')||'';
    const maxPct=Math.max(...pie.map(c=>c.pct||0),1);
    const COLORS=['#60a5fa','#EF9F27','#a78bfa','#34d399','#f97316','#f87171'];
    if(!pie.length)return`<div class="empty">Categorieën worden opgebouwd gedurende de dag.</div>`;
    return`<div class="cat-section">
${pie.map((c,i)=>{
  const col=COLORS[i%COLORS.length]; const barW=Math.round((c.pct||0)/maxPct*100);
  const active=(c.w_now||0)>10;
  return`<div class="cat-row">
    <div style="font-size:12px">${c.icon||'🔧'}</div>
    <div style="font-size:12px;color:rgba(255,255,255,${active?'0.85':'0.4'})">${c.name||'—'}</div>
    <div style="font-size:12px;font-weight:700;text-align:right;color:${active?'rgba(255,255,255,0.9)':'rgba(255,255,255,0.3)'}">${Math.round(c.w_now||0)} W</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.4);text-align:right">${parseFloat(c.kwh||0).toFixed(2)} kWh</div>
    <div style="font-size:11px;font-weight:700;text-align:right;color:${active?col:'rgba(255,255,255,0.3)'}">${Math.round(c.pct||0)}%</div>
  </div>
  <div class="cat-bg"><div class="cat-fg" style="width:${barW}%;background:${active?col:'rgba(255,255,255,0.12)'}"></div></div>`;
}).join('')}
</div>
${ins?`<div class="ins">${ins}</div>`:''}`;
  }

  /* ── KAMERS ─────────────────────────────────────────────────────────────── */
  _tabRooms(){
    const rooms=(this._a('sensor.cloudems_kamers_overzicht','rooms',[])||[]).slice().sort((a,b)=>b.power_w-a.power_w);
    const devList=this._a('sensor.cloudems_nilm_devices','device_list',[])||this._a('sensor.cloudems_nilm_devices','devices',[])||[];
    const top=this._a('sensor.cloudems_kamers_overzicht','top_room','')||'';
    const maxW=rooms[0]?.power_w||1;
    const active=rooms.filter(r=>r.power_w>0); const inactive=rooms.filter(r=>r.power_w<=0);
    const roomDevs=(room)=>devList.filter(d=>(d.room||'').toLowerCase()===(room||'').toLowerCase());
    const phC=ph=>ph==='L1'?'#60a5fa':ph==='L2'?'#a78bfa':ph==='L3'?'#34d399':'rgba(255,255,255,0.25)';
    const stC=d=>d.user_suppressed?'rgba(255,255,255,0.3)':d.confirmed?'#34d399':'#a78bfa';
    const stL=d=>d.user_suppressed?'genegeerd':d.confirmed?'bevestigd':'lerend';

    const buildRow=r=>{
      const isTop=r.room?.toLowerCase()===top.toLowerCase()&&r.power_w>0;
      const barPct=Math.round(r.power_w/maxW*100);
      const kwh=(r.kwh_today||0).toFixed(2);
      const name=this._cap(r.room||'?');
      const devs=roomDevs(r.room);
      const isExp=this._expanded.has(r.room);
      const hasDevs=devs.length>0;
      const inactive_room=r.power_w<=0;
      let devRows='';
      if(isExp&&devs.length>0){
        devRows=devs.map(d=>`<div class="dvrow">
          <div class="dot" style="background:${d.is_on?'#22c55e':'rgba(255,255,255,0.15)'}"></div>
          <div style="font-size:11px;color:rgba(255,255,255,0.7);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${d.name||d.device_type||'?'}</div>
          <div style="font-size:11px;text-align:right;color:rgba(255,255,255,0.5)">${d.is_on?Math.round(d.power_w||0)+' W':'—'}</div>
          <div style="font-size:10px;text-align:center;font-weight:700;color:${phC(d.phase||'?')}">${d.phase||'?'}</div>
          <div style="font-size:10px;text-align:right;color:${stC(d)}">${stL(d)}</div>
        </div>`).join('');
      }else if(isExp){devRows=`<div style="padding:5px 25px;font-size:11px;color:rgba(255,255,255,0.25)">Geen apparaten bekend</div>`;}
      return`<div class="row${isTop?' top':''}${inactive_room?' off':''}" data-room="${r.room}" style="cursor:${hasDevs?'pointer':'default'}">
        <div class="rname">${name}</div>
        <div class="rpw" style="${inactive_room?'color:rgba(255,255,255,0.2)':''}">${this._fmt(r.power_w)}</div>
        <div class="rbg"><div class="rfg" style="width:${barPct}%;background:${isTop?'#EF9F27':'#378ADD'}"></div></div>
        <div class="rkwh">${kwh} kWh</div>
        <div class="rexp">${hasDevs?(isExp?'▲':'▼'):''}</div>
      </div>
      ${isExp?`<div class="dvblock">${devRows}</div>`:''}`;
    };

    if(!rooms.length)return`<div class="empty">Geen kamerdata beschikbaar</div>`;
    return`
${active.length?`<div class="sec-lbl">actief</div>${active.map(buildRow).join('')}`:''}
${inactive.length?`<div class="sep"></div><div class="sec-lbl">uit · vandaag kWh</div>${inactive.map(buildRow).join('')}`:''}`;
  }

  /* ── APPARATEN ───────────────────────────────────────────────────────────── */
  _tabDevices(){
    const devList=this._a('sensor.cloudems_nilm_running_devices','device_list',[])||this._a('sensor.cloudems_nilm_running_devices','devices',[])||[];
    const l1=this._v('sensor.cloudems_current_l1')||this._v('sensor.cloudems_grid_phase_l1_current');
    const l2=this._v('sensor.cloudems_current_l2')||this._v('sensor.cloudems_grid_phase_l2_current');
    const l3=this._v('sensor.cloudems_current_l3')||this._v('sensor.cloudems_grid_phase_l3_current');
    const phC=ph=>ph==='L1'?'#60a5fa':ph==='L2'?'#a78bfa':ph==='L3'?'#34d399':'rgba(255,255,255,0.25)';
    const q=(this._devSearch||'').toLowerCase();
    const filtered=q?devList.filter(d=>(d.name||d.device_type||'').toLowerCase().includes(q)):devList;
    const totalW=filtered.reduce((s,d)=>s+(d.power_w||0),0)||1;
    if(!devList.length)return`<div class="empty">Geen actieve apparaten gevonden</div>`;
    return`
<div style="padding:8px 12px 4px">
  <input id="dev-search" type="text" placeholder="🔍 Zoek apparaat…" value="${this._devSearch||''}"
    style="width:100%;box-sizing:border-box;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:7px;padding:6px 10px;font-size:12px;color:rgba(255,255,255,0.85);outline:none;font-family:monospace">
</div>
<div class="ph-bar">
  <div class="ph-chip"><div class="ph-dot" style="background:#60a5fa"></div><span style="font-weight:700">${l1.toFixed(1)}A</span><span style="color:rgba(255,255,255,0.35);font-size:11px">L1</span></div>
  <div class="ph-chip"><div class="ph-dot" style="background:#a78bfa"></div><span style="font-weight:700">${l2.toFixed(1)}A</span><span style="color:rgba(255,255,255,0.35);font-size:11px">L2</span></div>
  <div class="ph-chip"><div class="ph-dot" style="background:#34d399"></div><span style="font-weight:700">${l3.toFixed(1)}A</span><span style="color:rgba(255,255,255,0.35);font-size:11px">L3</span></div>
  <div class="ph-chip"><span>🔌</span><span style="font-weight:700">${filtered.length}</span><span style="color:rgba(255,255,255,0.35);font-size:11px">${q?'gevonden':'actief'}</span></div>
</div>
${filtered.length===0?`<div class="empty">Geen apparaten gevonden voor "${q}"</div>`:`
<div class="dhdr"><div style="text-align:center">Nr</div><div>Apparaat</div><div style="text-align:right">W</div><div style="text-align:center">Fase</div><div style="text-align:center">Bron</div><div style="text-align:right">%</div></div>
${filtered.slice(0,20).map((d,i)=>{
  const isTop=i===0&&!q; const pct=Math.round((d.power_w||0)/totalW*100);
  const bron=d.source_type==='smart_plug'?'🔌':'🧠';
  return`<div class="drow${isTop?' top':''}">
    <div class="dnr">${i+1}</div>
    <div class="dn">${d.name||d.device_type||'?'}</div>
    <div class="dw">${Math.round(d.power_w||0)} W</div>
    <div class="dph" style="color:${phC(d.phase||'?')}">${d.phase||'?'}</div>
    <div class="dbr">${bron}</div>
    <div class="dpct">${pct}%</div>
  </div>`;
}).join('')}`}`;
  }

  /* ── ZONNE ───────────────────────────────────────────────────────────────── */
  _tabSolar(){
    const invs=this._a('sensor.cloudems_solar_system','inverters',[])||[];
    if(!invs.length)return`<div class="empty">Geen omvormers geconfigureerd</div>`;
    return invs.map(inv=>{
      const w=parseFloat(inv.current_w||0); const peak=parseFloat(inv.peak_w||0)||1;
      const est=parseFloat(inv.estimated_wp||0); const util=parseFloat(inv.utilisation_pct||0);
      const oriPct=parseFloat(inv.orientation_learning_pct||0);
      const slug=(inv.label||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/,'');
      const dimSt=this._s(`switch.cloudems_pv_dimmer_${slug}`);
      const dimOn=dimSt?.state==='on';
      const dimPct=this._v(`number.cloudems_pv_dimmer_${slug}`,100);
      return`<div class="sol-inv">
        <div class="sol-hdr">
          <div class="sol-name">☀️ ${inv.label||'Omvormer'}</div>
          <div class="sol-w" style="color:${w>50?'#EF9F27':'rgba(255,255,255,0.3)'}">${this._fmt(w)}${est?' / '+Math.round(est/1000).toFixed(1)+' kWp':''}</div>
        </div>
        <div class="sol-stats">
          <div class="sol-stat"><div class="ssl">Piek 7d</div><div class="ssv">${this._fmt(parseFloat(inv.peak_w_7d||peak))}</div></div>
          <div class="sol-stat"><div class="ssl">Richting</div><div class="ssv">${inv.azimuth_compass||'?'}${inv.tilt_deg?' · '+inv.tilt_deg+'°':''}</div></div>
          <div class="sol-stat"><div class="ssl">Fase</div><div class="ssv" style="color:${inv.phase_certain?'#34d399':'rgba(255,255,255,0.4)'}">${inv.phase||'?'}${!inv.phase_certain?' (leren)':''}</div></div>
        </div>
        <div class="sbarlbl"><span>Benutting</span><span>${Math.round(util)}% van ${this._fmt(peak)}</span></div>
        <div class="sbarbg"><div class="sbarfg" style="width:${Math.min(100,util)}%;background:#EF9F27"></div></div>
        <div class="sbarlbl"><span>Dimmer</span><span style="color:${dimOn?'#34d399':'rgba(255,255,255,0.3)'}">${dimOn?dimPct+'% — actief':'uit'}</span></div>
        <div class="sbarbg"><div class="sbarfg" style="width:${dimOn?dimPct:100}%;background:${dimOn?'#34d399':'rgba(255,255,255,0.15)'}"></div></div>
        <div class="badges">
          ${oriPct<100?`<span class="badge bl">oriëntatie lerend ${Math.round(oriPct)}%</span>`:`<span class="badge bg">oriëntatie bekend</span>`}
          ${dimOn?`<span class="badge bg">dimmer aan</span>`:`<span class="badge" style="color:rgba(255,255,255,0.3);border-color:rgba(255,255,255,0.1)">dimmer uit</span>`}
        </div>
        ${oriPct<100?`
        <div class="sbarlbl" style="margin-top:6px"><span>🧭 Oriëntatie leerproces</span><span style="color:#60a5fa">${Math.round(oriPct)}% voltooid</span></div>
        <div class="sbarbg"><div class="sbarfg" style="width:${oriPct}%;background:linear-gradient(90deg,#60a5fa,#a78bfa)"></div></div>
        <div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:3px">Nog ${inv.orientation_samples_needed||'?'} helder-dag opnames nodig voor nauwkeurige richting</div>`:''}
      </div>`;
    }).join('');
  }

  /* ── BATTERIJ ────────────────────────────────────────────────────────────── */
  _tabBat(bw,soc){
    const chargeKwh=this._a('sensor.cloudems_battery_power','charge_kwh_today',0)||0;
    const disKwh=this._a('sensor.cloudems_battery_power','discharge_kwh_today',0)||0;
    const bd=this._a('sensor.cloudems_batterij_epex_schema','battery_decision',{})||{};
    const batSt=this._a('sensor.cloudems_batterij_epex_schema','batteries',[])||[];
    const nexusMode=this._a('sensor.cloudems_batterij_epex_schema','mode','—')||'—';
    const sliderLev=this._v('sensor.cloudems_slider_leveren');
    const sliderZon=this._v('sensor.cloudems_slider_zonladen');
    const actIcon=bd.action==='charge'?'⚡':bd.action==='discharge'?'🔋':'💤';
    const actLabel=bd.action==='charge'?'Laden':bd.action==='discharge'?'Ontladen':'Idle';
    return`
<div class="bat-top">
  <div class="bc"><div class="bcv" style="color:${soc>30?'#34d399':'#f87171'}">${Math.round(soc)}%</div><div class="bcl">SOC</div></div>
  <div class="bc"><div class="bcv" style="color:${bw>50?'#34d399':bw<-50?'#EF9F27':'rgba(255,255,255,0.4)'}">${this._fmt(Math.abs(bw))}</div><div class="bcl">${bw>50?'laden':bw<-50?'ontladen':'idle'}</div></div>
  <div class="bc"><div class="bcv">${parseFloat(disKwh).toFixed(2)}</div><div class="bcl">ontladen kWh</div></div>
</div>
<div class="bat-rows">
  <div class="bat-row"><div class="bat-k">⚡ Geladen vandaag</div><div class="bat-v">${parseFloat(chargeKwh).toFixed(2)} kWh</div></div>
  <div class="bat-row"><div class="bat-k">🔋 Ontladen vandaag</div><div class="bat-v">${parseFloat(disKwh).toFixed(2)} kWh</div></div>
  ${sliderLev?`<div class="bat-row"><div class="bat-k">↓ Leveren aan huis</div><div class="bat-v">${this._fmt(sliderLev)}</div></div>`:''}
  ${sliderZon?`<div class="bat-row"><div class="bat-k">☀️ Zonneladen</div><div class="bat-v">${this._fmt(sliderZon)}</div></div>`:''}
</div>
${bd.action?`<div style="padding:0 13px 10px"><div class="nexus">
  <div class="nx-hdr"><div class="nx-title">⚡ Nexus sturing</div><div class="nx-mode">${nexusMode}</div></div>
  <div class="nx-row"><span>Beslissing</span><span>${actIcon} ${actLabel}</span></div>
  ${bd.reason?`<div class="nx-row"><span>Reden</span><span style="max-width:60%;text-align:right">${(bd.reason||'').substring(0,60)}</span></div>`:''}
  ${bd.soc_target!=null?`<div class="nx-row"><span>SoC doel</span><span>${Math.round(bd.soc_target)}%</span></div>`:''}
</div></div>`:''}
${(()=>{
  const chargeH=this._a('sensor.cloudems_batterij_epex_schema','charge_hours',[])||[];
  const disH=this._a('sensor.cloudems_batterij_epex_schema','discharge_hours',[])||[];
  if(!chargeH.length&&!disH.length)return'';
  const now=new Date().getHours();
  const allH=Array.from({length:24},(_,h)=>h);
  const bars=allH.map(h=>{
    const isCharge=chargeH.includes(h); const isDis=disH.includes(h); const isNow=h===now;
    const col=isCharge?'#34d399':isDis?'#f87171':'rgba(255,255,255,0.06)';
    return`<div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
      <div style="width:100%;height:24px;background:${col};border-radius:2px;opacity:${isNow?1:0.75};${isNow?'outline:1px solid rgba(255,255,255,0.4)':''}"></div>
      <span style="font-size:7px;color:rgba(255,255,255,${isNow?'0.8':'0.2'});text-align:center">${String(h).padStart(2,'0')}</span>
    </div>`;
  }).join('');
  return`<div style="padding:0 13px 10px">
    <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px">Laadschema vandaag</div>
    <div style="display:flex;align-items:flex-end;gap:1px">${bars}</div>
    <div style="display:flex;gap:12px;margin-top:5px">
      <div style="display:flex;align-items:center;gap:4px;font-size:10px;color:rgba(255,255,255,0.4)"><div style="width:10px;height:10px;background:#34d399;border-radius:2px"></div>Laden (${chargeH.length}u)</div>
      <div style="display:flex;align-items:center;gap:4px;font-size:10px;color:rgba(255,255,255,0.4)"><div style="width:10px;height:10px;background:#f87171;border-radius:2px"></div>Ontladen (${disH.length}u)</div>
    </div>
  </div>`;
})()}`;
  }

  /* ── BOILER ──────────────────────────────────────────────────────────────── */
  _tabBoiler(){
    const boilers=this._a('sensor.cloudems_boiler_status','boilers',[])||[];
    if(!boilers.length)return`<div class="empty">Geen boiler geconfigureerd</div>`;
    return boilers.map(b=>{
      const temp=b.temp_c??'—'; const sp=b.active_setpoint_c??b.setpoint_c??60;
      const slug=(b.label||'boiler_1').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/,'');
      const pw=this._v(`sensor.cloudems_boiler_${slug}_power`,b.current_power_w??0);
      const maxPw=b.power_w||2500; const mode=(b.actual_mode||'').toUpperCase();
      const tempPct=temp!=='—'?Math.round((parseFloat(temp)-20)/(85-20)*100):0;
      const pwPct=Math.round(pw/maxPw*100);
      const cop=b.cop_at_current_temp;
      const costSt=this._a('sensor.cloudems_boiler_status','cost_comparison',{})||{};
      return`
<div class="boil-top">
  <div class="boil-tank"><div class="boil-fill" style="height:${tempPct}%"></div></div>
  <div class="boil-info">
    <div class="boil-name">${b.label||'Boiler 1'}</div>
    <div class="boil-sub">${b.boiler_type||''} · ${b.entity_id||''}</div>
    <div style="margin-top:4px;display:flex;align-items:center;gap:7px">
      <div class="boil-temp">${temp}°C</div>
      ${mode?`<div class="boil-badge">${mode}</div>`:''}
    </div>
  </div>
  <div style="text-align:right"><div style="font-size:18px;font-weight:700;color:#EF9F27">${this._fmt(pw)}</div><div style="font-size:10px;color:rgba(255,255,255,0.35)">nu</div></div>
</div>
<div class="boil-bars">
  <div class="bbar">
    <div class="bbarlbl"><span>Temperatuur</span><span>${temp}°C / ${sp}°C setpoint</span></div>
    <div class="bbarbg"><div class="bbarfg" style="width:${tempPct}%;background:linear-gradient(90deg,#60a5fa,#EF9F27)"></div></div>
  </div>
  <div class="bbar">
    <div class="bbarlbl"><span>Vermogen</span><span>${this._fmt(pw)} / ${this._fmt(maxPw)} max</span></div>
    <div class="bbarbg"><div class="bbarfg" style="width:${pwPct}%;background:#EF9F27"></div></div>
  </div>
</div>
<div class="boil-stats">
  <div class="bstat"><div class="bstatv" style="color:#f87171">${this._a(`sensor.cloudems_boiler_${slug}_temp`,'showers_today',0)||0}</div><div class="bstatl">douches</div></div>
  <div class="bstat"><div class="bstatv" style="color:#60a5fa">—</div><div class="bstatl">liter</div></div>
  ${cop!=null?`<div class="bstat"><div class="bstatv" style="color:#34d399">${parseFloat(cop).toFixed(1)}</div><div class="bstatl">COP</div></div>`:'<div class="bstat"></div>'}
</div>
<div class="boil-foot">⚡ Elekriciteit vs gas vergelijking beschikbaar via Boiler tab</div>`;
    }).join('');
  }

  /* ── ROLLUIKEN ───────────────────────────────────────────────────────────── */
  _tabShutters(){
    const shutterData=this._a('sensor.cloudems_status','shutters',{})||{};
    const shutters=shutterData.shutters||[];
    if(!shutters.length)return`<div class="empty">Geen rolluiken geconfigureerd</div>`;
    return`
<div class="shut-hdr">
  <span style="font-size:11px;font-weight:700;color:rgba(255,255,255,0.5)">${shutters.length} rolluiken</span>
  <div class="shut-btns">
    <div class="shut-btn">⬆ Alles op</div>
    <div class="shut-btn">⬇ Alles neer</div>
  </div>
</div>
${shutters.map(s=>{
  const pos=parseFloat(s.position_pct??s.current_position??0);
  const name=s.friendly_name||s.entity_id||'Rolluik';
  const auto=s.auto_enabled?'automatisch':'handmatig';
  const mode=s.mode||auto;
  return`<div class="shut-row">
    <div><div class="shut-name">${name}</div><div class="shut-sub">${pos>0?'open':'dicht'} · ${mode}</div></div>
    <div class="shut-pbg"><div class="shut-pfg" style="width:${pos}%"></div></div>
    <div class="shut-pct">${Math.round(pos)}%</div>
  </div>`;
}).join('')}
<div class="shut-info">Rolluik bediening via CloudEMS Rolluiken tab</div>`;
  }

  /* ── EV ──────────────────────────────────────────────────────────────────── */
  _tabEV(){
    const evSt=this._s('sensor.cloudems_ev_sessie_leermodel');
    const active=this._a('sensor.cloudems_ev_sessie_leermodel','session_active',false);
    const curA=this._a('sensor.cloudems_ev_sessie_leermodel','session_current_a',0)||0;
    const kwh=this._a('sensor.cloudems_ev_sessie_leermodel','session_kwh_so_far',0)||0;
    const cost=this._a('sensor.cloudems_ev_sessie_leermodel','session_cost_so_far',0)||0;
    const predKwh=this._a('sensor.cloudems_ev_sessie_leermodel','predicted_kwh',null);
    const optStart=this._a('sensor.cloudems_goedkoopste_laadmoment','state',null)||this._v('sensor.cloudems_goedkoopste_laadmoment',null);
    const sessions=this._a('sensor.cloudems_ev_sessie_leermodel','sessions_total',0)||0;
    const ready=this._a('sensor.cloudems_ev_sessie_leermodel','model_ready',false);
    const pw=curA*230;
    return`
<div class="tab-block">
  <div class="tb-hdr">🚗 EV Lader <span class="tb-sub" style="color:${active?'#34d399':'rgba(255,255,255,0.35)'}">${active?'SESSIE ACTIEF':'Niet verbonden'}</span></div>
  ${active?`
  <div class="alert alert-g"><span style="font-size:14px">⚡</span><span>Actieve laadsessie — ${curA.toFixed(1)}A · ${this._fmt(pw)}</span></div>
  <div class="stat-row"><div class="stat-k">Geladen deze sessie</div><div class="stat-v">${parseFloat(kwh).toFixed(2)} kWh</div></div>
  <div class="stat-row"><div class="stat-k">Kosten deze sessie</div><div class="stat-v">€${parseFloat(cost).toFixed(2)}</div></div>`:`
  <div class="stat-row"><div class="stat-k">Status</div><div class="stat-v">Niet actief</div></div>`}
</div>
<div class="tab-block">
  <div class="tb-hdr">📅 Planning <span class="tb-sub">${ready?'model gereed':'leren...'}</span></div>
  ${predKwh?`<div class="stat-row"><div class="stat-k">Voorspeld kWh</div><div class="stat-v">${parseFloat(predKwh).toFixed(1)} kWh</div></div>`:''}
  ${optStart?`<div class="stat-row"><div class="stat-k">Optimaal laadmoment</div><div class="stat-v" style="color:#34d399">${String(Math.round(optStart)).padStart(2,'0')}:00</div></div>`:''}
  <div class="stat-row"><div class="stat-k">Sessies geleerd</div><div class="stat-v">${sessions}</div></div>
</div>`;
  }

  /* ── E-BIKE ──────────────────────────────────────────────────────────────── */
  _tabEbike(){
    const sessions=this._a('sensor.cloudems_micro_mobiliteit','active_sessions',[])||[];
    const kwh=this._a('sensor.cloudems_micro_mobiliteit','kwh_today',0)||0;
    const cost=this._a('sensor.cloudems_micro_mobiliteit','cost_today_eur',0)||0;
    const profiles=this._a('sensor.cloudems_micro_mobiliteit','vehicle_profiles',[])||[];
    const advice=this._a('sensor.cloudems_micro_mobiliteit','advice','')||'';
    const bestH=this._a('sensor.cloudems_micro_mobiliteit','best_charge_hour',null);
    const sessToday=this._a('sensor.cloudems_micro_mobiliteit','sessions_today',[])||[];
    return`
<div class="tab-block">
  <div class="tb-hdr">🚲 E-bike laders <span class="tb-sub" style="color:${sessions.length?'#34d399':'rgba(255,255,255,0.35)'}">${sessions.length?sessions.length+' actief':'Geen sessie'}</span></div>
  ${sessions.map(s=>`
  <div class="alert alert-g"><span style="font-size:14px">🚲</span><span>${s.name||'E-bike'} — ${this._fmt((s.power_w||0))}</span></div>
  <div class="stat-row"><div class="stat-k">Geladen</div><div class="stat-v">${parseFloat(s.kwh_so_far||0).toFixed(2)} kWh</div></div>`).join('')||`<div style="font-size:11px;color:rgba(255,255,255,0.3);padding:4px 0">Geen actieve laadsessie</div>`}
</div>
<div class="tab-block">
  <div class="tb-hdr">📊 Vandaag</div>
  <div class="stat-row"><div class="stat-k">Totaal geladen</div><div class="stat-v">${parseFloat(kwh).toFixed(2)} kWh</div></div>
  <div class="stat-row"><div class="stat-k">Kosten vandaag</div><div class="stat-v">€${parseFloat(cost).toFixed(2)}</div></div>
  ${bestH!=null?`<div class="stat-row"><div class="stat-k">Beste laadtijd</div><div class="stat-v" style="color:#34d399">${String(Math.round(bestH)).padStart(2,'0')}:00</div></div>`:''}
  ${sessToday.length?`<div class="stat-row"><div class="stat-k">Sessies vandaag</div><div class="stat-v">${sessToday.length}</div></div>`:''}
</div>
${profiles.length?`<div class="tab-block">
  <div class="tb-hdr">🚲 Voertuigen</div>
  ${profiles.map(p=>`<div class="stat-row"><div class="stat-k">${p.name||'E-bike'}</div><div class="stat-v">${p.battery_kwh||'?'} kWh · ${p.charge_power_w||'?'} W</div></div>`).join('')}
</div>`:''}
${advice?`<div class="ins" style="border-top:1px solid rgba(255,255,255,0.05);padding:7px 13px">${advice}</div>`:''}`;
  }

  /* ── ZWEMBAD ─────────────────────────────────────────────────────────────── */
  _tabPool(){
    const filterOn=this._a('sensor.cloudems_zwembad_status','filter_is_on',false);
    const heatOn=this._a('sensor.cloudems_zwembad_status','heat_is_on',false);
    const filterMode=this._a('sensor.cloudems_zwembad_status','filter_mode','off')||'off';
    const heatMode=this._a('sensor.cloudems_zwembad_status','heat_mode','off')||'off';
    const filterReason=this._a('sensor.cloudems_zwembad_status','filter_reason','')||'';
    const heatReason=this._a('sensor.cloudems_zwembad_status','heat_reason','')||'';
    const waterTemp=this._a('sensor.cloudems_zwembad_status','water_temp_c',null);
    const heatSp=this._a('sensor.cloudems_zwembad_status','heat_setpoint_c',28);
    const filterW=this._a('sensor.cloudems_zwembad_status','filter_power_w',0)||0;
    const heatW=this._a('sensor.cloudems_zwembad_status','heat_power_w',0)||0;
    const filterH=this._a('sensor.cloudems_zwembad_status','filter_hours_today',0)||0;
    const filterTarget=this._a('sensor.cloudems_zwembad_status','filter_target_hours',4)||4;
    const advice=this._a('sensor.cloudems_zwembad_status','advice','')||'';
    const tempPct=waterTemp!=null?Math.round((parseFloat(waterTemp)-15)/(35-15)*100):0;
    return`
<div class="tab-block">
  <div class="tb-hdr">🏊 Zwembad status</div>
  ${!filterOn&&!heatOn?`<div class="alert alert-y"><span>💤</span><span>Systeem in standby</span></div>`:''}
  ${filterOn?`<div class="alert alert-g"><span>🔄</span><span>Filter actief — ${this._fmt(filterW)} ${filterMode?'· '+filterMode:''}</span></div>`:''}
  ${heatOn?`<div class="alert alert-g"><span>🌡️</span><span>Verwarming actief — ${this._fmt(heatW)}</span></div>`:''}
</div>
<div class="tab-block">
  <div class="tb-hdr">🌡️ Watertemperatuur</div>
  ${waterTemp!=null?`
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:7px">
    <div style="font-size:28px;font-weight:700;color:${parseFloat(waterTemp)>=heatSp?'#34d399':'#60a5fa'}">${parseFloat(waterTemp).toFixed(1)}°C</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.4)">setpoint ${heatSp}°C</div>
  </div>
  <div class="bbarlbl"><span>Temperatuur</span><span>${parseFloat(waterTemp).toFixed(1)}°C / ${heatSp}°C</span></div>
  <div class="bbarbg"><div class="bbarfg" style="width:${tempPct}%;background:linear-gradient(90deg,#60a5fa,#34d399)"></div></div>`:`<div style="font-size:11px;color:rgba(255,255,255,0.3)">Temperatuursensor niet geconfigureerd</div>`}
</div>
<div class="tab-block">
  <div class="tb-hdr">🔄 Filter</div>
  <div class="stat-row"><div class="stat-k">Status</div><div class="stat-v" style="color:${filterOn?'#34d399':'rgba(255,255,255,0.4)'}">${filterOn?'Aan':'Uit'} · ${filterMode}</div></div>
  <div class="stat-row"><div class="stat-k">Vandaag</div><div class="stat-v">${parseFloat(filterH).toFixed(1)}u / ${filterTarget}u doel</div></div>
  <div class="bbarlbl" style="margin-top:5px"><span>Voortgang</span><span>${parseFloat(filterH).toFixed(1)}u</span></div>
  <div class="bbarbg"><div class="bbarfg" style="width:${Math.min(100,Math.round(filterH/filterTarget*100))}%;background:#60a5fa"></div></div>
  ${filterReason?`<div style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:4px;font-style:italic">${filterReason}</div>`:''}
</div>
${advice?`<div class="ins" style="border-top:1px solid rgba(255,255,255,0.05);padding:7px 13px">💡 ${advice}</div>`:''}`;
  }

  /* ── PRIJZEN ─────────────────────────────────────────────────────────────── */
  _tabPrices(){
    const prices=this._a('sensor.cloudems_price_current_hour','next_hours',[])||[];
    const cur=this._s('sensor.cloudems_price_current_hour');
    const curCt=cur?parseFloat(cur.state)*100:null;
    if(!prices.length&&curCt===null)return`<div class="empty">Prijsdata niet beschikbaar.</div>`;
    const now=new Date();
    const all=[{hour:now.getHours(),ct:curCt,current:true},...prices.slice(0,23).map((p,i)=>({
      hour:(now.getHours()+i+1)%24,ct:p.price_eur_kwh*100,current:false
    }))];
    const vals=all.map(p=>p.ct).filter(v=>v!==null);
    const mx=Math.max(...vals,35); const mn=Math.min(...vals,0);
    const minCt=Math.min(...vals); const minIdx=all.findIndex(p=>p.ct===minCt);
    return`<div style="padding:8px 0">
      <div style="display:flex;align-items:flex-end;gap:2px;padding:0 12px">
        ${all.map((p,i)=>{
          const h=p.ct!==null?Math.max(6,Math.round((p.ct-mn)/(mx-mn||1)*60+6)):6;
          const isCheapest=i===minIdx;
          return`<div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1;min-width:0">
            ${isCheapest?`<div style="font-size:7px;color:#34d399;text-align:center">★</div>`:''}
            ${p.current?`<div style="font-size:7px;color:rgba(255,255,255,0.5);text-align:center">nu</div>`:'<div style="font-size:7px;color:transparent">.</div>'}
            <div style="width:100%;height:${h}px;background:${p.ct!==null?PCOL(p.ct):'rgba(255,255,255,0.1)'};border-radius:2px;opacity:${p.current?1:0.7};${p.current?'outline:1px solid rgba(255,255,255,0.3)':''}"></div>
            <div style="font-size:7px;color:rgba(255,255,255,${p.current?'0.8':'0.25'});text-align:center">${String(p.hour).padStart(2,'0')}</div>
          </div>`;
        }).join('')}
      </div>
      ${minIdx>=0?`<div style="margin:10px 12px 0;padding:8px 10px;background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.2);border-radius:7px;font-size:11px;color:#34d399">
        ⭐ Goedkoopste uur: ${String(all[minIdx].hour).padStart(2,'0')}:00 — ${all[minIdx].ct!==null?all[minIdx].ct.toFixed(1)+'ct':'—'}
      </div>`:''}
      <div style="display:flex;justify-content:space-between;padding:8px 12px 0;font-size:10px;color:rgba(255,255,255,0.3)">
        <span>Nu: ${curCt!==null?curCt.toFixed(1)+'ct':'—'}</span>
        <span>Min: ${Math.min(...vals).toFixed(1)}ct</span>
        <span>Max: ${Math.max(...vals).toFixed(1)}ct</span>
      </div>
    </div>`;
  }

  /* ── HISTORIE ─────────────────────────────────────────────────────────────── */
  _tabHistory(){
    const decs=this._a('sensor.cloudems_decisions_history','decisions',[])||[];
    if(!decs.length)return`<div class="empty">Nog geen beslissingen opgeslagen.</div>`;
    const catC={boiler:'#a78bfa',battery:'#60a5fa',ev:'#34d399',shutter:'#fbbf24',peak:'#ef4444',solar:'#EF9F27'};
    const cc=c=>catC[(c||'').toLowerCase()]||'rgba(255,255,255,0.3)';
    return`<div style="padding:4px 0">
      ${decs.slice(0,15).map((d,i)=>{
        const col=cc(d.category);
        const ts=d.ts?new Date(d.ts):null;
        const tijdStr=ts?`${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')}`:'—';
        return`<div style="display:flex;gap:10px;padding:7px 13px;border-bottom:1px solid rgba(255,255,255,0.04);align-items:flex-start">
          <div style="display:flex;flex-direction:column;align-items:center;gap:3px;flex-shrink:0">
            <div style="width:8px;height:8px;border-radius:50%;background:${col};margin-top:3px"></div>
            ${i<decs.slice(0,15).length-1?`<div style="width:1px;flex:1;background:rgba(255,255,255,0.07);min-height:16px"></div>`:''}
          </div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">
              <div style="font-size:10px;font-weight:700;color:${col};text-transform:uppercase;letter-spacing:0.05em">${d.category||'—'}</div>
              <div style="font-size:10px;color:rgba(255,255,255,0.3)">${tijdStr} · ${this._ago(d.ts)}</div>
            </div>
            <div style="font-size:11px;color:rgba(255,255,255,0.75);line-height:1.4">${d.message||d.reason||'—'}</div>
            ${d.solar_w!=null||d.soc_pct!=null||d.price_all_in_eur_kwh!=null?`<div style="display:flex;gap:8px;margin-top:3px">
              ${d.solar_w!=null?`<span style="font-size:10px;color:rgba(255,255,255,0.3)">☀️ ${this._fmt(d.solar_w)}</span>`:''}
              ${d.soc_pct!=null?`<span style="font-size:10px;color:rgba(255,255,255,0.3)">🔋 ${Math.round(d.soc_pct)}%</span>`:''}
              ${d.price_all_in_eur_kwh!=null?`<span style="font-size:10px;color:rgba(255,255,255,0.3)">€ ${Math.round(d.price_all_in_eur_kwh*100)}ct</span>`:''}
            </div>`:''}
          </div>
        </div>`;
      }).join('')}
    </div>`;
  }

  /* ── BIND EVENTS ─────────────────────────────────────────────────────────── */
  _bind(){
    const sr=this.shadowRoot;
    const TABS_ORDER=['status','cats','rooms','devs','solar','bat','boiler','shutters','ev','ebike','pool','prices','history'];

    // Tab clicks
    sr.querySelectorAll('.tab[data-tab]').forEach(el=>{
      el.addEventListener('click',()=>{ this._tab=el.dataset.tab; this._prev=''; this._render(); });
    });

    // Klikbare status blokken → navigeer naar juiste tab
    sr.querySelectorAll('.sp-btn').forEach(btn=>{
      btn.addEventListener('click',e=>{
        e.stopPropagation();
        const sp=parseFloat(btn.dataset.sp);
        const ctrl=btn.closest('.boiler-sp-ctrl');
        const slug=ctrl?.dataset.slug||'boiler_1';
        this._hass.callService('water_heater','set_temperature',{entity_id:`water_heater.cloudems_boiler_${slug}`,temperature:sp});
        setTimeout(()=>{this._prev='';},500);
      });
    });
    sr.querySelectorAll('.sc[data-nav]').forEach(el=>{
      el.addEventListener('click',()=>{ this._tab=el.dataset.nav; this._prev=''; this._render(); });
    });

    // Kamer rijen uitklappen
    sr.querySelectorAll('.row[data-room]').forEach(el=>{
      el.addEventListener('click',()=>{
        const r=el.dataset.room;
        if(this._expanded.has(r)) this._expanded.delete(r); else this._expanded.add(r);
        this._prev=''; this._render();
      });
    });

    // Zoekbalk apparaten
    const devSearch=sr.querySelector('#dev-search');
    if(devSearch){
      devSearch.addEventListener('input',e=>{
        this._devSearch=e.target.value;
        this._prev=''; this._render();
      });
      devSearch.addEventListener('click',e=>e.stopPropagation());
    }
    const card=sr.querySelector('.card');
    if(card){
      card.addEventListener('touchstart',e=>{ this._swipeX=e.touches[0].clientX; },{passive:true});
      card.addEventListener('touchend',e=>{
        const dx=e.changedTouches[0].clientX-this._swipeX;
        if(Math.abs(dx)<50)return;
        const idx=TABS_ORDER.indexOf(this._tab);
        if(dx<0&&idx<TABS_ORDER.length-1) this._tab=TABS_ORDER[idx+1];
        else if(dx>0&&idx>0) this._tab=TABS_ORDER[idx-1];
        this._prev=''; this._render();
      },{passive:true});

      // Dubbeltik op header → refresh
      const hdr=sr.querySelector('.hdr');
      if(hdr){
        hdr.addEventListener('click',()=>{
          const now=Date.now();
          if(now-this._lastTap<400){ this._prev=''; this._render(); }
          this._lastTap=now;
        });
        hdr.style.cursor='pointer';
        hdr.title='Dubbel tikken om te verversen';
      }
    }
  }

  static getConfigElement(){return document.createElement('cloudems-home-card-editor');}
  static getStubConfig(){return {title:'CloudEMS Home', max_ampere:25};}
}

class CloudEMSHomeCardEditor extends HTMLElement {
  setConfig(c){this._config=c||{};}
  set hass(h){}
  connectedCallback(){
    if(this._built)return; this._built=true;
    this.innerHTML=`<div style="padding:12px;font-size:13px;display:flex;flex-direction:column;gap:8px">
      <label>Max ampere per fase<br><input type="number" id="max_a" value="${this._config.max_ampere||25}" min="10" max="40" style="width:80px;margin-top:4px;padding:4px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.07);color:inherit"></label>
    </div>`;
    this.querySelector('#max_a').addEventListener('change',e=>{
      this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:{...this._config,max_ampere:parseInt(e.target.value)}},bubbles:true,composed:true}));
    });
  }
}

customElements.define('cloudems-home-card', CloudEMSHomeCard);
customElements.define('cloudems-home-card-editor', CloudEMSHomeCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-home-card',name:'CloudEMS Home',description:'Volledig energie overzicht — 11 tabs'});
console.info('%c CloudEMS Home Card v'+HCV,'color:#EF9F27;font-weight:700');
