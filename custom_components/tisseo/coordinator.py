"""Data coordinator for Tisséo departures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MAX_DEPARTURES,
    CONF_REFRESH_SECONDS,
    CONF_ROUTE_IDS,
    CONF_STOP_AREA_ID,
    DEFAULT_MAX_DEPARTURES,
    DEFAULT_REFRESH_SECONDS,
    DOMAIN,
    STATIC_REFRESH_INTERVAL,
)
from .feed import (
    Departure,
    ScheduledStopTime,
    StopArea,
    TisseoClient,
    TisseoError,
    merge_departures,
    realtime_departures,
    scheduled_departures,
    PARIS,
)

_LOGGER = logging.getLogger(__name__)
HORIZON = timedelta(hours=3)


@dataclass(frozen=True)
class TisseoData:
    """Latest Tisséo data exposed to entities."""

    departures: tuple[Departure, ...]
    updated_at: datetime


class TisseoCoordinator(DataUpdateCoordinator[TisseoData]):
    """Poll the real-time feed and occasionally refresh the static feed."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TisseoClient
    ) -> None:
        refresh = int(entry.options.get(CONF_REFRESH_SECONDS, DEFAULT_REFRESH_SECONDS))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=refresh),
            always_update=False,
        )
        self.client = client
        self.stop_area: StopArea | None = None
        self.route_ids = set(entry.options.get(CONF_ROUTE_IDS, entry.data[CONF_ROUTE_IDS]))
        self.max_departures = int(
            entry.options.get(CONF_MAX_DEPARTURES, DEFAULT_MAX_DEPARTURES)
        )
        self.stop_times: list[ScheduledStopTime] = []
        self._static_loaded_at: datetime | None = None

    async def async_initialize(self) -> None:
        """Load static route and schedule metadata."""
        await self._async_refresh_static()

    async def _async_refresh_static(self) -> None:
        static = await self.client.async_load_static()
        self.stop_area = static.get_stop_area(self.config_entry.data[CONF_STOP_AREA_ID])
        self.stop_times = await self.hass.async_add_executor_job(
            static.scheduled_stop_times, self.stop_area, self.route_ids
        )
        self._static_loaded_at = datetime.now(PARIS)

    async def _async_update_data(self) -> TisseoData:
        now = datetime.now(PARIS)
        try:
            if (
                self.client.static is None
                or self.stop_area is None
                or self._static_loaded_at is None
                or now - self._static_loaded_at >= STATIC_REFRESH_INTERVAL
            ):
                await self._async_refresh_static()
            content = await self.client.async_realtime()
            assert self.client.static is not None
            assert self.stop_area is not None
            realtime = await self.hass.async_add_executor_job(
                realtime_departures,
                content,
                self.client.static,
                self.stop_area,
                self.route_ids,
                now,
                HORIZON,
            )
            theoretical = await self.hass.async_add_executor_job(
                scheduled_departures,
                self.client.static,
                self.stop_times,
                now,
                HORIZON,
            )
        except TisseoError as err:
            raise UpdateFailed(f"Erreur Tisséo : {err}") from err
        return TisseoData(tuple(merge_departures(realtime, theoretical)), now)
