# gps_parser - Enhanced GPS Configuration Management

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.4.0-green)](https://github.com/vedur-is/gps_parser)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Enhanced GPS configuration management package for Veðurstofan Íslands (Icelandic Met Office) GPS processing ecosystem. Provides centralized configuration parsing and management for GPS stations, processing parameters, and system paths.

## =€ Features

### ( Enhanced in v0.4.0
- **<¯ Station Timeout Categories**: Configure connection timeouts based on station type (fixed_wired, mobile, very_remote)
- **= FTP Mode Detection**: Automatic FTP mode determination based on IP ranges or explicit configuration
- **™ Session Management**: Configurable session types with receiver paths and logging settings
- **=Â System Paths**: Centralized tool path management (RxTools, processing tools, data directories)
- **=' CLI Defaults**: Configurable default values for command-line applications
- ** Configuration Validation**: Comprehensive validation and error reporting

### <× Core Features
- **=' XDG Compliance**: Standard configuration directory (`~/.config/gpsconfig/`)
- **=Ë Extended Interpolation**: Variable substitution and path expansion support
- **= Backward Compatibility**: Legacy configuration support maintained
- **=à Easy Setup**: Automated configuration deployment script

## =æ Installation

```bash
# Install package
pip install gps_parser

# Setup user configuration (run once)
cd gps_parser
./scripts/setup-config.sh

# Optional: Install with development dependencies
pip install gps_parser[dev]
```

## =€ Quick Start

### Basic Usage

```python
import gps_parser

# Initialize configuration parser
parser = gps_parser.ConfigParser()

# Get station information (legacy API)
eldc_info = parser.getStationInfo('ELDC')
print(eldc_info)

# Get station timeout configuration (v0.4.0)
timeout_config = parser.getStationTimeout('ELDC')
print(f"Connection timeout: {timeout_config['connection_timeout']}s")

# Determine FTP mode for station (v0.4.0)
ftp_mode = parser.getStationFtpMode('ELDC', '10.6.1.90')
print(f"FTP mode: {ftp_mode}")

# Get system tool path (v0.4.0)
bin2asc_path = parser.getSystemPath('bin2asc_path')
print(f"RxTools bin2asc: {bin2asc_path}")

# Get CLI default values (v0.4.0)
default_session = parser.getDefaultValue('default_session')
print(f"Default session: {default_session}")
```

### Configuration Validation

```python
# Validate station configuration
validation = parser.validateStationConfig('ELDC')
if validation['valid']:
    print(" Station configuration is valid")
else:
    print("L Configuration errors:")
    for error in validation['errors']:
        print(f"  - {error}")

# Check for warnings
if validation['warnings']:
    print("   Configuration warnings:")
    for warning in validation['warnings']:
        print(f"  - {warning}")
```

### Session Configuration

```python
# Get session configuration for different data types
session_config = parser.getSessionConfig('status_1hr')
print(f"Session letter: {session_config['session_letter']}")
print(f"Session path: {session_config['session_path']}")
print(f"Receiver path: {session_config['receiver_path']}")
```

## =Ë Configuration Schema

### stations.cfg - Enhanced Station Configuration

```ini
# Individual station configuration
[ELDC]
router_ip = 10.6.1.90
receiver_type = PolaRX5
receiver_ftpport = 2160
timeout_category = mobile           # NEW: timeout category
ftp_mode = passive                 # NEW: explicit FTP mode
connection_timeout = 25            # NEW: optional timeout override

# Global timeout categories (NEW)
[TIMEOUT_CATEGORIES]
fixed_wired = 10,30,180,8192      # connection,inactivity,progress,min_speed
mobile = 20,60,300,2048
very_remote = 30,120,600,1024

# Network-based FTP mode rules (NEW)
[NETWORK_RULES]
ip_range_10_4 = active            # Internal IMO network
ip_range_10_6 = passive           # Extended network
domain_default = auto             # Domain-based stations

# Session type configuration (NEW)
[SESSIONS]
15s_24hr = a,LOG1_15s_24hr,/DSK1/SSN/
1Hz_1hr = b,LOG2_1Hz_1hr,/DSK1/SSN/
status_1hr = b,LOG5_status_1hr,/DSK1/SSN/
```

### postprocess.cfg - System Configuration

```ini
# System tool paths (NEW)
[PATHS]
bin2asc_path = /opt/rxtools/bin/bin2asc
sbf2rin_path = /home/gpsops/bin/sbf2rin
teqc_path = /home/gpsops/bin/teqc
data_prepath = /data/
receiver_base_path = /DSK1/SSN/

# CLI default values (NEW)
[DEFAULTS]
default_days_back = 10
default_session = 15s_24hr
default_compression = .gz
health_extraction_pattern = *.sbf*
ftp_connection_retries = 3

# Legacy configuration (maintained)
[Configs]
figDir = /home/bgo/gamit-times/figures/
totPath = /mnt/gpsdata/
# ... other legacy settings
```

## =' API Reference

### Enhanced Methods (v0.4.0)

#### `getStationTimeout(station_id: str) -> Dict[str, int]`
Get timeout configuration based on station's timeout category.

**Returns:**
```python
{
    'connection_timeout': 20,      # seconds
    'inactivity_timeout': 60,      # seconds  
    'progress_timeout': 300,       # seconds
    'min_speed_threshold': 2048    # bytes/sec
}
```

#### `getStationFtpMode(station_id: str, router_ip: str) -> str`
Determine FTP mode based on explicit config or network rules.

**Returns:** `'active'`, `'passive'`, or `'auto'`

#### `getSessionConfig(session_type: str) -> Dict[str, str]`
Get session configuration for data collection types.

**Parameters:**
- `session_type`: `'15s_24hr'`, `'1Hz_1hr'`, `'status_1hr'`

#### `getSystemPath(path_name: str) -> str`
Get system tool paths with environment expansion.

**Common paths:**
- `'bin2asc_path'` - RxTools bin2asc tool
- `'sbf2rin_path'` - SBF to RINEX converter
- `'data_prepath'` - Data storage directory

#### `getDefaultValue(setting_name: str) -> Union[str, int, float]`
Get configurable default values for applications.

#### `validateStationConfig(station_id: str) -> Dict[str, Any]`
Comprehensive station configuration validation.

### Legacy Methods (maintained)

#### `getStationInfo(station_id: str) -> Dict[str, Any]`
Get complete station information dictionary.

#### `get_config(section: str, option: str) -> str`  
Get specific configuration value.

#### `getPostProcessDir(option: str) -> str`
Get postprocess directory paths.

## <× Integration Examples

### For receivers Package

```python
from gps_parser import ConfigParser

def get_station_config(station_id: str):
    """Replace hardcoded station configuration with gps_parser calls."""
    parser = ConfigParser()
    
    # Get basic station info
    station_info = parser.getStationInfo(station_id)
    if not station_info:
        return None
        
    station_data = station_info['station']
    
    # Get enhanced configuration
    timeout_config = parser.getStationTimeout(station_id)
    ftp_mode = parser.getStationFtpMode(station_id, station_data['router_ip'])
    
    # Build unified configuration
    return {
        'router': {'ip': station_data['router_ip']},
        'receiver': {
            'ftpport': int(station_data['receiver_ftpport']),
            'ftp_mode': ftp_mode,
            'type': station_data['receiver_type']
        },
        'timeouts': timeout_config,
        'station': {
            'id': station_id.upper(),
            'router_type': station_data.get('router_type'),
            'connection_type': station_data.get('connection_type')
        }
    }
```

### For Health Monitoring

```python
def setup_health_extraction():
    """Configure health monitoring with gps_parser defaults."""
    parser = ConfigParser()
    
    # Get configurable paths and settings
    bin2asc_path = parser.getSystemPath('bin2asc_path')
    pattern = parser.getDefaultValue('health_extraction_pattern')
    output_formats = parser.getDefaultValue('health_output_formats')
    
    return {
        'bin2asc_path': bin2asc_path,
        'file_pattern': pattern,
        'output_formats': output_formats.split(',')
    }
```

## =€ Migration Guide

### From Hardcoded Configuration

**Before (hardcoded):**
```python
# L Hardcoded values in application
TIMEOUT_VALUES = {
    'ELDC': (20, 60, 300, 2048),
    'THOB': (10, 30, 180, 8192),
    # ... 60+ stations
}
```

**After (config-based):**
```python
#  Configuration-driven approach
parser = ConfigParser()
timeout_config = parser.getStationTimeout(station_id)
```

### From getSeptentrio2 Station Lists

**Before:**
```python
# L Hardcoded passive mode stations
passive_mode_stations = {'ROTH', 'SVIN', 'SVIE', ...}
pasv = station_id in passive_mode_stations
```

**After:**
```python
#  Rule-based FTP mode determination  
ftp_mode = parser.getStationFtpMode(station_id, router_ip)
pasv = (ftp_mode == 'passive')
```

## >ê Testing

```bash
# Run package tests
pytest tests/ -v

# Test with coverage
pytest tests/ --cov=gps_parser --cov-report=html

# Test configuration parsing
python -c "
import gps_parser
parser = gps_parser.ConfigParser()
print(' Configuration parsing works')
print(f'ELDC timeout: {parser.getStationTimeout(\"ELDC\")}')
"
```

## =Á Configuration Directory

### Default Location
- **Linux/macOS**: `~/.config/gpsconfig/`
- **Custom**: Set `GPS_CONFIG_PATH` environment variable

### Structure
```
~/.config/gpsconfig/
   stations.cfg          # Station metadata and operational parameters
   postprocess.cfg       # System paths and processing configuration
   stations.cfg.backup.* # Automatic backups (created by setup script)
   postprocess.cfg.backup.*
```

## =' Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/vedur-is/gps_parser.git
cd gps_parser

# Install with development dependencies
pip install -e .[dev]

# Run tests
pytest tests/ -v

# Code formatting
black src/ tests/
ruff check src/ tests/
```

### Adding New Configuration

1. **Extend configuration templates** in `data/`
2. **Add new methods** to `ConfigParser` class
3. **Add tests** for new functionality
4. **Update documentation** in README.md and CLAUDE.md
5. **Version bump** in pyproject.toml

## > Integration Ecosystem

Part of the GPS processing ecosystem at Veðurstofan Íslands:

- **=ð receivers**: GPS receiver data management (primary consumer)
- **=Ê tostools**: TOS API integration and operational data
- **ð gtimes**: GPS time processing utilities
- **=È geo_dataread**: GPS data analysis and processing

## =Ä License

MIT License - see [LICENSE](LICENSE) file for details.

## =e Authors

- **Benedikt Gunnar Ófeigsson** - *Lead Developer* - bgo@vedur.is
- **Maria Fernanda Gonzalez** - *Co-Developer* - mariagr@vedur.is

## <â Organization

**Veðurstofan Íslands** (Icelandic Meteorological Office)  
GPS Processing and Geodynamics Department

---

**=€ Enhanced Configuration Management for GPS Processing Excellence**