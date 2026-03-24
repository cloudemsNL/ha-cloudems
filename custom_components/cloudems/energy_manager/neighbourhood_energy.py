# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Neighbourhood Energy Sharing v1.0.0

Enables multiple CloudEMS installations in the same street/neighbourhood
to share surplus PV energy via a local MQTT broker.

How it works:
  1. Publish own surplus (W) on MQTT: cloudems/neighbourhood/{node_id}/surplus
  2. Subscribe to surplus from neighbour nodes
  3. Fairness token: each node tracks how much it gave vs received
  4. Report shared energy for P2P billing

Privacy: node_id is a hash of entry_id (not traceable to address).
         Only surplus power is shared — no personal data.

MQTT topics:
  cloudems/neighbourhood/{node_id}/surplus    → own surplus W (published every 30s)
  cloudems/neighbourhood/{node_id}/status     → online heartbeat
  cloudems/neighbourhood/+/surplus            → subscribe to all neighbours

Configuration:
  neighbourhood_enabled       bool
  neighbourhood_mqtt_broker   str    — MQTT broker IP (local network)
  neighbourhood_mqtt_port     int    — default 1883
  neighbourhood_node_id       str    — auto-generated from entry_id if empty
  neighbourhood_max_share_w   float  — max W to offer neighbours (default 1000)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PUBLISH_INTERVAL_S = 30
NEIGHBOUR_TIMEOUT_S = 120   # remove neighbour if no update for 2 min


@dataclass
class NeighbourNode:
    node_id:    str
    surplus_w:  float = 0.0
    last_seen:  float = 0.0
    shared_kwh: float = 0.0   # total kWh we received from them


@dataclass
class NeighbourhoodStatus:
    enabled:          bool  = False
    node_id:          str   = ""
    own_surplus_w:    float = 0.0
    neighbours:       list  = field(default_factory=list)
    total_available_w: float = 0.0
    shared_given_kwh: float = 0.0
    shared_recv_kwh:  float = 0.0
    mqtt_connected:   bool  = False


class NeighbourhoodEnergy:
    """
    P2P neighbourhood energy sharing via local MQTT.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("neighbourhood_enabled", False)
        self._mqtt_client = None
        self._connected   = False
        self._node_id     = self._build_node_id()
        self._neighbours: dict[str, NeighbourNode] = {}
        self._own_surplus  = 0.0
        self._given_kwh    = 0.0
        self._recv_kwh     = 0.0
        self._last_publish = 0.0

    def _build_node_id(self) -> str:
        """Build anonymous node ID from config entry ID."""
        raw = self._config.get("neighbourhood_node_id") or \
              self._config.get("entry_id") or \
              "cloudems_default"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    async def async_setup(self) -> None:
        """Connect to MQTT broker if enabled."""
        if not self._enabled:
            return
        broker = self._config.get("neighbourhood_mqtt_broker", "")
        if not broker:
            _LOGGER.info("NeighbourhoodEnergy: no MQTT broker configured, using HA MQTT")
            await self._setup_ha_mqtt()
        else:
            await self._setup_external_mqtt(broker)

    async def _setup_ha_mqtt(self) -> None:
        """Use Home Assistant's built-in MQTT integration."""
        try:
            from homeassistant.components import mqtt
            if not self._hass.data.get("mqtt"):
                _LOGGER.warning("NeighbourhoodEnergy: HA MQTT not available")
                return

            topic = f"cloudems/neighbourhood/+/surplus"
            await mqtt.async_subscribe(self._hass, topic, self._on_mqtt_message)
            self._connected = True
            _LOGGER.info("NeighbourhoodEnergy: subscribed via HA MQTT (node=%s)", self._node_id)
        except Exception as e:
            _LOGGER.warning("NeighbourhoodEnergy: MQTT setup failed: %s", e)

    async def _setup_external_mqtt(self, broker: str) -> None:
        """Connect to external MQTT broker."""
        try:
            import aiomqtt
            port = int(self._config.get("neighbourhood_mqtt_port", 1883))
            # Store connection params for tick
            self._mqtt_broker = broker
            self._mqtt_port   = port
            self._connected   = True
            _LOGGER.info("NeighbourhoodEnergy: external MQTT configured (%s:%d)", broker, port)
        except ImportError:
            _LOGGER.warning("NeighbourhoodEnergy: aiomqtt not available, using HA MQTT")
            await self._setup_ha_mqtt()
        except Exception as e:
            _LOGGER.warning("NeighbourhoodEnergy: external MQTT failed: %s", e)

    def _on_mqtt_message(self, msg) -> None:
        """Handle incoming neighbour surplus message."""
        try:
            parts   = msg.topic.split("/")
            node_id = parts[2] if len(parts) >= 3 else "unknown"
            if node_id == self._node_id:
                return  # own message

            payload = json.loads(msg.payload)
            surplus_w = float(payload.get("surplus_w", 0))
            now = time.time()

            if node_id not in self._neighbours:
                self._neighbours[node_id] = NeighbourNode(node_id=node_id)
                _LOGGER.info("NeighbourhoodEnergy: new neighbour %s", node_id)

            self._neighbours[node_id].surplus_w = surplus_w
            self._neighbours[node_id].last_seen = now
        except Exception as e:
            _LOGGER.debug("NeighbourhoodEnergy: message parse error: %s", e)

    async def async_tick(self, own_surplus_w: float) -> None:
        """Call every coordinator cycle."""
        if not self._enabled or not self._connected:
            return

        self._own_surplus = max(0.0, own_surplus_w)
        now = time.time()

        # Publish own surplus every 30s
        if now - self._last_publish >= PUBLISH_INTERVAL_S:
            await self._publish_surplus()
            self._last_publish = now

        # Remove timed-out neighbours
        self._neighbours = {
            nid: n for nid, n in self._neighbours.items()
            if now - n.last_seen < NEIGHBOUR_TIMEOUT_S
        }

        # Accumulate received kWh (rough: surplus × time)
        total_neighbour_w = sum(n.surplus_w for n in self._neighbours.values())
        if total_neighbour_w > 100:
            self._recv_kwh += total_neighbour_w / 1000 * (10 / 3600)

        # Accumulate given kWh
        max_share = float(self._config.get("neighbourhood_max_share_w", 1000))
        if self._own_surplus > 100:
            shared = min(self._own_surplus, max_share)
            self._given_kwh += shared / 1000 * (10 / 3600)

    async def _publish_surplus(self) -> None:
        """Publish own surplus to MQTT."""
        max_share = float(self._config.get("neighbourhood_max_share_w", 1000))
        offer_w   = min(self._own_surplus, max_share)

        payload = json.dumps({
            "node_id":    self._node_id,
            "surplus_w":  round(offer_w, 1),
            "ts":         time.time(),
        })

        try:
            from homeassistant.components import mqtt
            await mqtt.async_publish(
                self._hass,
                f"cloudems/neighbourhood/{self._node_id}/surplus",
                payload,
            )
        except Exception as e:
            _LOGGER.debug("NeighbourhoodEnergy: publish failed: %s", e)

    def get_status(self) -> NeighbourhoodStatus:
        neighbours = [
            {
                "node_id":   n.node_id,
                "surplus_w": n.surplus_w,
                "last_seen": round(time.time() - n.last_seen, 0),
            }
            for n in self._neighbours.values()
        ]
        total_available = sum(n.surplus_w for n in self._neighbours.values())

        return NeighbourhoodStatus(
            enabled           = self._enabled,
            node_id           = self._node_id[:8] + "...",  # truncate for privacy
            own_surplus_w     = round(self._own_surplus, 1),
            neighbours        = neighbours,
            total_available_w = round(total_available, 1),
            shared_given_kwh  = round(self._given_kwh, 3),
            shared_recv_kwh   = round(self._recv_kwh, 3),
            mqtt_connected    = self._connected,
        )

    def to_dict(self) -> dict:
        s = self.get_status()
        return {
            "enabled":           s.enabled,
            "node_id":           s.node_id,
            "own_surplus_w":     s.own_surplus_w,
            "neighbours":        s.neighbours,
            "total_available_w": s.total_available_w,
            "shared_given_kwh":  s.shared_given_kwh,
            "shared_recv_kwh":   s.shared_recv_kwh,
            "mqtt_connected":    s.mqtt_connected,
        }
