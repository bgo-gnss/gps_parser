# gps_parser - Enhanced GPS Configuration Management

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.4.0-green)](https://github.com/vedur-is/gps_parser)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Enhanced GPS configuration management package for Veðurstofan Íslands (Icelandic Met Office) GPS processing ecosystem. Provides centralized configuration parsing and management for GPS stations, processing parameters, and system paths.

## Features

### Enhanced in v0.4.0
- **Station Timeout Categories**: Configure connection timeouts based on station type (fixed_wired, mobile, very_remote)
- **FTP Mode Detection**: Automatic FTP mode determination based on IP ranges or explicit configuration
- **Session Management**: Configurable session types with receiver paths and logging settings
- **System Paths**: Centralized tool path management (RxTools, processing tools, data directories)
- **CLI Defaults**: Configurable default values for command-line applications
- **Configuration Validation**: Comprehensive validation and error reporting

### Core Features
- **XDG Compliance**: Standard configuration directory (`~/.config/gpsconfig/`)
- **Extended Interpolation**: Variable substitution and path expansion support
- **Backward Compatibility**: Legacy configuration support maintained
- **Easy Setup**: Automated configuration deployment script

## Installation

```bash
# Install package
pip install gps_parser

# Setup user configuration (run once)
cd gps_parser
./scripts/setup-config.sh

# Optional: Install with development dependencies
pip install gps_parser[dev]
```

## Quick Start

### Basic Usage

```python
import gps_parser

# Initialize configuration parser
parser = gps_parser.ConfigParser()

# Get station information
station_info = parser.getStationInfo('ELDC')
print(f"Station: {station_info['station']['station_name']}")
print(f"Router IP: {station_info['station']['router_ip']}")

# Get timeout configuration
timeout_config = parser.getStationTimeout('ELDC')
print(f"Connection timeout: {timeout_config['connection_timeout']} seconds")
print(f"Inactivity timeout: {timeout_config['inactivity_timeout']} seconds")

# Get FTP mode
ftp_mode = parser.getStationFtpMode('ELDC', '10.6.1.90')
print(f"FTP mode: {ftp_mode}")

# Get system paths
bin2asc_path = parser.getSystemPath('bin2asc_path')
print(f"bin2asc tool: {bin2asc_path}")

# Get default values
default_session = parser.getDefaultValue('default_session')
print(f"Default session: {default_session}")
```

### Configuration Validation

```python
# Validate station configuration
validation = parser.validateStationConfig('ELDC')

if validation['valid']:
    print("Station configuration is valid")
else:
    print("Configuration errors:")
    for error in validation['errors']:
        print(f"  - {error}")

# Check for warnings
if validation['warnings']:
    print("Configuration warnings:")
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

## Configuration Schema

### stations.cfg - Enhanced Station Configuration

```ini
# Individual station configuration
[ELDC]
router_ip = 10.6.1.90
receiver_type = PolaRX5
receiver_ftpport = 2160
timeout_category = extended_network
ftp_mode = passive

# Global timeout categories
[TIMEOUT_CATEGORIES]
fixed_wired = 10,30,180,8192
mobile = 20,60,300,2048
very_remote = 30,120,600,1024

# Network-based FTP mode rules
[NETWORK_RULES]
ip_range_10_4 = active
ip_range_10_6 = passive
domain_default = auto

# Session type mappings
[SESSIONS]
15s_24hr = a,LOG1_15s_24hr,/DSK1/SSN/
1Hz_1hr = b,LOG2_1Hz_1hr,/DSK1/SSN/
status_1hr = b,LOG5_status_1hr,/DSK1/SSN/
```

### postprocess.cfg - System Configuration

```ini
# System tool paths
[PATHS]
sbf2rin_path = /home/gpsops/bin/sbf2rin
teqc_path = /home/gpsops/bin/teqc
bin2asc_path = /opt/rxtools/bin/bin2asc
data_prepath = /data/
receiver_base_path = /DSK1/SSN/

# Default values for CLI applications
[DEFAULTS]
default_days_back = 10
default_session = 15s_24hr
default_compression = .gz
health_extraction_pattern = *.sbf*
ftp_connection_retries = 3
```

## API Reference

### Enhanced Methods (v0.4.0)

#### `getStationTimeout(station_id: str) -> Dict[str, int]`
Get timeout configuration based on station's timeout category.

#### `getStationFtpMode(station_id: str, router_ip: str) -> str`
Determine FTP mode using explicit config or network rules.

#### `getSessionConfig(session_type: str) -> Dict[str, str]`
Get session configuration (letter, paths) for receiver data types.

#### `getSystemPath(path_name: str) -> str`
Get system tool paths with environment variable expansion.

#### `getDefaultValue(setting_name: str) -> Union[str, int, float]`
Get default values for CLI applications with type conversion.

#### `validateStationConfig(station_id: str) -> Dict[str, Any]`
Validate station configuration completeness and correctness.

### Core Methods

#### `getStationInfo(station_id: str = "") -> Union[List[str], Dict[str, Dict]]`
Get complete station information dictionary.

#### `get_config(section: str, option: str) -> str`
Get specific configuration value.

#### `getPostProcessDir(option: str) -> str`
Get postprocess directory paths.

## Integration Examples

### For receivers Package

```python
from gps_parser import ConfigParser

def get_station_config(station_id: str):
    """Replace hardcoded station configuration with gps_parser calls."""
    parser = ConfigParser()
    
    # Get timeout configuration
    timeout_config = parser.getStationTimeout(station_id)
    
    # Get FTP mode
    station_info = parser.getStationInfo(station_id)
    router_ip = station_info['station']['router_ip']
    ftp_mode = parser.getStationFtpMode(station_id, router_ip)
    
    # Get system paths
    bin2asc_path = parser.getSystemPath('bin2asc_path')
    
    return {
        'timeouts': timeout_config,
        'ftp_mode': ftp_mode,
        'bin2asc_path': bin2asc_path
    }

def get_health_config():
    """Get health monitoring configuration."""
    parser = ConfigParser()
    
    pattern = parser.getDefaultValue('health_extraction_pattern')
    output_formats = parser.getDefaultValue('health_output_formats')
    bin2asc_path = parser.getSystemPath('bin2asc_path')
    
    return {
        'bin2asc_path': bin2asc_path,
        'file_pattern': pattern,
        'output_formats': output_formats.split(',')
    }
```

## Migration Guide

### From Hardcoded Configuration

**Before (hardcoded):**
```python
# Hardcoded values in application
TIMEOUT_VALUES = {
    'ELDC': (20, 60, 300, 2048),
    'TEST': (10, 30, 180, 8192)
}

# Hardcoded FTP mode detection
def get_ftp_mode(router_ip):
    if router_ip.startswith('10.4.'):
        return 'active'
    elif router_ip.startswith('10.6.'):
        return 'passive'
    return 'auto'
```

**After:**
```python
# Rule-based FTP mode determination
ftp_mode = parser.getStationFtpMode(station_id, router_ip)
pasv = (ftp_mode == 'passive')
```

## Testing

```bash
# Run package tests
pytest tests/ -v

# Test with coverage
pytest tests/ --cov=gps_parser --cov-report=html

# Basic functionality test
python -c "
import gps_parser
parser = gps_parser.ConfigParser()
print('Configuration parsing works')
print(f'ELDC timeout: {parser.getStationTimeout(\"ELDC\")}')
"
```

## Configuration Directory

### Default Location
- **Linux/macOS**: `~/.config/gpsconfig/`
- **Custom**: Set `GPS_CONFIG_PATH` environment variable

### Structure
```
~/.config/gpsconfig/
├── stations.cfg      # Station definitions and rules
└── postprocess.cfg   # System paths and defaults
```

### Setup
```bash
# Automated setup
./scripts/setup-config.sh

# Manual setup
mkdir -p ~/.config/gpsconfig/
cp data/stations.cfg ~/.config/gpsconfig/
cp data/postprocess.cfg ~/.config/gpsconfig/
```

## Development

### Adding New Configuration

1. **Extend configuration templates** in `data/`
2. **Add new methods** to `ConfigParser` class
3. **Add tests** for new functionality
4. **Update documentation** in README.md and CLAUDE.md
5. **Version bump** in pyproject.toml

## Integration Ecosystem

Part of the GPS processing ecosystem at Veðurstofan Íslands:

- **receivers**: GPS receiver data management (primary consumer)
- **tostools**: TOS API integration and operational data
- **gtimes**: GPS time processing utilities
- **geo_dataread**: GPS data analysis and processing

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Authors

- **Benedikt Gunnar Ófeigsson** - *Lead Developer* - bgo@vedur.is
- **Maria Fernanda Gonzalez** - *Co-Developer* - mariagr@vedur.is

## Organization

**Veðurstofan Íslands** (Icelandic Meteorological Office)  
GPS Processing and Geodynamics Department

---

**Enhanced Configuration Management for GPS Processing Excellence**