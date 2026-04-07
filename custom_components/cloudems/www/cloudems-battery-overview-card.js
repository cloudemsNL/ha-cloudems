// CloudEMS Battery Overview Card — week + uur-voor-uur plan
const BOV_VERSION = "5.5.318";

class CloudEMSBatteryOverviewCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._tab = 'vandaag';
    this._initialized = false;
  }

  setConfig(c) { this._config = c || {}; }

  set hass(h) {
    this._hass = h;
    if (!this._initialized) {
      this._buildSkeleton();
      this._initialized = true;
    }
    this._updateContent();
  }

  _buildSkeleton() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block }
        ha-card { background:#0d1117; border:1px solid rgba(255,255,255,.06); border-radius:16px; overflow:hidden; font-family:'Inter',ui-sans-serif,sans-serif; color:#cbd5e1; padding:16px 20px }
        .tab-bar { display:flex; gap:2px; margin-bottom:16px; background:rgba(255,255,255,.04); border-radius:8px; padding:3px }
        .tab { flex:1; text-align:center; padding:6px 4px; font-size:11px; font-weight:600; border-radius:6px; cursor:pointer; color:#475569; transition:all .15s }
        .tab.active { background:rgba(255,255,255,.08); color:#f1f5f9 }
        .scroll-area { max-height:380px; overflow-y:auto; overflow-x:hidden }
        .scroll-area::-webkit-scrollbar { width:4px }
        .scroll-area::-webkit-scrollbar-thumb { background:#1e293b; border-radius:2px }
        .scroll-row:hover { background:rgba(255,255,255,.02) }
      </style>
      <ha-card>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          <div style="font-size:18px">⚡</div>
          <div id="card-title" style="font-size:13px;font-weight:700;color:#f1f5f9">Batterijplan</div>
        </div>
        <div class="tab-bar" id="tab-bar">
          <div class="tab" data-tab="week">Week</div>
          <div class="tab" data-tab="gisteren">Gisteren</div>
          <div class="tab active" data-tab="vandaag">Vandaag</div>
          <div class="tab" data-tab="morgen">Morgen</div>
        </div>
        <div id="content"></div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll('.tab').forEach(el => {
      el.addEventListener('click', () => {
        this._tab = el.dataset.tab;
        this.shadowRoot.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === this._tab));
        this.shadowRoot.getElementById('card-title').textContent =
          this._tab === 'week' ? 'Week overzicht batterij' : 'Uur-voor-uur Batterijplan';
        this._updateContent();
      });
    });
  }

  _updateContent() {
    const h = this._hass;
    if (!h) return;
    const content = this.shadowRoot.getElementById('content');
    if (!content) return;

    // Bewaar scroll positie
    const scrollEl = content.querySelector('.scroll-area');
    const scrollTop = scrollEl ? scrollEl.scrollTop : 0;

    const sav  = h.states['sensor.cloudems_battery_savings'];
    const sch  = h.states['sensor.cloudems_battery_schedule']
              || h.states['sensor.cloudems_batterij_epex_schema']
              || Object.values(h.states).find(s =>
                   s?.attributes?.schedule !== undefined &&
                   s?.attributes?.soc_pct !== undefined &&
                   s?.entity_id?.includes('battery_schedule'));

    const savA = sav?.attributes || {};
    const schA = sch?.attributes || {};

    const history   = savA.daily_history || savA.history || [];
    const yesterday = schA.schedule_yesterday || [];
    const today     = schA.schedule || schA.schedule_today || schA.slots || [];
    const tomorrow  = schA.schedule_tomorrow || [];
    const soc_now   = parseFloat(schA.soc_pct ?? h.states['sensor.cloudems_battery_so_c']?.state ?? 0);
    const payback  = h?.states['sensor.cloudems_payback']?.attributes || {};
    const accuracy = (schA.plan_accuracy) || {};
    const alpha    = h?.states['sensor.cloudems_alpha']?.attributes || {};
    const tab = this._tab;

    let html = '';
    if (tab === 'maand') {
      html = this._maandHtml(schA, accuracy);
    } else if (tab === 'terugverdien') {
      html = this._paybackHtml(payback);
    } else if (tab === 'alpha') {
      html = this._alphaHtml(alpha);
    } else if (tab === 'week') {
      html = this._weekHtml(history);
    } else {
      let slots = tab === 'gisteren' ? yesterday : tab === 'morgen' ? tomorrow : today;
      if (tab === 'vandaag' && new Date().getHours() < 6 && yesterday.length > 0) {
        const hoursNeeded = 6 - new Date().getHours();
        const prevSlots = yesterday.slice(-hoursNeeded).map(s => ({...s, _from_yesterday: true}));
        slots = [...prevSlots, ...slots];
      }
      html = this._planHtml(slots, tab, schA, soc_now);
    }

    content.innerHTML = html;

    // Herstel scroll positie of scroll naar huidig uur
    const newScroll = content.querySelector('.scroll-area');
    if (newScroll && scrollTop > 0) {
      newScroll.scrollTop = scrollTop;
    }
  }

  _planHtml(slots, tab, schA, soc_now) {
    if (!slots.length) {
      const hr = schA.human_reason || '';
      return `<div style="padding:20px;font-size:12px;color:#475569;text-align:center">
        ${hr ? `<div style="color:#94a3b8;margin-bottom:10px;font-style:italic;font-size:11px">${hr}</div>` : ''}
        <div style="font-size:10px">⏳ Plan wordt opgebouwd na de volgende cyclus.</div>
      </div>`;
    }

    const nowH = new Date().getHours();

    // Kleuren per tariefgroep achtergrond
    const tgBg = tg => tg === 'high' ? 'rgba(249,115,22,.06)' : tg === 'low' ? 'rgba(16,185,129,.05)' : 'transparent';

    const rows = slots.map(s => {
      const hr    = parseInt(s.hour ?? s.from_hour ?? 0);
      const past  = tab !== 'morgen' && (hr < nowH || !!s._from_yesterday);
      const now   = tab === 'vandaag' && hr === nowH;
      const act   = s.action || 'idle';
      const chgW  = s.charge_w ?? null;
      const disW  = s.discharge_w ?? null;
      const pvW   = s.pv_w ?? 0;
      const hwW   = s.house_w ?? 0;
      const price = s.price_all_in ?? s.price_allin ?? s.price ?? null;
      const tg    = s.tariff_group || '';
      const soc0  = s.soc_start ?? null;
      const soc1  = s.soc_end ?? s.soc_pct ?? null;
      // Verleden uren: SOC niet tonen (plan-SOC klopt niet voor verleden)
      const socStr = past ? '—' : (soc0 != null && soc1 != null
        ? `${Math.round(soc0)}→${Math.round(soc1)}%`
        : soc1 != null ? `${Math.round(soc1)}%` : '');

      const priceCol = tg === 'high' ? '#f97316' : tg === 'low' ? '#10b981' : '#64748b';
      const bg = now ? 'rgba(96,165,250,.08)' : tgBg(tg);
      const bl = now ? '2px solid #60a5fa' : '2px solid transparent';

      // Laad/ontlaad kolommen
      const actual = s.actual || null;
      // Verleden: werkelijk gemeten vermogen
      const actChg   = actual && (actual.bat_w || 0) > 0 ? Math.round(actual.bat_w) : null;
      const actDis   = actual && (actual.bat_w || 0) < 0 ? Math.round(Math.abs(actual.bat_w)) : null;
      const actPvV   = actual ? Math.round(actual.pv_w || 0) : null;
      const actHwV   = actual ? Math.round(actual.house_w || 0) : null;
      const chgDisp  = past && actual ? actChg : (chgW > 0 ? Math.round(chgW) : null);
      const disDisp  = past && actual ? actDis : (disW > 0 ? Math.round(disW) : null);
      const pvDisp   = past && actual ? (actPvV > 0 ? actPvV : null) : (s.pv_w > 0 ? Math.round(s.pv_w) : null);
      const hwDisp   = past && actual ? actHwV : (s.house_w > 0 ? Math.round(s.house_w) : null);
      const isActual = past && !!actual;

      const chgStr = chgDisp ? `<span style="color:${isActual?'#34d399':'#10b981'}">${chgDisp}W</span>` : '<span style="color:#374151">—</span>';
      const disStr = disDisp ? `<span style="color:${isActual?'#fb923c':'#f97316'}">${disDisp}W</span>` : '<span style="color:#374151">—</span>';
      // Fix 3: toon afwijking gepland vs werkelijk voor verleden uren
      const planChg = chgW > 0 ? Math.round(chgW) : 0;
      const planDis = disW > 0 ? Math.round(disW) : 0;
      const actChgV = actual && (actual.bat_w || 0) > 0 ? Math.round(actual.bat_w) : 0;
      const actDisV = actual && (actual.bat_w || 0) < 0 ? Math.round(Math.abs(actual.bat_w)) : 0;
      const diffChg = isActual && planChg ? actChgV - planChg : null;
      const diffDis = isActual && planDis ? actDisV - planDis : null;
      const diffStr = (diffChg !== null || diffDis !== null) ?
        `<span style="font-size:8px;color:${Math.abs(diffChg||diffDis)>200?'#f87171':'#4b5563'};margin-left:2px">${
          diffChg !== null ? (diffChg>0?'+':'')+diffChg+'W' :
          diffDis !== null ? (diffDis>0?'+':'')+diffDis+'W' : ''
        }</span>` : '';
      const pvStr  = pvW > 50 ? `<span style="color:#f59e0b">${Math.round(pvW)}W</span>` : '<span style="color:#374151">—</span>';
      const hwStr  = hwW > 0 ? `${Math.round(hwW)}W` : '—';

      return `<div style="display:grid;grid-template-columns:34px 36px 36px 42px 44px 48px 1fr;gap:3px;align-items:center;padding:3px 6px;border-radius:4px;background:${bg};border-left:${bl};opacity:${past?.45:1}">
        <div style="font-size:10px;font-weight:600;color:${now?'#60a5fa':past?'#374151':'#64748b'};font-family:monospace">${String(hr).padStart(2,'0')}:00</div>
        <div style="font-size:10px;text-align:right;font-family:monospace">${chgStr}${isActual&&diffChg!==null?diffStr:''}</div>
        <div style="font-size:10px;text-align:right;font-family:monospace">${disStr}${isActual&&diffDis!==null?diffStr:''}</div>
        <div style="font-size:10px;text-align:right;font-family:monospace">${pvStr}</div>
        <div style="font-size:10px;color:#94a3b8;text-align:right;font-family:monospace">${hwStr}</div>
        <div style="font-size:10px;color:${priceCol};text-align:right;font-family:monospace;font-weight:600">${price != null ? price.toFixed(1)+'ct' : '—'}</div>
        <div style="font-size:9px;color:#475569;text-align:right;font-family:monospace">${socStr}</div>
      </div>`;
    }).join('');

    // Header
    const header = `<div style="display:grid;grid-template-columns:34px 36px 36px 42px 44px 48px 1fr;gap:3px;padding:2px 6px 6px;border-bottom:1px solid #1e293b;margin-bottom:2px">
      <div style="font-size:9px;color:#374151;font-weight:700">UUR</div>
      <div style="font-size:9px;color:#10b981;font-weight:700;text-align:right">LADEN</div>
      <div style="font-size:9px;color:#f97316;font-weight:700;text-align:right">LEVER.</div>
      <div style="font-size:9px;color:#f59e0b;font-weight:700;text-align:right">PV</div>
      <div style="font-size:9px;color:#94a3b8;font-weight:700;text-align:right">HUIS</div>
      <div style="font-size:9px;color:#64748b;font-weight:700;text-align:right">PRIJS</div>
      <div style="font-size:9px;color:#475569;font-weight:700;text-align:right">SOC</div>
    </div>`;

    // ── Grafiek ──────────────────────────────────────────────────────────────
    const chartHtml = (() => {
      const W = 320, H = 110, PAD = 28, RPAD = 8, TOP = 8, BOT = 20;
      const plotW = W - PAD - RPAD;
      const plotH = H - TOP - BOT;
      const n = slots.length || 24;
      const barW = Math.max(2, Math.floor(plotW / n) - 1);

      // Maxima voor schaling
      const maxPow = Math.max(
        ...slots.map(s => Math.max(s.charge_w||0, s.discharge_w||0, s.pv_w||0, s.house_w||0)), 500);

      const yPow  = v => TOP + plotH - (v / maxPow * plotH);
      const xSlot = i => PAD + i * (plotW / n) + (plotW / n - barW) / 2;

      // Bars + lijnen
      let bars = '', pvPts = '', hwPts = '', socPts = '';
      slots.forEach((s, i) => {
        const x   = xSlot(i);
        const chg = s.charge_w    || 0;
        const dis = s.discharge_w || 0;
        const pv  = s.pv_w        || 0;
        const hw  = s.house_w     || 0;
        const soc = s.soc_end     ?? s.soc_pct ?? null;
        const mid = TOP + plotH;

        // Groen omhoog (laden), oranje omlaag (levering)
        if (chg > 0) {
          const h = Math.max(1, (chg / maxPow) * plotH);
          bars += `<rect x="${x}" y="${mid - h}" width="${barW}" height="${h}" fill="#10b981" opacity="0.75"/>`;
        }
        if (dis > 0) {
          const h = Math.max(1, (dis / maxPow) * (plotH * 0.6));
          bars += `<rect x="${x}" y="${mid}" width="${barW}" height="${h}" fill="#f97316" opacity="0.65"/>`;
        }

        // PV lijn (geel)
        const pvY = yPow(pv);
        pvPts += `${i === 0 ? 'M' : 'L'}${x + barW/2},${pvY} `;

        // Huis lijn (grijs)
        const hwY = yPow(hw);
        hwPts += `${i === 0 ? 'M' : 'L'}${x + barW/2},${hwY} `;

        // SOC lijn (blauw, rechter as 0-100%)
        if (soc !== null) {
          const socY = TOP + plotH - (soc / 100 * plotH);
          socPts += `${i === 0 ? 'M' : 'L'}${x + barW/2},${socY} `;
        }
      });

      // Uur-labels (elke 4 uur)
      let xLabels = '';
      for (let i = 0; i < n; i += 4) {
        const x = xSlot(i) + barW/2;
        xLabels += `<text x="${x}" y="${H - 4}" text-anchor="middle" font-size="8" fill="#374151">${String(i).padStart(2,'0')}</text>`;
      }

      // Y-as labels
      const yLabels = [0, 0.5, 1].map(f => {
        const v = Math.round(maxPow * f / 100) * 100;
        const y = yPow(v);
        return `<text x="${PAD - 3}" y="${y + 3}" text-anchor="end" font-size="8" fill="#374151">${v>=1000?(v/1000).toFixed(1)+'k':v}</text>
                <line x1="${PAD}" y1="${y}" x2="${W - RPAD}" y2="${y}" stroke="#1e293b" stroke-width="0.5"/>`;
      }).join('');

      // SOC Y-as rechts
      const socLabels = [0, 50, 100].map(v => {
        const y = TOP + plotH - (v / 100 * plotH);
        return `<text x="${W - RPAD + 2}" y="${y + 3}" text-anchor="start" font-size="8" fill="#60a5fa">${v}%</text>`;
      }).join('');

      // Nul-lijn
      const zeroY = TOP + plotH;

      return `<div style="overflow:hidden;margin:12px 0 4px"><svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;display:block">
        <!-- Grid -->
        ${yLabels}
        <!-- Nul-lijn -->
        <line x1="${PAD}" y1="${zeroY}" x2="${W-RPAD}" y2="${zeroY}" stroke="#2d3748" stroke-width="1"/>
        <!-- Huidig uur markering -->
        ${tab === 'vandaag' ? (() => {
          const nowH2 = new Date().getHours();
          const nowMin = new Date().getMinutes();
          const nowFrac = nowH2 + nowMin / 60;
          const nowX = PAD + (nowFrac / n) * plotW + barW / 2;
          return `<line x1="${nowX}" y1="${TOP}" x2="${nowX}" y2="${zeroY}" stroke="#ef9f27" stroke-width="1.5" stroke-dasharray="3,2" opacity="0.8"/>
                  <text x="${nowX}" y="${TOP - 2}" text-anchor="middle" font-size="7" fill="#ef9f27">nu</text>`;
        })() : ''}
        <!-- Bars -->
        ${bars}
        <!-- PV lijn -->
        <path d="${pvPts}" fill="none" stroke="#f59e0b" stroke-width="1.5" opacity="0.9"/>
        <!-- Huis lijn -->
        <path d="${hwPts}" fill="none" stroke="#64748b" stroke-width="1" stroke-dasharray="3,2" opacity="0.7"/>
        <!-- SOC lijn -->
        <path d="${socPts}" fill="none" stroke="#60a5fa" stroke-width="1.5" opacity="0.85"/>
        <!-- SOC Y-as -->
        ${socLabels}
        <!-- X-labels -->
        ${xLabels}
        <!-- Legenda -->
        <rect x="${PAD}" y="1" width="8" height="5" fill="#10b981" rx="1"/>
        <text x="${PAD+10}" y="7" font-size="8" fill="#10b981">Laden</text>
        <rect x="${PAD+38}" y="1" width="8" height="5" fill="#f97316" rx="1"/>
        <text x="${PAD+48}" y="7" font-size="8" fill="#f97316">Levering</text>
        <line x1="${PAD+90}" y1="3" x2="${PAD+98}" y2="3" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="${PAD+100}" y="7" font-size="8" fill="#f59e0b">PV</text>
        <line x1="${PAD+115}" y1="3" x2="${PAD+123}" y2="3" stroke="#64748b" stroke-width="1" stroke-dasharray="2,1"/>
        <text x="${PAD+125}" y="7" font-size="8" fill="#64748b">Huis</text>
        <line x1="${PAD+148}" y1="3" x2="${PAD+156}" y2="3" stroke="#60a5fa" stroke-width="1.5"/>
        <text x="${PAD+158}" y="7" font-size="8" fill="#60a5fa">SOC%</text>
      </svg></div>`;
    })();

    return `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span style="font-size:10px;color:#374151">PV · Huis · Prijs → Verwacht plan</span>
        <span style="font-size:13px;font-weight:700;color:#10b981;font-family:monospace">${soc_now.toFixed(0)}%<span style="font-size:10px;color:#475569;font-weight:400"> SOC</span></span>
      </div>
      ${chartHtml}
      ${header}
      <div class="scroll-area">${rows}</div>`;
  }

  _maandHtml(schA, accuracy) {
    // Monthly history from pv_daily_history monthly aggregation
    const months = (schA.monthly_history || []).slice(-12).reverse();
    // Plan accuracy
    const accScore  = accuracy.score;
    const accHours  = accuracy.hours_measured || 0;
    const accDev    = accuracy.avg_deviation_w || 0;
    const accNote   = accuracy.note || '';

    const monthRows = months.length ? months.map(m => {
      const eff = m.efficiency_pct;
      return `<div style="display:grid;grid-template-columns:70px 1fr 1fr 1fr;gap:4px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:11px;align-items:center">
        <div style="color:#94a3b8;font-weight:600">${m.month}</div>
        <div><span style="color:#10b981">⚡${(m.charge_kwh||0).toFixed(1)}</span><span style="color:#4b5563"> kWh</span></div>
        <div><span style="color:#f97316">↓${(m.discharge_kwh||0).toFixed(1)}</span><span style="color:#4b5563"> kWh</span></div>
        <div style="text-align:right">
          ${eff!=null?`<span style="color:${eff>=90?'#4ade80':eff>=80?'#f59e0b':'#f87171'}">${eff.toFixed(0)}%</span>`:''}
        </div>
      </div>`;
    }).join('') : '<div style="color:#374151;padding:16px;text-align:center">Monthly data builds at the end of each month</div>';

    return `<div style="padding:16px">
      ${accScore!=null?`
      <div style="background:rgba(96,165,250,.1);border-radius:8px;padding:10px;margin-bottom:12px">
        <div style="font-size:10px;color:#6b7280;margin-bottom:2px">PLAN ACCURACY</div>
        <div style="font-size:22px;font-weight:700;color:${accScore>=80?'#4ade80':accScore>=60?'#f59e0b':'#f87171'}">${accScore.toFixed(0)}%</div>
        <div style="font-size:10px;color:#6b7280">avg deviation ${accDev}W over ${accHours} hours</div>
      </div>`:''}
      <div style="font-size:10px;font-weight:600;color:#6b7280;margin-bottom:8px">MONTHLY HISTORY</div>
      <div style="display:grid;grid-template-columns:70px 1fr 1fr 1fr;gap:4px;padding:4px 0;font-size:9px;color:#6b7280">
        <div>Month</div><div>Charged</div><div>Discharged</div><div style="text-align:right">Efficiency</div>
      </div>
      ${monthRows}
    </div>`;
  }

  _paybackHtml(p) {
    if (!p || !p.purchase_price_eur) return '<div style="padding:24px;color:#6b7280;text-align:center">Terugverdientijd wordt berekend...<br><small>Start zodra dagelijks revenue bekend is</small></div>';
    const pct    = parseFloat(p.payback_pct||0);
    const months = p.months_remaining;
    const date   = p.payback_date ? new Date(p.payback_date).toLocaleDateString('nl-NL',{month:'long',year:'numeric'}) : null;
    const daily  = parseFloat(p.daily_rate_eur||0);
    const monthly= parseFloat(p.monthly_rate_eur||0);
    const earned = parseFloat(p.total_earned_eur||0);
    const price  = parseFloat(p.purchase_price_eur||0);
    const remaining = parseFloat(p.remaining_eur||0);
    const isEst        = p.purchase_source === 'estimated';
    const dataSource   = p.data_source || 'cloudems_estimated';
    const isLive       = dataSource === 'zonneplan_live';
    const sourceNote   = p.data_source_note || '';
    const installDate  = p.install_date ? new Date(p.install_date).toLocaleDateString('nl-NL',{day:'numeric',month:'long',year:'numeric'}) : null;
    const daysInstall  = p.days_since_install;
    const rateBasis    = p.rate_basis || '';
    return `
      <div style="padding:16px">
        <div style="font-size:11px;color:#6b7280;margin-bottom:12px">${p.purchase_note||''}</div>
        <div style="font-size:10px;margin-bottom:8px;padding:4px 8px;border-radius:4px;background:${isLive?'rgba(74,222,128,.1)':'rgba(245,158,11,.1)'};color:${isLive?'#4ade80':'#f59e0b'};display:inline-block">
          ${isLive ? '✅ Live Zonneplan data' : '⚠️ Estimated — install ha-zonneplan-one for accuracy'}
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <div>
            <div style="font-size:28px;font-weight:700;color:#f59e0b">${months!=null?Math.round(months)+' mnd':'—'}</div>
            <div style="font-size:11px;color:#6b7280">nog te gaan${date?' ('+date+')':''}</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:18px;font-weight:600;color:#4ade80">${pct!=null?pct.toFixed(1):'—'}%</div>
            <div style="font-size:10px;color:#6b7280">terugverdiend</div>
          </div>
        </div>
        <div style="background:#1e293b;border-radius:8px;height:8px;margin-bottom:12px">
          <div style="background:linear-gradient(90deg,#4ade80,#f59e0b);width:${Math.min(100,pct)}%;height:100%;border-radius:8px;transition:width .3s"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px">
          <div><span style="color:#6b7280">Aanschaf</span><br><b style="color:#fff">€${price.toFixed(0)}${isEst?' (schatting)':''}</b></div>
          <div><span style="color:#6b7280">Verdiend</span><br><b style="color:#4ade80">€${earned!=null?earned.toFixed(2):'—'}</b></div>
          <div><span style="color:#6b7280">Resterend</span><br><b style="color:#f59e0b">€${remaining!=null?remaining.toFixed(2):'—'}</b></div>
          <div><span style="color:#6b7280">Tempo</span><br><b style="color:#60a5fa">€${monthly!=null?monthly.toFixed(2):'—'}/mnd</b>${isLive?'<span style="font-size:8px;color:#4ade80"> live</span>':''}</div>
        </div>
        ${installDate ? `<div style="font-size:10px;color:#6b7280;margin-top:8px">In gebruik sinds: <b style="color:#e2e8f0">${installDate}</b>${daysInstall?` (${daysInstall} dagen)`:''}</div>` : ''}
        ${rateBasis ? `<div style="font-size:9px;color:#374151;margin-top:2px">Tempo berekend op basis van: ${rateBasis}</div>` : ''}
        <div style="display:none">
        </div>
      </div>`;
  }

  _alphaHtml(a) {
    if (!a || !a.tracking) return '<div style="padding:24px;color:#6b7280;text-align:center">CloudEMS Alpha meting wordt opgebouwd...<br><small>Vergelijkt CloudEMS met Zonneplan baseline</small></div>';
    const todayAlpha = parseFloat(a.alpha_eur_today||0);
    const avgAlpha   = parseFloat(a.avg_alpha_eur_day||0);
    const monthAlpha = parseFloat(a.avg_alpha_eur_month||0);
    const cumAlpha   = parseFloat(a.cumulative_alpha_eur||0);
    const hist       = a.history_30d || [];
    const maxAlpha   = Math.max(...hist.map(d=>Math.abs(d.alpha||0)), 0.01);
    const barsHtml   = hist.slice(-14).map(d => {
      const h = Math.round(Math.abs(d.alpha||0) / maxAlpha * 60);
      const c = d.alpha>=0?'#4ade80':'#f87171';
      const dt= new Date(d.date).toLocaleDateString('nl-NL',{day:'numeric',month:'short'});
      return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;gap:2px">
        <div style="font-size:7px;color:#374151">${(d.alpha||0)>0?'+':''}${((d.alpha||0)*100).toFixed(0)}ct</div>
        <div style="width:100%;background:${c};border-radius:2px;height:${h}px;min-height:2px"></div>
        <div style="font-size:7px;color:#374151;writing-mode:vertical-lr;transform:rotate(180deg)">${dt}</div>
      </div>`;
    }).join('');
    return `
      <div style="padding:16px">
        <div style="font-size:11px;color:#6b7280;margin-bottom:12px">Extra verdienst CloudEMS t.o.v. standaard Zonneplan strategie</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px">
          <div style="background:rgba(74,222,128,.1);border-radius:8px;padding:10px;text-align:center">
            <div style="font-size:20px;font-weight:700;color:${todayAlpha>=0?'#4ade80':'#f87171'}">${todayAlpha>=0?'+':''}€${todayAlpha.toFixed(3)}</div>
            <div style="font-size:10px;color:#6b7280">vandaag</div>
          </div>
          <div style="background:rgba(96,165,250,.1);border-radius:8px;padding:10px;text-align:center">
            <div style="font-size:20px;font-weight:700;color:#60a5fa">€${monthAlpha!=null?monthAlpha.toFixed(2):'—'}</div>
            <div style="font-size:10px;color:#6b7280">gem/maand</div>
          </div>
          <div style="background:rgba(245,158,11,.1);border-radius:8px;padding:10px;text-align:center">
            <div style="font-size:20px;font-weight:700;color:#f59e0b">+€${cumAlpha!=null?cumAlpha.toFixed(2):'—'}</div>
            <div style="font-size:10px;color:#6b7280">cumulatief</div>
          </div>
          <div style="background:rgba(74,222,128,.07);border-radius:8px;padding:10px;text-align:center">
            <div style="font-size:20px;font-weight:700;color:#4ade80">€${avgAlpha!=null?avgAlpha.toFixed(3):'—'}</div>
            <div style="font-size:10px;color:#6b7280">gem/dag</div>
          </div>
        </div>
        ${hist.length ? `<div style="display:flex;gap:2px;align-items:flex-end;height:80px">${barsHtml}</div>` : ''}
      </div>`;
  }

  _weekHtml(history) {
    const days = ['Ma','Di','Wo','Do','Vr','Za','Zo'];
    const todayIdx = (new Date().getDay() + 6) % 7;
    const bars = Array.from({length:7}, (_,i) => {
      const d = history[history.length - 7 + i] || null;
      return { label: days[(todayIdx - 6 + i + 7) % 7], isToday: i === 6,
               charge_kwh: d?.charge_kwh ?? 0, discharge_kwh: d?.discharge_kwh ?? 0,
               saving_eur: d?.saving_eur ?? d?.savings_eur ?? 0 };
    });
    const maxKwh = Math.max(...bars.map(b => Math.max(b.charge_kwh, b.discharge_kwh)), 0.1);
    const totalSaving = bars.reduce((s,b) => s + (b.saving_eur||0), 0);
    const totalCharge = bars.reduce((s,b) => s + (b.charge_kwh||0), 0);
    const totalDisch  = bars.reduce((s,b) => s + (b.discharge_kwh||0), 0);

    const barsHtml = bars.map(b => {
      const chH = Math.round((b.charge_kwh / maxKwh) * 80);
      const diH = Math.round((b.discharge_kwh / maxKwh) * 80);
      return `<div style="display:flex;flex-direction:column;align-items:center;gap:3px;flex:1">
        <div style="font-size:9px;color:#475569;font-family:monospace">${b.saving_eur>0?'+€'+b.saving_eur.toFixed(2):''}</div>
        <div style="height:80px;display:flex;align-items:flex-end;gap:2px">
          <div style="width:10px;height:${chH}px;background:#10b981;border-radius:2px 2px 0 0;min-height:${b.charge_kwh>0?2:0}px"></div>
          <div style="width:10px;height:${diH}px;background:#f97316;border-radius:2px 2px 0 0;min-height:${b.discharge_kwh>0?2:0}px"></div>
        </div>
        <div style="font-size:10px;font-weight:${b.isToday?700:400};color:${b.isToday?'#f59e0b':'#475569'}">${b.label}</div>
        ${b.isToday?'<div style="width:4px;height:4px;border-radius:50%;background:#f59e0b"></div>':''}
      </div>`;
    }).join('');

    return `
      <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
        <div style="background:rgba(16,185,129,.1);border-radius:8px;padding:8px 12px">
          <div style="font-size:13px;font-weight:700;color:#10b981;font-family:monospace">+€${totalSaving.toFixed(2)}</div>
          <div style="font-size:9px;color:#475569;margin-top:2px">Bespaard week</div>
        </div>
        <div style="background:rgba(16,185,129,.07);border-radius:8px;padding:8px 12px">
          <div style="font-size:13px;font-weight:700;color:#10b981;font-family:monospace">⚡ ${totalCharge.toFixed(1)} kWh</div>
          <div style="font-size:9px;color:#475569;margin-top:2px">Geladen</div>
        </div>
        <div style="background:rgba(249,115,22,.07);border-radius:8px;padding:8px 12px">
          <div style="font-size:13px;font-weight:700;color:#f97316;font-family:monospace">↓ ${totalDisch.toFixed(1)} kWh</div>
          <div style="font-size:9px;color:#475569;margin-top:2px">Ontladen</div>
        </div>
      </div>
      ${history.length ? `<div style="display:flex;gap:4px;align-items:flex-end;padding:0 4px">${barsHtml}</div>` :
        '<div style="text-align:center;color:#374151;padding:32px;font-size:12px">Weekdata wordt opgebouwd.</div>'}`;
  }

  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-battery-overview-card'))
  customElements.define('cloudems-battery-overview-card', CloudEMSBatteryOverviewCard);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-battery-overview-card'))
  window.customCards.push({ type: 'cloudems-battery-overview-card', name: 'CloudEMS Battery Overview' });
console.info(`%c CLOUDEMS-BATTERY-OVERVIEW %c v${BOV_VERSION} `, 'background:#10b981;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px', 'background:#0d1117;color:#10b981;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
