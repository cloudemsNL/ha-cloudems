// CloudEMS AI Card v5.5.465 — AI Status, k-NN learning model
const CARD_AI_VERSION = '5.5.465';

class CloudemsAiCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._cfg={};}
  static getConfigElement(){return document.createElement('cloudems-ai-card-editor');}
  setConfig(c){this._cfg=c||{};this._render();}
  _render(){
    var sh=this.shadowRoot;sh.innerHTML='';
    var s=document.createElement('style');s.textContent=':host{display:block;padding:12px}';sh.appendChild(s);
    var d=document.createElement('div');d.style.cssText='color:var(--secondary-text-color);font-size:13px';
    d.textContent='Geen configuratie nodig.';sh.appendChild(d);
  }
}
if(!customElements.get('cloudems-ai-card-editor'))customElements.define('cloudems-ai-card-editor',CloudemsAiCardEditor);

class CloudemsAiCard extends HTMLElement {
  set hass(h){this._hass=h;this._update();}
  setConfig(c){this._config=c;}
  getCardSize(){return 3;}
  static getConfigElement(){return document.createElement('cloudems-ai-card-editor');}
  static getStubConfig(){return {};}

  _fmt(v,unit=''){if(v==null||v===undefined)return '—';return v+unit;}

  _update(){
    if(!this._hass)return;
    const st=this._hass.states['sensor.cloudems_ai_status'];
    if(!st){this.innerHTML='<ha-card style="padding:16px;color:var(--secondary-text-color)">AI Status sensor niet gevonden.</ha-card>';return;}
    const a=st.attributes||{};
    const state=st.state||'—';
    const ready=a.ready===true;
    const nTrained=a.n_trained||0;
    const nBuf=a.buffer_size||0;
    const retrainAt=a.retrain_at||24;
    const nSince=a.n_since_train||0;
    const confirmed=a.devices_confirmed||0;
    const total=a.devices_total||0;
    const provider=a.provider||'database';
    const modelVer=a.model_version||'—';
    const onnx=a.onnx_available===true;
    const confThr=a.confidence_threshold_pct||65;
    const solar=a.solar_learning||{};

    const statusColor=ready?'#4ade80':nTrained>0?'#fb923c':'#6b7280';
    const statusLabel=ready?'Gereed':'Aan het leren';
    const bufPct=retrainAt>0?Math.min(100,Math.round(nBuf/retrainAt*100)):0;

    this.innerHTML=`<ha-card style="padding:16px;font-family:var(--paper-font-body1_-_font-family,inherit)">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <span style="font-size:22px">🧠</span>
        <div>
          <div style="font-size:14px;font-weight:700;color:#e2e8f0">Lokale AI — k-NN Model</div>
          <div style="font-size:11px;color:${statusColor};font-weight:600">${statusLabel}</div>
        </div>
        <div style="margin-left:auto;font-size:11px;color:#6b7280">
          ${onnx?'<span style="color:#60a5fa">ONNX ✓</span>':'<span style="color:#6b7280">ONNX ✗</span>'}
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
        <div style="background:#1e293b;border-radius:8px;padding:10px">
          <div style="font-size:10px;color:#6b7280;margin-bottom:2px">Getraind</div>
          <div style="font-size:20px;font-weight:700;color:#e2e8f0">${nTrained}</div>
          <div style="font-size:10px;color:#6b7280">samples</div>
        </div>
        <div style="background:#1e293b;border-radius:8px;padding:10px">
          <div style="font-size:10px;color:#6b7280;margin-bottom:2px">NILM apparaten</div>
          <div style="font-size:20px;font-weight:700;color:#e2e8f0">${confirmed}<span style="font-size:12px;color:#6b7280">/${total}</span></div>
          <div style="font-size:10px;color:#6b7280">bevestigd</div>
        </div>
      </div>

      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;margin-bottom:4px">
          <span>Buffer hertraining</span>
          <span>${nBuf}/${retrainAt} (${bufPct}%)</span>
        </div>
        <div style="background:#1e293b;border-radius:4px;height:6px;overflow:hidden">
          <div style="height:100%;width:${bufPct}%;background:${bufPct>=100?'#4ade80':'#60a5fa'};border-radius:4px;transition:width .3s"></div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;color:#6b7280;margin-bottom:12px">
        <div>Provider: <span style="color:#e2e8f0">${provider}</span></div>
        <div>Model: <span style="color:#e2e8f0">${modelVer}</span></div>
        <div>Drempel: <span style="color:#e2e8f0">${confThr}%</span></div>
        <div>Status: <span style="color:${statusColor}">${state}</span></div>
      </div>

      ${solar.profiles>0?`
      <div style="border-top:1px solid #1e293b;padding-top:10px">
        <div style="font-size:11px;font-weight:600;color:#6b7280;margin-bottom:6px">☀️ Solar leren</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;color:#6b7280">
          <div>Profielen: <span style="color:#e2e8f0">${solar.profiles}</span></div>
          <div>Piek: <span style="color:#e2e8f0">${solar.estimated_kwp||0} kWp</span></div>
        </div>
      </div>`:''}
    </ha-card>`;
  }
}
if(!customElements.get('cloudems-ai-card'))customElements.define('cloudems-ai-card',CloudemsAiCard);

window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-ai-card',name:'CloudEMS AI',description:'Lokale AI status — k-NN model'});
