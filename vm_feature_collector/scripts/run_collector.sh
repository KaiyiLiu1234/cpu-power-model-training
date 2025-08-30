#!/bin/bash
"""
VM Feature Collector Run Script

Convenience script for running the VM Feature Collector with common configurations.
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DURATION=300
INTERVAL=1.0
OUTPUT_DIR="data"
VERBOSE=false
KEPLER_URL="http://localhost:28282/metrics"
SYNC=true

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_usage() {
    echo -e "${BLUE}VM Feature Collector Run Script${NC}"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -d, --duration SECONDS     Collection duration in seconds (default: 300)"
    echo "  -i, --interval SECONDS     Collection interval in seconds (default: 1.0)"
    echo "  -o, --output-dir PATH       Output directory (default: data)"
    echo "  -k, --kepler-url URL        Kepler metrics URL (default: http://localhost:28282/metrics)"
    echo "  -v, --verbose               Enable verbose logging"
    echo "  -n, --no-sync               Disable synchronized collection"
    echo "  -t, --test                  Run quick test (10 seconds)"
    echo "  -h, --help                  Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                          # Run with defaults (5 minutes)"
    echo "  $0 -d 600 -v               # Run for 10 minutes with verbose output"
    echo "  $0 -t                       # Quick test run"
    echo "  $0 -d 3600 -i 0.5           # 1 hour collection with 0.5s interval"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--duration)
            DURATION="$2"
            shift 2
            ;;
        -i|--interval)
            INTERVAL="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -k|--kepler-url)
            KEPLER_URL="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -n|--no-sync)
            SYNC=false
            shift
            ;;
        -t|--test)
            DURATION=10
            VERBOSE=true
            print_info "Test mode: 10 second collection with verbose output"
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Validate inputs
if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [ "$DURATION" -le 0 ]; then
    print_error "Duration must be a positive integer"
    exit 1
fi

if ! [[ "$INTERVAL" =~ ^[0-9]+\.?[0-9]*$ ]] || [ "$(echo "$INTERVAL <= 0" | bc -l)" -eq 1 ]; then
    print_error "Interval must be a positive number"
    exit 1
fi

# Setup environment
setup_environment() {
    print_info "Setting up environment..."
    
    # Create directories
    mkdir -p "$PROJECT_DIR/$OUTPUT_DIR"
    mkdir -p "$PROJECT_DIR/logs"
    
    # Check Python dependencies
    if ! python3 -c "import psutil, requests" 2>/dev/null; then
        print_error "Python dependencies not found. Run scripts/install_deps.sh first."
        exit 1
    fi
    
    # Check if VM feature collector exists
    if [ ! -f "$PROJECT_DIR/src/vm_feature_collector.py" ]; then
        print_error "VM feature collector not found at $PROJECT_DIR/src/vm_feature_collector.py"
        exit 1
    fi
    
    # Check perf access
    if ! perf stat -e cpu-cycles true 2>/dev/null; then
        print_warning "Performance counters not accessible. Some features may be unavailable."
        print_warning "Try: sudo sysctl kernel.perf_event_paranoid=1"
    fi
    
    print_info "Environment setup completed"
}

# Pre-flight checks
preflight_checks() {
    print_info "Running pre-flight checks..."
    
    # Check system load
    load=$(uptime | awk -F'load average:' '{ print $2 }' | awk '{ print $1 }' | sed 's/,//')
    if [ "$(echo "$load > 5.0" | bc -l)" -eq 1 ]; then
        print_warning "High system load detected ($load). This may affect collection accuracy."
    fi
    
    # Check available memory
    available_mem=$(free -m | awk 'NR==2{print $7}')
    if [ "$available_mem" -lt 100 ]; then
        print_warning "Low available memory (${available_mem}MB). This may affect collection."
    fi
    
    # Check disk space
    disk_usage=$(df "$PROJECT_DIR" | awk 'NR==2{print $5}' | sed 's/%//')
    if [ "$disk_usage" -gt 90 ]; then
        print_warning "Low disk space (${disk_usage}% used). Check output directory space."
    fi
    
    # Test Kepler connectivity
    if curl -s --connect-timeout 5 "$KEPLER_URL" >/dev/null 2>&1; then
        print_info "✓ Kepler accessible at $KEPLER_URL"
    else
        print_warning "✗ Kepler not accessible at $KEPLER_URL - continuing without process metrics"
    fi
    
    print_info "Pre-flight checks completed"
}

# Generate output filename
generate_filename() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local hostname=$(hostname -s)
    echo "${OUTPUT_DIR}/vm_features_${hostname}_${timestamp}.json"
}

# Run the collector
run_collector() {
    local output_file=$(generate_filename)
    
    print_info "Starting VM Feature Collector"
    print_info "=============================="
    print_info "Duration: ${DURATION} seconds"
    print_info "Interval: ${INTERVAL} seconds"
    print_info "Output: $output_file"
    print_info "Kepler URL: $KEPLER_URL"
    print_info "Synchronized: $SYNC"
    print_info "Verbose: $VERBOSE"
    print_info ""
    
    # Build command arguments
    local args=(
        "--duration" "$DURATION"
        "--interval" "$INTERVAL"
        "--output" "$output_file"
        "--kepler-url" "$KEPLER_URL"
    )
    
    if [ "$VERBOSE" = true ]; then
        args+=("--verbose")
    fi
    
    if [ "$SYNC" = false ]; then
        args+=("--no-sync")
    fi
    
    # Change to project directory
    cd "$PROJECT_DIR"
    
    # Run the collector
    print_info "Executing: python3 src/vm_feature_collector.py ${args[*]}"
    python3 src/vm_feature_collector.py "${args[@]}"
    
    # Check if output was created
    if [ -f "$output_file" ]; then
        local file_size=$(stat -f%z "$output_file" 2>/dev/null || stat -c%s "$output_file")
        print_info "Collection completed successfully!"
        print_info "Output file: $output_file (${file_size} bytes)"
        
        # Show basic statistics
        if command -v jq >/dev/null 2>&1; then
            local point_count=$(jq '. | length' "$output_file")
            print_info "Collected $point_count feature points"
        fi
        
        # Check if CSV was also created
        local csv_file="${output_file%.json}.csv"
        if [ -f "$csv_file" ]; then
            print_info "CSV output: $csv_file"
        fi
    else
        print_error "Output file not created - check logs for errors"
        exit 1
    fi
}

# Main function
main() {
    print_info "VM Feature Collector Runner"
    print_info "VM: $(hostname)"
    print_info "Date: $(date)"
    print_info ""
    
    setup_environment
    preflight_checks
    run_collector
    
    print_info ""
    print_info "VM feature collection completed successfully!"
    print_info "Check the output files in the $OUTPUT_DIR directory."
}

# Run main function
main "$@"