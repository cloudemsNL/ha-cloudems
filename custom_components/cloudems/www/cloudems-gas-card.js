/**
 * CloudEMS Gas Card — cloudems-gas-card
 * Toont gasverbruik per periode met drill-down per klik.
 * Klik op periode → zie breakdown (week→dagen, maand→weken, jaar→maanden)
 */

const CARD_GAS_VERSION = '5.5.465';

class CloudEMSGasCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass    = null;
    this._prev    = '';
    this._drill   = null;   // 'week' | 'maand' | 'jaar' | null
    this._showFib = false;  // toggle m³/uur sectie
  }

  setConfig(c) {
    this._config = c || {};
    setTimeout(() => { this._prev = ''; this._render(); }, 3000);
  }

  
  static getConfigElement(){return document.createElement('cloudems-gas-card-editor');}
  set hass(h) {
    this._hass = h;
    this._render();
  }

  _s(e)          { return this._hass?.states?.[e] || null; }
  _v(e, d = 0)   { const s = this._s(e); if (!s || s.state === 'unavailable' || s.state === 'unknown') return d; return parseFloat(s.state) || d; }
  _a(e, k, d=null){ return this._s(e)?.attributes?.[k] ?? d; }

  _render() {
    if (!this._hass) return;

    const gs = 'sensor.cloudems_gasstand';
    const wb = 'sensor.cloudems_goedkoopste_warmtebron';

    const stand      = this._v(gs, null);
    const dagM3      = this._a(gs, 'dag_m3',    0);
    const weekM3     = this._a(gs, 'week_m3',   0);
    const maandM3    = this._a(gs, 'maand_m3',  0);
    const jaarM3     = this._a(gs, 'jaar_m3',   0);
    const dagEur     = this._a(gs, 'dag_eur',   0);
    const weekEur    = this._a(gs, 'week_eur',  0);
    const maandEur   = this._a(gs, 'maand_eur', 0);
    const jaarEur    = this._a(gs, 'jaar_eur',  0);
    const prijs      = this._a(gs, 'gas_prijs_per_m3', 1.25);
    const kwh        = this._a(gs, 'gas_kwh', null);
    const ttfSpot    = this._a(gs, 'gas_ttf_spot_eur_m3', null);
    const ttfSource  = this._a(gs, 'gas_ttf_source', null);
    const ttfComps   = this._a(gs, 'gas_ttf_components', null);
    const ttfAge     = this._a(gs, 'gas_ttf_cache_age_min', null);
    const gasSupp    = this._a(gs, 'gas_supplier', 'none');
    const gasNb      = this._a(gs, 'gas_netbeheerder', 'default');
    const dayRecords = this._a(gs, 'day_records', []);

    const sig = [stand, dagM3, weekM3, maandM3, jaarM3, dayRecords.length, this._drill].join('|');
    if (sig === this._prev) return;
    this._prev = sig;

    // ── Normaliseer op daggemiddelde voor eerlijke balkbreedte ────────────────
    const avg = v => v; // raw vergelijking — vandaag vs week/7 etc.
    const maxAvg = Math.max(dagM3, weekM3/7, maandM3/30, jaarM3/365, 0.001);

    // Gisteren uit day_records
    const yesterdayStr = (() => {
      const d = new Date(); d.setDate(d.getDate() - 1);
      return d.toISOString().split('T')[0];
    })();
    const yesterdayRec = dayRecords.find(r => r.date === yesterdayStr)
                      || dayRecords.find(r => (r.date || r.day || '') === yesterdayStr);
    const gisterM3  = yesterdayRec ? (yesterdayRec.gas_m3 ?? 0) : null;
    const gisterEur = yesterdayRec ? (yesterdayRec.cost_eur ?? (gisterM3 != null ? gisterM3 * prijs : 0)) : null;

    const periodes = [
      { id: 'dag',      label: 'Vandaag',         m3: dagM3,    eur: dagEur,    avg: dagM3,       hasBreak: false },
      { id: 'gisteren', label: 'Gisteren',         m3: gisterM3, eur: gisterEur, avg: gisterM3,    hasBreak: false },
      { id: 'week',     label: 'Laatste 7 dagen',  m3: weekM3,   eur: weekEur,   avg: weekM3/7,    hasBreak: true  },
      { id: 'maand',    label: 'Deze maand',        m3: maandM3,  eur: maandEur,  avg: maandM3/30,  hasBreak: true  },
      { id: 'jaar',     label: 'Dit jaar',          m3: jaarM3,   eur: jaarEur,   avg: jaarM3/365,  hasBreak: true  },
    ];

    // ── Drill-down data berekenen ─────────────────────────────────────────────
    const today = new Date();
    const todayStr = today.toISOString().split('T')[0];

    // Groepeer dagrecords per week (ma-zo) of per maand
    const groupByWeek = (records) => {
      const weeks = {};
      records.forEach(r => {
        const d = new Date(r.date);
        const mon = new Date(d); mon.setDate(d.getDate() - d.getDay() + (d.getDay() === 0 ? -6 : 1));
        const key = mon.toISOString().split('T')[0];
        if (!weeks[key]) weeks[key] = { label: `Wk ${mon.getDate()}/${mon.getMonth()+1}`, m3: 0, cost: 0, days: 0 };
        weeks[key].m3   += r.gas_m3;
        weeks[key].cost += r.cost_eur;
        weeks[key].days++;
      });
      return Object.values(weeks).slice(-5);
    };

    const groupByMonth = (records) => {
      const months = {};
      const mnNames = ['Jan','Feb','Mrt','Apr','Mei','Jun','Jul','Aug','Sep','Okt','Nov','Dec'];
      records.forEach(r => {
        const key = r.date.substring(0, 7);
        if (!months[key]) months[key] = { label: mnNames[parseInt(r.date.substring(5,7))-1], m3: 0, cost: 0 };
        months[key].m3   += r.gas_m3;
        months[key].cost += r.cost_eur;
      });
      return Object.values(months);
    };

    // ── HTML opbouwen ─────────────────────────────────────────────────────────
    const fmtM3  = v => v > 0 ? `${v.toFixed(2)} m³` : '—';
    const fmtEur = v => v > 0 ? `€${v.toFixed(2)}` : '—';
    const gasActive = stand !== null && stand > 0;

    let periodeRows = '';
    periodes.forEach(p => {
      const barW = Math.min(100, Math.round((p.avg / maxAvg) * 100));
      const isOpen = this._drill === p.id;
      const canDrill = p.hasBreak && dayRecords.length > 0;

      // Drill-down inhoud
      let drillHtml = '';
      if (isOpen && canDrill) {
        let items = [];
        if (p.id === 'week') {
          // Laatste 7 dagrecords
          const cutoff = new Date(today); cutoff.setDate(today.getDate() - 7);
          const cutStr = cutoff.toISOString().split('T')[0];
          items = dayRecords.filter(r => r.date >= cutStr).slice(-7);
          items = items.map(r => ({
            label: new Date(r.date).toLocaleDateString('nl-NL', {weekday:'short', day:'numeric', month:'short'}),
            m3: r.gas_m3, cost: r.cost_eur, indicatief: false
          }));
        } else if (p.id === 'maand') {
          // Groepeer op weken
          const mn = todayStr.substring(0, 7);
          const mnRecs = dayRecords.filter(r => r.date.startsWith(mn));
          items = groupByWeek(mnRecs).map(w => ({
            label: w.label, m3: w.m3, cost: w.cost, indicatief: false
          }));
        } else if (p.id === 'jaar') {
          // Groepeer op maanden
          const yr = todayStr.substring(0, 4);
          const yrRecs = dayRecords.filter(r => r.date.startsWith(yr));
          items = groupByMonth(yrRecs).map(m => ({
            label: m.label, m3: m.m3, cost: m.cost, indicatief: true
          }));
        }

        const drillMax = Math.max(...items.map(i => i.m3), 0.001);
        drillHtml = `<div class="drill">` + items.map(item => {
          const bw = Math.min(100, Math.round((item.m3 / drillMax) * 100));
          return `<div class="drow">
            <span class="dlabel">${item.label}</span>
            <div class="pbar-wrap"><div class="pbar" style="width:${bw}%"></div></div>
            <span class="dval">${item.m3 > 0 ? item.m3.toFixed(2) + ' m³' : '—'}</span>
            <span class="deur ${item.indicatief ? 'indicatief' : ''}">${item.cost > 0 ? '€' + item.cost.toFixed(2) : '—'}${item.indicatief ? '*' : ''}</span>
          </div>`;
        }).join('') + `${items.some(i=>i.indicatief) ? '<div class="indicatief-note">* indicatief op basis van huidige prijs</div>' : ''}</div>`;
      }

      const _TTGas = window.CloudEMSTooltip;
      const _ttProw = _TTGas ? _TTGas.html('gs-'+p.id, p.label, [
        {label:'Sensor',    value:'cloudems_gasstand'},
        {label:'Verbruik',  value:gasActive ? fmtM3(p.m3) : '—'},
        {label:'Kosten',    value:gasActive && p.eur > 0 ? fmtEur(p.eur) : '—'},
        {label:'Gem. per dag', value:gasActive ? fmtM3(p.avg)+'/dag' : '—', dim:true},
        {label:'Gasprijs',  value:prijs ? fmtEur(prijs)+'/m³' : '—', dim:true},
        ...(ttfSpot != null ? [{label:'TTF spot', value:'€'+ttfSpot.toFixed(4)+'/m³', dim:true}] : []),
      ], {footer: canDrill ? 'Klik om uit te klappen per periode' : '● Gemeten via P1 of gasmeter'}) : {wrap:'',tip:''};
      periodeRows += `
        <div class="prow ${canDrill ? 'clickable' : ''} ${isOpen ? 'open' : ''}" data-id="${p.id}" style="position:relative" ${_ttProw.wrap}>
          <span class="plabel">${p.label}${canDrill ? `<span class="chevron">${isOpen ? '▲' : '▼'}</span>` : ''}</span>
          <div class="pbar-wrap"><div class="pbar" style="width:${barW}%"></div></div>
          <span class="pval">${gasActive ? fmtM3(p.m3) : '—'}</span>
          <span class="peur">${gasActive && p.eur > 0 ? fmtEur(p.eur) : '—'}</span>
          ${_ttProw.tip}
        </div>
        ${drillHtml}`;
    });

    // ── Warmtebron ────────────────────────────────────────────────────────────
    const wbState   = this._s(wb)?.state || '';
    const elecPrijs = this._a(wb, 'elec_price_kwh', null);
    const gasHeat   = this._a(wb, 'gas_per_kwh_heat', null);
    const elecHeat  = this._a(wb, 'elec_boiler_per_kwh_heat', null);
    const hpHeat    = this._a(wb, 'heat_pump_per_kwh_heat', null);
    const isElec    = wbState === 'elektriciteit';
    const isGas     = wbState === 'gas';
    const wbColor   = isElec ? '#4caf50' : isGas ? '#ff8040' : '#ffd600';
    const wbLabel   = isElec ? '⚡ Elektriciteit is goedkoper' : isGas ? '🔥 Gas is goedkoper' : '≈ Ongeveer gelijk';

    const wpBoilerHeat = this._a(wb, 'elec_wp_boiler_per_kwh_heat', null);
    const hpCop        = this._a(wb, 'heat_pump_cop', null);
    const hpCopSource  = this._a(wb, 'heat_pump_cop_source', null);
    const wpBoilerCop  = this._a(wb, 'heat_pump_boiler_cop', null);
    const hasHp        = this._a(wb, 'has_heat_pump', false);

    const copLabel = (cop, source) => {
      if (!cop) return '';
      const src = source === 'geleerd' ? '📡' : source === 'config' ? '⚙️' : '📋';
      return ` <span style="font-size:10px;color:rgba(255,255,255,0.35)">${src} COP ${parseFloat(cop).toFixed(1)}</span>`;
    };

    // WP altijd tonen — ook zonder geconfigureerde WP-entity (informatief)
    // COP: geleerd > config > default (3.5 ruimte, 2.8 boiler)
    const _dispHpCop      = hpCop      || 3.5;
    const _dispWpBoilerCop = wpBoilerCop || 2.8;
    const _elecHpDisp      = elecPrijs != null ? elecPrijs / _dispHpCop * 100 : null;
    const _elecWpBoilerDisp = elecPrijs != null ? elecPrijs / _dispWpBoilerCop * 100 : null;
    const _hpHeatDisp      = hpHeat      || (_elecHpDisp ? _elecHpDisp / 100 : null);
    const _wpBoilerDisp    = wpBoilerHeat || (_elecWpBoilerDisp ? _elecWpBoilerDisp / 100 : null);

    const bronItems = [
      { label: 'Gas via CV (90% eff.)',        val: gasHeat,       best: isGas,  suffix: '' },
      { label: 'Elektrische boiler (resist.)',  val: elecHeat,      best: isElec && !_hpHeatDisp && !_wpBoilerDisp, suffix: '' },
      { label: 'WP boiler',                    val: _wpBoilerDisp,  best: isElec && _wpBoilerDisp && _wpBoilerDisp <= (elecHeat||Infinity) && _wpBoilerDisp <= (_hpHeatDisp||Infinity), suffix: copLabel(_dispWpBoilerCop, hpCopSource) },
      { label: 'Warmtepomp (ruimte)',           val: _hpHeatDisp,    best: isElec && _hpHeatDisp && _hpHeatDisp < (_wpBoilerDisp||Infinity) && _hpHeatDisp < (elecHeat||Infinity), suffix: copLabel(_dispHpCop, hpCopSource) },
    ];

    const bronRows = bronItems.map(b => `
      <div class="brow">
        <span class="blabel">${b.label}${b.suffix}</span>
        <span class="bval">${b.val != null ? (b.val*100).toFixed(1)+' ct/kWh' : '—'}</span>
        <span class="bbest">${b.best ? '✅' : ''}</span>
      </div>`).join('');

    const meterstand = stand !== null ? stand.toLocaleString('nl-NL', {minimumFractionDigits:2}) : '—';
    const kwhStr     = kwh !== null ? parseFloat(kwh).toLocaleString('nl-NL', {minimumFractionDigits:2}) : '—';

    // ── Fibonacci m³/uur berekening ──────────────────────────────────────────
    // gas_fib_hours: server-berekend door coordinator, veilig klein formaat
    const fibRows = this._a(gs, 'gas_fib_hours', []);
    const fibMax  = Math.max(...fibRows.map(r => r.m3 || 0), 0.001);
    const hasAnyFibData = fibRows.some(r => r.m3 !== null);

    const fibHtml = hasAnyFibData
      ? '<div class="fib-section">' + fibRows.map(r => {
          if (r.m3 === null) {
            return `<div class="fib-row">
              <span class="fib-label">laatste ${r.hours}u</span>
              <div class="fib-bar-wrap"></div>
              <span class="fib-m3" style="color:rgba(255,255,255,0.2)">—</span>
              <span class="fib-rate" style="color:rgba(255,255,255,0.2)">geen data</span>
            </div>`;
          }
          const barW = Math.min(100, Math.round((r.m3 / fibMax) * 100));
          const norm = r.m3 / fibMax;
          const barColor = norm < 0.33 ? '#4ade80' : norm < 0.66 ? '#fb923c' : '#f87171';
          const rateStr = (r.rate_m3h < 0.001) ? '0.000 m³/h' : r.rate_m3h.toFixed(3) + ' m³/h';
          return `<div class="fib-row">
            <span class="fib-label">laatste ${r.hours}u</span>
            <div class="fib-bar-wrap"><div class="fib-bar" style="width:${barW}%;background:${barColor}"></div></div>
            <span class="fib-m3">${r.m3.toFixed(3)} m³</span>
            <span class="fib-rate">${rateStr}</span>
          </div>`;
        }).join('') + '</div>'
      : '<div class="fib-section"><div class="fib-nodata">⏳ Data wordt verzameld — beschikbaar na ~1 uur gebruik</div></div>';

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; font-family: var(--primary-font-family, sans-serif); }
        .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; overflow: hidden; }
        .t { font-size: 13px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: rgba(255,255,255,0.5); padding: 14px 16px 10px; }

        .stand { display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
        .stand-item { flex: 1; padding: 10px 16px 12px; }
        .stand-item + .stand-item { border-left: 1px solid rgba(255,255,255,0.06); }
        .stand-lbl { font-size: 10px; color: rgba(255,255,255,0.4); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 3px; }
        .stand-val { font-size: 18px; font-weight: 700; color: #fff; }
        .stand-unit { font-size: 11px; color: rgba(255,255,255,0.5); margin-left: 3px; }

        .periodes { padding: 8px 14px 4px; }
        .prow { display: grid; grid-template-columns: 110px 1fr 70px 60px; align-items: center; gap: 8px; padding: 5px 0; border-radius: 6px; }
        .prow.clickable { cursor: pointer; }
        .prow.clickable:hover { background: rgba(255,255,255,0.04); }
        .prow.open .plabel { color: #fff; }
        .plabel { font-size: 12px; color: rgba(255,255,255,0.6); display: flex; align-items: center; gap: 4px; }
        .chevron { font-size: 8px; color: rgba(255,255,255,0.3); }
        .pbar-wrap { background: rgba(255,255,255,0.06); border-radius: 3px; height: 6px; overflow: hidden; }
        .pbar { height: 100%; background: linear-gradient(90deg, #ff8040, #ffd600); border-radius: 3px; transition: width .4s; }
        .pval { font-size: 12px; color: rgba(255,255,255,0.85); text-align: right; }
        .peur { font-size: 12px; color: #ffd600; text-align: right; font-weight: 600; }

        .drill { margin: 2px 0 6px 8px; border-left: 2px solid rgba(255,136,0,0.3); padding-left: 10px; }
        .drow { display: grid; grid-template-columns: 90px 1fr 70px 60px; align-items: center; gap: 8px; padding: 3px 0; }
        .dlabel { font-size: 11px; color: rgba(255,255,255,0.5); }
        .dval { font-size: 11px; color: rgba(255,255,255,0.7); text-align: right; }
        .deur { font-size: 11px; color: rgba(255,214,0,0.8); text-align: right; }
        .deur.indicatief { color: rgba(255,214,0,0.5); }
        .indicatief-note { font-size: 10px; color: rgba(255,255,255,0.25); margin-top: 4px; }

        hr { border: none; border-top: 1px solid rgba(255,255,255,0.07); margin: 0; }
        .footer { font-size: 11px; color: rgba(255,255,255,0.3); padding: 4px 16px 10px; }

        .wbadge { margin: 10px 16px 8px; padding: 6px 10px; border-radius: 8px; font-size: 13px; font-weight: 600;
          background: rgba(255,255,255,0.05); border: 1px solid ${wbColor}44; color: ${wbColor}; }
        .bronnen { padding: 4px 14px 4px; }
        .brow { display: grid; grid-template-columns: 1fr 90px 24px; align-items: center; gap: 6px; padding: 4px 0; }
        .blabel { font-size: 12px; color: rgba(255,255,255,0.7); }
        .bval { font-size: 12px; color: rgba(255,255,255,0.9); text-align: right; font-weight: 600; }
        .bbest { text-align: center; font-size: 14px; }

        /* ── m³/uur fibonacci sectie ── */
        .fib-toggle { display: flex; align-items: center; gap: 8px; padding: 8px 16px 4px; cursor: pointer; border-top: 1px solid rgba(255,255,255,0.07); }
        .fib-toggle-lbl { font-size: 12px; font-weight: 700; color: rgba(255,255,255,0.5); letter-spacing: .05em; text-transform: uppercase; flex: 1; }
        .fib-toggle-chevron { font-size: 10px; color: rgba(255,255,255,0.3); }
        .fib-section { padding: 4px 14px 12px; }
        .fib-row { display: grid; grid-template-columns: 70px 1fr 72px 64px; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
        .fib-row:last-child { border-bottom: none; }
        .fib-label { font-size: 12px; color: rgba(255,255,255,0.55); }
        .fib-bar-wrap { background: rgba(255,255,255,0.06); border-radius: 3px; height: 5px; overflow: hidden; }
        .fib-bar { height: 100%; border-radius: 3px; transition: width .5s cubic-bezier(.4,0,.2,1); }
        .fib-m3 { font-size: 12px; color: rgba(255,255,255,0.85); text-align: right; }
        .fib-rate { font-size: 11px; color: rgba(255,160,40,0.85); text-align: right; font-family: monospace; }
        .fib-nodata { font-size: 11px; color: rgba(255,255,255,0.25); padding: 8px 0; text-align: center; }
      </style>

      <div class="card">
        <div class="t">🔥 Gas</div>

        <div class="stand">
          <div class="stand-item">
            <div class="stand-lbl">Gasmeter stand</div>
            <div class="stand-val">${meterstand}<span class="stand-unit">m³</span></div>
          </div>
          <div class="stand-item">
            <div class="stand-lbl">Equivalent</div>
            <div class="stand-val">${kwhStr}<span class="stand-unit">kWh</span></div>
          </div>
        </div>

        <div class="t" style="padding-bottom:2px">Verbruik & Kosten</div>
        <div class="periodes">${periodeRows}</div>
        <div class="footer">Gasprijs: €${prijs.toFixed(4)}/m³${ttfSource ? ` (${ttfSource === 'ttf' || ttfSource === 'ttf_cached' ? '📡 TTF' : ttfSource === 'sensor' ? '🔌 sensor' : '⚙️ vast'})` : ''} · Stand: ${stand ? stand.toFixed(1) : '—'} m³</div>
        ${ttfSpot != null ? `<div class="footer" style="color:#6b7280;font-size:10px">TTF spot: €${ttfSpot.toFixed(4)}/m³${ttfComps ? ` · EB: €${(ttfComps.eb||0).toFixed(4)} · netbeheer: €${(ttfComps.netbeheer||0).toFixed(4)} · opslag: €${(ttfComps.opslag||0).toFixed(4)}` : ''}${ttfAge != null ? ` · ${ttfAge}min geleden` : ''}</div>` : ''}

        <hr>

        <div class="t" style="padding-bottom:4px">⚡🔥 Goedkoopste Warmtebron</div>
        <div class="wbadge">${wbLabel}</div>
        <div class="bronnen">${bronRows}</div>
        ${elecPrijs != null ? `<div class="footer">Huidige stroomprijs: €${elecPrijs.toFixed(4)}/kWh</div>` : ''}

        <div class="fib-toggle" id="fib-toggle">
          <span class="fib-toggle-lbl">⏱ m³ per uur</span>
          <span class="fib-toggle-chevron">${this._showFib ? '▲' : '▼'}</span>
        </div>
        ${this._showFib ? fibHtml : ''}
      </div>`;

    // Toggle fibonacci sectie
    const fibToggle = this.shadowRoot.getElementById('fib-toggle');
    if (fibToggle) {
      fibToggle.addEventListener('click', () => {
        this._showFib = !this._showFib;
        this._prev = '';
        this._render();
      });
    }

    // Klik-events voor drill-down
    this.shadowRoot.querySelectorAll('.prow.clickable').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.dataset.id;
        this._drill = this._drill === id ? null : id;
        this._prev = '';
        this._render();
      });
    });
  }

  getCardSize() { return 7; }
  static getConfigElement(){return document.createElement('cloudems-gas-card-editor');}
  static getStubConfig() { return {}; }
}




class CloudemsGasCardEditor extends HTMLElement{
  constructor(){super();this.attachShadow({mode:'open'});this._cfg={};}
  setConfig(c){this._cfg=c||{};this._render();}
  _render(){
    var self=this;var c=this._cfg;var sh=this.shadowRoot;sh.innerHTML='';
    var style=document.createElement('style');
    style.textContent=':host{display:block;padding:12px}';
    sh.appendChild(style);
    // Titel veld
    var rowT=document.createElement('div');rowT.style.marginBottom='10px';
    var lblT=document.createElement('label');lblT.textContent='Titel';lblT.style.cssText='display:block;font-size:12px;color:#aaa;margin-bottom:4px';
    var inpT=document.createElement('input');inpT.type='text';inpT.id='title';
    inpT.style.cssText='background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;box-sizing:border-box;width:100%';inpT.value=c.title||'';inpT.placeholder='(automatisch)';
    rowT.appendChild(lblT);rowT.appendChild(inpT);sh.appendChild(rowT);
    inpT.addEventListener('change',function(){
      var nc=Object.assign({},c);
      if(inpT.value)nc.title=inpT.value;else delete nc.title;
      self.dispatchEvent(new CustomEvent('config-changed',{detail:{config:nc},bubbles:true,composed:true}));
    });
    
  }
}
if(!customElements.get('cloudems-gas-card-editor'))customElements.define('cloudems-gas-card-editor',CloudemsGasCardEditor);

if (!customElements.get('cloudems-gas-card')) {
}
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-gas-card')) {
  window.customCards.push({ type: 'cloudems-gas-card', name: 'CloudEMS Gas Card', description: 'Gas verbruik met drill-down per periode' });
}

if (!customElements.get('cloudems-gas-card-editor')) {
  class _cloudems_gas_card_editor extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});}
    setConfig(c){this._cfg=c;this._render();}
    _fire(key,val){this._cfg={...this._cfg,[key]:val};this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));}
    _render(){
      this.shadowRoot.innerHTML=`<style>.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:0.5px solid rgba(255,255,255,0.08)}label{font-size:12px;color:rgba(255,255,255,0.6)}input{background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.15);border-radius:6px;color:#fff;padding:4px 8px;font-size:12px;width:180px}</style>
      <div style="padding:8px"><div class="row"><label>Geen opties</label></div></div>`;
    }
  }
}
