/* CloudEMS Card Editors v5.5.465 — gedeeld editors-bestand */

var BASE_EDITOR_STYLE = `
  :host{display:block;padding:12px}
  label{display:block;font-size:12px;color:var(--secondary-text-color,#aaa);margin-bottom:4px}
  .row{margin-bottom:12px}
  .hint{font-size:11px;color:var(--secondary-text-color,#aaa);margin-top:3px;opacity:.75}
  input[type=text],input[type=number],select,textarea{
    width:100%;background:var(--card-background-color,#1c1c1c);
    border:1px solid var(--divider-color,rgba(255,255,255,.15));
    border-radius:6px;color:var(--primary-text-color,#fff);
    padding:5px 8px;font-size:13px;box-sizing:border-box}
  input[type=checkbox]{margin-right:6px}
  .cb-row{display:flex;align-items:center;margin-bottom:10px}
  .section-title{font-size:11px;font-weight:700;color:var(--primary-text-color,#fff);
    letter-spacing:.05em;text-transform:uppercase;margin:14px 0 8px;
    border-top:1px solid rgba(255,255,255,.08);padding-top:10px}
`;


class CloudemsBaseEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._cfg={};}
  setConfig(c){this._cfg=c||{};this._render();}
  _fire(nc){this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:nc},bubbles:true,composed:true}));}
  _tf(id,label,key,placeholder,hint){
    var c=this._cfg;var self=this;
    var d=document.createElement('div');d.className='row';
    var l=document.createElement('label');l.textContent=label;
    var i=document.createElement('input');i.type='text';i.id=id;
    i.value=c[key]||'';if(placeholder)i.placeholder=placeholder;
    i.addEventListener('change',function(){var nc=Object.assign({},c);if(i.value)nc[key]=i.value;else delete nc[key];self._fire(nc);});
    d.appendChild(l);d.appendChild(i);
    if(hint){var h=document.createElement('div');h.className='hint';h.textContent=hint;d.appendChild(h);}
    return d;
  }
  _nf(id,label,key,def,min,max){
    var c=this._cfg;var self=this;
    var d=document.createElement('div');d.className='row';
    var l=document.createElement('label');l.textContent=label;
    var i=document.createElement('input');i.type='number';i.id=id;
    i.value=c[key]!=null?c[key]:def;if(min!=null)i.min=min;if(max!=null)i.max=max;
    i.style.width='100px';
    i.addEventListener('change',function(){var nc=Object.assign({},c);nc[key]=parseFloat(i.value)||def;self._fire(nc);});
    d.appendChild(l);d.appendChild(i);return d;
  }
  _bf(id,label,key,def){
    var c=this._cfg;var self=this;
    var d=document.createElement('div');d.className='cb-row';
    var i=document.createElement('input');i.type='checkbox';i.id=id;
    i.checked=c[key]!=null?c[key]:def;
    var l=document.createElement('label');l.textContent=label;l.style.marginBottom='0';
    i.addEventListener('change',function(){var nc=Object.assign({},c);nc[key]=i.checked;self._fire(nc);});
    d.appendChild(i);d.appendChild(l);return d;
  }
  _sf(id,label,key,opts,def){
    var c=this._cfg;var self=this;
    var d=document.createElement('div');d.className='row';
    var l=document.createElement('label');l.textContent=label;
    var s=document.createElement('select');s.id=id;
    opts.forEach(function(o){var opt=document.createElement('option');opt.value=o.v||o;opt.textContent=o.l||o;if((c[key]||def)===(o.v||o))opt.selected=true;s.appendChild(opt);});
    s.addEventListener('change',function(){var nc=Object.assign({},c);nc[key]=s.value;self._fire(nc);});
    d.appendChild(l);d.appendChild(s);return d;
  }
  _title(){return this._tf('title','Titel','title','(automatisch)');}
  _sec(text){var d=document.createElement('div');d.className='section-title';d.textContent=text;return d;}
  _noconfig(){var d=document.createElement('div');d.style.cssText='padding:8px;font-size:12px;color:var(--secondary-text-color,#aaa)';d.textContent='Geen configuratie nodig — alles automatisch via CloudEMS.';return d;}
  _baseRender(fields){
    var sh=this.shadowRoot;sh.innerHTML='';
    var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    fields.forEach(function(f){if(f)sh.appendChild(f);});
  }
}

class CloudemsFlowCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    var note=document.createElement('div');
    note.className='hint';
    note.textContent='Entiteiten worden automatisch geladen vanuit CloudEMS sensoren.';
    sh.appendChild(note);
  }
}
if(!customElements.get('cloudems-flow-card-editor'))customElements.define('cloudems-flow-card-editor',CloudemsFlowCardEditor);

class CloudemsAircoCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-airco-card-editor'))customElements.define('cloudems-airco-card-editor',CloudemsAircoCardEditor);

class CloudemsAlertsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-alerts-card-editor'))customElements.define('cloudems-alerts-card-editor',CloudemsAlertsCardEditor);

class CloudemsApplianceCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-appliance-card-editor'))customElements.define('cloudems-appliance-card-editor',CloudemsApplianceCardEditor);

class CloudemsAtmosphericCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-atmospheric-card-editor'))customElements.define('cloudems-atmospheric-card-editor',CloudemsAtmosphericCardEditor);

class CloudemsBatterijArbitrageCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-batterij-arbitrage-card-editor'))customElements.define('cloudems-batterij-arbitrage-card-editor',CloudemsBatterijArbitrageCardEditor);

class CloudemsBatteryOverviewCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-battery-overview-card-editor'))customElements.define('cloudems-battery-overview-card-editor',CloudemsBatteryOverviewCardEditor);

class CloudemsBatteryPlanCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-battery-plan-card-editor'))customElements.define('cloudems-battery-plan-card-editor',CloudemsBatteryPlanCardEditor);

class CloudemsBeheerCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-beheer-card-editor'))customElements.define('cloudems-beheer-card-editor',CloudemsBeheerCardEditor);

class CloudemsBlackoutCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-blackout-card-editor'))customElements.define('cloudems-blackout-card-editor',CloudemsBlackoutCardEditor);

class CloudemsCircadianCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-circadian-card-editor'))customElements.define('cloudems-circadian-card-editor',CloudemsCircadianCardEditor);

class CloudemsDagrapportCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-dagrapport-card-editor'))customElements.define('cloudems-dagrapport-card-editor',CloudemsDagrapportCardEditor);

class CloudemsDecisionsLearnerCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-decisions-learner-card-editor'))customElements.define('cloudems-decisions-learner-card-editor',CloudemsDecisionsLearnerCardEditor);

class CloudemsDemandCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-demand-card-editor'))customElements.define('cloudems-demand-card-editor',CloudemsDemandCardEditor);

class CloudemsEbikeCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-ebike-card-editor'))customElements.define('cloudems-ebike-card-editor',CloudemsEbikeCardEditor);

class CloudemsEgaugeCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-egauge-card-editor'))customElements.define('cloudems-egauge-card-editor',CloudemsEgaugeCardEditor);

class CloudemsEvLaadplanCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-ev-laadplan-card-editor'))customElements.define('cloudems-ev-laadplan-card-editor',CloudemsEvLaadplanCardEditor);

class CloudemsFaseBalansCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-fase-balans-card-editor'))customElements.define('cloudems-fase-balans-card-editor',CloudemsFaseBalansCardEditor);

class CloudemsFaseHistoriekCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-fase-historiek-card-editor'))customElements.define('cloudems-fase-historiek-card-editor',CloudemsFaseHistoriekCardEditor);

class CloudemsFcrCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-fcr-card-editor'))customElements.define('cloudems-fcr-card-editor',CloudemsFcrCardEditor);

class CloudemsFutureShadowCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-future-shadow-card-editor'))customElements.define('cloudems-future-shadow-card-editor',CloudemsFutureShadowCardEditor);

class CloudemsKamerHeatmapCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-kamer-heatmap-card-editor'))customElements.define('cloudems-kamer-heatmap-card-editor',CloudemsKamerHeatmapCardEditor);

class CloudemsKlimaatCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-klimaat-card-editor'))customElements.define('cloudems-klimaat-card-editor',CloudemsKlimaatCardEditor);

class CloudemsKostenCalculatorCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-kosten-calculator-card-editor'))customElements.define('cloudems-kosten-calculator-card-editor',CloudemsKostenCalculatorCardEditor);

class CloudemsLampAutoCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-lamp-auto-card-editor'))customElements.define('cloudems-lamp-auto-card-editor',CloudemsLampAutoCardEditor);

class CloudemsLearningCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-learning-card-editor'))customElements.define('cloudems-learning-card-editor',CloudemsLearningCardEditor);

class CloudemsLifecycleCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-lifecycle-card-editor'))customElements.define('cloudems-lifecycle-card-editor',CloudemsLifecycleCardEditor);

class CloudemsLoadPlanCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-load-plan-card-editor'))customElements.define('cloudems-load-plan-card-editor',CloudemsLoadPlanCardEditor);

class CloudemsNeighbourhoodCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-neighbourhood-card-editor'))customElements.define('cloudems-neighbourhood-card-editor',CloudemsNeighbourhoodCardEditor);

class CloudemsOptimizerCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-optimizer-card-editor'))customElements.define('cloudems-optimizer-card-editor',CloudemsOptimizerCardEditor);

class CloudemsP1CardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-p1-card-editor'))customElements.define('cloudems-p1-card-editor',CloudemsP1CardEditor);

class CloudemsPhaseOutletCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-phase-outlet-card-editor'))customElements.define('cloudems-phase-outlet-card-editor',CloudemsPhaseOutletCardEditor);

class CloudemsPiekdagenCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-piekdagen-card-editor'))customElements.define('cloudems-piekdagen-card-editor',CloudemsPiekdagenCardEditor);

class CloudemsPoolCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-pool-card-editor'))customElements.define('cloudems-pool-card-editor',CloudemsPoolCardEditor);

class CloudemsPrijsverloopCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-prijsverloop-card-editor'))customElements.define('cloudems-prijsverloop-card-editor',CloudemsPrijsverloopCardEditor);

class CloudemsStandbyCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-standby-card-editor'))customElements.define('cloudems-standby-card-editor',CloudemsStandbyCardEditor);

class CloudemsV2hCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-v2h-card-editor'))customElements.define('cloudems-v2h-card-editor',CloudemsV2hCardEditor);

class CloudemsVacationCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-vacation-card-editor'))customElements.define('cloudems-vacation-card-editor',CloudemsVacationCardEditor);

class CloudemsVersionCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-version-card-editor'))customElements.define('cloudems-version-card-editor',CloudemsVersionCardEditor);

class CloudemsVveCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-vve-card-editor'))customElements.define('cloudems-vve-card-editor',CloudemsVveCardEditor);

class CloudemsWarmtebronCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-warmtebron-card-editor'))customElements.define('cloudems-warmtebron-card-editor',CloudemsWarmtebronCardEditor);

class CloudemsWeekCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-week-card-editor'))customElements.define('cloudems-week-card-editor',CloudemsWeekCardEditor);

class CloudemsZelfconsumptieCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-zelfconsumptie-card-editor'))customElements.define('cloudems-zelfconsumptie-card-editor',CloudemsZelfconsumptieCardEditor);

class CloudemsAiTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-ai-tabs-card-editor'))customElements.define('cloudems-ai-tabs-card-editor',CloudemsAiTabsCardEditor);

class CloudemsApparaatTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-apparaat-tabs-card-editor'))customElements.define('cloudems-apparaat-tabs-card-editor',CloudemsApparaatTabsCardEditor);

class CloudemsBeslissingenTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-beslissingen-tabs-card-editor'))customElements.define('cloudems-beslissingen-tabs-card-editor',CloudemsBeslissingenTabsCardEditor);

class CloudemsDiagnoseTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-diagnose-tabs-card-editor'))customElements.define('cloudems-diagnose-tabs-card-editor',CloudemsDiagnoseTabsCardEditor);

class CloudemsFaseTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-fase-tabs-card-editor'))customElements.define('cloudems-fase-tabs-card-editor',CloudemsFaseTabsCardEditor);

class CloudemsKlimaatTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-klimaat-tabs-card-editor'))customElements.define('cloudems-klimaat-tabs-card-editor',CloudemsKlimaatTabsCardEditor);

class CloudemsLampenTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-lampen-tabs-card-editor'))customElements.define('cloudems-lampen-tabs-card-editor',CloudemsLampenTabsCardEditor);

class CloudemsNilmVisualTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-nilm-visual-tabs-card-editor'))customElements.define('cloudems-nilm-visual-tabs-card-editor',CloudemsNilmVisualTabsCardEditor);

class CloudemsSolarTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-solar-tabs-card-editor'))customElements.define('cloudems-solar-tabs-card-editor',CloudemsSolarTabsCardEditor);

class CloudemsToekomstTabsCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-toekomst-tabs-card-editor'))customElements.define('cloudems-toekomst-tabs-card-editor',CloudemsToekomstTabsCardEditor);

class CloudemsAiCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._noconfig());
  }
}
if(!customElements.get('cloudems-ai-card-editor'))customElements.define('cloudems-ai-card-editor',CloudemsAiCardEditor);

class CloudemsLampCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._sf('mode','Modus','mode',[{v:'auto',l:'Automatisch'},{v:'handmatig',l:'Handmatig'},{v:'schema',l:'Schema'}],'auto'));
    sh.appendChild(this._bf('enabled','Ingeschakeld','enabled',true));
  }
}
if(!customElements.get('cloudems-lamp-card-editor'))customElements.define('cloudems-lamp-card-editor',CloudemsLampCardEditor);

class CloudemsFuseMonitorCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._nf('fuse_a','Zekering (A)','fuse_a',25,1,200));
    sh.appendChild(this._nf('warn_pct','Waarschuwing (%)','warn_pct',80,50,99));
    sh.appendChild(this._nf('alert_pct','Alarm (%)','alert_pct',95,50,100));
  }
}
if(!customElements.get('cloudems-fuse-monitor-card-editor'))customElements.define('cloudems-fuse-monitor-card-editor',CloudemsFuseMonitorCardEditor);

class CloudemsEnergiePotentieelCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._bf('show_bat','Toon batterij','show_bat',true));
    sh.appendChild(this._bf('show_pv','Toon zonne-energie','show_pv',true));
    sh.appendChild(this._nf('rows','Rijen','rows',3,1,10));
  }
}
if(!customElements.get('cloudems-energie-potentieel-card-editor'))customElements.define('cloudems-energie-potentieel-card-editor',CloudemsEnergiePotentieelCardEditor);

class CloudemsClimateEpexCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._tf('sensor','Klimaat sensor','sensor','sensor.cloudems_climate_epex_status'));
    sh.appendChild(this._tf('price_sensor','Prijs sensor','price_sensor','sensor.cloudems_huidige_energieprijs'));
  }
}
if(!customElements.get('cloudems-climate-epex-card-editor'))customElements.define('cloudems-climate-epex-card-editor',CloudemsClimateEpexCardEditor);

class CloudemsMiniPriceCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._bf('show_incl','Toon incl. belasting','show_incl',true));
  }
}
if(!customElements.get('cloudems-mini-price-card-editor'))customElements.define('cloudems-mini-price-card-editor',CloudemsMiniPriceCardEditor);

class CloudemsNilmVisualCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._nf('columns','Kolommen','columns',3,1,6));
    sh.appendChild(this._bf('show_off','Toon uitgeschakelde apparaten','show_off',false));
  }
}
if(!customElements.get('cloudems-nilm-visual-card-editor'))customElements.define('cloudems-nilm-visual-card-editor',CloudemsNilmVisualCardEditor);

class CloudemsStandbyRankingCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._nf('max_items','Max. apparaten','max_items',5,1,20));
  }
}
if(!customElements.get('cloudems-standby-ranking-card-editor'))customElements.define('cloudems-standby-ranking-card-editor',CloudemsStandbyRankingCardEditor);

class CloudemsSolarCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-solar-card-editor'))customElements.define('cloudems-solar-card-editor',CloudemsSolarCardEditor);

class CloudemsGasCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-gas-card-editor'))customElements.define('cloudems-gas-card-editor',CloudemsGasCardEditor);

class CloudemsSankeyCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
  }
}
if(!customElements.get('cloudems-sankey-card-editor'))customElements.define('cloudems-sankey-card-editor',CloudemsSankeyCardEditor);

class CloudemsApparaatTijdlijnCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._nf('max_devices','Max. apparaten','max_devices',10,1,50));
  }
}
if(!customElements.get('cloudems-apparaat-tijdlijn-card-editor'))customElements.define('cloudems-apparaat-tijdlijn-card-editor',CloudemsApparaatTijdlijnCardEditor);

class CloudemsEnergyVisualCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._nf('max_devices','Max. apparaten','max_devices',6,1,20));
  }
}
if(!customElements.get('cloudems-energy-visual-card-editor'))customElements.define('cloudems-energy-visual-card-editor',CloudemsEnergyVisualCardEditor);

class CloudemsAlertsTickerCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._nf('interval','Wissel-interval (ms)','interval',4000,500,30000));
  }
}
if(!customElements.get('cloudems-alerts-ticker-card-editor'))customElements.define('cloudems-alerts-ticker-card-editor',CloudemsAlertsTickerCardEditor);

class CloudemsArchCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._title());
    sh.appendChild(this._bf('border','Rand tonen','border',true));
  }
}
if(!customElements.get('cloudems-arch-card-editor'))customElements.define('cloudems-arch-card-editor',CloudemsArchCardEditor);

class CloudemsIsoCardEditor extends CloudemsBaseEditor {
  _render(){var sh=this.shadowRoot;sh.innerHTML='';var s=document.createElement('style');s.textContent=BASE_EDITOR_STYLE;sh.appendChild(s);
    sh.appendChild(this._sf('house_type','Woningtype','house_type',[{v:'vrijstaand',l:'Vrijstaand'},{v:'rijtjeshuis',l:'Rijtjeshuis'},{v:'appartement',l:'Appartement'},{v:'hoekwoning',l:'Hoekwoning'},{v:'twee_onder_een_kap',l:'Twee-onder-één-kap'}],'rijtjeshuis'));
    sh.appendChild(this._tf('custom_image_url','Eigen afbeelding URL','custom_image_url',''));
  }
}
if(!customElements.get('cloudems-iso-card-editor'))customElements.define('cloudems-iso-card-editor',CloudemsIsoCardEditor);


// cloudems-energy-view-card — volledige editor met entiteiten
class CloudemsEnergyViewCardEditor extends CloudemsBaseEditor {
  _render() {
    var sh = this.shadowRoot; sh.innerHTML = '';
    var s = document.createElement('style'); s.textContent = BASE_EDITOR_STYLE; sh.appendChild(s);
    var c = this._cfg;
    var e = c.entities || {};
    var self = this;

    sh.appendChild(this._title());
    sh.appendChild(this._nf('max_ampere','Max. zekering (A)','max_ampere',25,1,200));
    sh.appendChild(this._sec('Net'));
    sh.appendChild(this._entf('grid_entity','Entiteit','entities.grid.entity',e.grid&&e.grid.entity,'sensor.cloudems_grid_net_power'));
    sh.appendChild(this._entf('grid_name','Naam','entities.grid.name',e.grid&&e.grid.name,'Net'));
    sh.appendChild(this._sec('Zonne-energie'));
    sh.appendChild(this._entf('solar_entity','Entiteit','entities.solar_system.entity',e.solar_system&&e.solar_system.entity,'sensor.cloudems_solar_system'));
    sh.appendChild(this._sec('Batterij'));
    sh.appendChild(this._entf('bat_entity','Entiteit','entities.battery.entity',e.battery&&e.battery.entity,''));
    sh.appendChild(this._entf('bat_soc','SoC sensor','entities.battery.state_of_charge',e.battery&&e.battery.state_of_charge,''));
    sh.appendChild(this._entf('bat_name','Naam','entities.battery.name',e.battery&&e.battery.name,'Batterij'));
    sh.appendChild(this._sec('Thuis'));
    sh.appendChild(this._entf('home_entity','Entiteit','entities.home.entity',e.home&&e.home.entity,'sensor.cloudems_home_rest'));
    sh.appendChild(this._entf('home_name','Naam','entities.home.name',e.home&&e.home.name,'Thuis'));
  }
  _entf(id, label, path, val, placeholder) {
    var self = this;
    var d = document.createElement('div'); d.className = 'row';
    var l = document.createElement('label'); l.textContent = label;
    var i = document.createElement('input'); i.type = 'text'; i.id = id;
    i.value = val || ''; if (placeholder) i.placeholder = placeholder;
    i.addEventListener('change', function() {
      var nc = JSON.parse(JSON.stringify(self._cfg));
      var parts = path.split('.');
      var obj = nc;
      for (var pi = 0; pi < parts.length - 1; pi++) {
        if (!obj[parts[pi]]) obj[parts[pi]] = {};
        obj = obj[parts[pi]];
      }
      if (i.value) obj[parts[parts.length-1]] = i.value;
      else delete obj[parts[parts.length-1]];
      self._fire(nc);
    });
    d.appendChild(l); d.appendChild(i); return d;
  }
}
if(!customElements.get('cloudems-energy-view-card-editor'))
  customElements.define('cloudems-energy-view-card-editor', CloudemsEnergyViewCardEditor);
