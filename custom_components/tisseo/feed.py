"""Read the official Tisséo GTFS and GTFS-Realtime feeds."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO, TextIOWrapper
import logging
import socket
import unicodedata
from zoneinfo import ZoneInfo
from zipfile import BadZipFile, ZipFile

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

from .const import REALTIME_GTFS_URL, STATIC_GTFS_URL

_LOGGER = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
REQUEST_TIMEOUT = ClientTimeout(total=30)
PINNED_DNS = {
    # DNS fallback for Home Assistant installations whose internal resolver is
    # unavailable. HTTPS still validates the official hostname and certificate.
    "data.toulouse-metropole.fr": ("52.211.64.165", "18.200.140.238"),
}


class TisseoError(Exception):
    """Base Tisséo error."""


class TisseoConnectionError(TisseoError):
    """The official feed could not be reached."""


class TisseoFeedError(TisseoError):
    """The official feed could not be decoded."""


@dataclass(frozen=True)
class StopArea:
    """A passenger stop area."""

    stop_id: str
    name: str
    stop_ids: tuple[str, ...]


@dataclass(frozen=True)
class Route:
    """A route serving the configured stop."""

    route_id: str
    short_name: str
    long_name: str
    route_type: int
    color: str

    @property
    def label(self) -> str:
        mode = "Tram" if self.route_type == 0 else "Bus"
        return f"{self.short_name} · {mode} — {self.long_name}"


@dataclass(frozen=True)
class Trip:
    """Static trip metadata."""

    route_id: str
    service_id: str
    headsign: str


@dataclass(frozen=True)
class ScheduledStopTime:
    """One theoretical stop time."""

    trip_id: str
    stop_id: str
    seconds: int


@dataclass(frozen=True)
class Departure:
    """One upcoming vehicle passage."""

    route_id: str
    route_name: str
    destination: str
    stop_id: str
    when: datetime
    realtime: bool
    trip_id: str

    def as_dict(self, now: datetime) -> dict[str, object]:
        minutes = max(0, int((self.when - now).total_seconds() // 60))
        return {
            "ligne": self.route_name,
            "destination": self.destination,
            "heure": self.when.isoformat(),
            "dans_minutes": minutes,
            "temps_reel": self.realtime,
            "quai": self.stop_id,
        }


class StaticFeed:
    """Parsed subset of a Tisséo static GTFS archive."""

    def __init__(self, content: bytes) -> None:
        try:
            self._zip = ZipFile(BytesIO(content))
        except BadZipFile as err:
            raise TisseoFeedError("Archive GTFS statique invalide") from err
        self.stops = self._read("stops.txt")
        self.routes_by_id = {
            row["route_id"]: Route(
                row["route_id"],
                row.get("route_short_name", ""),
                row.get("route_long_name", ""),
                int(row.get("route_type", 3)),
                row.get("route_color", ""),
            )
            for row in self._read("routes.txt")
        }
        self.trips_by_id = {
            row["trip_id"]: Trip(
                row["route_id"], row["service_id"], row.get("trip_headsign", "")
            )
            for row in self._read("trips.txt")
        }

    def _read(self, name: str) -> list[dict[str, str]]:
        stream = TextIOWrapper(self._zip.open(name), encoding="utf-8-sig", newline="")
        return list(csv.DictReader(stream))

    def find_stop_areas(self, query: str, limit: int = 20) -> list[StopArea]:
        """Find parent stop areas by accent-insensitive name."""
        needle = _fold(query)
        parents = {
            row["stop_id"]: row["stop_name"]
            for row in self.stops
            if row.get("location_type") == "1" and needle in _fold(row["stop_name"])
        }
        children: dict[str, list[str]] = {key: [] for key in parents}
        for row in self.stops:
            parent = row.get("parent_station", "")
            if parent in children:
                children[parent].append(row["stop_id"])
        return [
            StopArea(stop_id, name, tuple(children[stop_id]))
            for stop_id, name in sorted(parents.items(), key=lambda item: item[1])
        ][:limit]

    def get_stop_area(self, stop_area_id: str) -> StopArea:
        """Return a stop area and its physical platforms."""
        name = next(
            (
                row["stop_name"]
                for row in self.stops
                if row["stop_id"] == stop_area_id
            ),
            stop_area_id,
        )
        children = tuple(
            row["stop_id"]
            for row in self.stops
            if row.get("parent_station") == stop_area_id
        )
        if not children:
            raise TisseoFeedError("Arrêt introuvable dans le GTFS Tisséo")
        return StopArea(stop_area_id, name, children)

    def routes_for_stop(self, stop_area: StopArea) -> list[Route]:
        """Return routes that have at least one trip through the stop."""
        stop_ids = set(stop_area.stop_ids)
        trip_ids = {
            row["trip_id"]
            for row in self._read("stop_times.txt")
            if row["stop_id"] in stop_ids
        }
        route_ids = {
            self.trips_by_id[trip_id].route_id
            for trip_id in trip_ids
            if trip_id in self.trips_by_id
        }
        return sorted(
            (self.routes_by_id[value] for value in route_ids),
            key=lambda route: (route.route_type != 0, route.short_name),
        )

    def scheduled_stop_times(
        self, stop_area: StopArea, route_ids: set[str]
    ) -> list[ScheduledStopTime]:
        """Return only times needed for the selected stop and routes."""
        stop_ids = set(stop_area.stop_ids)
        trip_ids = {
            trip_id
            for trip_id, trip in self.trips_by_id.items()
            if trip.route_id in route_ids
        }
        result: list[ScheduledStopTime] = []
        for row in self._read("stop_times.txt"):
            if row["stop_id"] not in stop_ids or row["trip_id"] not in trip_ids:
                continue
            value = row.get("departure_time") or row.get("arrival_time")
            try:
                result.append(
                    ScheduledStopTime(row["trip_id"], row["stop_id"], _gtfs_seconds(value))
                )
            except (TypeError, ValueError):
                continue
        return result

    def active_services(self, service_date: date) -> set[str]:
        """Resolve calendar and exception rules for a date."""
        ymd = service_date.strftime("%Y%m%d")
        weekday = service_date.strftime("%A").lower()
        active = {
            row["service_id"]
            for row in self._read("calendar.txt")
            if row.get("start_date", "") <= ymd <= row.get("end_date", "")
            and row.get(weekday) == "1"
        }
        for row in self._read("calendar_dates.txt"):
            if row.get("date") != ymd:
                continue
            if row.get("exception_type") == "1":
                active.add(row["service_id"])
            elif row.get("exception_type") == "2":
                active.discard(row["service_id"])
        return active


class TisseoResolver(AbstractResolver):
    """Use normal DNS first, with a verified-HTTPS fallback for HA DNS outages."""

    def __init__(self) -> None:
        self._default = DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[dict[str, object]]:
        try:
            return await self._default.resolve(host, port, family)
        except OSError:
            if not (addresses := PINNED_DNS.get(host)):
                raise
            return [
                {
                    "hostname": host,
                    "host": address,
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": socket.AI_NUMERICHOST,
                }
                for address in addresses
            ]

    async def close(self) -> None:
        await self._default.close()


class TisseoClient:
    """Download and combine Tisséo static and real-time information."""

    def __init__(self) -> None:
        self._session = ClientSession(
            connector=TCPConnector(resolver=TisseoResolver(), ttl_dns_cache=3600)
        )
        self.static: StaticFeed | None = None
        self._etag: str | None = None
        self._last_realtime: bytes | None = None

    async def async_close(self) -> None:
        """Close the dedicated verified-HTTPS session."""
        await self._session.close()

    async def async_load_static(self) -> StaticFeed:
        """Download the official static feed."""
        try:
            async with self._session.get(STATIC_GTFS_URL, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                content = await response.read()
        except (ClientError, TimeoutError) as err:
            raise TisseoConnectionError("Téléchargement GTFS impossible") from err
        try:
            self.static = StaticFeed(content)
        except (KeyError, UnicodeError, BadZipFile) as err:
            raise TisseoFeedError("Lecture GTFS impossible") from err
        return self.static

    async def async_realtime(self) -> bytes:
        """Download GTFS-RT, using Tisséo's ETag as recommended."""
        headers = {"If-None-Match": self._etag} if self._etag else {}
        try:
            async with self._session.get(
                REALTIME_GTFS_URL, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 304 and self._last_realtime is not None:
                    return self._last_realtime
                response.raise_for_status()
                self._etag = response.headers.get("ETag")
                self._last_realtime = await response.read()
                return self._last_realtime
        except (ClientError, TimeoutError) as err:
            raise TisseoConnectionError("Téléchargement GTFS-RT impossible") from err


def realtime_departures(
    content: bytes,
    static: StaticFeed,
    stop_area: StopArea,
    route_ids: set[str],
    now: datetime,
    horizon: timedelta,
) -> list[Departure]:
    """Decode upcoming real-time stop updates."""
    stop_ids = set(stop_area.stop_ids)
    end = now + horizon
    result: list[Departure] = []
    try:
        entities = _message_values(content, 2)
    except ValueError as err:
        raise TisseoFeedError("Flux GTFS-RT invalide") from err
    for entity in entities:
        trip_updates = _message_values(entity, 3)
        if not trip_updates:
            continue
        trip_update = trip_updates[0]
        trip_messages = _message_values(trip_update, 1)
        if not trip_messages:
            continue
        descriptor = trip_messages[0]
        trip_id = _string_value(descriptor, 1)
        route_id = _string_value(descriptor, 5)
        if route_id not in route_ids:
            continue
        trip = static.trips_by_id.get(trip_id)
        route = static.routes_by_id.get(route_id)
        if route is None:
            continue
        for update in _message_values(trip_update, 2):
            stop_id = _string_value(update, 4)
            if stop_id not in stop_ids:
                continue
            # Arrival is the useful passage time at a terminus; elsewhere the
            # arrival/departure difference is normally only a few seconds.
            arrival = _first_message(update, 2)
            departure = _first_message(update, 3)
            timestamp = _varint_value(arrival, 2) or _varint_value(departure, 2)
            if not timestamp:
                continue
            when = datetime.fromtimestamp(timestamp, PARIS)
            if now - timedelta(minutes=1) <= when <= end:
                result.append(
                    Departure(
                        route_id,
                        route.short_name,
                        trip.headsign if trip else "Destination inconnue",
                        stop_id,
                        when,
                        True,
                        trip_id,
                    )
                )
    return result


def scheduled_departures(
    static: StaticFeed,
    stop_times: list[ScheduledStopTime],
    now: datetime,
    horizon: timedelta,
) -> list[Departure]:
    """Build theoretical passages, including times after 24:00."""
    result: list[Departure] = []
    end = now + horizon
    for service_day in (now.date() - timedelta(days=1), now.date()):
        active = static.active_services(service_day)
        midnight = datetime.combine(service_day, datetime.min.time(), PARIS)
        for stop_time in stop_times:
            trip = static.trips_by_id.get(stop_time.trip_id)
            if trip is None or trip.service_id not in active:
                continue
            when = midnight + timedelta(seconds=stop_time.seconds)
            if not now <= when <= end:
                continue
            route = static.routes_by_id[trip.route_id]
            result.append(
                Departure(
                    trip.route_id,
                    route.short_name,
                    trip.headsign,
                    stop_time.stop_id,
                    when,
                    False,
                    stop_time.trip_id,
                )
            )
    return result


def merge_departures(
    realtime: list[Departure], theoretical: list[Departure]
) -> list[Departure]:
    """Prefer real-time information for the same trip and platform."""
    realtime_keys = {(item.trip_id, item.stop_id) for item in realtime}
    merged = realtime + [
        item
        for item in theoretical
        if (item.trip_id, item.stop_id) not in realtime_keys
    ]
    return sorted(merged, key=lambda item: item.when)


def _gtfs_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _fold(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value).casefold()
        if not unicodedata.combining(char)
    )


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    """Read one unsigned protobuf varint without a third-party dependency."""
    value = 0
    shift = 0
    while position < len(data) and shift < 70:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise ValueError("varint protobuf invalide")


def _protobuf_fields(data: bytes):
    """Yield (field number, wire type, value) from a protobuf message."""
    position = 0
    while position < len(data):
        key, position = _read_varint(data, position)
        field_number, wire_type = key >> 3, key & 7
        if field_number == 0:
            raise ValueError("champ protobuf invalide")
        if wire_type == 0:
            value, position = _read_varint(data, position)
        elif wire_type == 1:
            if position + 8 > len(data):
                raise ValueError("fixed64 protobuf tronqué")
            value = data[position : position + 8]
            position += 8
        elif wire_type == 2:
            size, position = _read_varint(data, position)
            if position + size > len(data):
                raise ValueError("message protobuf tronqué")
            value = data[position : position + size]
            position += size
        elif wire_type == 5:
            if position + 4 > len(data):
                raise ValueError("fixed32 protobuf tronqué")
            value = data[position : position + 4]
            position += 4
        else:
            raise ValueError(f"type protobuf non pris en charge : {wire_type}")
        yield field_number, wire_type, value


def _message_values(data: bytes, field_number: int) -> list[bytes]:
    return [
        value
        for number, wire_type, value in _protobuf_fields(data)
        if number == field_number and wire_type == 2 and isinstance(value, bytes)
    ]


def _first_message(data: bytes, field_number: int) -> bytes:
    values = _message_values(data, field_number)
    return values[0] if values else b""


def _string_value(data: bytes, field_number: int) -> str:
    values = _message_values(data, field_number)
    return values[0].decode("utf-8") if values else ""


def _varint_value(data: bytes, field_number: int) -> int:
    if not data:
        return 0
    return next(
        (
            int(value)
            for number, wire_type, value in _protobuf_fields(data)
            if number == field_number and wire_type == 0
        ),
        0,
    )
