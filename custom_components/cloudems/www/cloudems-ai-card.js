// CloudEMS AI Card v1.4.0 — Local AI status, k-NN model trained on own data
const CARD_AI_VERSION = '5.4.8';
// No pre-trained data — learns purely from this installation
'use strict';

class CloudemsAiCard extends HTMLElement {
  setConfig(c) { this._cfg = { title: '🧠 Lokale AI', ...c }; }
  set hass(h) { this._hass = h; this._render(); }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    const h = this._hass;
    const ai = h?.states['sensor.cloudems_ai_status'];
    if (!ai) { this.shadowRoot.innerHTML = `<div style="padding:16px;color:rgba(255,255,255,.3);font-size:12px">sensor.cloudems_ai_status niet gevonden</div>`; return; }

    const attr     = ai.attributes || {};
    const state    = ai.state || 'unavailable';
    const ready    = attr.ready === true;
    const nTrained    = attr.n_trained || 0;
    const bufSize     = attr.buffer_size || 0;
    const nSinceTrain = attr.n_since_train != null ? attr.n_since_train : null;
    const retrainAt   = attr.retrain_at || 24;
    const onnx     = attr.onnx_available === true;
    const provider = attr.default_provider || 'onnx_local';
    const providers= attr.providers || [provider];
    const version  = attr.model_version || 'none';
    const label    = attr.last_label || '—';
    const conf     = attr.last_confidence != null ? Math.round(attr.last_confidence * 100) : null;
    const expl        = attr.last_explanation || '';
    const nilmStats   = attr.nilm_seq2p || null;
    const evStats     = attr.ev_learner || null;
    const shutterStats = attr.shutter_learner || null;
    const outcomeStats  = attr.outcome_stats || null;
    const thresholds    = attr.thresholds || null;
    const learningLog   = attr.learning_log || null;
    const sanity        = attr.sanity || null;
    const anomalies     = sanity && sanity.anomalies && sanity.anomalies.length > 0 ? sanity.anomalies : null;
    const contract = attr.contract_version || '—';

    const MIN_SAMPLES = 48;
    const progress = Math.min(100, Math.round((nTrained / MIN_SAMPLES) * 100));

    const statusCol = ready ? '#4ade80' : '#fbbf24';
    const statusTxt = ready ? 'Actief' : (nTrained === 0 ? 'Nog geen data' : `Leren (${progress}%)`);

    const labelColors = {
      charge_battery:'#4ade80', discharge_battery:'#f87171',
      run_boiler:'#fb923c', export_surplus:'#f5c518',
      defer_load:'#a78bfa', idle:'rgba(255,255,255,.3)',
    };
    const labelCol = labelColors[label] || 'rgba(255,255,255,.4)';

    const kv = (l, v, col='rgba(255,255,255,.7)') =>
      `<div class="row"><span class="lbl">${l}</span><span class="val" style="color:${col}">${v}</span></div>`;

    this.shadowRoot.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:#1e1e2e;border:1px solid rgba(255,255,255,.07);border-radius:14px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;justify-content:space-between;padding:13px 16px 10px;border-bottom:1px solid rgba(255,255,255,.06)}
  .title{font-size:12px;font-weight:700;color:rgba(255,255,255,.5);text-transform:uppercase;letter-spacing:.8px}
  .badge{font-size:10px;font-weight:700;padding:2px 10px;border-radius:10px;background:${statusCol}22;color:${statusCol};border:1px solid ${statusCol}55}
  .body{padding:12px 16px 14px}
  .row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04)}
  .row:last-child{border:none}
  .lbl{font-size:11px;color:rgba(163,163,163,.65)}
  .val{font-size:11px;font-weight:600}
  .prog-bg{background:rgba(255,255,255,.07);border-radius:4px;height:6px;margin:10px 0 6px;overflow:hidden}
  .prog-fill{height:6px;border-radius:4px;background:${ready?'#4ade80':'#fbbf24'};transition:width .4s;width:${ready?100:progress}%}
  .expl{font-size:10px;color:rgba(163,163,163,.55);font-style:italic;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.05);line-height:1.5}
  .providers{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .prov{font-size:9px;padding:2px 8px;border-radius:8px;border:1px solid rgba(255,255,255,.12);color:rgba(255,255,255,.4)}
  .prov.active{border-color:#60a5fa55;color:#60a5fa;background:#60a5fa15}
  .influence{margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,.05)}
  .inf-title{font-size:10px;color:rgba(163,163,163,.4);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}
  .inf-row{display:flex;justify-content:space-between;align-items:center;padding:3px 0}
  .inf-lbl{font-size:11px;color:rgba(163,163,163,.55)}
  .inf-val{font-size:11px;font-weight:600;text-align:right}
</style>
<div class="card">
  <div class="hdr">
    <span class="title">${this._cfg.title}</span>
    <span class="badge">${statusTxt}</span>
  </div>
  <div class="body">
    ${anomalies ? `
    <div style="background:#ef444415;border:1px solid #ef444440;border-radius:8px;padding:8px 10px;margin-bottom:10px">
      <div style="font-size:10px;font-weight:700;color:#f87171;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px">
        ⚠ ${anomalies.length} data-anomalie${anomalies.length>1?'s':''} actief
      </div>
      ${anomalies.slice(0,3).map(a=>`
      <div style="font-size:10px;color:#fca5a5;padding:2px 0;border-bottom:1px solid rgba(239,68,68,.1)">
        <span style="color:#ef4444;font-weight:600">[${a.check_id}]</span>
        ${a.description.length>60?a.description.slice(0,60)+'…':a.description}
        <span style="color:rgba(255,255,255,.3)">(${a.active_min}min)</span>
      </div>`).join('')}
    </div>
    ` : ''}
    ${!ready ? `
      <div style="font-size:11px;color:rgba(255,255,255,.35);margin-bottom:6px">
        Het model leert van jouw installatie. 1 sample per minuut.
      </div>
      <div class="prog-bg"><div class="prog-fill"></div></div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px">
        <span style="font-size:10px;color:rgba(255,255,255,.3)">${nTrained} / ${MIN_SAMPLES} samples</span>
        <span style="font-size:10px;color:#fbbf24;font-weight:600">
          ${nTrained === 0
            ? '⏱ ~2 min tot eerste model'
            : nTrained < MIN_SAMPLES
              ? '⏱ nog ~' + (MIN_SAMPLES - nTrained) + ' min'
              : ''}
        </span>
      </div>
      <div style="font-size:10px;color:rgba(255,255,255,.2);margin-top:6px;line-height:1.5">
        Fase 1: k-NN patroonherkenning (lokaal, geen cloud).<br>
        Bootstrap-heuristieken zijn al actief als tijdelijke basis.
      </div>
    ` : `
      <div style="font-size:10px;color:#4ade8044;margin-bottom:6px">
        ✓ Model actief — leert continu bij van elke beslissing.
      </div>
    `}
    ${kv('Laatste beslissing', label !== '—' ? label.replace(/_/g,' ') : '—', labelCol)}
    ${conf !== null ? kv('Zekerheid', conf + '%', conf >= 70 ? '#4ade80' : conf >= 40 ? '#fbbf24' : '#f87171') : ''}
    ${kv('Getraind op', nTrained.toLocaleString() + ' samples')}
    ${kv('Buffer', bufSize + ' samples')}
      ${nSinceTrain != null ? kv('Nieuw (→retrain)', nSinceTrain + ' / ' + retrainAt) : ''}
    ${kv('Model versie', version)}
    ${kv('Contract', 'v' + contract)}
    ${kv('ONNX runtime', onnx ? '✓ Beschikbaar' : '— k-NN fallback', onnx ? '#4ade80' : 'rgba(255,255,255,.35)')}
    ${expl ? `<div class="expl">${expl}</div>` : ''}
    ${ready ? `
    <div class="influence">
      <div class="inf-title">Invloed op modules</div>
      <div class="inf-row">
        <span class="inf-lbl">🔋 Batterij</span>
        <span class="inf-val" style="color:${label==='charge_battery'?'#4ade80':label==='discharge_battery'?'#f87171':'rgba(255,255,255,.3)'}">
          ${label==='charge_battery'?'nudge laden ↑':label==='discharge_battery'?'nudge ontladen ↑':'geen'}
          ${conf!==null&&(label==='charge_battery'||label==='discharge_battery')?` (${conf}%)`:''}
        </span>
      </div>
      <div class="inf-row">
        <span class="inf-lbl">🔥 Boiler</span>
        <span class="inf-val" style="color:${label==='run_boiler'?'#fb923c':'rgba(255,255,255,.3)'}">
          ${label==='run_boiler'?`surplus drempel -200W (${conf}%)`:'geen'}
        </span>
      </div>
      <div style="font-size:9px;color:rgba(255,255,255,.2);margin-top:6px">
        Veiligheidsregels worden nooit overschreven
      </div>
    </div>
    ` : `<div style="font-size:10px;color:rgba(255,255,255,.25);margin-top:8px">Invloed actief na eerste training (${MIN_SAMPLES} samples)</div>`}
    <div class="providers">
      ${providers.map(p => `<span class="prov${p===provider?' active':''}">${p}</span>`).join('')}
    </div>
    ${thresholds && thresholds.n_learned > 0 ? `
    <div class="influence" style="margin-top:8px">
      <div class="inf-title">Zelfgeleerde drempels (${thresholds.n_learned}/${thresholds.n_thresholds})</div>
      ${Object.entries(thresholds.thresholds||{}).filter(([,v])=>v.n_obs>=5).slice(0,4).map(([name,v])=>`
      <div class="inf-row">
        <span class="inf-lbl" style="font-size:10px">${name.replace(/_/g,' ').toLowerCase()}</span>
        <span class="inf-val" style="color:${v.confidence>0.8?'#4ade80':'#facc15'};font-size:10px">
          ${v.active.toFixed(2)} <span style="opacity:.4">(def ${v.default.toFixed(2)})</span>
        </span>
      </div>`).join('')}
    </div>` : ''}
    ${nilmStats || evStats || shutterStats ? `
    <div class="influence" style="margin-top:8px">
      <div class="inf-title">Lerende modules</div>
      ${nilmStats ? `<div class="inf-row"><span class="inf-lbl">🔌 NILM Seq2Point</span><span class="inf-val" style="color:${nilmStats.n_signatures>0?'#4ade80':'rgba(255,255,255,.3)'}">
        ${nilmStats.n_signatures} handtekeningen · ${nilmStats.unexplained_w}W onverklaard</span></div>` : ''}
      ${evStats ? `<div class="inf-row"><span class="inf-lbl">🚗 EV Patronen</span><span class="inf-val" style="color:${evStats.ready?'#4ade80':'rgba(255,255,255,.3)'}">
        ${evStats.n_trips} ritten${evStats.ready?' · actief':' · leren'}</span></div>` : ''}
      ${shutterStats ? `<div class="inf-row"><span class="inf-lbl">🪟 Rolluiken</span><span class="inf-val" style="color:${shutterStats.shutters_ready>0?'#4ade80':'rgba(255,255,255,.3)'}">
        ${shutterStats.total_obs} observaties · ${shutterStats.shutters_ready}/${shutterStats.n_shutters} actief</span></div>` : ''}
      ${outcomeStats ? `<div class="inf-row"><span class="inf-lbl">🎯 Uitkomsten</span><span class="inf-val" style="color:${(outcomeStats.avg_reward||0)>0?'#4ade80':'#f87171'}">
        ${outcomeStats.n_measured} gemeten · gem. reward ${((outcomeStats.avg_reward||0)*100).toFixed(0)}%</span></div>` : ''}
      ${learningLog ? `<div class="inf-row"><span class="inf-lbl">📓 Trainingslog</span><span class="inf-val" style="color:${learningLog.training_ready?'#4ade80':'rgba(255,255,255,.3)'}">
        ${learningLog.n_entries} entries · ${learningLog.n_with_outcome} met uitkomst${learningLog.training_ready?' · klaar':''}
      </span></div>` : ''}
    </div>
    ` : ''}
  </div>
</div>`;
  }

  static getConfigElement() { return document.createElement('cloudems-ai-card-editor'); }
  static getStubConfig() { return { title: '🧠 Lokale AI' }; }
}

class CloudemsAiCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `
      <label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label>
      <input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px"
        id="t" value="${this._config?.title||'🧠 Lokale AI'}"/>`;
    this.shadowRoot.getElementById('t').addEventListener('input', e =>
      this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-ai-card')) customElements.define('cloudems-ai-card', CloudemsAiCard);
if (!customElements.get('cloudems-ai-card-editor')) customElements.define('cloudems-ai-card-editor', CloudemsAiCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: 'cloudems-ai-card', name: 'CloudEMS AI', description: 'Lokale AI status — leert van eigen data' });
