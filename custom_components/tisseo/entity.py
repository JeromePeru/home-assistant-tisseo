"""Base entity for Tisséo."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TisseoConfigEntry
from .const import DOMAIN
from .coordinator import TisseoCoordinator


class TisseoEntity(CoordinatorEntity[TisseoCoordinator]):
    """Entity tied to a Tisséo stop coordinator."""

    _attr_has_entity_name = True

    def __init__(self, entry: TisseoConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Tisséo Voyageurs",
            model="GTFS / GTFS-Realtime",
            name=entry.title,
            configuration_url="https://data.toulouse-metropole.fr/explore/dataset/tisseo-gtfs/",
        )
