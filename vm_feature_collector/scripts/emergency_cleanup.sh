#!/bin/bash
"""
Emergency Cleanup Script for VM Feature Collector

Use this script if the VM feature collector gets stuck and won't respond to Ctrl+C.
This will force-kill all related processes.

Usage:
    ./scripts/emergency_cleanup.sh
    # OR
    bash scripts/emergency_cleanup.sh
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[CLEANUP]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info "Emergency cleanup for VM Feature Collector"
print_info "=========================================="

# Kill Python VM feature collector processes
print_info "Killing VM feature collector processes..."
if pgrep -f "vm_feature_collector.py" > /dev/null; then
    pkill -f "vm_feature_collector.py" || true
    print_info "✓ Killed VM feature collector processes"
else
    print_info "✓ No VM feature collector processes found"
fi

# Kill all stress-ng processes
print_info "Killing stress-ng processes..."
if pgrep stress-ng > /dev/null; then
    pkill stress-ng || true
    sleep 2
    # Force kill if still running
    if pgrep stress-ng > /dev/null; then
        print_warning "Force killing stubborn stress-ng processes..."
        pkill -9 stress-ng || true
        killall -9 stress-ng 2>/dev/null || true
    fi
    print_info "✓ Killed stress-ng processes"
else
    print_info "✓ No stress-ng processes found"
fi

# Kill any Python processes that might be related
print_info "Checking for related Python processes..."
related_processes=$(pgrep -f "stress_workloads\|sequence_demo\|run_with_stress" || true)
if [ -n "$related_processes" ]; then
    print_warning "Killing related processes: $related_processes"
    echo "$related_processes" | xargs kill -9 2>/dev/null || true
    print_info "✓ Killed related processes"
else
    print_info "✓ No related processes found"
fi

# Check system load after cleanup
print_info "Checking system status after cleanup..."
load_avg=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//')
cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//' 2>/dev/null || echo "N/A")

print_info "System status:"
print_info "  Load average: $load_avg"
print_info "  CPU usage: $cpu_usage%"

# Verify cleanup was successful
remaining_stress=$(pgrep stress-ng | wc -l)
remaining_collector=$(pgrep -f "vm_feature_collector.py" | wc -l)

if [ "$remaining_stress" -eq 0 ] && [ "$remaining_collector" -eq 0 ]; then
    print_info ""
    print_info "🎉 CLEANUP SUCCESSFUL! 🎉"
    print_info "All VM feature collector and stress processes have been terminated."
    print_info ""
    print_info "You can now safely restart the VM feature collector:"
    print_info "  python3 src/vm_feature_collector.py --stress-workload cpu_cycling --duration 300"
else
    print_error ""
    print_error "⚠️ CLEANUP INCOMPLETE ⚠️"
    print_error "Some processes may still be running:"
    print_error "  stress-ng processes: $remaining_stress"
    print_error "  collector processes: $remaining_collector"
    print_error ""
    print_error "You may need to:"
    print_error "  1. Restart your terminal session"
    print_error "  2. Reboot the system if processes are truly stuck"
    print_error "  3. Check for hung processes: ps aux | grep -E '(stress|vm_feature)'"
fi

print_info ""
print_info "Emergency cleanup completed."