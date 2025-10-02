# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `gps_parser` - a centralized GPS configuration management package for Veðurstofan Íslands (Icelandic Met Office) GPS library ecosystem. It provides unified configuration parsing and management for GPS station metadata, processing parameters, and system paths.

## 🏗️ Architecture

### Core Components
- **ConfigParser Class**: Central configuration manager with ExtendedInterpolation support
- **stations.cfg**: GPS station metadata and operational parameters
- **postprocess.cfg**: Processing paths, tool locations, and system defaults
- **setup-config.sh**: Configuration deployment script for user environments

### Design Principles
- **Centralized Configuration**: Single source of truth for all GPS library packages
- **XDG Compliance**: Standard config location `~/.config/gpsconfig/` or `GPS_CONFIG_PATH`
- **Extended Interpolation**: Support for variable substitution and path expansion
- **Environment Flexibility**: Support for development, staging, and production configs

## 📦 Package Structure

```
gps_parser/
├── src/gps_parser/
│   ├── __init__.py          # Main ConfigParser class
│   ├── cli/                 # CLI commands
│   │   ├── __init__.py      # CLI entry point
│   │   └── config.py        # gps-config deploy command
│   ├── stations.cfg         # Station configuration template
│   └── postprocess.cfg      # Processing configuration template
├── data/                    # Configuration templates for setup
│   ├── stations.cfg
│   └── postprocess.cfg
├── scripts/
│   └── setup-config.sh      # User configuration setup
├── tests/                   # Package tests
└── pyproject.toml          # Package metadata and dependencies
```

## 🔧 Development Commands

### Package Installation
```bash
# Development installation
cd gps_parser
pip install -e .

# Setup user configuration (run once)
./scripts/setup-config.sh
```

### Testing
```bash
# Run package tests
pytest tests/ -v

# Test configuration parsing
python -c "import gps_parser; parser = gps_parser.ConfigParser(); print(parser.getStationInfo('ELDC'))"
```

### Configuration Management

#### gps-config CLI Tool (NEW in v0.4.0)
```bash
# Auto-detect environment and deploy configuration
gps-config deploy

# Deploy specific environment (laptop-bgo, production, rek.vedur.is, staging)
gps-config deploy --env rek.vedur.is

# Preview changes without writing files
gps-config deploy --dry-run --show-diff

# Deploy with verbose output
gps-config deploy --verbose

# Deploy from custom config directory
gps-config deploy --config-dir /path/to/gps-config-data
```

#### Traditional Configuration Setup
```bash
# Check config location
echo $GPS_CONFIG_PATH  # or default ~/.config/gpsconfig/

# Update user config from templates (legacy method)
./scripts/setup-config.sh --update
```

## 🎯 Current Status: Phase 1 Configuration Extensions

### ✅ **Base Infrastructure Complete**:
- Modern package structure with pyproject.toml
- ConfigParser with ExtendedInterpolation support
- XDG-compliant configuration directory handling
- Basic station and postprocess configuration parsing
- Setup script for user environment deployment
- **NEW**: `gps-config deploy` CLI tool for template-based deployment

### 🔄 **Phase 1 Implementation (Current Sprint)**:

**1. Enhanced Configuration Schema**:
- **stations.cfg Extensions**: Add timeout categories, FTP mode rules, session mappings
- **postprocess.cfg Extensions**: Add system paths, tool locations, CLI defaults
- **Validation Support**: Configuration completeness and correctness checking

**2. Extended API Methods**:
```python
# New methods to implement:
def getStationTimeout(self, station_id: str) -> dict
def getStationFtpMode(self, station_id: str, router_ip: str) -> str  
def getSessionConfig(self, session_type: str) -> dict
def getSystemPath(self, path_name: str) -> str
def getDefaultValue(self, setting_name: str) -> any
def validateStationConfig(self, station_id: str) -> dict
```

**3. Configuration Categories**:
- **Network Configuration**: FTP modes, timeout values, connection parameters
- **Session Management**: Receiver session types, paths, and logging configurations
- **System Integration**: Tool paths, data directories, default values
- **Station Metadata**: Enhanced station information with operational parameters

### 🎯 **Integration Objectives**:

**Primary Consumer: receivers package**
- Eliminate hardcoded station lists (60+ stations currently hardcoded)
- Replace hardcoded FTP mode detection with config-based rules
- Replace hardcoded timeout values with station-type based configuration
- Replace hardcoded system paths with configurable path resolution

**Future Consumers: tostools, other GPS packages**  
- Provide unified station configuration for operational data integration
- Support automatic configuration updates from TOS API
- Enable consistent configuration across GPS processing pipeline

## 📋 Configuration Schema (Phase 1)

### Enhanced stations.cfg Structure
```ini
# Existing station sections (enhanced):
[STATION_ID]
router_ip = 10.6.1.90
receiver_type = PolaRX5
receiver_ftpport = 2160
# NEW FIELDS:
timeout_category = extended_network
ftp_mode = passive
connection_timeout = 20  # Optional override
inactivity_timeout = 60  # Optional override

# NEW GLOBAL SECTIONS:
[TIMEOUT_CATEGORIES]
fixed_wired = connection_timeout:10,inactivity_timeout:30,progress_timeout:180,min_speed_threshold:8192
mobile = connection_timeout:20,inactivity_timeout:60,progress_timeout:300,min_speed_threshold:2048
very_remote = connection_timeout:30,inactivity_timeout:120,progress_timeout:600,min_speed_threshold:1024

[NETWORK_RULES]
ip_range_10_4 = active    # Internal IMO network
ip_range_10_6 = passive   # Extended network  
domain_default = auto     # Auto-detect for domain names

[SESSIONS]
15s_24hr = session_letter:a,session_path:LOG1_15s_24hr,receiver_path:/DSK1/SSN/
1Hz_1hr = session_letter:b,session_path:LOG2_1Hz_1hr,receiver_path:/DSK1/SSN/
status_1hr = session_letter:b,session_path:LOG5_status_1hr,receiver_path:/DSK1/SSN/
```

### Enhanced postprocess.cfg Structure  
```ini
[PATHS]
# System tool paths
sbf2rin_path = /home/gpsops/bin/sbf2rin
teqc_path = /home/gpsops/bin/teqc
bin2asc_path = /opt/rxtools/bin/bin2asc
data_prepath = /data/
receiver_base_path = /DSK1/SSN/

[DEFAULTS]  
# CLI default values
default_days_back = 10
default_session = 15s_24hr
default_compression = .gz
default_end_offset_days = 1
health_extraction_pattern = *.sbf*
```

## 🚀 Configuration Deployment with gps-config

The `gps-config deploy` command provides template-based configuration deployment for multiple environments from a single source (gps-config-data repository).

### Template System

**Template files** (`.template` suffix) contain `{{variable}}` placeholders that are replaced with environment-specific values during deployment:

```ini
# receivers.cfg.template
prepath = {{data_prepath}}
tmp_dir = {{tmp_dir}}
```

**Environment files** (`environments/*.env`) define values for each environment:

```ini
# environments/laptop-bgo.env
[paths]
data_prepath = /home/bgo/work/projects/gps/gpslibrary_new/receivers/tmp/data/
tmp_dir = /home/bgo/tmp/download/

[scheduler]
database = ~/.cache/gps_receivers/scheduler.db
max_workers = 2
```

**Variable resolution**: The tool creates variables with both `section_key` (e.g., `scheduler_database`) and `key` (e.g., `database`) formats for flexibility.

### Deployment Workflow

1. **Auto-detect environment** from hostname (or specify with `--env`)
2. **Load environment file** from `environments/<env>.env`
3. **Find template files** (all `*.template` files)
4. **Render templates** by replacing `{{variables}}`
5. **Write output files** (remove `.template` suffix)

### Supported Environments

- **laptop-bgo**: Development laptop (2 workers, DEBUG logging)
- **production**: Generic production servers (5 workers, INFO logging)
- **rek.vedur.is**: Primary production server (100 workers, 173 stations)
- **staging**: Testing servers (3 workers, DEBUG logging)

### CLI Options

```bash
# Basic deployment
gps-config deploy                           # Auto-detect environment
gps-config deploy --env rek.vedur.is       # Specific environment

# Preview and validation
gps-config deploy --dry-run                # Don't write files
gps-config deploy --show-diff              # Show what would change
gps-config deploy --verbose                # Detailed output

# Custom config location
gps-config deploy --config-dir /path/to/gps-config-data
```

### Integration with gps-config-data

The deployment tool expects to work with the `gps-config-data` repository structure:

```
gps-config-data/
├── environments/
│   ├── laptop-bgo.env
│   ├── production.env
│   ├── rek.vedur.is.env
│   └── staging.env
├── receivers.cfg.template
├── scheduler.yaml.template
├── postprocess.cfg.template
├── stations.cfg              # Shared (not templated)
├── database.cfg              # Shared (uses env vars for secrets)
└── DEPLOYMENT.md            # Deployment guide
```

### Example Deployment Session

```bash
$ gps-config deploy --dry-run --show-diff
Auto-detected environment: laptop-bgo
Loaded 55 variables from laptop-bgo.env
Found 3 template files

Configuration changes for environment 'laptop-bgo':
  New file: receivers.cfg
  --- /dev/null
  +++ receivers.cfg
  + prepath = /home/bgo/work/projects/gps/gpslibrary_new/receivers/tmp/data/
  ...

$ gps-config deploy --verbose
Auto-detected environment: laptop-bgo
Loaded 55 variables from laptop-bgo.env
Found 3 template files

Deploying to ~/.config/gpsconfig...
  updated: receivers.cfg
  updated: scheduler.yaml
  updated: postprocess.cfg

✓ Successfully deployed 3 configuration files
  3 files updated, 0 unchanged
```

## 🧪 Testing Strategy

### Unit Tests
- Configuration parsing for all new sections
- Timeout resolution logic validation
- FTP mode determination accuracy
- Session configuration retrieval
- System path resolution
- Error handling for missing/invalid configurations

### Integration Tests
- Full configuration loading from templates
- Cross-section configuration dependencies
- Environment variable override behavior
- Configuration validation completeness

### Example Test Cases
```python
def test_station_timeout_resolution():
    """Test timeout category assignment and value resolution."""
    
def test_ftp_mode_determination():
    """Test FTP mode rules for different IP ranges."""
    
def test_session_config_retrieval():
    """Test session mapping and path resolution."""

def test_system_path_resolution():
    """Test tool path configuration and environment overrides."""
```

## 🚀 Integration Patterns

### For receivers Package (Phase 2)
```python
# Replace hardcoded values with config calls:
from gps_parser import ConfigParser

parser = ConfigParser()

# Instead of hardcoded station lists:
timeout_config = parser.getStationTimeout('ELDC')

# Instead of hardcoded FTP mode detection:  
ftp_mode = parser.getStationFtpMode('ELDC', '10.6.1.90')

# Instead of hardcoded paths:
bin2asc_path = parser.getSystemPath('bin2asc_path')

# Instead of hardcoded defaults:
default_session = parser.getDefaultValue('default_session')
```

### Error Handling Pattern
```python
try:
    station_config = parser.getStationInfo('STATION_ID')
    if validation := parser.validateStationConfig('STATION_ID'):
        # Handle validation errors
        print(f"Configuration issues: {validation['errors']}")
except Exception as e:
    print(f"Configuration error: {e}")
```

## 🔄 Development Workflow

### Configuration Changes
1. **Update templates**: Modify `data/stations.cfg` and `data/postprocess.cfg`
2. **Extend API**: Add new methods to `src/gps_parser/__init__.py`
3. **Add tests**: Create tests for new functionality
4. **Update setup**: Enhance `scripts/setup-config.sh` if needed
5. **Document API**: Update this CLAUDE.md with new methods

### Version Management
- **0.3.0**: Current base version with basic configuration support
- **0.4.0**: Phase 1 enhanced configuration schema and extended API
- **0.5.0**: Future validation and advanced configuration features

## 📝 Dependencies

### Core Dependencies
- **Python**: >=3.8 (supports up to 3.13)
- **Standard Library**: configparser, os, pathlib for configuration handling

### Development Dependencies  
- **pytest**: Testing framework
- **Coverage tools**: For test coverage analysis
- **Build tools**: hatchling for package building

## 🌐 Integration Ecosystem

This package serves as configuration backbone for:
- **receivers**: GPS receiver data management and health monitoring
- **tostools**: TOS API integration and operational data management
- **gtimes**: GPS time processing (indirect dependency via receivers)
- **geo_dataread**: GPS data analysis (potential future consumer)

## 📋 Phase 1 Implementation Checklist

### Configuration Schema
- [ ] Add TIMEOUT_CATEGORIES section to stations.cfg template
- [ ] Add NETWORK_RULES section to stations.cfg template  
- [ ] Add SESSIONS section to stations.cfg template
- [ ] Add PATHS section to postprocess.cfg template
- [ ] Add DEFAULTS section to postprocess.cfg template

### API Extensions
- [ ] Implement getStationTimeout() method
- [ ] Implement getStationFtpMode() method
- [ ] Implement getSessionConfig() method  
- [ ] Implement getSystemPath() method
- [ ] Implement getDefaultValue() method
- [ ] Implement validateStationConfig() method

### Infrastructure
- [ ] Update pyproject.toml to version 0.4.0
- [ ] Enhance setup-config.sh for new sections
- [ ] Add comprehensive test suite for new functionality
- [ ] Update README.md with enhanced documentation
- [ ] Create migration guide for dependent packages

### Testing & Validation
- [ ] Test timeout resolution with different station categories
- [ ] Test FTP mode determination with various IP ranges
- [ ] Test session configuration parsing and retrieval
- [ ] Test system path resolution and environment overrides
- [ ] Test configuration validation and error reporting
- [ ] Integration test with receivers package

## 🚧 Future Enhancements (Post Phase 1)

- **Dynamic Configuration**: Hot-reload configuration changes
- **Configuration Validation**: Comprehensive schema validation
- **Web Interface**: Configuration management web UI
- **Backup/Restore**: Configuration versioning and rollback
- **Template Engine**: Dynamic configuration generation
- **Integration API**: REST API for configuration management

---

**Project Type**: Configuration management library for GPS processing ecosystem  
**Primary Language**: Python with INI configuration format  
**Key Domain**: GPS station configuration, operational parameters, system integration  
**Organization**: Veðurstofan Íslands (Icelandic Meteorological Office)

*Created for Phase 1 configuration extensions - gps_parser v0.4.0 development*