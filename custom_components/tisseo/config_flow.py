"""Config flow for Tisséo departures."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_FAVORITE_DIRECTION,
    CONF_FAVORITE_ROUTE_ID,
    CONF_MAX_DEPARTURES,
    CONF_REFRESH_SECONDS,
    CONF_ROUTE_IDS,
    CONF_ROUTE_OPTIONS,
    CONF_STOP_AREA_ID,
    CONF_STOP_NAME,
    DEFAULT_MAX_DEPARTURES,
    DEFAULT_REFRESH_SECONDS,
    DEFAULT_STOP_QUERY,
    DOMAIN,
    MAX_REFRESH_SECONDS,
    MIN_REFRESH_SECONDS,
)
from .feed import Route, StaticFeed, StopArea, TisseoClient, TisseoError


class TisseoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a stop and the lines to follow."""

    VERSION = 1

    def __init__(self) -> None:
        self._static: StaticFeed | None = None
        self._stops: dict[str, StopArea] = {}
        self._stop: StopArea | None = None
        self._routes: dict[str, Route] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search an official Tisséo stop."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                client = TisseoClient()
                try:
                    self._static = await client.async_load_static()
                finally:
                    await client.async_close()
                matches = await self.hass.async_add_executor_job(
                    self._static.find_stop_areas, user_input[CONF_STOP_NAME]
                )
            except TisseoError:
                errors["base"] = "cannot_connect"
            else:
                if not matches:
                    errors["base"] = "stop_not_found"
                else:
                    self._stops = {item.stop_id: item for item in matches}
                    return await self.async_step_stop()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_NAME, default=DEFAULT_STOP_QUERY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select one search result."""
        if user_input is not None:
            self._stop = self._stops[user_input[CONF_STOP_AREA_ID]]
            assert self._static is not None
            routes = await self.hass.async_add_executor_job(
                self._static.routes_for_stop, self._stop
            )
            self._routes = {route.route_id: route for route in routes}
            return await self.async_step_lines()
        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_AREA_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=key, label=value.name)
                                for key, value in self._stops.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_lines(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose followed lines."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_ROUTE_IDS]
            if not selected:
                errors["base"] = "select_line"
            else:
                assert self._stop is not None
                await self.async_set_unique_id(self._stop.stop_id)
                self._abort_if_unique_id_configured()
                route_options = {
                    route_id: route.label for route_id, route in self._routes.items()
                }
                return self.async_create_entry(
                    title=f"Tisséo — {self._stop.name}",
                    data={
                        CONF_STOP_AREA_ID: self._stop.stop_id,
                        CONF_STOP_NAME: self._stop.name,
                        CONF_ROUTE_IDS: selected,
                        CONF_ROUTE_OPTIONS: route_options,
                    },
                    options={
                        CONF_ROUTE_IDS: selected,
                        CONF_FAVORITE_ROUTE_ID: "",
                        CONF_FAVORITE_DIRECTION: "",
                        CONF_MAX_DEPARTURES: user_input[CONF_MAX_DEPARTURES],
                        CONF_REFRESH_SECONDS: user_input[CONF_REFRESH_SECONDS],
                    },
                )
        return self.async_show_form(
            step_id="lines",
            data_schema=_lines_schema(
                self._routes,
                list(self._routes),
                DEFAULT_MAX_DEPARTURES,
                DEFAULT_REFRESH_SECONDS,
                "",
                "",
            ),
            errors=errors,
        )

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create an initial entry from YAML; it remains editable in the UI."""
        stop_area_id = import_data[CONF_STOP_AREA_ID]
        await self.async_set_unique_id(stop_area_id)
        self._abort_if_unique_id_configured(updates=import_data)
        try:
            client = TisseoClient()
            try:
                static = await client.async_load_static()
            finally:
                await client.async_close()
            stop = static.get_stop_area(stop_area_id)
            routes = await self.hass.async_add_executor_job(static.routes_for_stop, stop)
        except TisseoError:
            return self.async_abort(reason="cannot_connect")
        route_options = {route.route_id: route.label for route in routes}
        requested = import_data.get(CONF_ROUTE_IDS) or list(route_options)
        selected = [route_id for route_id in requested if route_id in route_options]
        if not selected:
            selected = list(route_options)
        return self.async_create_entry(
            title=f"Tisséo — {stop.name}",
            data={
                CONF_STOP_AREA_ID: stop.stop_id,
                CONF_STOP_NAME: stop.name,
                CONF_ROUTE_IDS: selected,
                CONF_ROUTE_OPTIONS: route_options,
            },
            options={
                CONF_ROUTE_IDS: selected,
                CONF_FAVORITE_ROUTE_ID: "",
                CONF_FAVORITE_DIRECTION: "",
                CONF_MAX_DEPARTURES: DEFAULT_MAX_DEPARTURES,
                CONF_REFRESH_SECONDS: DEFAULT_REFRESH_SECONDS,
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TisseoOptionsFlow:
        return TisseoOptionsFlow(config_entry)


class TisseoOptionsFlow(config_entries.OptionsFlow):
    """Let users change lines and display limits later."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_ROUTE_IDS]:
                errors["base"] = "select_line"
            else:
                return self.async_create_entry(title="", data=user_input)
        labels = self._entry.data.get(CONF_ROUTE_OPTIONS, {})
        routes = {
            route_id: _route_from_label(route_id, label)
            for route_id, label in labels.items()
        }
        current = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=_lines_schema(
                routes,
                current.get(CONF_ROUTE_IDS, self._entry.data[CONF_ROUTE_IDS]),
                current.get(CONF_MAX_DEPARTURES, DEFAULT_MAX_DEPARTURES),
                current.get(CONF_REFRESH_SECONDS, DEFAULT_REFRESH_SECONDS),
                current.get(CONF_FAVORITE_ROUTE_ID, ""),
                current.get(CONF_FAVORITE_DIRECTION, ""),
            ),
            errors=errors,
        )


def _lines_schema(
    routes: dict[str, Route],
    selected: list[str],
    max_departures: int,
    refresh_seconds: int,
    favorite_route_id: str,
    favorite_direction: str,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ROUTE_IDS, default=selected): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=key, label=value.label)
                        for key, value in routes.items()
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_MAX_DEPARTURES, default=max_departures
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=12,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_REFRESH_SECONDS, default=refresh_seconds
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_REFRESH_SECONDS,
                    max=MAX_REFRESH_SECONDS,
                    step=5,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="s",
                )
            ),
            vol.Optional(
                CONF_FAVORITE_ROUTE_ID, default=favorite_route_id
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value="", label="Aucune")]
                    + [
                        selector.SelectOptionDict(value=key, label=value.label)
                        for key, value in routes.items()
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_FAVORITE_DIRECTION, default=favorite_direction
            ): selector.TextSelector(),
        }
    )


def _route_from_label(route_id: str, label: str) -> Route:
    short_name = label.split(" · ", 1)[0]
    route_type = 0 if "Tram" in label else 3
    return Route(route_id, short_name, label, route_type, "")
