"""Constants for the Tisséo integration."""

from datetime import timedelta

DOMAIN = "tisseo"
PLATFORMS = ["sensor"]

CONF_STOP_AREA_ID = "stop_area_id"
CONF_STOP_NAME = "stop_name"
CONF_ROUTE_IDS = "route_ids"
CONF_ROUTE_OPTIONS = "route_options"
CONF_FAVORITE_ROUTE_ID = "favorite_route_id"
CONF_FAVORITE_DIRECTION = "favorite_direction"
CONF_MAX_DEPARTURES = "max_departures"
CONF_REFRESH_SECONDS = "refresh_seconds"

DEFAULT_STOP_QUERY = "Aéroconstellation"
DEFAULT_MAX_DEPARTURES = 5
DEFAULT_REFRESH_SECONDS = 30
MIN_REFRESH_SECONDS = 15
MAX_REFRESH_SECONDS = 300

STATIC_GTFS_URL = (
    "https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/"
    "tisseo-gtfs/alternative_exports/utf_8tisseo_gtfs_v2_zip"
)
REALTIME_GTFS_URL = (
    "https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/"
    "tisseo-gtfs/alternative_exports/https_api_tisseo_fr_opendata_gtfsrt_gtfsrt_pb"
)
STATIC_REFRESH_INTERVAL = timedelta(hours=6)
