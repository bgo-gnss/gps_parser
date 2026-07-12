"""
Tests for the module-level parsed-config cache in gps_parser.

The cache memoizes the parsed stations.cfg + postprocess.cfg keyed on
(resolved path, st_mtime_ns, st_size). These tests pin the two properties
that matter:

- repeated constructions over UNCHANGED files share a single parse
  (the underlying files are read exactly once), and
- ANY change to a file (content+size, size-preserving content with an
  mtime bump, or the file appearing) invalidates the cache and the new
  values are returned — never the stale parse.
"""

import os
from unittest.mock import patch

import pytest

import gps_parser


STATIONS_V1 = """# test stations configuration
[THEY]
Station_NAME = Þorvaldseyri
router_ip = 157.157.40.186
receiver_type = NetR9
"""

POSTPROCESS_V1 = """[FILES]
coordFile = station_coord.xyz

[PATHS]
totPath = /mnt/gpsdata/
"""


@pytest.fixture(autouse=True)
def _isolated_cache():
    """Each test starts and ends with an empty parse cache."""
    gps_parser.clear_config_cache()
    yield
    gps_parser.clear_config_cache()


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def _bump_mtime(path, delta_ns=2_000_000_000):
    """Force an mtime bump so invalidation does not depend on filesystem
    timestamp granularity (a rewrite can land within the same coarse
    timestamp tick as the original write)."""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + delta_ns))


@pytest.fixture
def cfg_dir(tmp_path):
    _write(tmp_path / "stations.cfg", STATIONS_V1)
    _write(tmp_path / "postprocess.cfg", POSTPROCESS_V1)
    with patch.dict(os.environ, {"GPS_CONFIG_PATH": str(tmp_path)}):
        yield tmp_path


class TestCacheSharing:
    def test_unchanged_files_parsed_exactly_once(self, cfg_dir, monkeypatch):
        """Two ConfigParser() over the same unchanged files share one parse."""
        calls = []
        real_parse = gps_parser._parse_config_files

        def counting_parse(stations_path, postprocess_path):
            calls.append((stations_path, postprocess_path))
            return real_parse(stations_path, postprocess_path)

        monkeypatch.setattr(gps_parser, "_parse_config_files", counting_parse)

        p1 = gps_parser.ConfigParser()
        p2 = gps_parser.ConfigParser()

        # the underlying files were read+parsed once, not twice
        assert len(calls) == 1
        # both instances share the identical parsed structure
        assert p1.config is p2.config
        # and return the same values through the public API
        assert p1.get_config("THEY", "router_ip") == "157.157.40.186"
        assert p2.get_config("THEY", "router_ip") == "157.157.40.186"
        assert p1.getStationInfo("THEY") == p2.getStationInfo("THEY")
        assert p1.getPostProcessDir("totPath") == "/mnt/gpsdata/"

    def test_duplicate_key_scan_runs_once_per_parse(self, cfg_dir, monkeypatch):
        """The duplicate-key line scan is tied to the cached parse, not to
        every construction; it re-runs after the file changes."""
        scans = []
        real_scan = gps_parser._warn_duplicate_keys

        def counting_scan(cfg_path):
            scans.append(cfg_path)
            return real_scan(cfg_path)

        monkeypatch.setattr(gps_parser, "_warn_duplicate_keys", counting_scan)

        gps_parser.ConfigParser()
        gps_parser.ConfigParser()
        assert len(scans) == 1  # once per parse, not per construction

        stations = cfg_dir / "stations.cfg"
        _write(stations, STATIONS_V1 + "\n# changed\n")
        _bump_mtime(stations)

        gps_parser.ConfigParser()
        assert len(scans) == 2  # file changed -> fresh parse -> fresh scan


class TestCacheInvalidation:
    def test_file_change_returns_new_value_not_stale_cache(self, cfg_dir):
        """Rewrite with a changed value + bumped mtime -> new value served."""
        p1 = gps_parser.ConfigParser()
        assert p1.get_config("THEY", "router_ip") == "157.157.40.186"

        stations = cfg_dir / "stations.cfg"
        _write(stations, STATIONS_V1.replace("157.157.40.186", "10.99.99.99"))
        _bump_mtime(stations)

        p2 = gps_parser.ConfigParser()
        assert p2.get_config("THEY", "router_ip") == "10.99.99.99"
        assert p2.config is not p1.config
        # the old instance keeps its original (pre-change) parse untouched
        assert p1.get_config("THEY", "router_ip") == "157.157.40.186"

    def test_size_change_alone_invalidates(self, cfg_dir):
        """A rewrite that changes file size invalidates even if the
        filesystem timestamps old and new writes identically (coarse
        mtime granularity) — st_size is part of the signature."""
        p1 = gps_parser.ConfigParser()

        stations = cfg_dir / "stations.cfg"
        old_stat = os.stat(stations)
        _write(stations, STATIONS_V1 + "extra_key = extra_value\n")
        # simulate coarse-granularity timestamps: restore the ORIGINAL mtime
        os.utime(stations, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))

        p2 = gps_parser.ConfigParser()
        assert p2.get_config("THEY", "extra_key") == "extra_value"
        assert p2.config is not p1.config

    def test_same_size_rewrite_with_mtime_bump_invalidates(self, cfg_dir):
        """A size-preserving rewrite is caught via st_mtime_ns."""
        p1 = gps_parser.ConfigParser()
        assert p1.get_config("THEY", "receiver_type") == "NetR9"

        stations = cfg_dir / "stations.cfg"
        replacement = STATIONS_V1.replace("NetR9", "NetRX")  # same length
        assert len(replacement.encode()) == len(STATIONS_V1.encode())
        _write(stations, replacement)
        _bump_mtime(stations)

        p2 = gps_parser.ConfigParser()
        assert p2.get_config("THEY", "receiver_type") == "NetRX"

    def test_postprocess_change_also_invalidates(self, cfg_dir):
        """Both files participate in the signature, not just stations.cfg."""
        p1 = gps_parser.ConfigParser()
        assert p1.getPostProcessDir("totPath") == "/mnt/gpsdata/"

        postprocess = cfg_dir / "postprocess.cfg"
        _write(postprocess, POSTPROCESS_V1.replace("/mnt/gpsdata/", "/data/new/"))
        _bump_mtime(postprocess)

        p2 = gps_parser.ConfigParser()
        assert p2.getPostProcessDir("totPath") == "/data/new/"
        assert p2.config is not p1.config

    def test_missing_file_appearing_invalidates(self, tmp_path):
        """Signature None (missing postprocess.cfg) differs from any real
        signature, so the file appearing later triggers a re-parse."""
        _write(tmp_path / "stations.cfg", STATIONS_V1)
        with patch.dict(os.environ, {"GPS_CONFIG_PATH": str(tmp_path)}):
            p1 = gps_parser.ConfigParser()
            with pytest.raises(Exception, match="not found"):
                p1.getPostProcessDir("totPath")

            _write(tmp_path / "postprocess.cfg", POSTPROCESS_V1)

            p2 = gps_parser.ConfigParser()
            assert p2.getPostProcessDir("totPath") == "/mnt/gpsdata/"

    def test_cache_is_keyed_per_config_dir(self, tmp_path):
        """Different GPS_CONFIG_PATH dirs never share a cache entry."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        for d, ip in ((dir_a, "1.1.1.1"), (dir_b, "2.2.2.2")):
            d.mkdir()
            _write(d / "stations.cfg", STATIONS_V1.replace("157.157.40.186", ip))
            _write(d / "postprocess.cfg", POSTPROCESS_V1)

        with patch.dict(os.environ, {"GPS_CONFIG_PATH": str(dir_a)}):
            p_a = gps_parser.ConfigParser()
        with patch.dict(os.environ, {"GPS_CONFIG_PATH": str(dir_b)}):
            p_b = gps_parser.ConfigParser()

        assert p_a.get_config("THEY", "router_ip") == "1.1.1.1"
        assert p_b.get_config("THEY", "router_ip") == "2.2.2.2"
        assert p_a.config is not p_b.config
