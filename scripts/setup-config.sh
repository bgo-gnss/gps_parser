#!/bin/bash

echo ""
echo "Copyright (c) 2011-2024 Icelandic Met Office"  
echo "gps_parser v0.4.0 - Enhanced Configuration Setup"
echo ""

# Configuration variables
DIR=${GPS_CONFIG_PATH:-$HOME/.config/gpsconfig/}
FILE_DIR="data"
UPDATE_MODE=false
GIT_SOURCE=""
GIT_REPO=""
FETCH_FROM_VEDUR=false
VEDUR_REPO="git@git.vedur.is:aut/gps-config-data.git"
TEMP_DIR=""

# Function to fetch and extract git repository content
fetch_git_config() {
    local repo_url="$1"

    # Check if git is available
    if ! command -v git &> /dev/null; then
        echo "ERROR: git command not found. Please install git to use repository fetching."
        exit 1
    fi

    # Create temporary directory
    TEMP_DIR=$(mktemp -d)
    if [[ $? -ne 0 ]]; then
        echo "ERROR: Failed to create temporary directory"
        exit 1
    fi

    # Set up cleanup trap
    trap 'cleanup_temp_dir' EXIT

    echo "  Cloning repository to temporary location..."
    if git clone "$repo_url" "$TEMP_DIR/repo" &> /dev/null; then
        echo "  ✅ Repository cloned successfully"

        # Check if configuration files exist in the repository
        if [[ -f "$TEMP_DIR/repo/stations.cfg" ]] && [[ -f "$TEMP_DIR/repo/postprocess.cfg" ]]; then
            echo "  ✅ Found required configuration files in repository"

            # Show all files and directories that will be copied
            echo "  📁 Repository content to be copied:"
            echo "     📄 Files:"
            find "$TEMP_DIR/repo" -maxdepth 1 -type f ! -name '.git*' | sed 's|.*/||' | sort | sed 's/^/       • /'

            # Show directories
            local dirs=$(find "$TEMP_DIR/repo" -maxdepth 1 -type d ! -path "$TEMP_DIR/repo" ! -name '.git*' | sed 's|.*/||' | sort)
            if [[ -n "$dirs" ]]; then
                echo "     📁 Directories:"
                echo "$dirs" | sed 's/^/       • /'
            fi

            FILE_DIR="$TEMP_DIR/repo"
        else
            echo "  ❌ ERROR: Required configuration files (stations.cfg, postprocess.cfg) not found in repository"
            echo "     Repository contents:"
            ls -la "$TEMP_DIR/repo" | head -10
            exit 1
        fi
    else
        echo "  ❌ ERROR: Failed to clone repository. Check the URL and your access permissions."
        echo "     Repository URL: $repo_url"
        exit 1
    fi
}

# Function to cleanup temporary directory
cleanup_temp_dir() {
    if [[ -n "$TEMP_DIR" ]] && [[ -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --update)
            UPDATE_MODE=true
            shift
            ;;
        --source)
            if [[ -n $2 && $2 != --* ]]; then
                GIT_SOURCE="$2"
                shift 2
            else
                echo "ERROR: --source requires a git repository URL"
                exit 1
            fi
            ;;
        --repo)
            if [[ -n $2 && $2 != --* ]]; then
                GIT_REPO="$2"
                shift 2
            else
                echo "ERROR: --repo requires a git repository URL"
                exit 1
            fi
            ;;
        --fetch-from-vedur)
            FETCH_FROM_VEDUR=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--update] [--source <git-url>] [--repo <git-url>] [--fetch-from-vedur] [--help]"
            echo ""
            echo "Options:"
            echo "  --update               Update existing configuration with new sections"
            echo "  --source <git-url>     Fetch configuration from specified git repository"
            echo "  --repo <git-url>       Same as --source (alternative flag name)"
            echo "  --fetch-from-vedur     Fetch configuration from official Vedur repository"
            echo "  --help                 Show this help message"
            echo ""
            echo "Git Repository Options:"
            echo "  Use either --source, --repo, or --fetch-from-vedur to fetch live configuration."
            echo "  Without these flags, local template files from data/ directory are used."
            echo ""
            echo "Examples:"
            echo "  $0                                    # Use local templates"
            echo "  $0 --fetch-from-vedur                # Fetch from official Vedur repo"
            echo "  $0 --source git@example.com:repo.git # Fetch from custom repository"
            echo "  $0 --repo https://github.com/user/gps-config.git # Same as --source"
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

# Validate git options and set repository URL
REPO_URL=""
if [[ "$FETCH_FROM_VEDUR" == true ]]; then
    REPO_URL="$VEDUR_REPO"
    echo "📡 Fetching configuration from official Vedur repository..."
elif [[ -n "$GIT_SOURCE" ]]; then
    REPO_URL="$GIT_SOURCE"
    echo "📡 Fetching configuration from: $REPO_URL"
elif [[ -n "$GIT_REPO" ]]; then
    REPO_URL="$GIT_REPO"
    echo "📡 Fetching configuration from: $REPO_URL"
fi

# Check for conflicting git options
if [[ "$FETCH_FROM_VEDUR" == true ]] && ([[ -n "$GIT_SOURCE" ]] || [[ -n "$GIT_REPO" ]]); then
    echo "ERROR: Cannot use --fetch-from-vedur with --source or --repo"
    echo "Use --help for usage information"
    exit 1
fi

if [[ -n "$GIT_SOURCE" ]] && [[ -n "$GIT_REPO" ]]; then
    echo "ERROR: Cannot use both --source and --repo flags"
    echo "Use --help for usage information"
    exit 1
fi

echo "Configuration directory: $DIR"
echo "Enhanced features in v0.4.0:"
echo "  - Station timeout categories and FTP mode configuration"
echo "  - System tool paths and CLI default values"
echo "  - Session type mappings and validation support"
if [[ -n "$REPO_URL" ]]; then
    echo "  - Live configuration fetching from git repository"
fi
echo ""

# Fetch git repository if specified
if [[ -n "$REPO_URL" ]]; then
    echo "🔄 Fetching configuration from git repository..."
    fetch_git_config "$REPO_URL"
    echo ""
fi

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
        if [[ -n "$REPO_URL" ]]; then
            echo "Installing configuration files from git repository..."
        else
            echo "Installing configuration files from local templates..."
        fi
    fi

    # Copy configuration files
    if [[ -n "$REPO_URL" ]]; then
        # Copy complete repository structure (excluding .git)
        echo "  📁 Copying complete repository structure..."

        # Use rsync for better copying with exclusions, or fallback to cp
        if command -v rsync &> /dev/null; then
            rsync -av --exclude='.git*' "$FILE_DIR/" "$DIR/"
        else
            # Fallback: copy with cp, excluding .git
            cp -r "$FILE_DIR"/* "$DIR/"
            # Remove any .git files that might have been copied
            find "$DIR" -name '.git*' -exec rm -rf {} + 2>/dev/null || true
        fi

        # Count total files and directories copied
        file_count=$(find "$DIR" -type f | wc -l)
        dir_count=$(find "$DIR" -type d | wc -l)
        echo "  ✅ Copied complete repository: $file_count files, $dir_count directories"
    else
        # Copy only the template configuration files
        cp "$FILE_DIR/postprocess.cfg" "$DIR/"
        cp "$FILE_DIR/stations.cfg" "$DIR/"
    fi
    
    # Validate installation
    if [ -f "$DIR/postprocess.cfg" ] && [ -f "$DIR/stations.cfg" ]; then
        echo ""
        echo "✅ Configuration setup completed successfully!"
        if [[ -n "$REPO_URL" ]]; then
            echo "📦 Source: Git repository ($REPO_URL)"
        else
            echo "📦 Source: Local template files"
        fi
        echo ""
        echo "📋 Next steps:"
        if [[ -n "$REPO_URL" ]]; then
            echo "  1. Review $DIR/stations.cfg (fetched from repository)"
            echo "  2. Review $DIR/postprocess.cfg for system paths"
            echo "  3. Test configuration: python -c \"import gps_parser; print('Config OK')\""
        else
            echo "  1. Edit $DIR/stations.cfg to add your GPS stations"
            echo "  2. Review $DIR/postprocess.cfg for system paths"
            echo "  3. Test configuration: python -c \"import gps_parser; print('Config OK')\""
        fi
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
