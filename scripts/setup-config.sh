#!/bin/bash

echo ""
echo "Copyright (c) 2011-2024 Icelandic Met Office"  
echo "gps_parser v0.4.0 - Enhanced Configuration Setup"
echo ""

# Configuration variables
DIR=${GPS_CONFIG_PATH:-$HOME/.config/gpsconfig/}
FILE_DIR="data"
UPDATE_MODE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --update)
            UPDATE_MODE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--update] [--help]"
            echo ""
            echo "Options:"
            echo "  --update    Update existing configuration with new sections"
            echo "  --help      Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  GPS_CONFIG_PATH    Override default config directory ($HOME/.config/gpsconfig/)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "Configuration directory: $DIR"
echo "Enhanced features in v0.4.0:"
echo "  - Station timeout categories and FTP mode configuration"
echo "  - System tool paths and CLI default values"
echo "  - Session type mappings and validation support"
echo ""

# Create directory if it doesn't exist
if [ ! -d "$DIR" ]; then
    echo "Creating configuration directory..."
    mkdir -p "$DIR"
    if [ $? -ne 0 ]; then
        echo ""
        echo "ERROR: Failed to create directory $DIR"
        echo "Check permissions or set GPS_CONFIG_PATH to a writable location"
        exit 1
    fi
fi

# Copy or update configuration files
if [ -d "$DIR" ]; then
    if [ "$UPDATE_MODE" = true ]; then
        echo "Updating configuration files..."
        
        # Backup existing files
        if [ -f "$DIR/stations.cfg" ]; then
            cp "$DIR/stations.cfg" "$DIR/stations.cfg.backup.$(date +%Y%m%d_%H%M%S)"
            echo "  Backed up existing stations.cfg"
        fi
        if [ -f "$DIR/postprocess.cfg" ]; then
            cp "$DIR/postprocess.cfg" "$DIR/postprocess.cfg.backup.$(date +%Y%m%d_%H%M%S)"
            echo "  Backed up existing postprocess.cfg"
        fi
    else
        echo "Installing configuration files..."
    fi
    
    # Copy enhanced configuration templates
    cp "$FILE_DIR/postprocess.cfg" "$DIR/"
    cp "$FILE_DIR/stations.cfg" "$DIR/"
    
    # Validate installation
    if [ -f "$DIR/postprocess.cfg" ] && [ -f "$DIR/stations.cfg" ]; then
        echo ""
        echo "✅ Configuration setup completed successfully!"
        echo ""
        echo "📋 Next steps:"
        echo "  1. Edit $DIR/stations.cfg to add your GPS stations"
        echo "  2. Review $DIR/postprocess.cfg for system paths"
        echo "  3. Test configuration: python -c \"import gps_parser; print('Config OK')\""
        echo ""
        echo "📖 Enhanced v0.4.0 features:"
        echo "  - Add 'timeout_category = mobile' to station sections"
        echo "  - Add 'ftp_mode = passive' for explicit FTP mode control"
        echo "  - TIMEOUT_CATEGORIES, NETWORK_RULES, SESSIONS sections available"
        echo "  - PATHS and DEFAULTS sections for system configuration"
        echo ""
        echo "📚 Documentation: See CLAUDE.md for complete configuration guide"
    else
        echo ""
        echo "❌ ERROR: Configuration files failed to copy!"
        echo "Check file permissions and available disk space"
        exit 1
    fi
else
    echo ""
    echo "❌ ERROR: Configuration directory creation failed"
    echo "Ensure you have write permissions or set GPS_CONFIG_PATH appropriately"
    exit 1
fi
