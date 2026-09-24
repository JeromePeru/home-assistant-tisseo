"""Sensors showing upcoming Tisséo departures."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TisseoConfigEntry
from .const import CONF_ROUTE_IDS, CONF_ROUTE_OPTIONS
from .entity import TisseoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TisseoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one overview sensor plus one sensor per selected line."""
    route_ids = entry.options.get(CONF_ROUTE_IDS, entry.data[CONF_ROUTE_IDS])
    route_options = entry.data.get(CONF_ROUTE_OPTIONS, {})
    entities: list[SensorEntity] = [TisseoOverviewSensor(entry)]
    entities.extend(
        TisseoRouteSensor(entry, route_id, route_options.get(route_id, route_id))
        for route_id in route_ids
    )
    async_add_entities(entities)


class TisseoOverviewSensor(TisseoEntity, SensorEntity):
    """Aggregate upcoming departures at the stop."""

    entity_description = SensorEntityDescription(
        key="next_departures",
        translation_key="next_departures",
        icon="mdi:bus-clock",
    )

    def __init__(self, entry: TisseoConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_next_departures"

    @property
    def native_value(self) -> int:
        """Return displayed departure count."""
        return len(self._items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = self.coordinator.data.updated_at
        return {
            "arret": self._entry.data.get("stop_name", self._entry.title),
            "passages": [item.as_dict(now) for item in self._items],
            "mis_a_jour": now.isoformat(),
            "source": "Tisséo Open Data GTFS-RT",
        }

    @property
    def _items(self):
        return self.coordinator.data.departures[: self.coordinator.max_departures]


class TisseoRouteSensor(TisseoEntity, SensorEntity):
    """Minutes until the next vehicle on one route."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "min"

    def __init__(self, entry: TisseoConfigEntry, route_id: str, label: str) -> None:
        super().__init__(entry)
        self.route_id = route_id
        self._attr_unique_id = f"{entry.entry_id}_{route_id.replace(':', '_')}"
        self._attr_name = label.split(" · ", 1)[0]
        self._attr_icon = "mdi:tram" if "Tram" in label else "mdi:bus"

    @property
    def native_value(self) -> int | None:
        items = self._items
        if not items:
            return None
        return max(
            0,
            int(
                (items[0].when - self.coordinator.data.updated_at).total_seconds()
                // 60
            ),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = self.coordinator.data.updated_at
        passages = [item.as_dict(now) for item in self._items]
        passages_suivants = " · ".join(
            "maintenant" if item["dans_minutes"] == 0 else f'{item["dans_minutes"]} min'
            for item in passages[1:3]
        )
        return {
            "passages": passages,
            "passages_suivants": passages_suivants or None,
            "prochaine_destination": self._items[0].destination if self._items else None,
            "temps_reel": self._items[0].realtime if self._items else None,
        }

    @property
    def _items(self):
        matches = [
            item
            for item in self.coordinator.data.departures
            if item.route_id == self.route_id
        ]
        return matches[: self.coordinator.max_departures]
