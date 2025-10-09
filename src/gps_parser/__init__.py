import configparser
import os
from typing import Dict, Any, Optional, Union
# import shutil


class ConfigParser:
    def __init__(self):
        # Setting up the working directories
        # self.config = configparser.ConfigParser()
        self.config = configparser.ConfigParser(
            interpolation=configparser.ExtendedInterpolation()
        )

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
        # Reading the stations.cfg file
        self.dest_stations_config_path = os.path.join(self.config_path, "stations.cfg")
        self.config.read(self.dest_stations_config_path)

        # Reading the postprocess.cfg file
        self.dest_postprocess_config_path = os.path.join(
            self.config_path, "postprocess.cfg"
        )
        self.config.read(self.dest_postprocess_config_path)

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
                cleaned_value = value.split('#')[0].strip()
                cleaned_info[key] = cleaned_value

            return {"station": cleaned_info}
        else:
            raise Exception(f"Station '{station_id}' not found in 'stations.cfg' file.")

    def getPostProcessDir(self, option):
        if self.config.has_section("PATHS"):
            if self.config.has_option("PATHS", option):
                return os.path.expanduser(self.config.get("PATHS", option))
        raise Exception(
            f"Option '{option}' not found in 'Configs' section of the postprocess configuration file."
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
        for timeout_field in ['connection_timeout', 'inactivity_timeout', 'progress_timeout', 'min_speed_threshold']:
            if self.config.has_option(station_upper, timeout_field):
                timeout_config[timeout_field] = int(self.config.get(station_upper, timeout_field))
        
        # If we have complete overrides, return them
        if len(timeout_config) == 4:
            return timeout_config
        
        # Otherwise, get timeout category and apply defaults
        timeout_category = self.config.get(station_upper, 'timeout_category', fallback='mobile')
        
        if not self.config.has_section('TIMEOUT_CATEGORIES'):
            # Fallback defaults if TIMEOUT_CATEGORIES section missing
            defaults = {
                'fixed_wired': (10, 30, 180, 8192),
                'mobile': (20, 60, 300, 2048),
                'very_remote': (30, 120, 600, 1024)
            }
            if timeout_category in defaults:
                conn, inact, prog, speed = defaults[timeout_category]
            else:
                conn, inact, prog, speed = defaults['mobile']  # Default to mobile
        else:
            # Parse category configuration
            if not self.config.has_option('TIMEOUT_CATEGORIES', timeout_category):
                timeout_category = 'mobile'  # Fallback to mobile
            
            category_config = self.config.get('TIMEOUT_CATEGORIES', timeout_category)
            try:
                conn, inact, prog, speed = map(int, category_config.split(','))
            except ValueError:
                raise Exception(f"Invalid timeout configuration for category '{timeout_category}': {category_config}")
        
        # Apply category defaults, but use any station-specific overrides
        result = {
            'connection_timeout': timeout_config.get('connection_timeout', conn),
            'inactivity_timeout': timeout_config.get('inactivity_timeout', inact),
            'progress_timeout': timeout_config.get('progress_timeout', prog),
            'min_speed_threshold': timeout_config.get('min_speed_threshold', speed)
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
        if self.config.has_option(station_upper, 'ftp_mode'):
            ftp_mode = self.config.get(station_upper, 'ftp_mode').lower()
            if ftp_mode in ['active', 'passive', 'auto']:
                return ftp_mode
        
        # Apply network rules based on IP address
        if self.config.has_section('NETWORK_RULES'):
            # Check IP range rules
            if router_ip.startswith('10.4.'):
                return self.config.get('NETWORK_RULES', 'ip_range_10_4', fallback='active')
            elif router_ip.startswith('10.6.'):
                return self.config.get('NETWORK_RULES', 'ip_range_10_6', fallback='passive')
            else:
                # Domain or other IP ranges
                return self.config.get('NETWORK_RULES', 'domain_default', fallback='auto')
        
        # Fallback logic if no NETWORK_RULES section
        if router_ip.startswith('10.4.'):
            return 'active'  # Internal IMO network
        elif router_ip.startswith('10.6.'):
            return 'passive'  # Extended network
        else:
            return 'auto'  # Domain-based or unknown ranges

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
        if not self.config.has_section('SESSIONS'):
            # Fallback defaults if SESSIONS section missing
            defaults = {
                '15s_24hr': ('a', 'LOG1_15s_24hr', '/DSK1/SSN/'),
                '1Hz_1hr': ('b', 'LOG2_1Hz_1hr', '/DSK1/SSN/'),
                'status_1hr': ('b', 'LOG5_status_1hr', '/DSK1/SSN/')
            }
            if session_type in defaults:
                letter, path, receiver_path = defaults[session_type]
                return {
                    'session_letter': letter,
                    'session_path': path,
                    'receiver_path': receiver_path
                }
            else:
                raise Exception(f"Unknown session type '{session_type}'")
        
        if not self.config.has_option('SESSIONS', session_type):
            raise Exception(f"Session type '{session_type}' not found in SESSIONS configuration")
        
        session_config = self.config.get('SESSIONS', session_type)
        try:
            letter, path, receiver_path = session_config.split(',')
            return {
                'session_letter': letter.strip(),
                'session_path': path.strip(),
                'receiver_path': receiver_path.strip()
            }
        except ValueError:
            raise Exception(f"Invalid session configuration for '{session_type}': {session_config}")

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
        if self.config.has_section('PATHS') and self.config.has_option('PATHS', path_name):
            path = self.config.get('PATHS', path_name)
            return os.path.expanduser(path)
        
        # Check legacy Configs section for backward compatibility  
        if self.config.has_section('Configs') and self.config.has_option('Configs', path_name):
            path = self.config.get('Configs', path_name)
            return os.path.expanduser(path)
        
        # Fallback defaults for critical paths
        defaults = {
            'bin2asc_path': '/opt/rxtools/bin/bin2asc',
            'sbf2rin_path': '/home/gpsops/bin/sbf2rin',
            'teqc_path': '/home/gpsops/bin/teqc',
            'data_prepath': './data/',
            'receiver_base_path': '/DSK1/SSN/'
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
        if self.config.has_section('DEFAULTS') and self.config.has_option('DEFAULTS', setting_name):
            value = self.config.get('DEFAULTS', setting_name)
            
            # Convert to appropriate type based on setting name
            if setting_name.endswith('_days') or setting_name.endswith('_retries') or setting_name.endswith('_timeout'):
                return int(value)
            elif setting_name.endswith('_threshold'):
                return float(value)
            else:
                return value  # String value
        
        # Fallback defaults  
        defaults = {
            'default_days_back': 10,
            'default_session': '15s_24hr',
            'default_compression': '.gz',
            'default_end_offset_days': 1,
            'health_extraction_pattern': '*.sbf*',
            'health_output_formats': 'csv,jsonl',
            'ftp_connection_retries': 3,
            'ftp_transfer_timeout': 300
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
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'config': {}
        }
        
        # Check if station section exists
        if not self.config.has_section(station_upper):
            result['valid'] = False
            result['errors'].append(f"Station '{station_upper}' not found in stations.cfg")
            return result
        
        # Required fields
        required_fields = ['router_ip', 'receiver_ftpport', 'receiver_type']
        optional_fields = ['timeout_category', 'ftp_mode', 'connection_type', 'router_type']
        
        # Check required fields
        for field in required_fields:
            if self.config.has_option(station_upper, field):
                result['config'][field] = self.config.get(station_upper, field)
            else:
                result['valid'] = False
                result['errors'].append(f"Missing required field '{field}' for station '{station_upper}'")
        
        # Check optional fields and warn if missing
        for field in optional_fields:
            if self.config.has_option(station_upper, field):
                result['config'][field] = self.config.get(station_upper, field)
            else:
                result['warnings'].append(f"Optional field '{field}' not set for station '{station_upper}'")
        
        # Validate field values
        if 'receiver_ftpport' in result['config']:
            try:
                port = int(result['config']['receiver_ftpport'])
                if not (1 <= port <= 65535):
                    result['errors'].append(f"Invalid FTP port {port} for station '{station_upper}'")
                    result['valid'] = False
            except ValueError:
                result['errors'].append(f"Invalid FTP port format for station '{station_upper}': {result['config']['receiver_ftpport']}")
                result['valid'] = False
        
        # Validate timeout category if present
        if 'timeout_category' in result['config']:
            valid_categories = ['fixed_wired', 'mobile', 'very_remote']
            if result['config']['timeout_category'] not in valid_categories:
                result['warnings'].append(f"Unknown timeout category '{result['config']['timeout_category']}' for station '{station_upper}', will use 'mobile'")
        
        # Validate FTP mode if present
        if 'ftp_mode' in result['config']:
            valid_modes = ['active', 'passive', 'auto']
            if result['config']['ftp_mode'] not in valid_modes:
                result['warnings'].append(f"Unknown FTP mode '{result['config']['ftp_mode']}' for station '{station_upper}', will use network rules")
        
        return result
