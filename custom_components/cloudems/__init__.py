# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS - Energy Management System for Home Assistant — v4.5.25."""
# BUG FIX: Platform.BINARY_SENSOR was missing from PLATFORMS list
from __future__ import annotations
import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import area_registry as ar

from .const import (
    DOMAIN, VERSION, CONF_HIDDEN_TABS, CLOUDEMS_TABS, CLOUDEMS_TABS_HIDDEN_DEFAULT,
    CONF_NILM_PRUNE_THRESHOLD, DEFAULT_NILM_PRUNE_THRESHOLD,
    CONF_NILM_PRUNE_MIN_DAYS, DEFAULT_NILM_PRUNE_MIN_DAYS,
)
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)

# FIX: Added Platform.BINARY_SENSOR — was missing in v1.4.0, causing cheap-hour
#      binary sensors to never be registered
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.CLIMATE,          # v4.0.8: CloudEMS zone thermostat
    Platform.TEXT,             # v4.3.6: rolluik tijden
]

LOVELACE_CARDS_URL     = f"/local/cloudems/cloudems-cards.js?v={VERSION}"
LOVELACE_CARDMOD_URL   = f"/local/cloudems/cloudems-card-mod.js?v={VERSION}"
LOVELACE_RESOURCE_TYPE = "module"
# cloudems-card.js bestaat niet — alle kaarten zitten in cloudems-cards.js.
# Constante alleen voor opruimen van stale registraties.
_STALE_CARD_JS_KEYWORD = "cloudems-card.js"

# v4.5.23: externe custom cards die CloudEMS nodig heeft
# v4.5.33: Alle externe cards zijn nagebouwd als CloudEMS eigen cards.
# Geen externe downloads meer nodig — alles zit in cloudems-cards.js en cloudems-card-mod.js.
_EXTERNAL_CARDS: list[dict] = []

# ── CloudEMS HA-ruimte aanmaken ───────────────────────────────────────────────

# Ruimtes die CloudEMS bij setup aanmaakt als ze nog niet bestaan
_CLOUDEMS_AREAS: list[tuple[str, str]] = [
    ("CloudEMS",         "mdi:lightning-bolt-circle"),   # voor eigen sensors
    ("CloudEMS Exclude", "mdi:filter-remove-outline"),   # voor Zonneplan/meters
]


def _ensure_cloudems_areas(hass: HomeAssistant) -> None:
    """Maak CloudEMS HA-ruimtes aan als ze nog niet bestaan.

    'CloudEMS Exclude' wordt aangemaakt zodat andere integraties (Zonneplan,
    Shelly, enz.) hun energiemeter-koppeling naar deze ruimte kunnen wijzen.
    Zo worden CloudEMS-interne metingen uitgesloten van de energiebalans.
    """
    try:
        area_reg = ar.async_get(hass)
        existing = {a.name.lower() for a in area_reg.areas.values()}
        for name, icon in _CLOUDEMS_AREAS:
            if name.lower() not in existing:
                area_reg.async_create(name, icon=icon)
                _LOGGER.info("CloudEMS: HA-ruimte '%s' aangemaakt", name)
            else:
                _LOGGER.debug("CloudEMS: HA-ruimte '%s' bestaat al", name)
    except Exception as exc:
        _LOGGER.warning("CloudEMS: ruimte aanmaken mislukt: %s", exc)


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register CloudEMS JS files as Lovelace resources.

    Uses the official lovelace storage collection API introduced in HA 2022.x.
    Falls back gracefully if lovelace is in yaml mode or unavailable.
    """
    try:
        # The correct public API: import the lovelace component and get its
        # ResourceStorageCollection via hass.data["lovelace"]["resources"].
        # We must wait until lovelace has fully loaded.
        from homeassistant.components import lovelace as lovelace_component  # noqa: PLC0415

        lovelace_data = hass.data.get(lovelace_component.DOMAIN)
        if lovelace_data is None:
            _LOGGER.debug("CloudEMS: lovelace component not yet available, skipping resource registration")
            return

        resources = lovelace_data.get("resources") if isinstance(lovelace_data, dict) else getattr(lovelace_data, "resources", None)
        if resources is None:
            _LOGGER.debug("CloudEMS: lovelace in yaml-mode or resources unavailable, skipping")
            return

        await resources.async_load()
        current_items = list(resources.async_items())

        # Stap 1: verwijder verouderde CloudEMS resource-entries
        # Inclusief de nooit-bestaande cloudems-card.js die fout werd geregistreerd
        stale_keywords = ["cloudems-card.js", "cloudems-cards.js", "cloudems-card-mod.js"]
        correct_urls   = {LOVELACE_CARDS_URL, LOVELACE_CARDMOD_URL}
        for item in current_items:
            item_url = item.get("url", "")
            if any(kw in item_url for kw in stale_keywords) and item_url not in correct_urls:
                try:
                    await resources.async_delete_item(item["id"])
                    _LOGGER.info("CloudEMS: verouderde Lovelace resource verwijderd → %s", item_url)
                except Exception as _del_err:
                    _LOGGER.debug("CloudEMS: kon verouderde resource niet verwijderen: %s", _del_err)

        # Herlaad na cleanup zodat current_items actueel is
        await resources.async_load()
        current_items = list(resources.async_items())
        current = {r.get("url", ""): r for r in current_items}

        # Stap 2: registreer/update de correcte resource-entries (alleen bestaande JS files)
        for url, keyword in [
            (LOVELACE_CARDS_URL,    "cloudems-cards.js"),
            (LOVELACE_CARDMOD_URL,  "cloudems-card-mod.js"),
        ]:
            matches = [v for k, v in current.items() if keyword in k]
            if matches:
                item = matches[0]
                if item.get("url") != url:
                    await resources.async_update_item(item["id"], {
                        "res_type": LOVELACE_RESOURCE_TYPE,
                        "url": url,
                    })
                    _LOGGER.info("CloudEMS: Lovelace resource bijgewerkt → %s", url)
                else:
                    _LOGGER.debug("CloudEMS: Lovelace resource al actueel: %s", url)
            else:
                await resources.async_create_item({
                    "res_type": LOVELACE_RESOURCE_TYPE,
                    "url": url,
                })
                _LOGGER.info("CloudEMS: Lovelace resource geregistreerd → %s", url)

    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("CloudEMS: kon Lovelace resources niet registreren: %s", err)


async def _async_install_vendor_cards(hass: HomeAssistant) -> None:
    """v4.5.33: Niet meer nodig — alle externe cards zijn nagebouwd als CloudEMS eigen cards.
    Functie blijft als no-op om bestaande call sites niet te breken.
    """
    _LOGGER.debug("CloudEMS: vendor card installatie overgeslagen — alles ingebouwd")


async def _async_apply_tab_visibility(hass: HomeAssistant, hidden_tabs: list[str]) -> None:
    """Pas subview-vlag aan in het CloudEMS Lovelace-dashboard op basis van hidden_tabs.

    Tabbladen in hidden_tabs krijgen ``subview: true`` → verdwijnen uit navigatiebalk.
    Alle andere CloudEMS-tabbladen krijgen ``subview: false`` → zichtbaar.

    Werkt via de HA Lovelace storage API (lovelace.dashboards / lovelace.config).
    Wanneer het dashboard in YAML-modus staat (file_mode), wordt de aanpassing
    overgeslagen en gelogged — de gebruiker moet de YAML dan zelf beheren.
    """
    import logging as _log
    _L = _log.getLogger(__name__)

    known_paths = {path for path, _ in CLOUDEMS_TABS}

    try:
        # HA stores Lovelace dashboards in hass.data["lovelace"]["dashboards"]
        lovelace = hass.data.get("lovelace")
        if not lovelace:
            _L.warning("CloudEMS tab visibility: Lovelace not available, skipping")
            return

        # Find the CloudEMS dashboard — it has views with paths starting 'cloudems-'
        _dashboards_obj = getattr(lovelace, "dashboards", None)
        dashboards = _dashboards_obj if _dashboards_obj is not None else (lovelace.get("dashboards", {}) if hasattr(lovelace, "get") else {})

        target_dashboard = None
        for _url_slug, dash in dashboards.items():
            try:
                cfg = await dash.async_load(force=False)
                views = cfg.get("views", [])
                if any(v.get("path", "").startswith("cloudems-") for v in views):
                    target_dashboard = dash
                    target_cfg = cfg
                    break
            except Exception:
                continue

        # Also check default dashboard
        if target_dashboard is None:
            try:
                default = dashboards.get("lovelace", None) if hasattr(dashboards, "get") else getattr(dashboards, "lovelace", None)
                if default is None:
                    # Try the lovelace object itself as default dashboard handler
                    _dash_obj = (dashboards.get("lovelace") if hasattr(dashboards, "get") else None) or getattr(dashboards, "lovelace", None)
                    if _dash_obj is None:
                        raise KeyError("lovelace dashboard not found")
                    cfg = await _dash_obj.async_load(force=False)
                    views = cfg.get("views", [])
                    if any(v.get("path", "").startswith("cloudems-") for v in views):
                        target_dashboard = _dash_obj
                        target_cfg = cfg
            except Exception:
                pass

        if target_dashboard is None:
            _L.warning(
                "CloudEMS tab visibility: kon het CloudEMS dashboard niet vinden. "
                "Controleer of het dashboard actief is in Lovelace."
            )
            return

        # Check for file mode (yaml-managed dashboard cannot be programmatically saved)
        if getattr(target_dashboard, "mode", None) == "yaml":
            _L.info(
                "CloudEMS tab visibility: dashboard staat in YAML-modus. "
                "Voeg 'subview: true' handmatig toe aan gewenste views in cloudems-dashboard.yaml."
            )
            return

        # Patch views
        views = target_cfg.get("views", [])
        changed = False
        for view in views:
            path = view.get("path", "")
            if path not in known_paths:
                continue
            should_be_subview = path in hidden_tabs
            current = bool(view.get("subview", False))
            if current != should_be_subview:
                view["subview"] = should_be_subview
                changed = True
                _L.debug(
                    "CloudEMS tab '%s': subview %s → %s",
                    path, current, should_be_subview,
                )

        if changed:
            await target_dashboard.async_save(target_cfg)
            hidden_labels = [label for p, label in CLOUDEMS_TABS if p in hidden_tabs]
            visible_labels = [label for p, label in CLOUDEMS_TABS if p not in hidden_tabs]
            _L.info(
                "CloudEMS tab visibility bijgewerkt — verborgen: %s | zichtbaar: %s",
                ", ".join(hidden_labels) or "geen",
                ", ".join(visible_labels),
            )
        else:
            _L.debug("CloudEMS tab visibility: geen wijzigingen nodig")

    except Exception as err:
        _log.getLogger(__name__).warning(
            "CloudEMS tab visibility: fout bij aanpassen dashboard: %s", err
        )



def _prune_climate_entities(hass, entry) -> None:
    """
    v4.2.1: Verwijder stale CloudEMS climate entities én orphan devices.
    Werkt in twee passes:
      Pass 1 — entities: verwijder stale climate entities
      Pass 2 — devices:  verwijder ALLE Zone Thermostaat / Klimaat Hub devices
                         van dit entry die geen entities meer hebben
    Pass 2 werkt onafhankelijk van pass 1 zodat ook devices die al in een
    eerdere run hun entities verloren hebben nu alsnog worden opgeruimd.
    """
    from homeassistant.helpers import entity_registry as er, device_registry as dr
    ent_reg  = er.async_get(hass)
    dev_reg  = dr.async_get(hass)
    entry_id = entry.entry_id
    config   = {**entry.data, **entry.options}
    enabled  = bool(config.get("climate_mgr_enabled", False))

    def _is_legacy(entity_id: str, unique_id: str) -> bool:
        for s in ("climate_schedule", "climate_scheduler"):
            if s in entity_id or s in unique_id:
                return True
        return False

    # ── Pass 1: entities ──────────────────────────────────────────────────
    removed_entities = 0
    for e in list(ent_reg.entities.values()):
        if e.config_entry_id != entry_id or e.domain != "climate":
            continue
        uid = e.unique_id or ""
        eid = e.entity_id or ""
        if (not enabled) or _is_legacy(eid, uid):
            ent_reg.async_remove(e.entity_id)
            removed_entities += 1
            _LOGGER.info("CloudEMS prune: entity verwijderd: %s", e.entity_id)

    # ── Pass 2: orphan devices ────────────────────────────────────────────
    # Bouw set van alle device_ids die nog minstens één entity hebben
    occupied_device_ids = {e.device_id for e in ent_reg.entities.values() if e.device_id}

    def _is_legacy_device(dev) -> bool:
        """Detecteer legacy rommel-devices op naam, identifier of model."""
        name = (dev.name or "").lower()
        for s in ("climate_schedule", "climate_scheduler"):
            if s in name:
                return True
        # Check ook de identifier tuples (DOMAIN, identifier_string)
        for ident in (dev.identifiers or set()):
            ident_str = str(ident[1]) if len(ident) > 1 else ""
            for s in ("climate_schedule", "climate_scheduler"):
                if s in ident_str:
                    return True
        return False

    removed_devices = 0
    for dev in list(dev_reg.devices.values()):
        # Alleen Zone Thermostaat en Klimaat Hub devices van CloudEMS
        if dev.model not in ("Zone Thermostaat", "Klimaat Hub"):
            continue
        # Controleer of dit device bij ons config entry hoort
        cfg_entries = getattr(dev, "config_entries", set()) or set()
        if entry_id not in cfg_entries:
            continue
        # Verwijder als: geen entities meer ÓFTEWEL een legacy rommel-naam
        if dev.id not in occupied_device_ids or _is_legacy_device(dev):
            # Verwijder eerst eventuele resterende entities van dit device
            for e in list(ent_reg.entities.values()):
                if e.device_id == dev.id:
                    ent_reg.async_remove(e.entity_id)
                    removed_entities += 1
                    _LOGGER.info("CloudEMS prune: entity van legacy device verwijderd: %s", e.entity_id)
            dev_reg.async_remove_device(dev.id)
            removed_devices += 1
            _LOGGER.info("CloudEMS prune: device verwijderd: %s", dev.name)

    if removed_entities or removed_devices:
        _LOGGER.info(
            "CloudEMS prune: %d entiteit(en) en %d device(s) opgeruimd",
            removed_entities, removed_devices,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up CloudEMS integration v%s", VERSION)

    # v3.9: Maak CloudEMS HA-ruimtes aan als ze nog niet bestaan.
    # "CloudEMS"         → voor alle CloudEMS sensors/switches (suggested_area)
    # "CloudEMS Exclude" → virtuele ruimte die Zonneplan en andere integraties
    #                      kunnen selecteren om CloudEMS-interne metingen uit
    #                      te sluiten van hun energiebalans.
    _ensure_cloudems_areas(hass)

    # v4.2.1: Prune stale CloudEMS climate entities als de functie uitgeschakeld is.
    # Zo blijven er geen orphan Zone Thermostaat devices achter in HA na het uitzetten.
    _prune_climate_entities(hass, entry)

    coordinator = CloudEMSCoordinator(hass, {**entry.data, **entry.options})
    await coordinator.async_setup()
    # Use async_refresh (not first_refresh) so a slow/failing first update
    # does NOT mark all entities unavailable — they will recover on the next poll.
    try:
        await coordinator.async_refresh()
    except Exception:  # noqa: BLE001
        _LOGGER.warning("CloudEMS: first refresh failed, entities will recover on next poll")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # v4.2.2: Centrale orphan pruner — ruimt alle verouderde dynamische CloudEMS-entiteiten
    # automatisch op: NILM sensoren, bevestig/afwijs-knoppen, omvormer sensoren,
    # kamermeters en zoneklimaat sensoren.
    from .orphan_pruner import OrphanPruner
    cfg_all = {**entry.data, **entry.options}
    _pruner = OrphanPruner(
        hass       = hass,
        entry      = entry,
        coordinator= coordinator,
        threshold  = int(cfg_all.get(CONF_NILM_PRUNE_THRESHOLD, DEFAULT_NILM_PRUNE_THRESHOLD)),
        min_days   = float(cfg_all.get(CONF_NILM_PRUNE_MIN_DAYS, DEFAULT_NILM_PRUNE_MIN_DAYS)),
    )
    _pruner.register()
    await _pruner.async_load()

    # Flush leerdata bij HA stop (harde restart, power-off) — voorkomt azimuth reset
    async def _flush_on_stop(event=None) -> None:
        try:
            await coordinator.async_shutdown()
        except Exception:
            pass

    # Registreer op zowel HA stop-event als config entry unload
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _flush_on_stop)
    )

    # v2.4.18: registreer CloudEMS als energy platform voor HA energiedashboard
    try:
        from homeassistant.components import energy as _energy_component
        if hasattr(_energy_component, "async_register_info"):
            from .energy import async_get_energy_info
            _energy_component.async_register_info(hass, DOMAIN, async_get_energy_info)
            _LOGGER.info("CloudEMS: geregistreerd als HA energy platform")
    except Exception as _ep_err:
        _LOGGER.debug("CloudEMS: energy platform registratie niet beschikbaar: %s", _ep_err)

    # Auto-register the Lovelace card resource so users don't have to do it manually.
    # We defer until HA is fully started so lovelace resources are available.
    from homeassistant.core import callback as _ha_callback

    @_ha_callback
    def _schedule_lovelace_registration(_now=None):
        hass.async_create_task(_async_register_lovelace_resource(hass))

    if hass.is_running:
        # HA already started (e.g. integration reload), register immediately
        _schedule_lovelace_registration()
    else:
        # Wait until HA is fully started before registering Lovelace resources
        from homeassistant.helpers.start import async_at_started
        async_at_started(hass, _schedule_lovelace_registration)

    # Apply tab visibility (subview flags) based on config
    cfg = {**entry.data, **entry.options}
    hidden_tabs = cfg.get(CONF_HIDDEN_TABS, list(CLOUDEMS_TABS_HIDDEN_DEFAULT))
    hass.async_create_task(_async_apply_tab_visibility(hass, hidden_tabs))

    # Registreer CloudEMS tablet dashboard als custom panel in de HA sidebar
    hass.async_create_task(_async_register_panel(hass))

    # Maak het CloudEMS Lovelace-dashboard automatisch aan als het nog niet bestaat
    # Dashboard aanmaken ook uitstellen tot HA volledig gestart is
    @_ha_callback
    def _schedule_dashboard_creation(_now=None):
        hass.async_create_task(_async_ensure_lovelace_dashboard(hass))

    if hass.is_running:
        _schedule_dashboard_creation()
    else:
        async_at_started(hass, _schedule_dashboard_creation)

    return True


async def _async_ensure_lovelace_dashboard(hass: HomeAssistant) -> None:
    """Maak het CloudEMS Lovelace-dashboard automatisch aan als het nog niet bestaat.

    Strategie: schrijf direct naar HA .storage bestanden, precies zoals HA zelf
    dat doet. Twee bestanden zijn nodig:
      1. lovelace_dashboards   — registreert het dashboard in de sidebar
      2. lovelace.{slug}       — bevat de views/kaarten configuratie

    Dit omzeilt alle interne lovelace-API's die tussen HA-versies wisselen.
    """
    import pathlib
    import yaml as _yaml
    import json
    import time

    _STORAGE  = pathlib.Path(hass.config.config_dir) / ".storage"
    _DASH_REG = _STORAGE / "lovelace_dashboards"
    _WWW      = pathlib.Path(__file__).parent / "www"

    # Productie + DEV dashboard definitie
    _DASHBOARDS = [
        {
            "slug":      "cloudems-lovelace",
            "title":     "CloudEMS",
            "icon":      "mdi:lightning-bolt",
            "yaml_file": "cloudems-dashboard.yaml",
            "admin":     False,
        },
        {
            "slug":      "cloudems-dev",
            "title":     "⚗️ CloudEMS DEV",
            "icon":      "mdi:flask",
            "yaml_file": "cloudems-dashboard-dev.yaml",
            "admin":     True,   # alleen admins — dev-omgeving
        },
    ]

    def _do_storage_work():
        """Alle blocking I/O in één executor-job."""
        # --- Stap 1: lovelace_dashboards (registratie-lijst) ---
        try:
            reg = json.loads(_DASH_REG.read_text(encoding="utf-8"))
        except Exception:
            reg = {"version": 1, "minor_version": 1, "key": "lovelace_dashboards", "data": {"items": []}}

        items = reg.get("data", {}).get("items", [])
        existing_ids = {it.get("url_path") for it in items}
        reg_changed = False
        newly_created = []

        for dash in _DASHBOARDS:
            slug      = dash["slug"]
            yaml_src  = _WWW / dash["yaml_file"]
            dash_cfg  = _STORAGE / f"lovelace.{slug}"

            if not yaml_src.exists():
                _LOGGER.debug("CloudEMS: %s niet gevonden, dashboard overgeslagen", dash["yaml_file"])
                continue

            dashboard_config = _yaml.safe_load(yaml_src.read_text(encoding="utf-8"))

            # Zorg dat resources in de storage-config de versie-cache-buster hebben.
            # Hiermee laadt de browser na elke update de nieuwste JS — geen hard refresh nodig.
            dashboard_config["resources"] = [
                {"url": f"/local/cloudems/cloudems-cards.js?v={VERSION}",    "type": "module"},
                {"url": f"/local/cloudems/cloudems-card-mod.js?v={VERSION}", "type": "module"},
            ]

            # Registreer in sidebar als nog niet aanwezig
            if slug not in existing_ids:
                items.append({
                    "id":              slug,
                    "url_path":        slug,
                    "require_admin":   dash["admin"],
                    "title":           dash["title"],
                    "icon":            dash["icon"],
                    "show_in_sidebar": True,
                    "mode":            "storage",
                })
                reg_changed = True
                newly_created.append(slug)
                _LOGGER.info("CloudEMS: dashboard '%s' geregistreerd", dash["title"])

            # --- Stap 2: lovelace.{slug} — altijd updaten na HACS-installatie ---
            cfg_data = {
                "version": 1, "minor_version": 1,
                "key": f"lovelace.{slug}",
                "data": {"config": dashboard_config},
            }
            dash_cfg.write_text(json.dumps(cfg_data, ensure_ascii=False, indent=2), encoding="utf-8")
            _LOGGER.info("CloudEMS: dashboard config bijgewerkt → %s", dash_cfg.name)

        if reg_changed:
            reg["data"]["items"] = items
            _DASH_REG.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

        return newly_created

    try:
        created = await hass.async_add_executor_job(_do_storage_work)
        if created:
            _LOGGER.info("CloudEMS: nieuwe dashboards aangemaakt: %s — herstart HA om sidebar te zien", created)
        else:
            _LOGGER.info("CloudEMS: alle dashboard configs bijgewerkt")

        # ── Live reload ────────────────────────────────────────────────────────
        # Na HACS-update zijn de .storage bestanden bijgewerkt maar HA heeft de
        # vorige versie nog in memory.  Forceer een reload van elk dashboard-object
        # zodat gebruikers zonder herstart de nieuwe views zien.
        await _async_reload_cloudems_dashboards(hass)

    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("CloudEMS: kon Lovelace dashboard niet aanmaken: %s", err)


async def _async_reload_cloudems_dashboards(hass: HomeAssistant) -> None:
    """Herlaad de CloudEMS dashboards in-memory zonder HA herstart.

    Na een HACS-update zijn de .storage bestanden bijgewerkt maar heeft HA de
    vorige versie nog in memory.  Deze functie roept async_load(force=True) aan
    op elk dashboard-object dat CloudEMS-views bevat, waarna HA de nieuwe YAML
    meteen toont in de browser — geen herstart nodig.

    Werkt via de officiële lovelace storage API.  Bij YAML-modus of als het
    dashboard nog niet bestaat wordt de reload stil overgeslagen.
    """
    CLOUDEMS_SLUGS = {"cloudems-lovelace", "cloudems-dev"}

    try:
        from homeassistant.components import lovelace as _ll  # noqa: PLC0415
        lovelace = hass.data.get(_ll.DOMAIN)
        if not lovelace:
            return

        dashboards = getattr(lovelace, "dashboards", None)
        if dashboards is None and hasattr(lovelace, "get"):
            dashboards = lovelace.get("dashboards", {})
        if not dashboards:
            return

        reloaded = []
        for slug, dash in dashboards.items():
            # Alleen onze eigen dashboards
            if slug not in CLOUDEMS_SLUGS:
                continue
            # YAML-modus dashboards kunnen niet programmatisch worden herladen
            if getattr(dash, "mode", None) == "yaml":
                continue
            try:
                await dash.async_load(force=True)
                reloaded.append(slug)
                _LOGGER.info("CloudEMS: dashboard '%s' in-memory herladen ✓", slug)
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("CloudEMS: reload '%s' mislukt (niet kritiek): %s", slug, e)

        if reloaded:
            # Stuur een Lovelace updated event zodat open browsers automatisch refreshen
            hass.bus.async_fire("lovelace_updated", {"url_path": slug} if len(reloaded) == 1 else {})

    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("CloudEMS: _async_reload_cloudems_dashboards fout (niet kritiek): %s", err)


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Registreer CloudEMS tablet dashboard als custom panel op /cloudems.

    De HTML staat in custom_components/cloudems/www/dashboard.html en wordt
    geserveerd via /local/cloudems/dashboard.html nadat de www/ map gekopieerd
    is (HA doet dit automatisch voor custom_components met een www/ submap).

    Panel URL: http://<ha-host>:8123/cloudems
    """
    import shutil, pathlib

    # Kopieer www/ naar /config/www/cloudems/ via executor (blocking I/O)
    src = pathlib.Path(__file__).parent / "www"
    dst = pathlib.Path(hass.config.config_dir) / "www" / "cloudems"

    def _copy_www():
        try:
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.rglob("*"):
                if f.is_file() and f.name != "cloudems-dashboard.yaml":
                    rel    = f.relative_to(src)
                    dest_f = dst / rel
                    dest_f.parent.mkdir(parents=True, exist_ok=True)
                    if not dest_f.exists() or f.stat().st_mtime > dest_f.stat().st_mtime:
                        shutil.copy2(f, dest_f)
        except Exception as _err:
            _LOGGER.warning("CloudEMS: kon www/ niet kopiëren naar /config/www/: %s", _err)

        # Kopieer cloudems-dashboard.yaml naar /config/ (altijd, zodat hij in sync blijft met de component)
        yaml_src = src / "cloudems-dashboard.yaml"
        yaml_dst = pathlib.Path(hass.config.config_dir) / "cloudems-dashboard.yaml"
        try:
            if yaml_src.exists():
                import hashlib
                src_hash = hashlib.md5(yaml_src.read_bytes()).hexdigest()
                dst_hash = hashlib.md5(yaml_dst.read_bytes()).hexdigest() if yaml_dst.exists() else ""
                if src_hash != dst_hash:
                    shutil.copy2(yaml_src, yaml_dst)
                    _LOGGER.info("CloudEMS: cloudems-dashboard.yaml bijgewerkt in /config/")
        except Exception as _err:
            _LOGGER.warning("CloudEMS: kon cloudems-dashboard.yaml niet kopiëren naar /config/: %s", _err)

    await hass.async_add_executor_job(_copy_www)

    # Registreer als panel_custom (HA sidebar)
    try:
        from homeassistant.components import frontend
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="CloudEMS",
            sidebar_icon="mdi:lightning-bolt",
            frontend_url_path="cloudems",
            config={"url": "/local/cloudems/dashboard.html"},
            require_admin=False,
        )
        # Simulator panel als tweede entry
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="CloudEMS Test",
            sidebar_icon="mdi:test-tube",
            frontend_url_path="cloudems-sim",
            config={"url": "/local/cloudems/simulator.html"},
            require_admin=True,  # alleen admins — ingreep in systeemgedrag
        )
        # Setup wizard — tablet/scherm installatie
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="CloudEMS Setup",
            sidebar_icon="mdi:tablet",
            frontend_url_path="cloudems-setup",
            config={"url": "/local/cloudems/setup-wizard.html"},
            require_admin=True,
        )
        _LOGGER.info("CloudEMS tablet dashboard geregistreerd op /cloudems")
    except Exception as _err:
        _LOGGER.debug("CloudEMS: panel registratie mislukt: %s", _err)


def _register_services(hass: HomeAssistant, entry: ConfigEntry, coordinator: CloudEMSCoordinator):

    async def confirm_device(call: ServiceCall):
        coordinator.confirm_nilm_device(
            call.data["device_id"],
            call.data["device_type"],
            call.data.get("name", call.data["device_type"]),
        )

    async def dismiss_device(call: ServiceCall):
        coordinator.dismiss_nilm_device(call.data["device_id"])

    async def name_undefined_power(call: ServiceCall):
        """v4.5.64: Geef het onverklaarde vermogen een naam.
        
        Het onverklaarde vermogen is het verschil tussen het totale huisverbruik
        en de som van alle door NILM herkende apparaten. Dit is altijd-aan verbruik
        dat NILM (nog) niet herkent, zoals een koelkast, waterontharder, of standby-last.
        
        Gebruik: cloudems.name_undefined_power met data: {name: "Koelkast + standby"}
        Leegmaken: {name: ""} reset naar default "Onverklaard vermogen"
        """
        name = call.data.get("name", "").strip()
        coordinator._undefined_power_name = name
        _LOGGER.info("CloudEMS: onverklaard vermogen hernoemd naar '%s'", name or "(reset)")



    # FIX: New service for feedback (correct/incorrect/maybe)
    async def nilm_feedback(call: ServiceCall):
        coordinator.set_nilm_feedback(
            call.data["device_id"],
            call.data["feedback"],          # correct | incorrect | maybe
            call.data.get("name",""),
            call.data.get("device_type",""),
        )

    async def rename_nilm_device(call: ServiceCall):
        """v1.20: Rename a NILM device (display name + optional type)."""
        coordinator.rename_nilm_device(
            call.data["device_id"],
            call.data["name"],
            call.data.get("device_type", ""),
        )

    async def hide_nilm_device(call: ServiceCall):
        """v1.20: Hide or unhide a NILM device from dashboards."""
        coordinator.hide_nilm_device(
            call.data["device_id"],
            call.data.get("hidden", True),
        )

    async def suppress_nilm_device(call: ServiceCall):
        """v1.20: Decline/suppress a NILM device — never show again."""
        coordinator.suppress_nilm_device(call.data["device_id"])

    async def assign_device_to_room(call: ServiceCall):
        """v1.20: Manually assign a NILM device to a room."""
        coordinator.assign_device_to_room(
            call.data["device_id"],
            call.data.get("room", ""),
        )

    async def include_nilm_device(call: ServiceCall):
        """v1.21: Hef auto-exclude op — apparaat gaat naar 'overig' (of keyword/heuristiek)."""
        rm = getattr(coordinator, "_room_meter", None)
        if rm:
            rm.include_device(call.data["device_id"])
            coordinator.async_update_listeners()

    async def exclude_nilm_device(call: ServiceCall):
        """v1.21: Forceer apparaat altijd naar CloudEMS Exclude ruimte."""
        rm = getattr(coordinator, "_room_meter", None)
        if rm:
            rm.exclude_device(call.data["device_id"])
            coordinator.async_update_listeners()

    async def label_nilm_device(call: ServiceCall):
        """v1.21: Sla een categorie-label op voor een NILM apparaat."""
        rm = getattr(coordinator, "_room_meter", None)
        if rm:
            ok = rm.label_device(
                call.data["device_id"],
                call.data.get("label", ""),
            )
            if ok:
                coordinator.async_update_listeners()
            else:
                _LOGGER.warning(
                    "label_nilm_device: onbekend label '%s'. "
                    "Geldige waarden: %s",
                    call.data.get("label"),
                    ", ".join(["meter","solar","battery","ev","heating",
                               "cooling","appliance","lighting","network","unknown"]),
                )

    async def set_phase_max_current(call: ServiceCall):
        coordinator._limiter.set_max_current(
            call.data["phase"],
            float(call.data["max_current"]),
        )

    async def force_price_update(call: ServiceCall):
        if coordinator._prices:
            await coordinator._prices.update()


    async def generate_report(call: ServiceCall):
        from .diagnostics import async_generate_report
        await async_generate_report(hass, entry)

    async def download_energy_report(call: ServiceCall):
        """Genereer een HTML-energierapport en sla op in /config/www/cloudems/.

        Het bestand is downloadbaar via /local/cloudems/rapport-YYYY-MM.html.
        Na generatie wordt sensor.cloudems_last_report_url bijgewerkt.
        """
        import os, pathlib
        from datetime import datetime as _dt, timezone as _tz
        from .energy_manager.monthly_report import MonthlyReportGenerator, _prev_month_label

        now   = _dt.now(_tz.utc)
        label = call.data.get("month", "") or _prev_month_label(now)
        data  = coordinator.data or {}

        # Bouw Markdown rapport
        gen    = MonthlyReportGenerator(hass, "")
        md_text = gen._build(data, label)  # noqa: SLF001

        # Converteer naar nette HTML
        html = _md_to_html(md_text, label)

        # Schrijf naar /config/www/cloudems/
        www_dir = pathlib.Path(hass.config.config_dir) / "www" / "cloudems"
        www_dir.mkdir(parents=True, exist_ok=True)
        filename = f"rapport-{label.lower().replace(' ', '-')}.html"
        filepath = www_dir / filename
        await hass.async_add_executor_job(filepath.write_text, html, "utf-8")

        url = f"/local/cloudems/{filename}"
        _LOGGER.info("CloudEMS rapport gegenereerd: %s", url)

        # Sla URL op zodat de dashboard sensor hem kan tonen
        # Gebruik aparte subkey "_reports" om niet te botsen met de coordinator object
        hass.data.setdefault(DOMAIN, {}).setdefault("_reports", {}).setdefault(entry.entry_id, {})
        hass.data[DOMAIN]["_reports"][entry.entry_id]["last_report_url"]   = url
        hass.data[DOMAIN]["_reports"][entry.entry_id]["last_report_label"] = label

        # Stuur een persistent notification met directe link
        from homeassistant.components.persistent_notification import async_create as _pn
        _pn(
            hass,
            message=f"[📥 Download rapport — {label}]({url})",
            title=f"☀️ CloudEMS Rapport gereed — {label}",
            notification_id="cloudems_report_ready",
        )

        # Ververs de sensor zodat de URL zichtbaar is in het dashboard
        coordinator.async_update_listeners()

    async def boiler_override(call: ServiceCall):
        """Manually force a boiler on or off."""
        if coordinator._boiler_ctrl:
            entity_id = call.data["entity_id"]
            state     = call.data.get("state", "on")
            domain    = entity_id.split(".")[0]
            await hass.services.async_call(
                domain, f"turn_{state}", {"entity_id": entity_id}, blocking=False
            )

    hass.services.async_register(DOMAIN, "confirm_device",         confirm_device)
    hass.services.async_register(DOMAIN, "dismiss_device",         dismiss_device)
    hass.services.async_register(DOMAIN, "nilm_feedback",          nilm_feedback)
    hass.services.async_register(DOMAIN, "rename_nilm_device",     rename_nilm_device)
    hass.services.async_register(DOMAIN, "hide_nilm_device",       hide_nilm_device)
    hass.services.async_register(DOMAIN, "suppress_nilm_device",   suppress_nilm_device)
    hass.services.async_register(DOMAIN, "assign_device_to_room",  assign_device_to_room)
    hass.services.async_register(DOMAIN, "name_undefined_power",   name_undefined_power,
        schema=vol.Schema({vol.Optional("name", default=""): str}))
    hass.services.async_register(DOMAIN, "include_nilm_device",    include_nilm_device,
        schema=vol.Schema({vol.Required("device_id"): str}))
    hass.services.async_register(DOMAIN, "exclude_nilm_device",    exclude_nilm_device,
        schema=vol.Schema({vol.Required("device_id"): str}))
    hass.services.async_register(DOMAIN, "label_nilm_device",      label_nilm_device,
        schema=vol.Schema({
            vol.Required("device_id"): str,
            vol.Optional("label", default=""): str,
        }))

    # ── v4.5.51: Meter topologie services ──────────────────────────────────

    async def meter_topology_approve(call: ServiceCall):
        """Bevestig een upstream-relatie in de meter-topologie."""
        topo = getattr(coordinator, "_meter_topology", None)
        if not topo:
            _LOGGER.warning("meter_topology niet beschikbaar")
            return
        topo.approve(call.data["upstream_id"], call.data["downstream_id"])

    async def meter_topology_decline(call: ServiceCall):
        """Wijs een upstream-relatie af in de meter-topologie."""
        topo = getattr(coordinator, "_meter_topology", None)
        if not topo:
            _LOGGER.warning("meter_topology niet beschikbaar")
            return
        topo.decline(call.data["upstream_id"], call.data["downstream_id"])

    async def meter_topology_set_root(call: ServiceCall):
        """Markeer een entity als root-meter (P1 / hoofdmeter)."""
        topo = getattr(coordinator, "_meter_topology", None)
        if not topo:
            return
        if call.data.get("is_root", True):
            topo.set_root_meter(call.data["entity_id"])
        else:
            topo.remove_root_meter(call.data["entity_id"])

    hass.services.async_register(DOMAIN, "meter_topology_approve", meter_topology_approve,
        schema=vol.Schema({
            vol.Required("upstream_id"):   str,
            vol.Required("downstream_id"): str,
        }))
    hass.services.async_register(DOMAIN, "meter_topology_decline", meter_topology_decline,
        schema=vol.Schema({
            vol.Required("upstream_id"):   str,
            vol.Required("downstream_id"): str,
        }))
    hass.services.async_register(DOMAIN, "meter_topology_set_root", meter_topology_set_root,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Optional("is_root", default=True): bool,
        }))

    async def zonneplan_battery_charge(call: ServiceCall):
        """v1.21: Laad de Nexus (Pad A: home_optimization + solar slider / Pad B: manual_control)."""
        zb = getattr(coordinator, "_zonneplan_bridge", None)
        if not zb or not zb.is_available:
            _LOGGER.warning("ZonneplanBridge niet beschikbaar of uitgeschakeld")
            return
        power_w = call.data.get("power_w")
        await zb.async_set_charge(power_w=float(power_w) if power_w else None)
        coordinator.async_update_listeners()

    async def zonneplan_battery_discharge(call: ServiceCall):
        """v1.21: Ontlaad de Nexus (Pad A: deliver_to_home slider / Pad B: manual_control)."""
        zb = getattr(coordinator, "_zonneplan_bridge", None)
        if not zb or not zb.is_available:
            _LOGGER.warning("ZonneplanBridge niet beschikbaar of uitgeschakeld")
            return
        power_w = call.data.get("power_w")
        await zb.async_set_discharge(power_w=float(power_w) if power_w else None)
        coordinator.async_update_listeners()

    async def zonneplan_set_mode(call: ServiceCall):
        """v1.21: Stel Batterijbesturingsmodus in (home_optimization/self_consumption/powerplay)."""
        zb = getattr(coordinator, "_zonneplan_bridge", None)
        if not zb or not zb.is_available:
            _LOGGER.warning("ZonneplanBridge niet beschikbaar of uitgeschakeld")
            return
        mode      = call.data.get("mode", "")
        deliver_w = call.data.get("deliver_to_home_w")
        solar_w   = call.data.get("solar_charge_w")
        if mode == "home_optimization":
            await zb.async_set_home_optimization(
                deliver_w = float(deliver_w) if deliver_w is not None else None,
                solar_w   = float(solar_w)   if solar_w   is not None else None,
            )
        elif mode == "self_consumption":
            await zb.async_set_self_consumption()
        elif mode == "powerplay":
            await zb.async_set_powerplay()
        else:
            await zb.async_set_mode(mode)
        coordinator.async_update_listeners()

    async def zonneplan_battery_auto(call: ServiceCall):
        """v2.1: Herstel automatisch beheer (opgeslagen modus of Powerplay)."""
        zb = getattr(coordinator, "_zonneplan_bridge", None)
        if not zb:
            return
        await zb.async_set_auto()
        coordinator.async_update_listeners()

    async def zonneplan_apply_forecast(call: ServiceCall):
        """
        v2.1: Voer forecast-beslissing uit op basis van tariefgroep + 8-uurs forecast.
        CloudEMS bepaalt automatisch laden/ontladen/hold/powerplay.
        Houdt rekening met anti-rondpompen en EV-blokker.
        """
        zb = getattr(coordinator, "_zonneplan_bridge", None)
        if not zb or not zb.is_available:
            _LOGGER.warning("ZonneplanBridge niet beschikbaar of uitgeschakeld")
            return
        action = await zb.async_apply_forecast_decision()
        _LOGGER.info("zonneplan_apply_forecast: actie=%s", action)
        coordinator.async_update_listeners()

    _zp_power_schema = vol.Schema({vol.Optional("power_w"): vol.Coerce(float)})
    _zp_mode_schema  = vol.Schema({
        vol.Required("mode"): vol.In(["home_optimization", "self_consumption", "powerplay"]),
        vol.Optional("deliver_to_home_w"): vol.Coerce(float),
        vol.Optional("solar_charge_w"):    vol.Coerce(float),
    })

    hass.services.async_register(DOMAIN, "zonneplan_battery_charge",    zonneplan_battery_charge,
        schema=_zp_power_schema)
    hass.services.async_register(DOMAIN, "zonneplan_battery_discharge",  zonneplan_battery_discharge,
        schema=_zp_power_schema)
    hass.services.async_register(DOMAIN, "zonneplan_set_mode",           zonneplan_set_mode,
        schema=_zp_mode_schema)
    hass.services.async_register(DOMAIN, "zonneplan_battery_auto",       zonneplan_battery_auto)
    hass.services.async_register(DOMAIN, "zonneplan_apply_forecast",     zonneplan_apply_forecast)
    hass.services.async_register(DOMAIN, "set_phase_max_current",  set_phase_max_current)
    hass.services.async_register(DOMAIN, "force_price_update",     force_price_update)
    hass.services.async_register(DOMAIN, "generate_report",        generate_report)
    hass.services.async_register(DOMAIN, "download_energy_report", download_energy_report,
        schema=vol.Schema({vol.Optional("month", default=""): str}))
    hass.services.async_register(DOMAIN, "boiler_override",        boiler_override)

    # v2.1: reset leerdata leveringsboiler-detectie
    async def reset_delivery_learning(call: ServiceCall):
        group_id = call.data.get("group_id") or None
        if coordinator._boiler_ctrl:
            coordinator._boiler_ctrl.reset_delivery_learning(group_id)
            coordinator.async_update_listeners()
            _LOGGER.info("CloudEMS: leveringsboiler leerdata gewist (group=%s)", group_id or "alle")

    hass.services.async_register(DOMAIN, "reset_delivery_learning",
        reset_delivery_learning,
        schema=vol.Schema({vol.Optional("group_id", default=""): str}))

    # v4.5.126: dump probe diagnostieklog naar bestand + notificatie
    async def dump_probe_log(call):
        import os as _os
        zb = getattr(coordinator, "_zonneplan_bridge", None)
        if not zb:
            await hass.services.async_call("persistent_notification", "create",
                {"title": "CloudEMS — Probe log",
                 "message": "Geen Zonneplan bridge actief.",
                 "notification_id": "cloudems_probe_log"}, blocking=False)
            return
        log_entries = []  # probe verwijderd — slider maxima uit HA attribuut
        if not log_entries:
            msg = "Probe log is leeg — start eerst 'Slider max leren' via de CloudEMS knoppen."
        else:
            lines = [f"[{e['ts']}] {e['level']:7s} {e['msg']}" for e in log_entries]
            msg = "\n".join(lines)
        # Schrijf naar /config
        try:
            log_path = _os.path.join(hass.config.config_dir, "cloudems_probe_log.txt")
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(f"CloudEMS Probe Diagnostieklog\n{'='*60}\n{msg}\n")
            file_msg = f"\n\n✅ Ook opgeslagen in: `{log_path}`"
        except Exception as exc:
            file_msg = f"\n\n⚠️ Bestand schrijven mislukt: {exc}"
        await hass.services.async_call("persistent_notification", "create",
            {"title": "CloudEMS — Probe diagnostieklog",
             "message": f"```\n{msg[-3000:]}\n```{file_msg}",
             "notification_id": "cloudems_probe_log"}, blocking=False)
        _LOGGER.info("CloudEMS probe log gedumpt (%d regels)", len(log_entries))

    hass.services.async_register(DOMAIN, "dump_probe_log", dump_probe_log)

    # v3.1: handmatig diagnostisch rapport uploaden naar GitHub
    async def upload_diagnostic_report(call):
        guardian = getattr(coordinator, "_guardian", None)
        if not guardian:
            _LOGGER.warning("CloudEMS: Guardian niet actief — rapport niet verstuurd")
            return
        reporter = getattr(guardian, "_log_reporter", None)
        if not reporter:
            _LOGGER.warning("CloudEMS: geen github_log_token geconfigureerd")
            await hass.services.async_call("persistent_notification", "create",
                {"title": "CloudEMS — Geen GitHub token",
                 "message": "Stel github_log_token in via de CloudEMS wizard (Diagnostics stap).",
                 "notification_id": "cloudems_no_github_token"}, blocking=False)
            return
        try:
            data = coordinator.data or {}
            report = await reporter.async_build_report(data, guardian.get_status(), "manual")
            url = await reporter.async_submit(report, auto=False)
            msg = f"Rapport aangemaakt: {url}" if url else "Versturen mislukt — zie HA logs"
            await hass.services.async_call("persistent_notification", "create",
                {"title": "✅ CloudEMS rapport" if url else "⚠️ CloudEMS rapport mislukt",
                 "message": msg, "notification_id": "cloudems_report_sent"}, blocking=False)
        except Exception as _e:
            _LOGGER.error("CloudEMS rapport upload fout: %s", _e)

    hass.services.async_register(DOMAIN, "upload_diagnostic_report", upload_diagnostic_report)

    # v2.6: slaapstand in/uitschakelen
    async def set_sleep_detector(call: ServiceCall):
        enabled = call.data.get("enabled", True)
        if hasattr(coordinator, "_sleep_detector"):
            coordinator._sleep_detector.set_enabled(enabled)
            coordinator.async_update_listeners()

    hass.services.async_register(DOMAIN, "set_sleep_detector",
        set_sleep_detector,
        schema=vol.Schema({vol.Required("enabled"): bool}))

    # v2.6: genereer HA automation blueprints
    async def generate_blueprints(call: ServiceCall):
        if not hasattr(coordinator, "_blueprint_gen"):
            return
        try:
            nilm_devs = (coordinator.data or {}).get("nilm_devices", [])
            files = await coordinator._blueprint_gen.async_generate_all(nilm_devs)
            from homeassistant.components.persistent_notification import async_create as _pn
            _pn(hass,
                message=f"✅ {len(files)} blueprints gegenereerd in `/config/blueprints/automation/cloudems/`:\n\n"
                        + "\n".join(f"• {f}" for f in files),
                title="CloudEMS Blueprints",
                notification_id="cloudems_blueprints_done")
        except Exception as err:
            _LOGGER.error("Blueprint generatie mislukt: %s", err)

    hass.services.async_register(DOMAIN, "generate_blueprints", generate_blueprints)

    # v2.6: zone klimaat services
    async def set_zone_preset(call: ServiceCall):
        """Stel handmatig een preset in voor een zone.
        Parameters:
          area_id: HA area id of zone naam
          preset:  comfort / eco / boost / sleep / away / solar
          hours:   hoe lang (default 4)
        """
        zm = getattr(coordinator, "_zone_climate", None)
        if zm:
            zm.set_override(
                call.data.get("area_id", ""),
                call.data.get("preset", "comfort"),
                float(call.data.get("hours", 4)),
            )
    hass.services.async_register(DOMAIN, "set_zone_preset", set_zone_preset,
        schema=vol.Schema({
            vol.Required("area_id"):                str,
            vol.Required("preset"):                 vol.In(["comfort","eco","boost","sleep","away","solar"]),
            vol.Optional("hours", default=4):       vol.All(vol.Coerce(float), vol.Range(min=0.5, max=24)),
        }))

    async def set_zone_schedule(call: ServiceCall):
        """Stel het weekschema in voor een zone.
        Parameters:
          area_id:  HA area id of zone naam
          schedule: lijst van {weekdays:[0-6], time:"HH:MM", preset:"comfort"}
        """
        zm = getattr(coordinator, "_zone_climate", None)
        if zm:
            zm.set_schedule(call.data.get("area_id", ""), call.data.get("schedule", []))
    hass.services.async_register(DOMAIN, "set_zone_schedule", set_zone_schedule,
        schema=vol.Schema({
            vol.Required("area_id"): str,
            vol.Required("schedule"): list,
        }))

    async def set_zone_temperature(call: ServiceCall):
        """Stel de preset-temperatuur in voor een zone.
        Parameters:
          area_id:  HA area id of zone naam
          preset:   comfort / eco / boost / sleep / away / solar
          temp:     doeltemperatuur in graden Celsius
        """
        zm = getattr(coordinator, "_zone_climate", None)
        if zm:
            zm.set_temp(
                call.data.get("area_id", ""),
                call.data.get("preset", "comfort"),
                float(call.data.get("temp", 20.0)),
            )
    hass.services.async_register(DOMAIN, "set_zone_temperature", set_zone_temperature,
        schema=vol.Schema({
            vol.Required("area_id"): str,
            vol.Required("preset"):  vol.In(["comfort","eco","boost","sleep","away","solar"]),
            vol.Required("temp"):    vol.All(vol.Coerce(float), vol.Range(min=5, max=30)),
        }))

    async def configure_zone(call: ServiceCall):
        """Configureer een zone: kachel-sensor, raam-sensor, aanwezigheid, schema.

        Parameters:
          zone_name         : naam van de zone (bijv. "woonkamer")
          stove_sensor      : entity_id van kachel-nabij temperatuursensor (optioneel)
          window_sensor     : entity_id van raam binary_sensor (optioneel)
          presence_sensor   : entity_id van aanwezigheids-sensor (optioneel)
          schedule          : lijst van {weekdays:[0-6], time:"HH:MM", preset:"comfort"}
          heating_type      : "cv" | "airco" | "both"
          has_wood_stove    : true/false — geeft aan dat er een houtkachel in deze zone is
        """
        sm = getattr(coordinator, "_smart_climate", None)
        if not sm:
            return
        zone_name = call.data.get("zone_name", "")
        zone = sm.get_zone(zone_name)
        if not zone:
            _LOGGER.warning("configure_zone: zone '%s' niet gevonden", zone_name)
            return

        if "stove_sensor" in call.data:
            if zone._stove:
                zone._stove._sensor = call.data["stove_sensor"]
            elif call.data.get("has_wood_stove") or zone._has_stove:
                from .energy_manager.smart_climate import WoodStoveDetector
                zone._stove = WoodStoveDetector(call.data["stove_sensor"])
                zone._has_stove = True

        if "has_wood_stove" in call.data:
            zone._has_stove = bool(call.data["has_wood_stove"])
            if zone._has_stove and not zone._stove:
                from .energy_manager.smart_climate import WoodStoveDetector
                zone._stove = WoodStoveDetector(call.data.get("stove_sensor"))

        if "window_sensor" in call.data:
            zone._window_sensor = call.data["window_sensor"]
        if "presence_sensor" in call.data:
            zone._presence_sensor = call.data["presence_sensor"]
        if "heating_type" in call.data:
            zone._heating_type = call.data["heating_type"]
        if "schedule" in call.data:
            zone.set_schedule(call.data["schedule"])

        _LOGGER.info("configure_zone: zone '%s' bijgewerkt", zone_name)

    hass.services.async_register(DOMAIN, "configure_zone", configure_zone,
        schema=vol.Schema({
            vol.Required("zone_name"):                   str,
            vol.Optional("stove_sensor"):                str,
            vol.Optional("window_sensor"):               str,
            vol.Optional("presence_sensor"):             str,
            vol.Optional("heating_type"):
                vol.In(["cv", "airco", "both"]),
            vol.Optional("has_wood_stove"):              bool,
            vol.Optional("schedule"):                    list,
        }))

    async def reset_drift_baseline(call: ServiceCall):
        """Reset the drift baseline for a device (e.g. after replacement).
        
        Parameters:
          device_id (optional): specific device id to reset. If omitted, resets ALL devices.
        """
        tracker = getattr(coordinator, "_device_drift", None)
        if not tracker:
            _LOGGER.warning("CloudEMS reset_drift_baseline: drift tracker not initialised")
            return
        device_id = call.data.get("device_id")
        if device_id:
            tracker._profiles.pop(device_id, None)
            _LOGGER.info("CloudEMS: drift baseline reset for device '%s'", device_id)
        else:
            tracker._profiles.clear()
            _LOGGER.info("CloudEMS: ALL drift baselines reset")
        tracker._dirty = True
        await tracker.async_maybe_save()

    async def mute_alert(call: ServiceCall):
        """Mute a CloudEMS alert by its key (suppresses for 24h).
        
        Parameters:
          alert_key: the alert key, e.g. 'device_drift:my_device_id'
        """
        engine = getattr(coordinator, "_notification_engine", None)
        if not engine:
            return
        key = call.data.get("alert_key", "")
        if key:
            engine.mute(key)
            _LOGGER.info("CloudEMS: alert '%s' muted", key)

    hass.services.async_register(DOMAIN, "reset_drift_baseline",   reset_drift_baseline)
    hass.services.async_register(DOMAIN, "mute_alert",             mute_alert)

    # ── reset_pv_orientation: wis geleerde azimuth/tilt voor één of alle omvormers ─
    async def reset_pv_orientation(call: ServiceCall) -> None:
        """Reset the learned orientation (azimuth/tilt) for one or all inverters.

        Parameters:
          inverter_id: (optional) entity_id of the inverter to reset.
                       If omitted, ALL inverters are reset.
        """
        pv = getattr(coordinator, "_pv_forecast", None)
        if not pv:
            _LOGGER.warning("CloudEMS reset_pv_orientation: PVForecast module not active.")
            return
        target_id = call.data.get("inverter_id") or None
        reset_count = 0
        for eid, profile in pv._profiles.items():
            if target_id and eid != target_id:
                continue
            profile.learned_azimuth       = None
            profile.learned_tilt          = None
            profile.orientation_confident = False
            profile.clear_sky_samples     = 0
            profile.hourly_yield_fraction = {}
            profile._drift_az_votes       = 0
            profile._drift_tilt_votes     = 0
            profile._prev_learned_az      = None
            reset_count += 1
        pv._dirty = True
        await pv.async_save()
        _LOGGER.info(
            "CloudEMS reset_pv_orientation: %d omvormer(s) gereset%s.",
            reset_count, f" (filter: {target_id})" if target_id else "",
        )

    hass.services.async_register(
        DOMAIN, "reset_pv_orientation", reset_pv_orientation,
        schema=vol.Schema({vol.Optional("inverter_id"): str}),
    )

    # ── v1.22: NILM cleanup service ───────────────────────────────────────────

    async def cleanup_nilm(call: ServiceCall) -> None:
        """
        Ruim NILM-data op.

        scope:
          full        — verwijder ALLE apparaten, reset alles (schone start)
          devices     — verwijder apparaten die langer dan `days` dagen niet gezien zijn
          energy      — reset alle energietellers (kWh)
          last_x_days — verwijder onbevestigde apparaten van de laatste `days` dagen
          week        — reset week-kWh tellers
          month       — reset maand-kWh tellers
          year        — reset jaar-kWh tellers
        """
        scope = call.data.get("scope", "full")
        days  = int(call.data.get("days", 0))

        result = coordinator.nilm.cleanup(scope=scope, days=days)

        # Direct opslaan zodat de cleanup ook na herstart bewaard blijft
        await coordinator.nilm.async_save()

        # scope=full: ook device_drift wissen zodat de tabel leeg is na schone start
        if scope == "full":
            drift = getattr(coordinator, "_device_drift", None)
            if drift is not None:
                drift_count = await drift.async_clear_all()
                _LOGGER.info("CloudEMS cleanup FULL: %d drift-profielen gewist", drift_count)

        _LOGGER.info(
            "CloudEMS NILM cleanup uitgevoerd: scope=%s days=%d "
            "→ %d verwijderd, %d gereset, %d resterend",
            result["scope"], result["days"],
            result["removed_devices"], result["reset_energy"],
            result["devices_remaining"],
        )

    hass.services.async_register(DOMAIN, "cleanup_nilm", cleanup_nilm)

    async def clear_drift_profiles(call: ServiceCall):
        """Wis drift-profielen — optioneel gefilterd op device_type.

        Handig na firmware-update of na het verwijderen van een verkeerd
        gedetecteerd apparaat (bijv. cirkelzaag). Zonder filter: alles weg.

        Gebruik:
          cloudems.clear_drift_profiles              # alles wissen
          cloudems.clear_drift_profiles
            device_type: power_tool                  # alleen gereedschap
        """
        drift = getattr(coordinator, "_device_drift", None)
        if drift is None:
            return
        filter_type = call.data.get("device_type", "").strip().lower()
        if filter_type:
            # Verwijder alleen profielen van het opgegeven device_type
            to_delete = [
                did for did, p in drift._profiles.items()
                if p.device_type.lower() == filter_type
            ]
            for did in to_delete:
                del drift._profiles[did]
            drift._dirty = True
            await drift.async_maybe_save()
            _LOGGER.info(
                "CloudEMS: %d drift-profiel(en) van type '%s' gewist",
                len(to_delete), filter_type,
            )
        else:
            count = await drift.async_clear_all()
            _LOGGER.info("CloudEMS: alle %d drift-profielen gewist", count)

    hass.services.async_register(DOMAIN, "clear_drift_profiles", clear_drift_profiles)


    async def nilm_device_profile(call: ServiceCall) -> None:
        """
        v3.6.0: Geeft het geleerde vermogensprofiel van een NILM-apparaat terug
        als persistent notification in HA.

        Parameters:
          device_id: ID van het apparaat (optioneel — zonder ID: alle profielen)
        """
        device_id = call.data.get("device_id", "")
        nilm = getattr(coordinator, "_nilm_detector", None)
        if nilm is None:
            _LOGGER.warning("nilm_device_profile: NILM niet beschikbaar")
            return

        if device_id:
            profile = nilm.get_device_profile(device_id)
            if profile is None:
                title   = f"NILM Profiel: {device_id}"
                message = "Geen profiel gevonden voor dit apparaat."
            else:
                pp = profile.get("power_profile", {})
                title = f"NILM Profiel: {profile.get('name', device_id)}"
                lines = [
                    f"**Type:** {profile.get('device_type','?')}",
                    f"**Fase:** {profile.get('phase','?')}",
                    f"**Vermogen (geleerd):** {pp.get('mean_w','?')} W ± {pp.get('std_w','?')} W",
                    f"**Min/Max gezien:** {pp.get('min_w','?')} / {pp.get('max_w','?')} W",
                    f"**Observaties:** {pp.get('n_samples',0)}",
                    f"**Profiel klaar:** {'ja' if pp.get('is_ready') else 'nee'}",
                    f"**Cycling:** {'ja' if pp.get('is_cycling') else 'nee'} "
                    f"(duty cycle: {round(pp.get('learned_duty_cycle',0)*100)}%)",
                    f"**Sessies:** {pp.get('session_count',0)}",
                    f"**Confirm streak:** {pp.get('confirm_streak',0)}",
                    f"**Confidence:** {round(profile.get('confidence',0)*100)}%",
                    f"**Bevestigd:** {'ja' if profile.get('confirmed') else 'nee'}",
                ]
                if pp.get("anomaly_flag"):
                    lines.append(f"⚠️ **Energie-anomalie:** {pp.get('anomaly_reason','')}")
                message = "\n".join(lines)
        else:
            profiles = nilm.get_all_device_profiles()
            if not profiles:
                title   = "NILM Profielen"
                message = "Geen geleerde profielen beschikbaar."
            else:
                title = f"NILM Profielen ({len(profiles)} apparaten)"
                rows = []
                for did, pp in sorted(profiles.items(),
                                      key=lambda x: -x[1].get("n_samples", 0)):
                    dev = nilm.get_device(did)
                    name = dev.display_name if dev else did
                    rows.append(
                        f"- **{name}**: {pp.get('mean_w','?')}W±{pp.get('std_w','?')}W "
                        f"(n={pp.get('n_samples',0)}, "
                        f"cycling={'ja' if pp.get('is_cycling') else 'nee'})"
                    )
                message = "\n".join(rows)

        hass.components.persistent_notification.async_create(
            message, title=title, notification_id="cloudems_nilm_profile"
        )
        _LOGGER.info("nilm_device_profile: %s", title)

    hass.services.async_register(
        DOMAIN, "nilm_device_profile", nilm_device_profile,
        schema=vol.Schema({vol.Optional("device_id", default=""): str}),
    )


    async def send_test_mail(call: ServiceCall) -> None:
        """Stuur een testmail om SMTP-configuratie te verifieren.

        Parameters:
          recipient (optional): overschrijf het geconfigureerde ontvangstadres.
        """
        from .mail import CloudEMSMailer
        import datetime

        cfg = {**coordinator.config_entry.data, **coordinator.config_entry.options}
        recipient_override = call.data.get("recipient", "").strip()
        if recipient_override:
            cfg["mail_to"] = recipient_override

        mailer = CloudEMSMailer(hass, cfg)
        if not mailer.enabled and not recipient_override:
            _LOGGER.warning(
                "CloudEMS send_test_mail: e-mail niet ingeschakeld. "
                "Schakel in via Configureren → E-mail rapporten."
            )
            hass.components.persistent_notification.async_create(
                "📧 **CloudEMS testmail mislukt**\n\n"
                "E-mail is niet ingeschakeld. Ga naar **Configureren → E-mail rapporten** "
                "en schakel e-mail in.",
                title="CloudEMS",
                notification_id="cloudems_mail_test",
            )
            return

        now_str = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
        subject = f"✅ CloudEMS testmail — {now_str}"
        body = (
            f"Dit is een testmail van CloudEMS.\n\n"
            f"Als je dit bericht ontvangt, is je SMTP-configuratie correct ingesteld.\n\n"
            f"Instellingen gebruikt:\n"
            f"  Server : {cfg.get('mail_host', '?')}\n"
            f"  Poort  : {cfg.get('mail_port', 587)}\n"
            f"  TLS    : {'ja' if cfg.get('mail_use_tls', True) else 'nee'}\n"
            f"  Van    : {cfg.get('mail_from') or cfg.get('mail_username', '?')}\n"
            f"  Naar   : {cfg.get('mail_to', '?')}\n\n"
            f"— CloudEMS {now_str}"
        )
        ok, err_msg = await mailer.async_test_connection()
        if not ok:
            _LOGGER.error("CloudEMS send_test_mail: verbindingstest mislukt: %s", err_msg)
            hass.components.persistent_notification.async_create(
                f"📧 **CloudEMS testmail mislukt**\n\n"
                f"Kan geen verbinding maken met de mailserver.\n\n"
                f"**Fout:** `{err_msg}`\n\n"
                f"Controleer server, poort en inloggegevens via "
                f"**Configureren → E-mail rapporten**.",
                title="CloudEMS",
                notification_id="cloudems_mail_test",
            )
            return

        success = await mailer._async_send(subject, body, None, None)
        if success:
            _LOGGER.info("CloudEMS send_test_mail: testmail verstuurd naar %s", cfg.get("mail_to"))
            hass.components.persistent_notification.async_create(
                f"📧 **CloudEMS testmail verstuurd**\n\n"
                f"Testmail succesvol verstuurd naar **{cfg.get('mail_to', '?')}**.\n\n"
                f"Controleer je inbox (en spam-map).",
                title="CloudEMS",
                notification_id="cloudems_mail_test",
            )
        else:
            hass.components.persistent_notification.async_create(
                f"📧 **CloudEMS testmail mislukt**\n\n"
                f"Verbinding geslaagd maar versturen mislukt. Controleer de logs voor details.",
                title="CloudEMS",
                notification_id="cloudems_mail_test",
            )

    hass.services.async_register(
        DOMAIN,
        "send_test_mail",
        send_test_mail,
        schema=vol.Schema({
            vol.Optional("recipient"): str,
        }),
    )

    # ── v1.25: Fase-detectie via dim-puls ────────────────────────────────────

    async def trigger_phase_probe(call: ServiceCall) -> None:
        """Herstart actieve fase-detectie voor één of alle omvormers."""
        mgr = getattr(coordinator, "_multi_inv_manager", None)
        if mgr is None:
            _LOGGER.warning("CloudEMS trigger_phase_probe: geen MultiInverterManager actief")
            return
        inverter_eid = call.data.get("inverter_entity_id")
        mgr.trigger_phase_probe(inverter_id=inverter_eid or None)

    hass.services.async_register(DOMAIN, "trigger_phase_probe", trigger_phase_probe)

    # ── v2.6: Fase-detectie resetten (zonder MultiInverterManager) ─────────

    async def reset_phase_detection(call: ServiceCall) -> None:
        """Reset fase-detectie voor één of alle omvormers zodat ze opnieuw leren.

        Optioneel: force_three_phase=true slaat direct 3F op zonder stemmen te wachten.
        Dit is handig als je zeker weet dat een omvormer 3-fasig is maar de detectie
        vastzit op een verkeerde fase.
        """
        sl = getattr(coordinator, "_solar_learner", None)
        if sl is None:
            _LOGGER.warning("reset_phase_detection: geen SolarLearner actief")
            return

        inverter_eid   = call.data.get("inverter_entity_id")
        force_3phase   = bool(call.data.get("force_three_phase", False))
        targets        = [inverter_eid] if inverter_eid else list(sl._profiles.keys())

        for eid in targets:
            if eid not in sl._profiles:
                _LOGGER.warning("reset_phase_detection: onbekende omvormer '%s'", eid)
                continue
            p = sl._profiles[eid]
            label = p.label
            if force_3phase:
                # Direct als 3-fasig markeren — gebruiker weet het zeker
                p.is_three_phase            = True
                p.phase_certain             = True
                p.detected_phase            = "3F"
                p.three_phase_votes         = THREE_PHASE_MIN_DETECTIONS
                p.phase_votes               = {}
                p._votes_obj                = None
                p.phase_post_votes          = {}
                p._post_votes_obj           = None
                p.phase_conflict_pct        = 0.0
                p._peak_over_single_phase_s = 0.0
                _LOGGER.warning(
                    "reset_phase_detection [%s]: DIRECT als 3-fasig ingesteld (force)", label
                )
            else:
                # Zachte reset: wis stemmen zodat detectie opnieuw begint
                p.phase_certain             = False
                p.detected_phase            = None
                p.is_three_phase            = False
                p.three_phase_votes         = 0
                p.phase_votes               = {}
                p._votes_obj                = None
                p.phase_post_votes          = {}
                p._post_votes_obj           = None
                p.phase_conflict_pct        = 0.0
                p._peak_over_single_phase_s = 0.0
                _LOGGER.info(
                    "reset_phase_detection [%s]: fase-detectie gereset, opnieuw leren", label
                )
            sl._dirty = True

        await sl._async_save()

        # Start ook de probe-cyclus als MultiInverterManager beschikbaar is
        mgr = getattr(coordinator, "_multi_inv_manager", None)
        if mgr and not force_3phase:
            for eid in targets:
                mgr.trigger_phase_probe(inverter_id=eid)
            _LOGGER.info("reset_phase_detection: probe-cyclus gestart voor %s", targets)

    try:
        from .energy_manager.solar_learner import THREE_PHASE_MIN_DETECTIONS
    except ImportError:
        THREE_PHASE_MIN_DETECTIONS = 4

    hass.services.async_register(
        DOMAIN,
        "reset_phase_detection",
        reset_phase_detection,
        schema=vol.Schema({
            vol.Optional("inverter_entity_id"): str,
            vol.Optional("force_three_phase", default=False): bool,
        }),
    )

    # ── v1.18.1: Nieuwe services ──────────────────────────────────────────────

    async def export_learning_data(call: ServiceCall) -> None:
        """
        Exporteer alle geleerde data naar /config/cloudems_export.json.
        Gebruik bij HA-migratie of nieuwe installatie om opnieuw te beginnen.
        """
        import json, os, time as _time
        export = {
            "version":   VERSION,
            "exported":  _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "modules":   {},
        }
        sl = getattr(coordinator, "_solar_learner", None)
        if sl:
            export["modules"]["solar_learner"] = sl._build_save_data()

        pv = getattr(coordinator, "_pv_forecast", None)
        if pv:
            pv_data = {}
            for eid, p in pv._profiles.items():
                pv_data[eid] = {
                    "learned_azimuth":       p.learned_azimuth,
                    "learned_tilt":          p.learned_tilt,
                    "orientation_confident": p.orientation_confident,
                    "clear_sky_samples":     p.clear_sky_samples,
                    "hourly_yield_fraction": p.hourly_yield_fraction,
                    "peak_wp":               p._peak_wp,
                }
            export["modules"]["pv_forecast"] = pv_data

        path = os.path.join(hass.config.config_dir, "cloudems_export.json")
        try:
            def _write():
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(export, f, indent=2, default=str)
            await hass.async_add_executor_job(_write)
            _LOGGER.info("CloudEMS: leerdata geëxporteerd naar %s", path)
            from homeassistant.components.persistent_notification import async_create
            async_create(hass, f"Leerdata opgeslagen in `{path}`",
                         title="CloudEMS Export", notification_id="cloudems_export")
        except Exception as exc:
            _LOGGER.error("CloudEMS export mislukt: %s", exc)

    async def import_learning_data(call: ServiceCall) -> None:
        """
        Importeer eerder geëxporteerde leerdata.
        Parameters:
          path (optional): pad naar het JSON-bestand (default: /config/cloudems_export.json)
        """
        import json, os
        path = call.data.get("path") or os.path.join(hass.config.config_dir, "cloudems_export.json")
        try:
            def _read():
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            export = await hass.async_add_executor_job(_read)
        except Exception as exc:
            _LOGGER.error("CloudEMS import lezen mislukt (%s): %s", path, exc)
            return

        modules = export.get("modules", {})
        imported = []

        sl = getattr(coordinator, "_solar_learner", None)
        if sl and "solar_learner" in modules:
            store_data = modules["solar_learner"]
            await sl._store.async_save(store_data)
            await sl.async_setup(backup=getattr(coordinator, "_learning_backup", None))
            imported.append("solar_learner")

        pv = getattr(coordinator, "_pv_forecast", None)
        if pv and "pv_forecast" in modules:
            await pv._store.async_save(modules["pv_forecast"])
            await pv.async_setup(backup=getattr(coordinator, "_learning_backup", None))
            imported.append("pv_forecast")

        _LOGGER.info("CloudEMS import: %s geladen uit %s", imported, path)
        from homeassistant.components.persistent_notification import async_create
        async_create(hass,
            f"Leerdata hersteld: {', '.join(imported)} (uit `{path}`)",
            title="CloudEMS Import", notification_id="cloudems_import")

    async def register_isolation_investment(call: ServiceCall) -> None:
        """Registreer een isolatie-investering voor gasverbruikstracking."""
        gas = getattr(coordinator, "_gas_analysis", None)
        if gas:
            gas.register_isolation_investment(call.data.get("date", ""))
            _LOGGER.info("CloudEMS: isolatie-investering geregistreerd")

    async def health_check(call: ServiceCall) -> None:
        """Log de status van alle zelflerende modules als persistent_notification."""
        lines = ["## 🩺 CloudEMS Health Check", ""]
        mods = {
            "solar_learner":   getattr(coordinator, "_solar_learner", None),
            "pv_forecast":     getattr(coordinator, "_pv_forecast", None),
            "battery_degrad":  getattr(coordinator, "_battery_degradation", None),
            "thermal_model":   getattr(coordinator, "_thermal_model", None),
            "hp_cop":          getattr(coordinator, "_hp_cop", None),
            "gas_analysis":    getattr(coordinator, "_gas_analysis", None),
            "clipping_loss":   getattr(coordinator, "_clipping_loss", None),
            "shadow_detect":   getattr(coordinator, "_shadow_detector", None),
            "device_drift":    getattr(coordinator, "_device_drift", None),
            "pv_health":       getattr(coordinator, "_pv_health", None),
            "pv_accuracy":     getattr(coordinator, "_pv_accuracy", None),
            "cost_forecaster": getattr(coordinator, "_cost_forecaster", None),
        }
        for name, mod in mods.items():
            if mod is None:
                lines.append(f"- ⬜ **{name}**: niet actief")
            else:
                dirty = getattr(mod, "_dirty", None)
                last  = getattr(mod, "_last_save", None)
                import time as _t
                age   = f"{int((_t.time() - last) / 60)}m geleden" if last else "?"
                lines.append(f"- ✅ **{name}**: actief | dirty={dirty} | opgeslagen: {age}")

        from homeassistant.components.persistent_notification import async_create
        async_create(hass, "\n".join(lines), title="CloudEMS Health", notification_id="cloudems_health")
        _LOGGER.info("CloudEMS health check uitgevoerd")

    hass.services.async_register(DOMAIN, "export_learning_data",         export_learning_data)
    hass.services.async_register(DOMAIN, "import_learning_data",         import_learning_data)
    hass.services.async_register(DOMAIN, "register_isolation_investment", register_isolation_investment)
    hass.services.async_register(DOMAIN, "health_check",                 health_check)

    # ── v1.25.9: Lampcirculatie services ──────────────────────────────────────

    async def lamp_circulation_test(call: ServiceCall) -> None:
        """Start testmodus: lampcirculatie draait 2 min ongeacht afwezigheid."""
        lc = coordinator._lamp_circulation
        if lc:
            msg = await lc.async_start_test()
            _LOGGER.info("CloudEMS lamp_circulation_test: %s", msg)
        else:
            _LOGGER.warning("CloudEMS lamp_circulation_test: geen lampen geconfigureerd")

    async def lamp_circulation_stop_test(call: ServiceCall) -> None:
        """Stop testmodus voortijdig."""
        lc = coordinator._lamp_circulation
        if lc:
            await lc.async_stop_test()

    async def lamp_circulation_set_enabled(call: ServiceCall) -> None:
        """Schakel lampcirculatie in of uit via dashboard-knop."""
        lc = coordinator._lamp_circulation
        if lc:
            enabled = bool(call.data.get("enabled", True))
            lc.set_enabled(enabled)
            _LOGGER.info("CloudEMS lamp_circulation_set_enabled: %s", enabled)

            # Persisteer naar coordinator._config zodat lazy-discovery + configure()
            # de instelling NIET terugzetten naar True bij de volgende coordinator-tick.
            lamp_cfg = coordinator._config.setdefault("lamp_circulation", {})
            lamp_cfg["enabled"] = enabled

            # Persisteer naar HA config entry zodat de instelling overleeft bij herstart.
            try:
                new_options = dict(entry.options)
                lc_opts = dict(new_options.get("lamp_circulation", {}))
                lc_opts["enabled"] = enabled
                new_options["lamp_circulation"] = lc_opts
                hass.config_entries.async_update_entry(entry, options=new_options)
            except Exception as _pe:
                _LOGGER.warning("CloudEMS: lamp_circulation enabled persisteren mislukt: %s", _pe)
        else:
            _LOGGER.warning("CloudEMS lamp_circulation_set_enabled: geen lampen geconfigureerd")

    hass.services.async_register(DOMAIN, "lamp_circulation_test",        lamp_circulation_test)
    hass.services.async_register(DOMAIN, "lamp_circulation_stop_test",   lamp_circulation_stop_test)
    hass.services.async_register(DOMAIN, "lamp_circulation_set_enabled", lamp_circulation_set_enabled)

    # v3.5.3: Test-mode simulator services
    async def simulator_set(call: ServiceCall):
        """Activeer de testmodus met gesimuleerde sensorwaarden."""
        overrides = {k: v for k, v in call.data.items() if k not in ("timeout_min", "note", "zone_temps", "stove_temps")}
        timeout_min = int(call.data.get("timeout_min", 30))
        note        = str(call.data.get("note", ""))
        zone_temps  = dict(call.data.get("zone_temps") or {})
        stove_temps = dict(call.data.get("stove_temps") or {})
        coordinator._simulator.activate(
            overrides, zone_temps=zone_temps, stove_temps=stove_temps,
            timeout_min=timeout_min, note=note,
        )
        await coordinator.async_request_refresh()

    async def simulator_clear(call: ServiceCall):
        """Stop de testmodus en herstel live sensorwaarden."""
        coordinator._simulator.deactivate("handmatig via service")
        await coordinator.async_request_refresh()

    async def simulator_zone_temp(call: ServiceCall):
        """Update één zone-temperatuur terwijl simulator actief is."""
        zone   = str(call.data["zone"])
        temp_c = float(call.data["temp_c"])
        coordinator._simulator.update_zone_temp(zone, temp_c)
        await coordinator.async_request_refresh()

    async def simulator_stove_temp(call: ServiceCall):
        """Update één houtkachel-temperatuur terwijl simulator actief is."""
        zone   = str(call.data["zone"])
        temp_c = float(call.data["temp_c"])
        coordinator._simulator.update_stove_temp(zone, temp_c)
        await coordinator.async_request_refresh()

    # v3.9: VTherm Central Mode + Timed Preset als CloudEMS services
    async def vtherm_set_central_mode(call: ServiceCall):
        """Stuur alle VTherm-thermostaten via Central Mode.
        Gebruik: cloudems.vtherm_set_central_mode hvac_mode=heat|eco|away|off
        """
        hvac_mode = call.data.get("hvac_mode", "heat")
        sc = getattr(coordinator, "_smart_climate", None)
        vbridge = getattr(sc, "_vtherm_bridge", None) if sc else None
        if not vbridge:
            _LOGGER.warning("vtherm_set_central_mode: VThermBridge niet beschikbaar")
            return
        ok = await vbridge.async_central_mode(hvac_mode)
        if ok:
            coordinator.async_update_listeners()

    async def vtherm_set_timed_preset(call: ServiceCall):
        """Zet zone tijdelijk op een preset (keert na duration_min terug).
        Gebruik: cloudems.vtherm_set_timed_preset zone=Woonkamer preset=comfort duration_min=60
        """
        zone_name    = call.data.get("zone", "")
        preset       = call.data.get("preset", "eco")
        duration_min = int(call.data.get("duration_min", 60))
        sc = getattr(coordinator, "_smart_climate", None)
        vbridge = getattr(sc, "_vtherm_bridge", None) if sc else None
        if not vbridge or not zone_name:
            _LOGGER.warning("vtherm_set_timed_preset: VThermBridge niet beschikbaar of geen zone")
            return
        # Zoek entity_ids voor de zone
        entity_ids = []
        for zone in getattr(sc, "_zones", []):
            if zone.name.lower() == zone_name.lower():
                entity_ids = [e for e in zone._climate_entity_ids if e.startswith("climate.")]
                break
        if not entity_ids:
            _LOGGER.warning("vtherm_set_timed_preset: zone '%s' niet gevonden", zone_name)
            return
        applied = await vbridge.async_set_zone_timed_preset(
            zone_name, entity_ids, preset, duration_min
        )
        _LOGGER.info(
            "VTherm timed preset '%s' → zone '%s' (%d min): %s",
            preset, zone_name, duration_min, applied
        )
        if applied:
            coordinator.async_update_listeners()

    hass.services.async_register(
        DOMAIN, "vtherm_set_central_mode", vtherm_set_central_mode,
        schema=vol.Schema({vol.Required("hvac_mode"): str}),
    )
    hass.services.async_register(
        DOMAIN, "vtherm_set_timed_preset", vtherm_set_timed_preset,
        schema=vol.Schema({
            vol.Required("zone"):                     str,
            vol.Optional("preset",       default="eco"): str,
            vol.Optional("duration_min", default=60):    int,
        }),
    )

    hass.services.async_register(DOMAIN, "simulator_set",        simulator_set)
    hass.services.async_register(DOMAIN, "simulator_clear",      simulator_clear)
    hass.services.async_register(DOMAIN, "simulator_zone_temp",  simulator_zone_temp)
    hass.services.async_register(DOMAIN, "simulator_stove_temp", simulator_stove_temp)

    # v3.9: set_module_state — schakel CloudEMS modules in/uit via Guardian
    async def set_module_state(call: ServiceCall):
        """Schakel een CloudEMS module in of uit via de SystemGuardian.

        Gebruik: cloudems.set_module_state module=boiler enabled=false
        """
        module  = call.data.get("module", "").strip()
        enabled = bool(call.data.get("enabled", True))
        guardian = getattr(coordinator, "_guardian", None)
        if not guardian:
            _LOGGER.warning("set_module_state: Guardian niet beschikbaar")
            return
        if not module:
            _LOGGER.warning("set_module_state: geen module opgegeven")
            return
        if enabled:
            guardian.enable_module(module)
            _LOGGER.info("CloudEMS: module '%s' ingeschakeld via service", module)
        else:
            guardian.disable_module(module)
            _LOGGER.info("CloudEMS: module '%s' uitgeschakeld via service", module)
        coordinator.async_update_listeners()

    hass.services.async_register(
        DOMAIN, "set_module_state", set_module_state,
        schema=vol.Schema({
            vol.Required("module"):           str,
            vol.Optional("enabled", default=True): bool,
        }),
    )

    # ── Reset-services voor dashboard reset-knoppen ───────────────────────────

    async def reset_nilm(call: ServiceCall) -> None:
        """Reset alle NILM-leerdata — alias voor cleanup_nilm scope=full."""
        result = coordinator.nilm.cleanup(scope="full", days=0)
        await coordinator.nilm.async_save()
        drift = getattr(coordinator, "_device_drift", None)
        if drift is not None:
            await drift.async_clear_all()
        coordinator.async_update_listeners()
        _LOGGER.info(
            "CloudEMS reset_nilm: %d apparaten verwijderd, %d gereset",
            result.get("removed_devices", 0), result.get("reset_energy", 0),
        )

    hass.services.async_register(DOMAIN, "reset_nilm", reset_nilm)

    async def reset_presence(call: ServiceCall) -> None:
        """Reset het 7×24 aanwezigheidspatroon van de AbsenceDetector."""
        absence = getattr(coordinator, "_absence", None)
        if absence is None:
            _LOGGER.warning("CloudEMS reset_presence: AbsenceDetector niet actief")
            return
        # Reset interne state — verwijder geleerde blokken
        if hasattr(absence, "_pattern"):
            absence._pattern = {}
        if hasattr(absence, "_history"):
            absence._history = []
        if hasattr(absence, "_store") and absence._store is not None:
            await absence._store.async_save({})
        coordinator.async_update_listeners()
        _LOGGER.info("CloudEMS reset_presence: aanwezigheidspatroon gewist")

    hass.services.async_register(DOMAIN, "reset_presence", reset_presence)

    async def reset_all_learning(call: ServiceCall) -> None:
        """Reset ALLE leerdata: NILM, aanwezigheid, PV-oriëntatie, fasedetectie, drift."""
        # NILM
        result = coordinator.nilm.cleanup(scope="full", days=0)
        await coordinator.nilm.async_save()
        # Device drift
        drift = getattr(coordinator, "_device_drift", None)
        if drift is not None:
            await drift.async_clear_all()
        # Aanwezigheid
        absence = getattr(coordinator, "_absence", None)
        if absence is not None:
            if hasattr(absence, "_pattern"):
                absence._pattern = {}
            if hasattr(absence, "_history"):
                absence._history = []
            if hasattr(absence, "_store") and absence._store is not None:
                await absence._store.async_save({})
        # PV-oriëntatie (solar learner)
        pv_fc = getattr(coordinator, "_pv_forecast", None)
        if pv_fc is not None:
            for inv in getattr(pv_fc, "_inverters", {}).values():
                if hasattr(inv, "reset_orientation"):
                    inv.reset_orientation()
        coordinator.async_update_listeners()
        _LOGGER.info(
            "CloudEMS reset_all_learning: NILM (%d app), aanwezigheid, "
            "PV-oriëntatie en drift gewist",
            result.get("removed_devices", 0),
        )

    hass.services.async_register(DOMAIN, "reset_all_learning", reset_all_learning)

    # ── Slimme uitstelmodus — annuleer wachtende schakelaar(s) ───────────────

    async def smart_delay_cancel(call: ServiceCall) -> None:
        """Annuleer uitgesteld inschakelen voor één of alle schakelaars."""
        sd = getattr(coordinator, "_smart_delay_scheduler", None)
        if sd is None:
            _LOGGER.warning("CloudEMS smart_delay_cancel: SmartDelayScheduler niet actief")
            return
        entity_id = call.data.get("entity_id")
        cancelled = sd.cancel(entity_id)
        coordinator.async_update_listeners()
        _LOGGER.info("CloudEMS smart_delay_cancel: %s geannuleerd", cancelled or "niets")

    hass.services.async_register(
        DOMAIN, "smart_delay_cancel", smart_delay_cancel,
        schema=vol.Schema({
            vol.Optional("entity_id"): str,
        }),
    )

    # ── Rolluiken handmatige bediening ────────────────────────────────────────

    async def shutter_manual(call: ServiceCall) -> None:
        """Handmatige override: open/dicht/stop een rolluik voor X uur."""
        sc = coordinator._shutter_ctrl
        if sc is None:
            _LOGGER.warning("CloudEMS: ShutterController niet actief")
            return
        entity_id = call.data.get("entity_id", "").strip()
        if not entity_id:
            _LOGGER.warning("CloudEMS shutter_manual: geen entity_id opgegeven")
            return
        action    = call.data["action"]
        position  = call.data.get("position")
        hours     = float(call.data.get("hours", 2.0))
        # hours=0 → automaat tijdelijk uitzetten zonder actie uitvoeren
        if hours <= 0:
            hours = 2.0   # standaard 2u override, geen fysieke actie
            await sc.async_manual_override(entity_id, "idle", position, hours)
        else:
            await sc.async_manual_override(entity_id, action, position, hours)
        coordinator.async_update_listeners()

    async def shutter_cancel_override(call: ServiceCall) -> None:
        """Annuleer handmatige override — automatische sturing hervat."""
        sc = coordinator._shutter_ctrl
        if sc is None:
            return
        entity_id = call.data.get("entity_id")
        if entity_id:
            sc.cancel_override(entity_id)
        else:
            # Annuleer alle overrides
            for eid in list(sc._states.keys()):
                sc.cancel_override(eid)
        coordinator.async_update_listeners()

    hass.services.async_register(
        DOMAIN, "shutter_manual", shutter_manual,
        schema=vol.Schema({
            vol.Optional("entity_id", default=""): str,
            vol.Required("action"):    vol.In(["open", "close", "stop", "idle"]),
            vol.Optional("position"):  vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Optional("hours", default=2.0): vol.Coerce(float),
        }),
    )
    hass.services.async_register(
        DOMAIN, "shutter_cancel_override", shutter_cancel_override,
        schema=vol.Schema({
            vol.Optional("entity_id"): str,
        }),
    )


# ── v4.5.51: Meter Topologie services ────────────────────────────────────────

    async def meter_topology_approve(call: ServiceCall):
        """Bevestig een upstream→downstream relatie."""
        topo = getattr(coordinator, "_meter_topology", None)
        if topo:
            topo.approve(call.data["upstream_id"], call.data["downstream_id"])
            await coordinator._store_topo.async_save(topo.dump())

    async def meter_topology_decline(call: ServiceCall):
        """Wijs een upstream→downstream relatie af."""
        topo = getattr(coordinator, "_meter_topology", None)
        if topo:
            topo.decline(call.data["upstream_id"], call.data["downstream_id"])
            await coordinator._store_topo.async_save(topo.dump())

    async def meter_topology_set_root(call: ServiceCall):
        """Markeer een entity als root meter (bijv. P1 sensor)."""
        topo = getattr(coordinator, "_meter_topology", None)
        if topo:
            topo.set_root_meter(call.data["entity_id"])
            await coordinator._store_topo.async_save(topo.dump())

    hass.services.async_register(
        DOMAIN, "meter_topology_approve", meter_topology_approve,
        schema=vol.Schema({
            vol.Required("upstream_id"):   str,
            vol.Required("downstream_id"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, "meter_topology_decline", meter_topology_decline,
        schema=vol.Schema({
            vol.Required("upstream_id"):   str,
            vol.Required("downstream_id"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, "meter_topology_set_root", meter_topology_set_root,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
        }),
    )


_CLOUDEMS_SERVICES = [
    "confirm_device", "dismiss_device", "nilm_feedback", "rename_nilm_device",
    "hide_nilm_device", "suppress_nilm_device", "assign_device_to_room",
    "include_nilm_device", "exclude_nilm_device", "label_nilm_device",
    "set_phase_max_current", "force_price_update", "generate_report",
    "download_energy_report", "generate_blueprints", "upload_diagnostic_report",
    "boiler_override", "reset_drift_baseline", "mute_alert", "cleanup_nilm",
    "export_learning_data", "import_learning_data", "register_isolation_investment",
    "health_check", "reset_delivery_learning",
    "lamp_circulation_test", "lamp_circulation_stop_test", "lamp_circulation_set_enabled",
    "simulator_set", "simulator_clear", "simulator_zone_temp", "simulator_stove_temp",
    "clear_drift_profiles",
    "nilm_device_profile",
    "set_module_state", "set_sleep_detector",
    "configure_zone", "set_zone_temperature", "set_zone_preset", "set_zone_schedule",
    "trigger_phase_probe",
    "vtherm_set_central_mode", "vtherm_set_timed_preset",
    "zonneplan_battery_charge", "zonneplan_battery_discharge", "zonneplan_set_mode",
    "zonneplan_battery_auto", "zonneplan_apply_forecast",
]


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Services altijd opruimen — ook als platform-unload faalt.
    # Zo voorkom je "service already exists" bij de volgende reload/setup.
    for service in _CLOUDEMS_SERVICES:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Coordinator opruimen (veilig: entry kan ontbreken als setup half-gevuld was)
    domain_data = hass.data.get(DOMAIN, {})
    coordinator = domain_data.pop(entry.entry_id, None)
    if coordinator is not None:
        try:
            await coordinator.async_shutdown()
        except Exception:
            pass

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass, config_entry) -> bool:
    """Migrate old config entries to current version.

    v1 → v2: removes legacy top-level inv/bat sensor keys that moved into
              CONF_INVERTER_CONFIGS / CONF_BATTERY_CONFIGS lists.
    v2 → v3: renames entity_ids that changed slug in v1.15
              (e.g. Efficientiedrift, device_drift unique_id normalisation).
    """
    version = config_entry.version
    _LOGGER.info("CloudEMS: migrating from version %s", version)

    if version == 1:
        # v1→v2: remove stale top-level sensor keys that are now inside nested configs
        stale_keys = [
            "solar_sensor_legacy", "battery_sensor_legacy",
            "inverter_entity", "bat_power_entity",
        ]
        new_data = {k: v for k, v in config_entry.data.items() if k not in stale_keys}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        version = 2
        _LOGGER.info("CloudEMS: migrated to version 2")

    if version == 2:
        # v2→v3: fix unique_id renames from v1.13→v1.15
        # Rename entity registry entries for slugs that changed
        slug_renames = {
            # old unique_id suffix → new unique_id suffix
            "_efficientiedrift":        "_device_drift",
            "_apparaat_efficientiedrift": "_device_drift",
            "_aanwezigheid":            "_occupancy",
            "_verbruik_anomalie":       "_anomaly",
        }
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        entry_id = config_entry.entry_id
        renamed = 0
        for old_suffix, new_suffix in slug_renames.items():
            old_uid = f"{entry_id}{old_suffix}"
            entity = ent_reg.async_get_entity_id("sensor", DOMAIN, old_uid) or                      ent_reg.async_get_entity_id("binary_sensor", DOMAIN, old_uid)
            if entity:
                ent_reg.async_update_entity(entity, new_unique_id=f"{entry_id}{new_suffix}")
                renamed += 1
                _LOGGER.info("CloudEMS migrate: renamed %s → %s", old_uid, f"{entry_id}{new_suffix}")
        if renamed:
            _LOGGER.info("CloudEMS: migrated %d entity unique_ids", renamed)
        hass.config_entries.async_update_entry(config_entry, version=3)
        _LOGGER.info("CloudEMS: migrated to version 3")
        version = 3

    if version == 3:
        # v3→v4: verwijder ALLE switch-registry-entries van dit entry (NILM + dimmer)
        # zodat HA ze fris aanmaakt. Achtergrond: CloudEMSHybridNILMSwitch en andere
        # schakelaars konden bij v1.22 niet laden door een ontbrekende coordinator-methode.
        # HA bewaar dan een "orphan" entry — zichtbaar als "Entiteit niet gevonden".
        # Oplossing: alle switches van dit entry wissen; async_setup_entry maakt ze opnieuw aan.
        from homeassistant.helpers import entity_registry as er
        ent_reg  = er.async_get(hass)
        entry_id = config_entry.entry_id

        # Verwijder alle switch- EN number-entities van dit config-entry (ook orphans)
        # zodat HA ze opnieuw aanmaakt met stabiele entity_ids (v1.25.4+)
        domains_to_clear = ("switch", "number")
        removed = 0
        for domain in domains_to_clear:
            stale = [
                e for e in ent_reg.entities.values()
                if e.config_entry_id == entry_id and e.domain == domain
            ]
            for stale_entry in stale:
                ent_reg.async_remove(stale_entry.entity_id)
                removed += 1
                _LOGGER.info(
                    "CloudEMS migrate v3→v4: %s verwijderd voor herregistratie: %s",
                    domain, stale_entry.entity_id,
                )
        if removed:
            _LOGGER.info(
                "CloudEMS: %d entiteit(en) verwijderd uit registry "
                "(worden opnieuw aangemaakt bij laden met stabiele entity_ids)", removed,
            )
        hass.config_entries.async_update_entry(config_entry, version=4)
        _LOGGER.info("CloudEMS: migrated to version 4")

    if version == 4:
        # v4→v5: lampcirculatie standaard UIT zetten.
        # De module werd automatisch ingeschakeld bij nieuwe installaties (default True).
        # Veiligheidsmaatregel: forceer enabled=False zodat gebruikers bewust moeten
        # kiezen om de inbraakbeveiliging aan te zetten via de wizard of het dashboard.
        new_data    = dict(config_entry.data)
        new_options = dict(config_entry.options)

        # Forceer in data-dict
        lc_data = dict(new_data.get("lamp_circulation", {}))
        lc_data["enabled"] = False
        new_data["lamp_circulation"] = lc_data

        # Forceer in options-dict (wordt bij OptionsFlow gebruikt)
        lc_opts = dict(new_options.get("lamp_circulation", {}))
        lc_opts["enabled"] = False
        new_options["lamp_circulation"] = lc_opts

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, options=new_options, version=5
        )
        _LOGGER.info("CloudEMS: migrated to version 5 — lamp_circulation.enabled → False")
        version = 5

    if version == 5:
        # v5→v6: hernoem entry titel naar "CloudEMS" (was "CloudEMS (3x25A)" o.i.d.)
        hass.config_entries.async_update_entry(config_entry, title="CloudEMS", version=6)
        _LOGGER.info("CloudEMS: migrated to version 6 — entry titel → CloudEMS")

    return True


# ── Rapport HTML helper ────────────────────────────────────────────────────────

def _md_to_html(md: str, title: str) -> str:
    """Converteer Markdown rapport naar standalone HTML met CloudEMS styling.

    Ondersteunde elementen:
      ## / ### koppen, -, numbered lists, **bold**, `code`, > blockquote,
      Markdown-tabellen (| col | col |), horizontale lijnen, lege regels.

    Render-logging: onbekende of mislukte patronen worden gelogd als WARNING
    zodat toekomstige versies automatisch verbeterd kunnen worden.
    """
    import re, html as _html
    import logging as _logging
    _log = _logging.getLogger(__name__)

    lines = md.split("\n")
    body_parts: list[str] = []

    # ── Render-statistieken (automatisch leren) ───────────────────────────────
    render_stats: dict = {
        "total_lines": len(lines),
        "tables": 0,
        "table_rows_ok": 0,
        "table_rows_malformed": 0,
        "headings": 0,
        "lists": 0,
        "blockquotes": 0,
        "code_inline": 0,
        "unrecognised": [],
    }

    # ── Helper: cel opmaken ───────────────────────────────────────────────────
    def _fmt(text: str) -> str:
        """Pas inline markdown toe: bold, code, italic."""
        t = _html.escape(text.strip())
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", t)
        return t

    # ── Tabel-buffer ──────────────────────────────────────────────────────────
    table_buffer: list[str] = []

    def _flush_table() -> None:
        """Zet gebufferde tabelregels om naar een <table>."""
        nonlocal table_buffer
        if not table_buffer:
            return

        # Filter separator-regels (|---|---|)
        rows = [r for r in table_buffer if not re.match(r"^\|[-| :]+\|?$", r.strip())]

        if not rows:
            _log.warning(
                "CloudEMS _md_to_html: tabel bevat alleen separator-regels, overgeslagen. "
                "Raw: %s", table_buffer
            )
            table_buffer = []
            return

        html_rows: list[str] = []
        for i, row in enumerate(rows):
            # Splits op | en verwijder lege eerste/laatste cel door strip
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if not cells:
                render_stats["table_rows_malformed"] += 1
                _log.warning(
                    "CloudEMS _md_to_html: lege tabelrij overgeslagen. Raw: %r", row
                )
                continue

            tag = "th" if i == 0 else "td"
            cell_html = "".join(f"<{tag}>{_fmt(c)}</{tag}>" for c in cells)
            html_rows.append(f"<tr>{cell_html}</tr>")
            render_stats["table_rows_ok"] += 1

        if html_rows:
            body_parts.append(
                "<table><thead>" + html_rows[0] + "</thead>"
                "<tbody>" + "".join(html_rows[1:]) + "</tbody></table>"
            )
            render_stats["tables"] += 1
            _log.debug(
                "CloudEMS _md_to_html: tabel gerenderd (%d rijen, %d kolommen).",
                len(html_rows),
                len(rows[0].strip().strip("|").split("|")) if rows else 0,
            )
        else:
            _log.warning(
                "CloudEMS _md_to_html: tabel had geen geldige rijen. Buffer: %s",
                table_buffer,
            )

        table_buffer = []

    # ── Verwerk regels ────────────────────────────────────────────────────────
    for line in lines:
        raw = line.rstrip()

        # Tabel-rij (begint of eindigt met |)
        is_table_row = raw.startswith("|") or ("|" in raw and raw.endswith("|"))
        is_separator  = re.match(r"^\|[-| :]+\|?$", raw.strip()) is not None

        if is_table_row or is_separator:
            table_buffer.append(raw)
            continue

        # Geen tabelrij → flush eventuele tabel-buffer
        _flush_table()

        if raw.startswith("## "):
            body_parts.append(f"<h2>{_fmt(raw[3:])}</h2>")
            render_stats["headings"] += 1

        elif raw.startswith("### "):
            body_parts.append(f"<h3>{_fmt(raw[4:])}</h3>")
            render_stats["headings"] += 1

        elif raw.startswith("#### "):
            body_parts.append(f"<h4>{_fmt(raw[5:])}</h4>")
            render_stats["headings"] += 1

        elif raw.startswith("---") and raw.strip("-") == "":
            body_parts.append("<hr>")

        elif raw.startswith("- ") or raw.startswith("* "):
            content = _fmt(raw[2:])
            body_parts.append(f"<li>{content}</li>")
            render_stats["lists"] += 1

        elif raw.startswith("> "):
            content = _fmt(raw[2:])
            body_parts.append(f"<blockquote>{content}</blockquote>")
            render_stats["blockquotes"] += 1

        elif raw.startswith("```"):
            body_parts.append("<pre><code>")  # open code block

        elif raw == "```":
            body_parts.append("</code></pre>")

        elif re.match(r"^\d+\.", raw):
            content = _fmt(raw)
            body_parts.append(f"<li class='numbered'>{content}</li>")
            render_stats["lists"] += 1

        elif raw == "":
            body_parts.append("<br>")

        else:
            # Controleer op patroon dat onbekend is maar wél tabel-achtig (diagnostiek)
            if raw.count("|") >= 2:
                render_stats["table_rows_malformed"] += 1
                _log.warning(
                    "CloudEMS _md_to_html: mogelijke tabelrij niet herkend "
                    "(begint niet met '|'): %r — voeg dit patroon toe aan de renderer.",
                    raw[:120],
                )
            content = _fmt(raw)
            body_parts.append(f"<p>{content}</p>")

    # Flush eventuele resterende tabel aan het einde
    _flush_table()

    # ── Render-rapport loggen ─────────────────────────────────────────────────
    _log.info(
        "CloudEMS _md_to_html render voltooid: %d regels, %d tabellen (%d rijen ok / %d malformed), "
        "%d koppen, %d lijstitems, %d blockquotes.",
        render_stats["total_lines"],
        render_stats["tables"],
        render_stats["table_rows_ok"],
        render_stats["table_rows_malformed"],
        render_stats["headings"],
        render_stats["lists"],
        render_stats["blockquotes"],
    )
    if render_stats["table_rows_malformed"] > 0:
        _log.warning(
            "CloudEMS _md_to_html: %d tabelrij(en) konden niet worden geparsed. "
            "Bekijk de WARNING-regels hierboven voor de exacte patronen.",
            render_stats["table_rows_malformed"],
        )

    body = "\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CloudEMS Rapport — {_html.escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #111827; color: #e5e7eb;
      max-width: 720px; margin: 0 auto; padding: 2rem 1.5rem;
      line-height: 1.6;
    }}
    h1 {{ color: #00b140; font-size: 1.6rem; margin-bottom: 1.5rem; border-bottom: 2px solid #00b140; padding-bottom: .5rem; }}
    h2 {{ color: #00d44e; font-size: 1.25rem; margin: 1.5rem 0 .5rem; }}
    h3 {{ color: #6ee7b7; font-size: 1rem; margin: 1.2rem 0 .4rem; }}
    li {{ margin-left: 1.2rem; margin-bottom: .2rem; }}
    li.numbered {{ list-style: decimal; margin-left: 1.5rem; }}
    strong {{ color: #f9fafb; }}
    hr {{ border: none; border-top: 1px solid #374151; margin: 1.5rem 0; }}
    p.footer {{ color: #6b7280; font-size: .85rem; font-style: italic; margin-top: 1rem; }}
    br {{ display: block; content: ''; margin: .3rem 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }}
    th {{ background: #1f2937; color: #00d44e; text-align: left; padding: .5rem .75rem;
          border-bottom: 2px solid #00b140; }}
    td {{ padding: .4rem .75rem; border-bottom: 1px solid #374151; color: #d1d5db; }}
    tr:hover td {{ background: #1f2937; }}
    code {{ background: #1f2937; color: #86efac; padding: .1rem .35rem;
            border-radius: 3px; font-size: .85em; }}
    pre code {{ display: block; padding: .75rem 1rem; white-space: pre-wrap;
                background: #1f2937; border-radius: 6px; margin: .75rem 0; }}
    blockquote {{ border-left: 3px solid #374151; margin: .5rem 0;
                  padding: .2rem .75rem; color: #9ca3af; font-style: italic; }}
    .print-btn {{
      display: inline-block; margin-bottom: 1.5rem;
      padding: .5rem 1.2rem; background: #00b140; color: #fff;
      border: none; border-radius: 6px; cursor: pointer;
      font-size: .9rem; text-decoration: none;
    }}
    @media print {{ .print-btn {{ display: none; }} body {{ background: #fff; color: #000; }} }}
  </style>
</head>
<body>
  <h1>☀️ CloudEMS Energierapport</h1>
  <button class="print-btn" onclick="window.print()">🖨️ Afdrukken / Opslaan als PDF</button>
  {body}
</body>
</html>"""
