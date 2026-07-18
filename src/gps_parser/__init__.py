import configparser
import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple, Union
# import shutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Passive-station schema (stations.cfg role/flag fields)
# ---------------------------------------------------------------------------
#
# stations.cfg carries three optional per-station keys describing the
# station's role in the processing network (see
# gpslibrary/GLOBAL_SITES_investigation.md):
#
#   station_role      = active | passive     (default: active)
#   is_reference_site = true | false         (default: false)
#   is_in_iceland     = true | false         (default: true)
#
# ``station_role = passive`` marks data-source-only stations (reference-frame
# ties / regional context series from the GLOBK processing) that IMO does not
# operate: they carry no receiver/router/connection keys, and every
# operational consumer (receivers scheduler + DB seeder, tostools fleet ops,
# cfg reconcile, aflogun catalog) must skip them. Consumers should treat a
# missing ``station_role`` as ``active`` (the pre-schema status quo).
#
# NOTE: distinct from the pre-existing ``health_check = passive`` key, which
# means "operated station, but don't actively poll health" — an unrelated
# concept that happens to share the word.

STATION_ROLE_ACTIVE = "active"
STATION_ROLE_PASSIVE = "passive"
STATION_ROLES = (STATION_ROLE_ACTIVE, STATION_ROLE_PASSIVE)

_BOOL_TRUE = {"true", "yes", "1", "on"}
_BOOL_FALSE = {"false", "no", "0", "off"}


def parse_config_bool(value: Any, default: bool = False) -> bool:
    """Parse a stations.cfg boolean field (``is_reference_site`` etc.).

    Accepts true/false, yes/no, 1/0, on/off (case-insensitive); ``None`` or
    empty string returns ``default``. Raises ``ValueError`` for anything else
    so validation surfaces typos instead of silently defaulting.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).split("#")[0].strip().lower()
    if not text:
        return default
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    raise ValueError(f"Not a boolean config value: {value!r}")


def parse_station_role(value: Any) -> str:
    """Parse a raw stations.cfg ``station_role`` value — THE canonical parser.

    This is the single source of truth for role parsing across the
    ecosystem (receivers, tostools, aflogun import it) — do not copy the
    logic elsewhere. Operates on a raw string so batch readers (plain
    ``configparser`` loops) can use it without building a full
    :class:`ConfigParser`.

    Semantics:
      * ``None`` / empty / whitespace → ``"active"`` (pre-schema status quo)
      * inline ``# comments`` stripped, case-insensitive
      * unknown values → ``"active"`` with a warning (fail-OPEN: a typo
        must never drop an operated station from the schedulers;
        ``validateStationConfig`` flags the bad value for correction)
    """
    role = str(value or "").split("#")[0].strip().lower()
    if role in STATION_ROLES:
        return role
    if role:
        logger.warning("Unknown station_role %r — treating as 'active'", value)
    return STATION_ROLE_ACTIVE


# ---------------------------------------------------------------------------
# Module-level parsed-config cache
# ---------------------------------------------------------------------------
#
# Every ``ConfigParser()`` used to fully re-parse stations.cfg (~4565 lines,
# ~196 sections) TWICE — once through ``configparser.read()`` and once through
# the pure-Python duplicate-key line scan — plus postprocess.cfg, on every
# construction. Measured at ~13-19 ms per construction, which was ~58% of the
# cumulative wall time of a full 173-station .NEU fleet run (see the
# 2026-07-11 I/O perf audit, finding F1). Callers across the ecosystem
# construct one ``ConfigParser`` per station (geo_dataread.openGlobkTimes,
# gps_plot.timesmatplt plot loop, ...), so the parse is memoized here, at the
# single in-scope choke point, and every caller benefits unchanged.
#
# Cache key / invalidation rationale:
#   * keyed on the *resolved* absolute paths of both config files, so a
#     GPS_CONFIG_PATH change (or symlink retarget) is a different entry;
#   * validated against a per-file signature ``(st_mtime_ns, st_size)``.
#     Plain ``st_mtime`` (seconds) is NOT enough: many filesystems store
#     coarse timestamps, so a rewrite landing within the same second as the
#     previous one would be invisible and serve a stale parse. ``st_mtime_ns``
#     catches sub-second rewrites where the filesystem records them, and
#     ``st_size`` additionally catches rewrites that a coarse-granularity
#     filesystem timestamps identically but that change the file length.
#     Any signature mismatch (including a file appearing/disappearing, which
#     flips the signature to/from ``None``) forces a full re-parse.
#
# The cached ``configparser.ConfigParser`` object is SHARED between all
# ``ConfigParser`` instances reading the same unchanged files. It must be
# treated as read-only; every accessor in this package only reads it.

# Per-file signature: (st_mtime_ns, st_size), or None if the file is missing.
_FileSignature = Optional[Tuple[int, int]]
# (stations signature, postprocess signature) -> parsed config
_CacheEntry = Tuple[Tuple[_FileSignature, _FileSignature], configparser.ConfigParser]

_config_cache: Dict[Tuple[str, str], _CacheEntry] = {}
_config_cache_lock = threading.Lock()


def _file_signature(path: str) -> _FileSignature:
    """Return the cache-invalidation signature ``(st_mtime_ns, st_size)``.

    Returns None when the file cannot be stat'ed (missing file), which is
    itself a valid signature state: it differs from any existing-file
    signature, so a file appearing later invalidates the cached parse.
    See the module-level cache comment for why mtime alone is insufficient.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def clear_config_cache() -> None:
    """Drop all memoized parsed configurations (primarily for tests)."""
    with _config_cache_lock:
        _config_cache.clear()


def _warn_duplicate_keys(cfg_path: str) -> None:
    """Scan a config file for duplicate keys and log warnings.

    With strict=False the parser silently takes the last value.
    This function detects those duplicates so operators can fix them.

    Runs once per cached parse (i.e. once per (path, mtime_ns, size)
    combination), not on every ``ConfigParser()`` construction — the scan
    alone re-read all ~4565 lines of stations.cfg per construction before
    the cache was introduced. Which key wins on a duplicate is unchanged
    (last value, decided by configparser itself); only the scan frequency
    changed.
    """
    try:
        seen: Dict[str, Dict[str, int]] = {}  # section -> {key -> line_number}
        current_section = None
        with open(cfg_path, "r") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                    continue
                if stripped.startswith("[") and "]" in stripped:
                    current_section = stripped[1 : stripped.index("]")]
                    if current_section not in seen:
                        seen[current_section] = {}
                    continue
                if current_section and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in seen[current_section]:
                        logger.warning(
                            "Duplicate key '%s' in [%s] at line %d "
                            "(first at line %d) in %s — using last value",
                            key,
                            current_section,
                            lineno,
                            seen[current_section][key],
                            cfg_path,
                        )
                    else:
                        seen[current_section][key] = lineno
    except Exception:
        pass  # Don't let duplicate detection break initialization


def _parse_config_files(
    stations_path: str, postprocess_path: str
) -> configparser.ConfigParser:
    """Parse stations.cfg + postprocess.cfg into one configparser (uncached).

    Identical read order and parser options to the pre-cache
    ``ConfigParser.__init__`` body, so the parsed values are byte-for-byte
    the same as before the cache existed.
    """
    # strict=False: duplicate keys resolve to last value instead of
    # crashing the entire config parse (which blocks ALL stations)
    config = configparser.ConfigParser(
        interpolation=configparser.ExtendedInterpolation(),
        strict=False,
    )

    # Reading the stations.cfg file
    config.read(stations_path)

    # Check for duplicate keys (warn but don't crash thanks to strict=False)
    _warn_duplicate_keys(stations_path)

    # Reading the postprocess.cfg file
    config.read(postprocess_path)

    return config


def _get_parsed_config(
    stations_path: str, postprocess_path: str
) -> configparser.ConfigParser:
    """Memoized parse of the two config files.

    Returns the already-parsed shared ``configparser.ConfigParser`` when both
    files are unchanged since the last parse (signature match); re-parses and
    replaces the cache entry when either file changed. The signatures are
    taken BEFORE parsing, so a write racing the parse can only make the
    cached entry look older than it is — the next construction then re-parses
    (never serves content newer than its recorded signature as stale-fresh).
    """
    key = (os.path.realpath(stations_path), os.path.realpath(postprocess_path))
    signature = (_file_signature(stations_path), _file_signature(postprocess_path))

    with _config_cache_lock:
        entry = _config_cache.get(key)
        if entry is not None and entry[0] == signature:
            return entry[1]

    # Parse outside the lock: a concurrent race parses twice (harmless, both
    # results identical) instead of serializing all constructions on file I/O.
    config = _parse_config_files(stations_path, postprocess_path)

    with _config_cache_lock:
        _config_cache[key] = (signature, config)

    return config


class ConfigParser:
    def __init__(self):
        # Setting up the working directories
        self.config_path = os.environ.get("GPS_CONFIG_PATH")
        if self.config_path is None:
            # [INFO:] if GPS_CONFIG_PATH is not set make ~/.gpsconfig/gpsconfig as default
            home = os.path.expanduser("~")
            self.config_path = os.path.join(home, ".config", "gpsconfig")

        if not os.path.isdir(self.config_path):
            raise Exception(
                f"Directory '{self.config_path}' does not exist.\nPlease create the "
                + "directory or provide a path to the config files trough GPS_CONFIG_PATH variable\n"
                + "Make sure the relevant config files are precent in the directory.\n"
                + "you can run the script script/setup-config.sh "
                + "to create the directory and copy example files"
            )

        # print(self.config_path)
        self.dest_stations_config_path = os.path.join(self.config_path, "stations.cfg")
        self.dest_postprocess_config_path = os.path.join(
            self.config_path, "postprocess.cfg"
        )

        # Memoized: repeated constructions over unchanged files share one
        # parsed config instead of re-parsing ~4565 lines per station
        # (~13-19 ms each, ~58% of a 173-station fleet run pre-cache).
        self.config = _get_parsed_config(
            self.dest_stations_config_path, self.dest_postprocess_config_path
        )

    def _warn_duplicate_keys(self, cfg_path: str) -> None:
        """Backward-compatible shim for the module-level scan (see above)."""
        _warn_duplicate_keys(cfg_path)

    # Establishing the methods usable through the package to interact with the cparser module
    def get_config(self, section, option):
        """
        This function gets a configuration option from the 'stations.cfg' file.
        """
        # Getting the configuration option
        return self.config.get(section, option)

    def get_stations_config_path(self):
        """
        This function returns the path to the 'stations.cfg' file.
        """
        return self.dest_stations_config_path

    def get_postprocess_config_path(self):
        """
        This function returns the path to the 'postprocess.cfg' file.
        """

        return self.dest_postprocess_config_path

    def getStationInfo(self, station_id: str = ""):
        """
        This function gets station information from the 'stations.cfg' file.
        """
        # Read the 'station' section from the 'stations.cfg' file

        if station_id == "":
            return [
                section
                for section in self.config.sections()
                if section not in ["Configs"]
            ]
        elif self.config.has_section(station_id):
            station_info = dict(self.config.items(station_id))

            # Strip inline comments (# ...) from all values
            # This fixes the bug where IP addresses like "10.4.1.251 # 18.8.2022"
            # would include the comment, causing DNS resolution failures
            cleaned_info = {}
            for key, value in station_info.items():
                # Remove everything after # and strip whitespace
                cleaned_value = value.split("#")[0].strip()
                cleaned_info[key] = cleaned_value

            return {"station": cleaned_info}
        else:
            raise Exception(f"Station '{station_id}' not found in 'stations.cfg' file.")

    def getStationRole(self, station_id: str) -> str:
        """Return the station's role: ``"active"`` or ``"passive"``.

        Thin section-aware wrapper over the canonical module-level
        :func:`parse_station_role` (missing key → active; unknown values
        fail OPEN to active with a warning).
        """
        station_upper = station_id.upper()
        if not self.config.has_section(station_upper):
            raise Exception(
                f"Station '{station_upper}' not found in 'stations.cfg' file."
            )
        return parse_station_role(
            self.config.get(station_upper, "station_role", fallback="")
        )

    def isPassiveStation(self, station_id: str) -> bool:
        """True when ``station_role = passive`` (data-source-only station)."""
        return self.getStationRole(station_id) == STATION_ROLE_PASSIVE

    def getPostProcessDir(self, option):
        # Check PATHS section first
        if self.config.has_section("PATHS") and self.config.has_option("PATHS", option):
            return os.path.expanduser(self.config.get("PATHS", option))

        # Check legacy Configs section for backward compatibility
        if self.config.has_section("Configs") and self.config.has_option(
            "Configs", option
        ):
            return os.path.expanduser(self.config.get("Configs", option))

        raise Exception(
            f"Option '{option}' not found in [PATHS] or [Configs] sections of the postprocess configuration file."
        )

    def getPostProcessConfig(self, option):
        """
        This function gets file paths from the 'postprocess.cfg' file.
        """
        # Read the 'Configs' section from the 'postprocess.cfg' file
        if self.config.has_section("FILES"):
            if self.config.has_option("FILES", option):
                filename = self.config.get("FILES", option)
                config_dir = self.config_path
                return os.path.join(config_dir, filename)
                # return os.path.expanduser(self.config.get("FILES", option))
        raise Exception(
            f"Option '{option}' not found in 'FILES' section of the postprocess configuration file."
        )

    # ==============================================================================
    # ENHANCED CONFIGURATION METHODS (v0.4.0)
    # ==============================================================================

    def getStationTimeout(self, station_id: str) -> Dict[str, int]:
        """
        Get timeout configuration for a station based on its timeout category.

        Args:
            station_id: Station identifier (e.g., 'ELDC')

        Returns:
            Dictionary with timeout values: connection_timeout, inactivity_timeout,
            progress_timeout, min_speed_threshold

        Raises:
            Exception: If station not found or timeout configuration missing
        """
        station_upper = station_id.upper()

        # Get station info to determine timeout category
        if not self.config.has_section(station_upper):
            raise Exception(f"Station '{station_upper}' not found in stations.cfg")

        # Check for station-specific timeout overrides first
        timeout_config = {}
        for timeout_field in [
            "connection_timeout",
            "inactivity_timeout",
            "progress_timeout",
            "min_speed_threshold",
        ]:
            if self.config.has_option(station_upper, timeout_field):
                timeout_config[timeout_field] = int(
                    self.config.get(station_upper, timeout_field)
                )

        # If we have complete overrides, return them
        if len(timeout_config) == 4:
            return timeout_config

        # Otherwise, get timeout category and apply defaults
        timeout_category = self.config.get(
            station_upper, "timeout_category", fallback="mobile"
        )

        if not self.config.has_section("TIMEOUT_CATEGORIES"):
            # Fallback defaults if TIMEOUT_CATEGORIES section missing
            defaults = {
                "fixed_wired": (10, 30, 180, 8192),
                "mobile": (20, 60, 300, 2048),
                "very_remote": (30, 120, 600, 1024),
            }
            if timeout_category in defaults:
                conn, inact, prog, speed = defaults[timeout_category]
            else:
                conn, inact, prog, speed = defaults["mobile"]  # Default to mobile
        else:
            # Parse category configuration
            if not self.config.has_option("TIMEOUT_CATEGORIES", timeout_category):
                timeout_category = "mobile"  # Fallback to mobile

            category_config = self.config.get("TIMEOUT_CATEGORIES", timeout_category)
            try:
                conn, inact, prog, speed = map(int, category_config.split(","))
            except ValueError:
                raise Exception(
                    f"Invalid timeout configuration for category '{timeout_category}': {category_config}"
                )

        # Apply category defaults, but use any station-specific overrides
        result = {
            "connection_timeout": timeout_config.get("connection_timeout", conn),
            "inactivity_timeout": timeout_config.get("inactivity_timeout", inact),
            "progress_timeout": timeout_config.get("progress_timeout", prog),
            "min_speed_threshold": timeout_config.get("min_speed_threshold", speed),
        }

        return result

    def getStationFtpMode(self, station_id: str, router_ip: str) -> str:
        """
        Determine FTP mode for a station based on explicit config or network rules.

        Args:
            station_id: Station identifier (e.g., 'ELDC')
            router_ip: Router IP address (e.g., '10.6.1.90')

        Returns:
            FTP mode: 'active', 'passive', or 'auto'

        Raises:
            Exception: If station not found
        """
        station_upper = station_id.upper()

        if not self.config.has_section(station_upper):
            raise Exception(f"Station '{station_upper}' not found in stations.cfg")

        # Check for explicit ftp_mode setting first
        if self.config.has_option(station_upper, "ftp_mode"):
            ftp_mode = self.config.get(station_upper, "ftp_mode").lower()
            if ftp_mode in ["active", "passive", "auto"]:
                return ftp_mode

        # Apply network rules based on IP address
        if self.config.has_section("NETWORK_RULES"):
            # Check IP range rules
            if router_ip.startswith("10.4."):
                return self.config.get(
                    "NETWORK_RULES", "ip_range_10_4", fallback="active"
                )
            elif router_ip.startswith("10.6."):
                return self.config.get(
                    "NETWORK_RULES", "ip_range_10_6", fallback="passive"
                )
            else:
                # Domain or other IP ranges
                return self.config.get(
                    "NETWORK_RULES", "domain_default", fallback="auto"
                )

        # Fallback logic if no NETWORK_RULES section
        if router_ip.startswith("10.4."):
            return "active"  # Internal IMO network
        elif router_ip.startswith("10.6."):
            return "passive"  # Extended network
        else:
            return "auto"  # Domain-based or unknown ranges

    def getSessionConfig(self, session_type: str) -> Dict[str, str]:
        """
        Get session configuration for a given session type.

        Args:
            session_type: Session type (e.g., '15s_24hr', '1Hz_1hr', 'status_1hr')

        Returns:
            Dictionary with session_letter, session_path, receiver_path

        Raises:
            Exception: If session type not found
        """
        if not self.config.has_section("SESSIONS"):
            # Fallback defaults if SESSIONS section missing
            defaults = {
                "15s_24hr": ("a", "LOG1_15s_24hr", "/DSK1/SSN/"),
                "1Hz_1hr": ("b", "LOG2_1Hz_1hr", "/DSK1/SSN/"),
                "status_1hr": ("b", "LOG5_status_1hr", "/DSK1/SSN/"),
            }
            if session_type in defaults:
                letter, path, receiver_path = defaults[session_type]
                return {
                    "session_letter": letter,
                    "session_path": path,
                    "receiver_path": receiver_path,
                }
            else:
                raise Exception(f"Unknown session type '{session_type}'")

        if not self.config.has_option("SESSIONS", session_type):
            raise Exception(
                f"Session type '{session_type}' not found in SESSIONS configuration"
            )

        session_config = self.config.get("SESSIONS", session_type)
        try:
            letter, path, receiver_path = session_config.split(",")
            return {
                "session_letter": letter.strip(),
                "session_path": path.strip(),
                "receiver_path": receiver_path.strip(),
            }
        except ValueError:
            raise Exception(
                f"Invalid session configuration for '{session_type}': {session_config}"
            )

    def getSystemPath(self, path_name: str) -> str:
        """
        Get system tool path from configuration.

        Args:
            path_name: Path identifier (e.g., 'bin2asc_path', 'sbf2rin_path', 'data_prepath')

        Returns:
            Expanded path string

        Raises:
            Exception: If path not found in configuration
        """
        # Check PATHS section first
        if self.config.has_section("PATHS") and self.config.has_option(
            "PATHS", path_name
        ):
            path = self.config.get("PATHS", path_name)
            return os.path.expanduser(path)

        # Check legacy Configs section for backward compatibility
        if self.config.has_section("Configs") and self.config.has_option(
            "Configs", path_name
        ):
            path = self.config.get("Configs", path_name)
            return os.path.expanduser(path)

        # Fallback defaults for critical paths
        defaults = {
            "bin2asc_path": "/opt/rxtools/bin/bin2asc",
            "sbf2rin_path": "/home/gpsops/bin/sbf2rin",
            "teqc_path": "/home/gpsops/bin/teqc",
            "data_prepath": "./data/",
            "receiver_base_path": "/DSK1/SSN/",
        }

        if path_name in defaults:
            return defaults[path_name]

        raise Exception(f"System path '{path_name}' not found in configuration")

    def getDefaultValue(self, setting_name: str) -> Union[str, int, float]:
        """
        Get default value for CLI or application settings.

        Args:
            setting_name: Setting identifier (e.g., 'default_days_back', 'default_session')

        Returns:
            Default value (type depends on setting)

        Raises:
            Exception: If setting not found in configuration
        """
        # Check DEFAULTS section
        if self.config.has_section("DEFAULTS") and self.config.has_option(
            "DEFAULTS", setting_name
        ):
            value = self.config.get("DEFAULTS", setting_name)

            # Convert to appropriate type based on setting name
            if (
                setting_name.endswith("_days")
                or setting_name.endswith("_retries")
                or setting_name.endswith("_timeout")
            ):
                return int(value)
            elif setting_name.endswith("_threshold"):
                return float(value)
            else:
                return value  # String value

        # Fallback defaults
        defaults = {
            "default_days_back": 10,
            "default_session": "15s_24hr",
            "default_compression": ".gz",
            "default_end_offset_days": 1,
            "health_extraction_pattern": "*.sbf*",
            "health_output_formats": "csv,jsonl",
            "ftp_connection_retries": 3,
            "ftp_transfer_timeout": 300,
        }

        if setting_name in defaults:
            return defaults[setting_name]

        raise Exception(f"Default value '{setting_name}' not found in configuration")

    def validateStationConfig(self, station_id: str) -> Dict[str, Any]:
        """
        Validate that a station has required configuration fields.

        Args:
            station_id: Station identifier (e.g., 'ELDC')

        Returns:
            Dictionary with validation results: {
                'valid': bool,
                'errors': list,
                'warnings': list,
                'config': dict
            }
        """
        station_upper = station_id.upper()
        result = {"valid": True, "errors": [], "warnings": [], "config": {}}

        # Check if station section exists
        if not self.config.has_section(station_upper):
            result["valid"] = False
            result["errors"].append(
                f"Station '{station_upper}' not found in stations.cfg"
            )
            return result

        # Role / flag schema fields (validated for every station)
        raw_role = (
            (self.config.get(station_upper, "station_role", fallback="") or "")
            .split("#")[0]
            .strip()
            .lower()
        )
        if raw_role and raw_role not in STATION_ROLES:
            result["valid"] = False
            result["errors"].append(
                f"Invalid station_role '{raw_role}' for station "
                f"'{station_upper}' (expected one of {STATION_ROLES})"
            )
        is_passive = raw_role == STATION_ROLE_PASSIVE
        result["config"]["station_role"] = raw_role or STATION_ROLE_ACTIVE

        for bool_field, bool_default in (
            ("is_reference_site", False),
            ("is_in_iceland", True),
        ):
            raw_bool = self.config.get(station_upper, bool_field, fallback=None)
            try:
                result["config"][bool_field] = parse_config_bool(raw_bool, bool_default)
            except ValueError:
                result["valid"] = False
                result["errors"].append(
                    f"Invalid boolean '{raw_bool}' for field '{bool_field}' "
                    f"of station '{station_upper}'"
                )

        # Required fields — only for operated (active-role) stations. Passive
        # stations are data-source descriptors: no receiver/router keys by
        # design, so requiring connection fields would be a contradiction.
        required_fields = ["router_ip", "receiver_ftpport", "receiver_type"]
        optional_fields = [
            "timeout_category",
            "ftp_mode",
            "connection_type",
            "router_type",
        ]

        if is_passive:
            for field in required_fields:
                if self.config.has_option(station_upper, field):
                    result["warnings"].append(
                        f"Passive station '{station_upper}' carries operational "
                        f"field '{field}' — passive stations are data-source-only"
                    )
        else:
            # Check required fields
            for field in required_fields:
                if self.config.has_option(station_upper, field):
                    result["config"][field] = self.config.get(station_upper, field)
                else:
                    result["valid"] = False
                    result["errors"].append(
                        f"Missing required field '{field}' for station '{station_upper}'"
                    )

        # Check optional fields and warn if missing
        for field in optional_fields:
            if self.config.has_option(station_upper, field):
                result["config"][field] = self.config.get(station_upper, field)
            else:
                result["warnings"].append(
                    f"Optional field '{field}' not set for station '{station_upper}'"
                )

        # Validate field values
        if "receiver_ftpport" in result["config"]:
            try:
                port = int(result["config"]["receiver_ftpport"])
                if not (1 <= port <= 65535):
                    result["errors"].append(
                        f"Invalid FTP port {port} for station '{station_upper}'"
                    )
                    result["valid"] = False
            except ValueError:
                result["errors"].append(
                    f"Invalid FTP port format for station '{station_upper}': {result['config']['receiver_ftpport']}"
                )
                result["valid"] = False

        # Validate timeout category if present
        if "timeout_category" in result["config"]:
            valid_categories = ["fixed_wired", "mobile", "very_remote"]
            if result["config"]["timeout_category"] not in valid_categories:
                result["warnings"].append(
                    f"Unknown timeout category '{result['config']['timeout_category']}' for station '{station_upper}', will use 'mobile'"
                )

        # Validate FTP mode if present
        if "ftp_mode" in result["config"]:
            valid_modes = ["active", "passive", "auto"]
            if result["config"]["ftp_mode"] not in valid_modes:
                result["warnings"].append(
                    f"Unknown FTP mode '{result['config']['ftp_mode']}' for station '{station_upper}', will use network rules"
                )

        return result
