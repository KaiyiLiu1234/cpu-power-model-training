#!/bin/bash
"""
VM Feature Collector Dependency Installation Script

This script installs system dependencies required for the VM Feature Collector
on various Linux distributions.
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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

# Detect the Linux distribution
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
        VERSION=$VERSION_ID
    else
        print_error "Cannot detect Linux distribution"
        exit 1
    fi
    
    print_info "Detected distribution: $DISTRO $VERSION"
}

# Install dependencies for Ubuntu/Debian
install_ubuntu_deps() {
    print_info "Installing dependencies for Ubuntu/Debian..."
    
    sudo apt-get update
    
    # Install perf tools
    KERNEL_VERSION=$(uname -r)
    sudo apt-get install -y linux-tools-${KERNEL_VERSION} || \
    sudo apt-get install -y linux-tools-generic || \
    print_warning "Could not install perf tools for kernel ${KERNEL_VERSION}"
    
    # Install Python development headers
    sudo apt-get install -y python3-dev python3-pip
    
    # Install other system tools
    sudo apt-get install -y curl wget
    
    print_info "Ubuntu/Debian dependencies installed successfully"
}

# Install dependencies for RHEL/Fedora/CentOS
install_rhel_deps() {
    print_info "Installing dependencies for RHEL/Fedora/CentOS..."
    
    # Use dnf for Fedora, yum for older RHEL/CentOS
    if command -v dnf &> /dev/null; then
        PKG_MGR="dnf"
    else
        PKG_MGR="yum"
    fi
    
    sudo $PKG_MGR update -y
    
    # Install perf tools
    sudo $PKG_MGR install -y perf
    
    # Install Python development
    sudo $PKG_MGR install -y python3-devel python3-pip
    
    # Install other system tools
    sudo $PKG_MGR install -y curl wget
    
    print_info "RHEL/Fedora/CentOS dependencies installed successfully"
}

# Install dependencies for SUSE
install_suse_deps() {
    print_info "Installing dependencies for SUSE..."
    
    sudo zypper refresh
    
    # Install perf tools
    sudo zypper install -y perf
    
    # Install Python development
    sudo zypper install -y python3-devel python3-pip
    
    # Install other system tools
    sudo zypper install -y curl wget
    
    print_info "SUSE dependencies installed successfully"
}

# Configure performance counter access
configure_perf_access() {
    print_info "Configuring performance counter access..."
    
    # Check current setting
    current_setting=$(sysctl -n kernel.perf_event_paranoid 2>/dev/null || echo "unknown")
    print_info "Current perf_event_paranoid setting: $current_setting"
    
    # Set for current session
    if [ "$current_setting" != "1" ] && [ "$current_setting" != "0" ] && [ "$current_setting" != "-1" ]; then
        print_info "Setting kernel.perf_event_paranoid=1 for current session..."
        sudo sysctl kernel.perf_event_paranoid=1
    fi
    
    # Make permanent
    if ! grep -q "kernel.perf_event_paranoid" /etc/sysctl.conf 2>/dev/null; then
        print_info "Making perf counter access permanent..."
        echo 'kernel.perf_event_paranoid=1' | sudo tee -a /etc/sysctl.conf
        print_info "Added kernel.perf_event_paranoid=1 to /etc/sysctl.conf"
    else
        print_info "Performance counter setting already exists in /etc/sysctl.conf"
    fi
}

# Install Python dependencies
install_python_deps() {
    print_info "Installing Python dependencies..."
    
    # Upgrade pip
    python3 -m pip install --upgrade pip
    
    # Install required packages
    python3 -m pip install psutil requests
    
    print_info "Python dependencies installed successfully"
}

# Test installation
test_installation() {
    print_info "Testing installation..."
    
    # Test perf access
    if perf stat -e cpu-cycles true 2>/dev/null; then
        print_info "✓ Performance counters accessible"
    else
        print_warning "✗ Performance counters not accessible - may need manual configuration"
    fi
    
    # Test Python modules
    if python3 -c "import psutil, requests" 2>/dev/null; then
        print_info "✓ Python dependencies available"
    else
        print_error "✗ Python dependencies not available"
        return 1
    fi
    
    # Test VM feature collector import
    if python3 -c "import sys; sys.path.append('src'); import vm_feature_collector" 2>/dev/null; then
        print_info "✓ VM Feature Collector module loadable"
    else
        print_warning "✗ VM Feature Collector module not loadable - check PYTHONPATH"
    fi
    
    print_info "Installation test completed"
}

# Main installation function
main() {
    print_info "VM Feature Collector Dependency Installation"
    print_info "============================================="
    
    # Check if running as root
    if [ "$EUID" -eq 0 ]; then
        print_warning "Running as root - some operations may not require sudo"
    fi
    
    # Detect distribution
    detect_distro
    
    # Install system dependencies based on distribution
    case $DISTRO in
        ubuntu|debian)
            install_ubuntu_deps
            ;;
        rhel|centos|fedora)
            install_rhel_deps
            ;;
        opensuse|sles)
            install_suse_deps
            ;;
        *)
            print_warning "Unsupported distribution: $DISTRO"
            print_warning "Please install dependencies manually:"
            print_warning "- perf tools (linux-tools, perf package)"
            print_warning "- python3-dev/python3-devel"
            print_warning "- python3-pip"
            ;;
    esac
    
    # Configure performance counter access
    configure_perf_access
    
    # Install Python dependencies
    install_python_deps
    
    # Test installation
    test_installation
    
    print_info "Installation completed!"
    print_info ""
    print_info "Next steps:"
    print_info "1. Reboot system to apply kernel parameter changes (optional)"
    print_info "2. Test the VM Feature Collector:"
    print_info "   python3 src/vm_feature_collector.py --duration 10 --verbose"
    print_info "3. Check the generated data files in the data/ directory"
}

# Run main function
main "$@"