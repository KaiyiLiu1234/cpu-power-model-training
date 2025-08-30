#!/bin/bash
"""
VM Feature Collector with Stress Workloads

This script runs the VM feature collector with various stress workloads to generate
comprehensive training data across different CPU utilization levels and computational
patterns. This is essential for training robust power prediction models.

Usage:
    ./run_with_stress.sh --workload cpu_cycling --duration 600
    ./run_with_stress.sh --workload comprehensive --duration 3600
    ./run_with_stress.sh --list-workloads
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default values
WORKLOAD=""
DURATION=300
INTERVAL=1.0
OUTPUT_DIR="data"
VERBOSE=false
KEPLER_URL="http://localhost:28282/metrics"
DRY_RUN=false

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

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

print_usage() {
    echo -e "${BLUE}VM Feature Collector with Stress Workloads${NC}"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -w, --workload TYPE         Stress workload type (required)"
    echo "  -d, --duration SECONDS      Collection duration in seconds (default: 300)"
    echo "  -i, --interval SECONDS      Collection interval in seconds (default: 1.0)"
    echo "  -o, --output-dir PATH       Output directory (default: data)"
    echo "  -k, --kepler-url URL        Kepler metrics URL (default: http://localhost:28282/metrics)"
    echo "  -v, --verbose               Enable verbose logging"
    echo "  -n, --dry-run               Show what would be done without executing"
    echo "  -l, --list-workloads        List available stress workloads"
    echo "  -h, --help                  Show this help message"
    echo ""
    echo "Available Workloads:"
    echo "  none                        No stress workload"
    echo "  cpu_cycling                 CPU load cycling (0-100% and back)"
    echo "  cpu_intensive               High CPU utilization patterns"
    echo "  memory_intensive            Memory allocation and access patterns"
    echo "  mixed_workload              CPU + memory + I/O combination"
    echo "  bursty_workload             Alternating high and low activity"
    echo "  matrix_computation          Matrix multiplication operations"
    echo "  branch_intensive            Branch prediction stress"
    echo "  cache_thrashing             Cache miss patterns"
    echo ""
    echo "Workload Sequences:"
    echo "  cpu_cycling:60,cpu_intensive:45    # 60s cycling, 45s intensive, repeat"
    echo "  cpu_cycling,cpu_intensive          # Equal time distribution"
    echo "  cpu_intensive,memory_intensive,mixed_workload  # Multi-workload cycling"
    echo "  idle                        System at rest"
    echo ""
    echo "Examples:"
    echo "  $0 -w cpu_cycling -d 600 -v                    # CPU cycling for 10 minutes"
    echo "  $0 -w cpu_intensive -d 1800                    # CPU intensive for 30 minutes"
    echo "  $0 -w 'cpu_cycling:60,cpu_intensive:45' -d 900 # Sequence cycling"
    echo "  $0 -w 'cpu_cycling,cpu_intensive' -d 1200      # Equal time sequence"
    echo "  $0 -l                                          # List all workloads"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--workload)
            WORKLOAD="$2"
            shift 2
            ;;
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
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -l|--list-workloads)
            cd "$PROJECT_DIR"
            python3 src/vm_feature_collector.py --list-workloads
            exit 0
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
if [[ -z "$WORKLOAD" ]]; then
    print_error "Workload type is required"
    print_usage
    exit 1
fi

if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [ "$DURATION" -le 0 ]; then
    print_error "Duration must be a positive integer"
    exit 1
fi

if ! [[ "$INTERVAL" =~ ^[0-9]+\.?[0-9]*$ ]] || [ "$(echo "$INTERVAL <= 0" | bc -l 2>/dev/null || echo "1")" -eq 1 ]; then
    print_error "Interval must be a positive number"
    exit 1
fi

# Setup environment
setup_environment() {
    print_info "Setting up environment..."
    
    # Change to project directory
    cd "$PROJECT_DIR"
    
    # Create directories
    mkdir -p "$OUTPUT_DIR"
    mkdir -p logs
    
    # Check Python dependencies
    if ! python3 -c "import psutil, requests" 2>/dev/null; then
        print_error "Python dependencies not found. Run scripts/install_deps.sh first."
        exit 1
    fi
    
    # Check if VM feature collector exists
    if [ ! -f "src/vm_feature_collector.py" ]; then
        print_error "VM feature collector not found at src/vm_feature_collector.py"
        exit 1
    fi
    
    # Check if stress workloads module exists
    if [ ! -f "src/stress_workloads.py" ]; then
        print_error "Stress workloads module not found at src/stress_workloads.py"
        exit 1
    fi
    
    # Check stress-ng availability
    if ! command -v stress-ng &> /dev/null; then
        print_warning "stress-ng not found. Install with:"
        print_warning "  sudo dnf install stress-ng  # or apt-get install stress-ng"
        if [[ "$WORKLOAD" != "none" && "$WORKLOAD" != "idle" ]]; then
            print_error "stress-ng is required for workload: $WORKLOAD"
            exit 1
        fi
    fi
    
    print_info "Environment setup completed"
}

# Pre-flight checks
preflight_checks() {
    print_info "Running pre-flight checks..."
    
    # Check system load
    load=$(uptime | awk -F'load average:' '{ print $2 }' | awk '{ print $1 }' | sed 's/,//')
    if [ "$(echo "$load > 5.0" | bc -l 2>/dev/null || echo "0")" -eq 1 ]; then
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
    
    # Test VM feature collector
    print_info "Testing VM feature collector..."
    if ! python3 src/vm_feature_collector.py --list-workloads >/dev/null 2>&1; then
        print_error "VM feature collector test failed"
        exit 1
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
    echo "${OUTPUT_DIR}/vm_features_${WORKLOAD}_${hostname}_${timestamp}.json"
}

# Monitor stress workload
monitor_stress() {
    local duration=$1
    local start_time=$(date +%s)
    local end_time=$((start_time + duration))
    
    print_info "Monitoring stress workload for ${duration} seconds..."
    
    while [ $(date +%s) -lt $end_time ]; do
        local elapsed=$(($(date +%s) - start_time))
        local remaining=$((duration - elapsed))
        local progress=$((elapsed * 100 / duration))
        
        # Get current system stats
        local cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//' 2>/dev/null || echo "N/A")
        local mem_usage=$(free | grep Mem | awk '{printf "%.1f", $3/$2 * 100.0}' 2>/dev/null || echo "N/A")
        local load_avg=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//' 2>/dev/null || echo "N/A")
        
        print_info "Stress monitor: ${progress}% complete (${remaining}s remaining) - CPU=${cpu_usage}% MEM=${mem_usage}% LOAD=${load_avg}"
        
        sleep 30
    done
}

# Run the VM feature collector with stress workload
run_collection() {
    local output_file=$(generate_filename)
    
    print_step "Starting VM Feature Collection with Stress Workload"
    print_info "========================================="
    print_info "Workload: $WORKLOAD"
    print_info "Duration: ${DURATION} seconds"
    print_info "Interval: ${INTERVAL} seconds"
    print_info "Output: $output_file"
    print_info "Kepler URL: $KEPLER_URL"
    print_info "Verbose: $VERBOSE"
    print_info ""
    
    if [ "$DRY_RUN" = true ]; then
        print_info "DRY RUN - Would execute:"
        echo "  python3 src/vm_feature_collector.py \\"
        echo "    --duration $DURATION \\"
        echo "    --interval $INTERVAL \\"
        echo "    --output '$output_file' \\"
        echo "    --kepler-url '$KEPLER_URL' \\"
        echo "    --stress-workload '$WORKLOAD'"
        if [ "$VERBOSE" = true ]; then
            echo "    --verbose"
        fi
        return 0
    fi
    
    # Build command arguments
    local args=(
        "--duration" "$DURATION"
        "--interval" "$INTERVAL"
        "--output" "$output_file"
        "--kepler-url" "$KEPLER_URL"
        "--stress-workload" "$WORKLOAD"
    )
    
    if [ "$VERBOSE" = true ]; then
        args+=("--verbose")
    fi
    
    # Run the collector in background so we can monitor
    print_info "Executing: python3 src/vm_feature_collector.py ${args[*]}"
    python3 src/vm_feature_collector.py "${args[@]}" &
    local collector_pid=$!
    
    # Monitor the collection in background
    monitor_stress "$DURATION" &
    local monitor_pid=$!
    
    # Wait for collector to finish
    wait $collector_pid
    local collector_exit_code=$?
    
    # Stop monitoring
    kill $monitor_pid 2>/dev/null || true
    wait $monitor_pid 2>/dev/null || true
    
    # Check results
    if [ $collector_exit_code -eq 0 ] && [ -f "$output_file" ]; then
        local file_size=$(stat -f%z "$output_file" 2>/dev/null || stat -c%s "$output_file")
        print_info "Collection completed successfully!"
        print_info "Output file: $output_file (${file_size} bytes)"
        
        # Show basic statistics if jq is available
        if command -v jq >/dev/null 2>&1; then
            local point_count=$(jq '. | length' "$output_file" 2>/dev/null || echo "unknown")
            print_info "Collected $point_count feature points"
        fi
        
        # Check if CSV was also created
        local csv_file="${output_file%.json}.csv"
        if [ -f "$csv_file" ]; then
            print_info "CSV output: $csv_file"
        fi
    else
        print_error "Collection failed - check logs for errors"
        exit 1
    fi
}

# Main function
main() {
    print_info "VM Feature Collector with Stress Workloads"
    print_info "VM: $(hostname)"
    print_info "Date: $(date)"
    print_info ""
    
    setup_environment
    preflight_checks
    run_collection
    
    print_info ""
    print_info "VM feature collection with stress workload completed successfully!"
    print_info "Output files are in the $OUTPUT_DIR directory."
    print_info ""
    print_info "Next steps:"
    print_info "1. Run this script with different workloads to collect comprehensive data"
    print_info "2. Collect corresponding power measurements on the baremetal side"
    print_info "3. Merge VM features with power data for model training"
}

# Handle script termination
cleanup() {
    print_info "Cleaning up..."
    # Kill any background processes
    jobs -p | xargs -r kill 2>/dev/null || true
    # Kill any stress-ng processes
    pkill -f stress-ng 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Run main function
main "$@"