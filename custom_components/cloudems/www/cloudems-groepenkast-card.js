// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
const GK_VERSION = "1.0.0";

// ── Kleuren ───────────────────────────────────────────────────────────────────
const C = {
  bg:         "#0d1117",
  surface:    "#161b22",
  surface2:   "#21262d",
  border:     "#30363d",
  text:       "#e6edf3",
  textMuted:  "#7d8590",
  textDim:    "#484f58",
  L1:         "#f97316",
  L2:         "#3b82f6",
  L3:         "#22c55e",
  "3F":       "#a855f7",
  main:       "#eab308",
  rcd:        "#06b6d4",
  rcbo:       "#8b5cf6",
  mcb:        "#94a3b8",
  mcb_3f:     "#a855f7",
  submeter:   "#f59e0b",
  leverOn:    "#22c55e",
  leverOff:   "#ef4444",
  leverLearn: "#f59e0b",
  red:        "#ef4444",
  orange:     "#f97316",
  yellow:     "#eab308",
  green:      "#22c55e",
  loadOk:     "#22c55e",
  loadWarn:   "#eab308",
  loadAlert:  "#ef4444",
  accent:     "#58a6ff",
};

// ── Iconen ────────────────────────────────────────────────────────────────────
const ICONS = {
  main:     "⚡",
  rcd:      "🛡",
  rcbo:     "🔒",
  mcb:      "▶",
  mcb_3f:   "⚡",
  submeter: "📊",
  L1:       "①",
  L2:       "②",
  L3:       "③",
  "3F":     "∿",
  red:      "🔴",
  orange:   "🟠",
  yellow:   "🟡",
  green:    "🟢",
};

class CloudEMSGroepenkastCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass      = null;
    this._config    = {};
    this._view      = "tree";        // "tree" | "box"
    this._expanded  = new Set();     // uitgeklapte nodes in boom
    this._learning  = null;          // actieve wizard state
    this._selected  = null;          // geselecteerde node voor detail
    this._editNode  = null;          // node in edit-mode
    this._showNEN   = false;
    this._data      = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const sensor = hass.states["sensor.cloudems_groepenkast"];
    this._data = sensor?.attributes || null;
    this._render();
  }

  // ── Renderen ──────────────────────────────────────────────────────────────

  _render() {
    if (!this.shadowRoot) return;
    const nodes   = this._data?.nodes || [];
    const session = this._data?.active_session || null;
    const nen     = this._data?.nen1010_findings || [];

    if (session && !this._learning) {
      this._learning = { ...session, phase: session.state };
    }

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="card">
        ${this._renderHeader(nodes, nen)}
        ${this._learning ? this._renderWizard() : ""}
        ${!this._learning ? this._renderMain(nodes, nen) : ""}
        ${this._selected && !this._learning ? this._renderDetail(nodes) : ""}
      </div>`;
    this._bindEvents();
  }

  _renderHeader(nodes, nen) {
    const redCount    = nen.filter(f => f.severity === "red").length;
    const orangeCount = nen.filter(f => f.severity === "orange").length;
    const learned     = nodes.filter(n => n.confidence > 0).length;

    return `
    <div class="header">
      <div class="header-left">
        <span class="title">⚡ GROEPENKAST</span>
        <span class="subtitle">${nodes.length} nodes · ${learned} geleerd</span>
      </div>
      <div class="header-right">
        ${redCount ? `<span class="badge badge-red">${ICONS.red} ${redCount}</span>` : ""}
        ${orangeCount ? `<span class="badge badge-orange">${ICONS.orange} ${orangeCount}</span>` : ""}
        <button class="btn-icon ${this._view === "tree" ? "active" : ""}" data-action="view-tree" title="Boomweergave">⋮⋮</button>
        <button class="btn-icon ${this._view === "box"  ? "active" : ""}" data-action="view-box"  title="Kastweergave">▦</button>
        <button class="btn-icon ${this._showNEN ? "active" : ""}" data-action="toggle-nen" title="NEN1010 bevindingen">📋</button>
        <button class="btn-icon" data-action="add-node" title="Groep toevoegen">＋</button>
      </div>
    </div>
    ${this._showNEN && nen.length ? this._renderNEN(nen) : ""}`;
  }

  _renderNEN(findings) {
    const rows = findings.map(f => `
      <div class="nen-row nen-${f.severity}">
        <span class="nen-icon">${ICONS[f.severity]}</span>
        <div>
          <div class="nen-msg">${f.message}</div>
          <div class="nen-detail">${f.detail}</div>
        </div>
        <span class="nen-code">${f.code}</span>
      </div>`).join("");
    return `<div class="nen-panel">${rows}</div>`;
  }

  _renderMain(nodes, nen) {
    if (this._view === "tree") return this._renderTree(nodes);
    return this._renderBox(nodes);
  }

  // ── BOOM-WEERGAVE ─────────────────────────────────────────────────────────

  _renderTree(nodes) {
    const roots = this._getRoots(nodes);
    const html  = roots.map(r => this._renderTreeNode(r, nodes, 0)).join("");
    return `<div class="tree">${html}</div>`;
  }

  _renderTreeNode(node, nodes, depth) {
    const children    = this._getChildren(node.id, nodes);
    const hasChildren = children.length > 0;
    const expanded    = this._expanded.has(node.id);
    const phaseColor  = C[node.phase] || C.mcb;
    const typeColor   = C[node.node_type] || C.mcb;
    const selected    = this._selected === node.id;
    const loadPct     = node.load_pct || 0;
    const loadColor   = loadPct > 0.95 ? C.loadAlert : loadPct > 0.80 ? C.loadWarn : C.loadOk;
    const isRCD       = ["rcd","rcbo","main"].includes(node.node_type);
    const isSubmeter  = node.node_type === "submeter";

    const leverColor  = this._learning?.node_id === node.id
      ? C.leverLearn
      : (node.current_power_w > 0 ? C.leverOn : C.leverOff);

    const indentPx = depth * 20;

    let powerInfo = "";
    if (node.current_power_w > 0) {
      powerInfo = `<span class="power">${this._fmt(node.current_power_w)}W</span>`;
    }
    if (node.rated_power_w > 0 && !isRCD) {
      const pct = Math.round(loadPct * 100);
      powerInfo += `<div class="load-bar-wrap">
        <div class="load-bar" style="width:${Math.min(pct,100)}%;background:${loadColor}"></div>
      </div>`;
    }

    let extraInfo = "";
    if (node.phase && !isRCD) {
      extraInfo += `<span class="phase-badge" style="background:${phaseColor}20;color:${phaseColor};border-color:${phaseColor}40">${node.phase}</span>`;
    }
    if (node.linked_rooms?.length) {
      extraInfo += node.linked_rooms.map(r =>
        `<span class="room-badge">${r}</span>`
      ).join("");
    }
    if (node.confidence > 0) {
      const conf = Math.round(node.confidence * 100);
      extraInfo += `<span class="conf-badge" style="opacity:${0.5 + node.confidence * 0.5}">${conf}%</span>`;
    }
    if (isSubmeter && node.voltage_drop_pct != null) {
      const drop = (node.voltage_drop_pct * 100).toFixed(1);
      const dropColor = node.voltage_drop_pct >= 0.05 ? C.red :
                        node.voltage_drop_pct >= 0.03 ? C.orange : C.yellow;
      extraInfo += `<span class="drop-badge" style="color:${dropColor}">ΔV ${drop}%</span>`;
    }

    const chevron = hasChildren
      ? `<span class="chevron ${expanded ? "open" : ""}" data-toggle="${node.id}">▶</span>`
      : `<span class="chevron-spacer"></span>`;

    const lever = !isRCD && !isSubmeter
      ? `<div class="lever" style="background:${leverColor}" data-node="${node.id}"></div>`
      : `<div class="lever-placeholder"></div>`;

    const learnBtn = !isRCD
      ? `<button class="learn-btn" data-learn="${node.id}" title="Leer apparaten">🎓</button>`
      : `<button class="learn-btn" data-learn="${node.id}" title="Leer groepen">🎓</button>`;

    const nodeHtml = `
    <div class="tree-node ${selected ? "selected" : ""}" style="padding-left:${indentPx}px"
         data-select="${node.id}">
      ${chevron}
      ${lever}
      <span class="node-type-icon" style="color:${typeColor}">${ICONS[node.node_type] || "▶"}</span>
      <div class="node-info">
        <div class="node-name">${node.name}
          ${node.ampere ? `<span class="ampere">${node.ampere}A</span>` : ""}
        </div>
        <div class="node-badges">${extraInfo}</div>
        ${powerInfo ? `<div class="node-power">${powerInfo}</div>` : ""}
      </div>
      <div class="node-actions">
        ${learnBtn}
        <button class="edit-btn" data-edit="${node.id}" title="Bewerken">✏️</button>
      </div>
    </div>`;

    let childrenHtml = "";
    if (hasChildren && expanded) {
      childrenHtml = `<div class="tree-children">
        ${children.map(c => this._renderTreeNode(c, nodes, depth + 1)).join("")}
      </div>`;
    } else if (hasChildren && !expanded) {
      // Toon samenvatting van children
      const totalW = children.reduce((s, c) => s + (c.current_power_w || 0), 0);
      childrenHtml = `<div class="tree-children-summary" data-toggle="${node.id}">
        <span style="padding-left:${indentPx + 44}px;color:${C.textMuted};font-size:11px">
          ${children.length} groepen${totalW > 0 ? ` · ${this._fmt(totalW)}W` : ""} — klik om uit te klappen
        </span>
      </div>`;
    }

    return nodeHtml + childrenHtml;
  }

  // ── KAST-WEERGAVE ─────────────────────────────────────────────────────────

  _renderBox(nodes) {
    const leaves = nodes.filter(n =>
      !["rcd", "rcbo", "main"].includes(n.node_type)
    );

    // Groepeer per aardlek voor kleurcodering
    const rcdColors = {};
    const rcdNodes  = nodes.filter(n => ["rcd","rcbo"].includes(n.node_type));
    const palette   = ["#1d4ed8","#065f46","#7c2d12","#4c1d95","#831843","#164e63"];
    rcdNodes.forEach((r, i) => {
      rcdColors[r.id] = palette[i % palette.length];
    });

    const boxItems = leaves.map(node => {
      // Zoek parent RCD kleur
      const parentColor = rcdColors[node.parent_id] || "#21262d";
      const loadPct     = node.load_pct || 0;
      const loadColor   = loadPct > 0.95 ? C.loadAlert : loadPct > 0.80 ? C.loadWarn : C.leverOn;
      const isOn        = node.current_power_w > 0;
      const phaseColor  = C[node.phase] || C.textDim;

      return `
      <div class="box-breaker" style="border-top:3px solid ${parentColor}"
           data-select="${node.id}">
        <div class="box-lever" style="background:${isOn ? loadColor : C.leverOff}"></div>
        <div class="box-label">${node.name}</div>
        <div class="box-ampere" style="color:${phaseColor}">${node.ampere || "?"}A</div>
        ${node.current_power_w > 0
          ? `<div class="box-power">${this._fmt(node.current_power_w)}W</div>`
          : ""}
        ${node.confidence > 0
          ? `<div class="box-conf">${Math.round(node.confidence * 100)}%</div>`
          : ""}
        <button class="box-learn" data-learn="${node.id}">🎓</button>
      </div>`;
    }).join("");

    // Legenda aardlekken
    const legend = rcdNodes.map(r => `
      <div class="box-legend-item">
        <span class="box-legend-dot" style="background:${rcdColors[r.id]}"></span>
        <span>${r.name}</span>
      </div>`).join("");

    return `
    <div class="box-panel">
      <div class="box-enclosure">
        <div class="box-rail top-rail">
          <div class="box-main">⚡ HOOFD</div>
        </div>
        <div class="box-grid">${boxItems}</div>
        <div class="box-rail bottom-rail">
          <div class="box-legend">${legend}</div>
        </div>
      </div>
    </div>`;
  }

  // ── WIZARD ────────────────────────────────────────────────────────────────

  _renderWizard() {
    if (!this._learning) return "";
    const s   = this._learning;
    const isAuto = s.auto_switch || false;

    let content = "";

    if (s.state === "waiting_off") {
      content = `
        <div class="wizard-step active">
          <div class="wizard-step-num">1</div>
          <div class="wizard-step-content">
            <div class="wizard-instruction">${s.instruction || `Zet '${s.node_name}' UIT`}</div>
            ${isAuto
              ? `<button class="btn-primary" data-action="auto-switch-off">🔌 Automatisch uitschakelen</button>`
              : ""}
            <button class="btn-primary" data-action="confirm-off">✅ Groep is uit — start meting</button>
            <button class="btn-cancel" data-action="cancel-learn">Annuleren</button>
          </div>
        </div>
        <div class="wizard-step">
          <div class="wizard-step-num">2</div>
          <div class="wizard-step-content pending">Meting uitvoeren...</div>
        </div>
        <div class="wizard-step">
          <div class="wizard-step-num">3</div>
          <div class="wizard-step-content pending">Resultaat</div>
        </div>`;

    } else if (s.state === "measuring") {
      content = `
        <div class="wizard-step done">
          <div class="wizard-step-num">✓</div>
          <div class="wizard-step-content">Groep is uitgeschakeld</div>
        </div>
        <div class="wizard-step active">
          <div class="wizard-step-num">2</div>
          <div class="wizard-step-content">
            <div class="wizard-instruction">Wacht ${s.wait_seconds || 8} seconden voor stabiele meting...</div>
            <div class="progress-bar"><div class="progress-fill" id="gk-progress"></div></div>
            <button class="btn-primary" data-action="finish-learn">📊 Meting afronden</button>
            <button class="btn-cancel"  data-action="cancel-learn">Annuleren</button>
          </div>
        </div>`;

    } else if (s.state === "confirming") {
      const conf = Math.round((s.confidence || 0) * 100);
      const devs = s.candidates || [];
      content = `
        <div class="wizard-step done"><div class="wizard-step-num">✓</div><div>Eerste meting klaar</div></div>
        <div class="wizard-step active">
          <div class="wizard-step-num">!</div>
          <div class="wizard-step-content">
            <div class="wizard-instruction">${s.instruction}</div>
            <div class="confidence-bar">
              <div class="confidence-fill" style="width:${conf}%;background:${C.orange}"></div>
              <span class="confidence-label">${conf}% — herhaling aanbevolen</span>
            </div>
            ${devs.length ? `<div class="found-devices">Gevonden: ${devs.map(d => d.device_id).join(", ")}</div>` : ""}
            <button class="btn-primary" data-action="start-learn-again">🔄 Tweede meting</button>
            <button class="btn-secondary" data-action="accept-result">✅ Accepteer resultaat (${conf}%)</button>
            <button class="btn-cancel" data-action="cancel-learn">Annuleren</button>
          </div>
        </div>`;

    } else if (s.state === "done") {
      const conf = Math.round((s.confidence || 0) * 100);
      const devs = s.devices || [];
      const color = conf >= 65 ? C.green : conf >= 40 ? C.orange : C.red;
      content = `
        <div class="wizard-step done"><div class="wizard-step-num">✓</div><div>Meting afgerond</div></div>
        <div class="wizard-step done"><div class="wizard-step-num">✓</div><div>Data verwerkt</div></div>
        <div class="wizard-step active">
          <div class="wizard-step-num">3</div>
          <div class="wizard-step-content">
            <div class="wizard-result">
              <div class="result-confidence" style="color:${color}">${conf}% zekerheid</div>
              ${s.detected_phase ? `<div class="result-phase">Fase: <strong style="color:${C[s.detected_phase]}">${s.detected_phase}</strong> (${Math.round((s.phase_confidence||0)*100)}%)</div>` : ""}
              ${devs.length ? `<div class="result-devices">${devs.length} apparaten gekoppeld</div>` : `<div class="result-devices">Geen apparaten gedetecteerd</div>`}
              ${s.rooms?.length ? `<div class="result-rooms">Ruimtes: ${s.rooms.join(", ")}</div>` : ""}
              ${s.phase_boosts?.length ? `<div class="result-boosts">+${s.phase_boosts.length} fase-bevestigingen doorgegeven</div>` : ""}
            </div>
            <button class="btn-primary" data-action="close-wizard">✅ Sluiten</button>
          </div>
        </div>`;
    }

    const meas = s.measurement_num ? ` (meting ${s.measurement_num}/2)` : "";
    return `
    <div class="wizard">
      <div class="wizard-header">
        🎓 Leren: <strong>${s.node_name || s.node_id}</strong>${meas}
      </div>
      <div class="wizard-steps">${content}</div>
    </div>`;
  }

  // ── DETAIL PANEL ──────────────────────────────────────────────────────────

  _renderDetail(nodes) {
    const node = nodes.find(n => n.id === this._selected);
    if (!node) return "";

    const phaseColor = C[node.phase] || C.textMuted;
    const isSubmeter = node.node_type === "submeter";

    let cable = "";
    if (isSubmeter) {
      cable = `
        <div class="detail-section">
          <div class="detail-label">Kabeldata</div>
          ${node.r_cable_ohm != null ? `<div class="detail-row"><span>R-kabel</span><span>${node.r_cable_ohm.toFixed(3)} Ω (${node.r_samples} metingen)</span></div>` : ""}
          ${node.estimated_mm2 != null ? `<div class="detail-row"><span>Geschatte dikte</span><span>${node.estimated_mm2} mm²</span></div>` : ""}
          ${node.voltage_drop_pct != null ? `<div class="detail-row"><span>Spanningsval</span><span style="color:${node.voltage_drop_pct >= 0.05 ? C.red : node.voltage_drop_pct >= 0.03 ? C.orange : C.yellow}">${(node.voltage_drop_pct*100).toFixed(1)}%</span></div>` : ""}
          ${node.current_voltage_v ? `<div class="detail-row"><span>Huidige spanning</span><span>${node.current_voltage_v.toFixed(1)} V</span></div>` : ""}
        </div>`;
    }

    return `
    <div class="detail-panel">
      <div class="detail-header">
        <span style="color:${C[node.node_type]}">${ICONS[node.node_type]}</span>
        <strong>${node.name}</strong>
        ${node.phase ? `<span style="color:${phaseColor}">${node.phase}</span>` : ""}
        <button class="detail-close" data-action="close-detail">✕</button>
      </div>
      <div class="detail-body">
        ${node.ampere ? `<div class="detail-row"><span>Beveiliging</span><span>${node.ampere}A · ${node.node_type.toUpperCase()}</span></div>` : ""}
        ${node.phase_confidence > 0 ? `<div class="detail-row"><span>Fase-zekerheid</span><span>${Math.round(node.phase_confidence*100)}%</span></div>` : ""}
        ${node.current_power_w > 0 ? `<div class="detail-row"><span>Huidig</span><span>${this._fmt(node.current_power_w)} W (${Math.round(node.load_pct*100)}%)</span></div>` : ""}
        ${node.linked_power_w > 0 ? `<div class="detail-row"><span>Geleerd verbruik</span><span>${node.linked_power_w} W</span></div>` : ""}
        ${node.confidence > 0 ? `<div class="detail-row"><span>Leer-zekerheid</span><span>${Math.round(node.confidence*100)}%</span></div>` : ""}
        ${node.measurement_count > 0 ? `<div class="detail-row"><span>Metingen</span><span>${node.measurement_count}×</span></div>` : ""}
        ${cable}
        ${node.linked_devices?.length ? `
          <div class="detail-section">
            <div class="detail-label">Apparaten (${node.linked_devices.length})</div>
            ${node.linked_devices.map(d => `
              <div class="detail-device">
                <span>${d}</span>
                <button class="unlink-btn" data-unlink="${node.id}" data-device="${d}" title="Ontkoppelen">✕</button>
              </div>`).join("")}
          </div>` : ""}
        ${node.linked_rooms?.length ? `
          <div class="detail-section">
            <div class="detail-label">Ruimtes</div>
            ${node.linked_rooms.map(r => `
              <div class="detail-device">
                <span>🏠 ${r}</span>
                <button class="unlink-btn" data-unlink-room="${node.id}" data-room="${r}">✕</button>
              </div>`).join("")}
            <button class="btn-small" data-add-room="${node.id}">+ Ruimte toevoegen</button>
          </div>` : `
          <div class="detail-section">
            <button class="btn-small" data-add-room="${node.id}">+ Ruimte toevoegen</button>
          </div>`}
        <div class="detail-actions">
          <button class="btn-primary" data-learn="${node.id}">🎓 Leer apparaten</button>
          <button class="btn-danger"  data-delete="${node.id}">🗑 Verwijder</button>
        </div>
      </div>
    </div>`;
  }

  // ── EVENT HANDLING ────────────────────────────────────────────────────────

  _bindEvents() {
    const root = this.shadowRoot;

    root.querySelectorAll("[data-action]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        this._handleAction(el.dataset.action);
      });
    });

    root.querySelectorAll("[data-toggle]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        const id = el.dataset.toggle;
        if (this._expanded.has(id)) this._expanded.delete(id);
        else this._expanded.add(id);
        this._render();
      });
    });

    root.querySelectorAll("[data-select]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        const id = el.dataset.select;
        this._selected = this._selected === id ? null : id;
        this._render();
      });
    });

    root.querySelectorAll("[data-learn]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        this._startLearning(el.dataset.learn);
      });
    });

    root.querySelectorAll("[data-edit]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        this._editNode = el.dataset.edit;
        this._render();
      });
    });

    root.querySelectorAll("[data-unlink]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        this._callService("unlink_device", {
          node_id: el.dataset.unlink, device_id: el.dataset.device,
        });
      });
    });

    root.querySelectorAll("[data-unlink-room]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        this._callService("unlink_room", {
          node_id: el.dataset.unlinkRoom, room: el.dataset.room,
        });
      });
    });

    root.querySelectorAll("[data-add-room]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        const room = prompt("Ruimte naam:");
        if (room?.trim()) {
          this._callService("link_room", {
            node_id: el.dataset.addRoom, room: room.trim(), linked: true,
          });
        }
      });
    });

    root.querySelectorAll("[data-delete]").forEach(el => {
      el.addEventListener("click", e => {
        e.stopPropagation();
        if (confirm(`Verwijder groep en alle kinderen?`)) {
          this._callService("remove_node", { node_id: el.dataset.delete });
          this._selected = null;
          this._render();
        }
      });
    });
  }

  _handleAction(action) {
    switch (action) {
      case "view-tree":
        this._view = "tree"; this._render(); break;
      case "view-box":
        this._view = "box"; this._render(); break;
      case "toggle-nen":
        this._showNEN = !this._showNEN; this._render(); break;
      case "add-node":
        this._showAddDialog(); break;
      case "confirm-off":
        this._callService("confirm_circuit_off", {});
        this._learning = { ...this._learning, state: "measuring", wait_seconds: 8 };
        this._render();
        break;
      case "auto-switch-off":
        this._callService("auto_switch_off", { node_id: this._learning?.node_id });
        break;
      case "finish-learn":
        this._callService("finish_circuit_learning", {});
        break;
      case "start-learn-again":
        if (this._learning?.node_id) this._startLearning(this._learning.node_id);
        break;
      case "accept-result":
        this._callService("accept_circuit_result", {});
        this._learning = null;
        this._render();
        break;
      case "cancel-learn":
        this._callService("cancel_circuit_learning", {});
        this._learning = null;
        this._render();
        break;
      case "close-wizard":
        this._learning = null; this._render(); break;
      case "close-detail":
        this._selected = null; this._render(); break;
    }
  }

  _startLearning(nodeId) {
    this._callService("start_circuit_learning", { node_id: nodeId });
    const nodes = this._data?.nodes || [];
    const node  = nodes.find(n => n.id === nodeId);
    this._learning = {
      state:         "waiting_off",
      node_id:       nodeId,
      node_name:     node?.name || nodeId,
      instruction:   `Zet '${node?.name || nodeId}' UIT en klik 'Meting starten'.`,
      auto_switch:   !!node?.switch_entity,
      measurement_num: 1,
    };
    this._render();
  }

  _callService(service, data) {
    if (!this._hass) return;
    this._hass.callService("cloudems", service, data).catch(err => {
      console.error("CloudEMS service fout:", err);
    });
  }

  _showAddDialog() {
    const name = prompt("Naam van de nieuwe groep:");
    if (!name?.trim()) return;
    const type = prompt("Type (main/rcd/rcbo/mcb/mcb_3f/submeter):", "mcb");
    const ampere = parseInt(prompt("Ampère:", "16")) || 16;
    this._callService("add_circuit_node", {
      name: name.trim(), node_type: type || "mcb", ampere,
    });
  }

  // ── Hulpfuncties ──────────────────────────────────────────────────────────

  _getRoots(nodes) {
    const ids = new Set(nodes.map(n => n.id));
    return nodes.filter(n => !n.parent_id || !ids.has(n.parent_id))
                .sort((a, b) => a.position - b.position);
  }

  _getChildren(parentId, nodes) {
    return nodes.filter(n => n.parent_id === parentId)
                .sort((a, b) => a.position - b.position);
  }

  _fmt(w) {
    if (w >= 1000) return (w / 1000).toFixed(1) + "k";
    return Math.round(w).toString();
  }

  // ── CSS ───────────────────────────────────────────────────────────────────

  _css() {
    return `
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :host { display: block; font-family: 'SF Mono', 'Fira Code', monospace; }

    .card {
      background: ${C.bg};
      border: 1px solid ${C.border};
      border-radius: 12px;
      overflow: hidden;
      color: ${C.text};
      font-size: 13px;
    }

    /* ── Header ── */
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid ${C.border};
      background: ${C.surface};
    }
    .title { font-size: 14px; font-weight: 700; letter-spacing: .05em; }
    .subtitle { font-size: 11px; color: ${C.textMuted}; margin-top: 2px; }
    .header-right { display: flex; align-items: center; gap: 6px; }
    .btn-icon {
      background: ${C.surface2}; border: 1px solid ${C.border};
      color: ${C.textMuted}; border-radius: 6px; padding: 4px 8px;
      cursor: pointer; font-size: 13px; transition: all .15s;
    }
    .btn-icon:hover, .btn-icon.active {
      background: ${C.accent}20; border-color: ${C.accent}60; color: ${C.accent};
    }
    .badge {
      padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;
    }
    .badge-red    { background: ${C.red}20;    color: ${C.red};    }
    .badge-orange { background: ${C.orange}20; color: ${C.orange}; }

    /* ── NEN1010 panel ── */
    .nen-panel { padding: 8px; border-bottom: 1px solid ${C.border}; }
    .nen-row {
      display: flex; align-items: flex-start; gap: 8px;
      padding: 6px 8px; border-radius: 6px; margin-bottom: 4px; font-size: 12px;
    }
    .nen-red    { background: ${C.red}15;    border-left: 3px solid ${C.red};    }
    .nen-orange { background: ${C.orange}15; border-left: 3px solid ${C.orange}; }
    .nen-yellow { background: ${C.yellow}15; border-left: 3px solid ${C.yellow}; }
    .nen-msg    { font-weight: 600; }
    .nen-detail { color: ${C.textMuted}; font-size: 11px; margin-top: 2px; }
    .nen-code   { margin-left: auto; color: ${C.textDim}; font-size: 10px; white-space: nowrap; }

    /* ── Boom ── */
    .tree { padding: 8px 0; }
    .tree-node {
      display: flex; align-items: center; gap: 6px;
      padding: 6px 12px; cursor: pointer; transition: background .1s;
      border-radius: 0;
    }
    .tree-node:hover   { background: ${C.surface2}; }
    .tree-node.selected { background: ${C.accent}15; border-left: 2px solid ${C.accent}; }
    .tree-children     { }
    .tree-children-summary { padding: 3px 0; cursor: pointer; }
    .tree-children-summary:hover span { color: ${C.accent}; }

    .chevron {
      color: ${C.textDim}; font-size: 10px; cursor: pointer;
      transition: transform .2s; min-width: 12px; text-align: center;
    }
    .chevron.open { transform: rotate(90deg); }
    .chevron-spacer { min-width: 12px; }

    .lever {
      width: 10px; height: 22px; border-radius: 3px;
      cursor: pointer; transition: background .2s; flex-shrink: 0;
    }
    .lever-placeholder { width: 10px; height: 22px; flex-shrink: 0; }

    .node-type-icon { font-size: 14px; min-width: 18px; text-align: center; }
    .node-info { flex: 1; min-width: 0; }
    .node-name { font-size: 13px; font-weight: 500; display: flex; align-items: center; gap: 6px; }
    .ampere    { font-size: 10px; color: ${C.textMuted}; font-weight: 400; }
    .node-badges { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
    .node-power  { margin-top: 2px; }
    .node-actions { display: flex; gap: 4px; opacity: 0; transition: opacity .15s; }
    .tree-node:hover .node-actions { opacity: 1; }

    .phase-badge, .room-badge, .conf-badge, .drop-badge {
      padding: 1px 6px; border-radius: 10px; font-size: 10px; font-weight: 600;
    }
    .room-badge  { background: ${C.surface2}; color: ${C.textMuted}; border: 1px solid ${C.border}; }
    .conf-badge  { background: ${C.green}15; color: ${C.green}; }
    .phase-badge { border: 1px solid; }

    .power       { font-size: 12px; color: ${C.text}; font-weight: 600; }
    .load-bar-wrap {
      height: 3px; background: ${C.surface2}; border-radius: 2px;
      margin-top: 3px; overflow: hidden; max-width: 80px;
    }
    .load-bar { height: 100%; border-radius: 2px; transition: width .3s; }

    .learn-btn, .edit-btn {
      background: none; border: none; cursor: pointer; font-size: 13px;
      padding: 2px 4px; border-radius: 4px; opacity: .7;
    }
    .learn-btn:hover { background: ${C.yellow}20; }
    .edit-btn:hover  { background: ${C.accent}20; }

    /* ── Kast ── */
    .box-panel { padding: 12px; }
    .box-enclosure {
      background: #0a0f18; border: 2px solid #3a4255;
      border-radius: 8px; padding: 10px; box-shadow: inset 0 2px 8px rgba(0,0,0,.5);
    }
    .box-rail {
      background: linear-gradient(90deg, #2a3040, #3a4255, #2a3040);
      height: 20px; border-radius: 4px; margin-bottom: 8px;
      display: flex; align-items: center; padding: 0 8px;
    }
    .box-main { color: ${C.main}; font-size: 11px; font-weight: 700; }
    .box-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
      gap: 6px;
    }
    .box-breaker {
      background: #1a2030; border: 1px solid #2a3040;
      border-radius: 4px; padding: 6px 4px;
      text-align: center; cursor: pointer; transition: all .15s;
      position: relative;
    }
    .box-breaker:hover { border-color: ${C.accent}60; background: #1f2840; }
    .box-lever {
      width: 18px; height: 28px; border-radius: 3px; margin: 0 auto 4px;
      transition: background .2s;
    }
    .box-label  { font-size: 9px; color: ${C.text}; line-height: 1.2; }
    .box-ampere { font-size: 10px; font-weight: 700; margin-top: 2px; }
    .box-power  { font-size: 9px; color: ${C.yellow}; }
    .box-conf   { font-size: 9px; color: ${C.green}; }
    .box-learn  {
      position: absolute; top: 2px; right: 2px;
      background: none; border: none; cursor: pointer; font-size: 10px; opacity: .5;
    }
    .box-learn:hover { opacity: 1; }
    .box-legend { display: flex; gap: 10px; flex-wrap: wrap; }
    .box-legend-item { display: flex; align-items: center; gap: 4px; font-size: 10px; color: ${C.textMuted}; }
    .box-legend-dot { width: 10px; height: 10px; border-radius: 2px; }
    .bottom-rail { margin-top: 8px; margin-bottom: 0; height: auto; padding: 6px 8px; }

    /* ── Wizard ── */
    .wizard {
      margin: 0; border-bottom: 1px solid ${C.border};
      background: ${C.surface};
    }
    .wizard-header {
      padding: 10px 16px; font-size: 13px;
      border-bottom: 1px solid ${C.border};
      background: ${C.yellow}10;
      color: ${C.yellow};
    }
    .wizard-steps { padding: 12px 16px; }
    .wizard-step {
      display: flex; gap: 12px; margin-bottom: 12px; align-items: flex-start;
    }
    .wizard-step-num {
      width: 24px; height: 24px; border-radius: 50%;
      background: ${C.surface2}; border: 2px solid ${C.border};
      display: flex; align-items: center; justify-content: center;
      font-size: 11px; font-weight: 700; flex-shrink: 0; color: ${C.textMuted};
    }
    .wizard-step.active .wizard-step-num { border-color: ${C.yellow}; color: ${C.yellow}; }
    .wizard-step.done   .wizard-step-num { border-color: ${C.green}; color: ${C.green}; background: ${C.green}20; }
    .wizard-step-content { flex: 1; }
    .wizard-instruction { margin-bottom: 10px; line-height: 1.5; }
    .pending { color: ${C.textDim}; }

    .progress-bar {
      height: 4px; background: ${C.surface2}; border-radius: 2px; margin: 8px 0;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%; width: 0%; background: ${C.yellow};
      animation: progress 8s linear forwards;
    }
    @keyframes progress { to { width: 100%; } }

    .confidence-bar {
      height: 6px; background: ${C.surface2}; border-radius: 3px; margin: 8px 0;
      position: relative; overflow: hidden;
    }
    .confidence-fill { height: 100%; border-radius: 3px; transition: width .5s; }
    .confidence-label {
      position: absolute; right: 0; top: -16px; font-size: 10px; color: ${C.orange};
    }
    .found-devices { font-size: 11px; color: ${C.textMuted}; margin-bottom: 8px; }

    .wizard-result { margin-bottom: 12px; }
    .result-confidence { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
    .result-phase, .result-devices, .result-rooms, .result-boosts {
      font-size: 12px; color: ${C.textMuted}; margin-top: 2px;
    }
    .result-boosts { color: ${C.green}; }

    /* ── Detail panel ── */
    .detail-panel {
      border-top: 1px solid ${C.border};
      background: ${C.surface};
    }
    .detail-header {
      display: flex; align-items: center; gap: 8px;
      padding: 10px 16px; border-bottom: 1px solid ${C.border};
      font-size: 14px;
    }
    .detail-close {
      margin-left: auto; background: none; border: none;
      cursor: pointer; color: ${C.textMuted}; font-size: 14px;
    }
    .detail-body { padding: 12px 16px; }
    .detail-section { margin-top: 12px; }
    .detail-label { font-size: 10px; color: ${C.textMuted}; text-transform: uppercase;
                    letter-spacing: .08em; margin-bottom: 4px; }
    .detail-row {
      display: flex; justify-content: space-between; padding: 4px 0;
      border-bottom: 1px solid ${C.border}20; font-size: 12px;
    }
    .detail-device {
      display: flex; justify-content: space-between; align-items: center;
      padding: 3px 0; font-size: 12px;
    }
    .unlink-btn {
      background: none; border: none; cursor: pointer;
      color: ${C.red}; font-size: 11px; opacity: .5;
    }
    .unlink-btn:hover { opacity: 1; }
    .detail-actions { display: flex; gap: 8px; margin-top: 12px; }

    /* ── Knoppen ── */
    .btn-primary, .btn-secondary, .btn-cancel, .btn-danger, .btn-small {
      padding: 7px 14px; border-radius: 6px; border: none;
      cursor: pointer; font-size: 12px; font-weight: 600;
      transition: all .15s; display: inline-block; margin: 3px 0;
    }
    .btn-primary   { background: ${C.accent};  color: #fff; }
    .btn-secondary { background: ${C.surface2}; color: ${C.text}; border: 1px solid ${C.border}; }
    .btn-cancel    { background: transparent; color: ${C.textMuted}; }
    .btn-danger    { background: ${C.red}20; color: ${C.red}; border: 1px solid ${C.red}40; }
    .btn-small     { background: ${C.surface2}; color: ${C.textMuted}; font-size: 11px; padding: 4px 8px; }
    .btn-primary:hover  { filter: brightness(1.15); }
    .btn-danger:hover   { background: ${C.red}40; }
    `;
  }

  // ── HA card config ─────────────────────────────────────────────────────────

  static getConfigElement() {
    const el = document.createElement("cloudems-groepenkast-card-editor");
    return el;
  }

  static getStubConfig() {
    return { type: "custom:cloudems-groepenkast-card" };
  }
}

// ── Editor ────────────────────────────────────────────────────────────────────

class CloudEMSGroepenkastCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; }
  connectedCallback() {
    this.innerHTML = `<div style="padding:12px;color:#e6edf3;font-family:monospace">
      <p style="color:#7d8590;font-size:12px">Geen extra configuratie vereist.</p>
      <p style="color:#7d8590;font-size:12px;margin-top:4px">
        Groepen worden beheerd via de kaart zelf.
      </p>
    </div>`;
  }
}

if (!customElements.get("cloudems-groepenkast-card")) {
  customElements.define("cloudems-groepenkast-card", CloudEMSGroepenkastCard);
}
if (!customElements.get("cloudems-groepenkast-card-editor")) {
  customElements.define("cloudems-groepenkast-card-editor", CloudEMSGroepenkastCardEditor);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type:        "cloudems-groepenkast-card",
  name:        "CloudEMS Groepenkast",
  description: "Digitale twin van de groepenkast — boom-weergave, leerproces, NEN1010 toetsing",
});
