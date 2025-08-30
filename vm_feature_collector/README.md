# VM Feature Collector

A Python tool for collecting virtual machine performance metrics that can be used for CPU power prediction models. This tool is designed to run inside virtual machines to gather features that are accessible in virtualized environments.

## Overview

The VM Feature Collector is part of the Kepler energy monitoring ecosystem. While Kepler on bare metal can directly measure hardware power consumption, virtual machines lack access to hardware power measurement interfaces (RAPL, IPMI, etc.). This tool collects VM-accessible performance metrics that can be used as features for machine learning models to predict CPU power consumption.

## Key Features

- **VM-Compatible Metrics**: Collects only metrics available within virtual machine environments
- **Performance Counters**: Gathers PMC data via perf when available
- **OS-Level Metrics**: Collects CPU, memory, I/O, and system metrics via /proc filesystem  
- **Kepler Integration**: Aggregates `kepler_process_cpu_seconds` as a node-level feature
- **Zone Focus**: Targets package and core zones for power prediction
- **Synchronized Collection**: Aligns all metrics to the same time window for accuracy
- **Multiple Output Formats**: Saves data in JSON and CSV formats
- **Timestamp Recording**: Records precise timestamps for synchronization with external power measurements
- **Stress Workload Integration**: Built-in stress-ng integration for generating diverse CPU utilization patterns
- **CPU Load Cycling**: Automated 0-100% CPU load cycling for comprehensive training data
- **Multiple Workload Types**: CPU-intensive, memory-intensive, mixed, bursty, and specialized computational patterns

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    VM Environment (Guest)                  │
│  ┌───────────────┐  ┌─────────────────┐  ┌─────────────────┐│
│  │ OS Counters   │  │ Memory Counters │  │ Perf Counters   ││  
│  │ /proc/stat    │  │ /proc/meminfo   │  │ CPU cycles,     ││
│  │ /proc/loadavg │  │ /proc/vmstat    │  │ instructions,   ││
│  │ CPU util      │  │ Page faults     │  │ cache misses    ││
│  └───────────────┘  └─────────────────┘  └─────────────────┘│
│                             ▲                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Stress Workload Manager                   ││
│  │   stress-ng integration for diverse CPU patterns       ││
│  │   - CPU cycling (0-100% and back)                      ││
│  │   - Matrix computation, branch prediction               ││
│  │   - Memory intensive, mixed workloads                  ││
│  └─────────────────────────────────────────────────────────┘│
│                             │                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │           VM Feature Collector                         ││
│  │     Collects features for power prediction             ││
│  │     - Package zone features                            ││
│  │     - Core zone features                               ││
│  │     - Node process CPU seconds (from VM Kepler)       ││
│  │     - Stress workload type annotation                  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                                │
                                │ Feature Data (JSON/CSV)
                                ▼
        ┌─────────────────────────────────────────────┐
        │        External Power Measurement           │
        │    (Baremetal Kepler tracking QEMU proc)   │
        └─────────────────────────────────────────────┘
                                │
                                ▼
        ┌─────────────────────────────────────────────┐
        │        Training Data Creation               │
        │     VM Features + Power Labels              │
        └─────────────────────────────────────────────┘
```

## Installation

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd vm_feature_collector

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

### Using pip

```bash
pip install vm-feature-collector
```

## Dependencies

- **Python 3.7+**
- **psutil**: System and process utilities
- **requests**: HTTP client for Kepler metrics (optional)
- **perf**: Linux performance counters (system dependency)

### System Requirements

- Linux operating system (tested on Fedora, Ubuntu)
- Performance counter access (`kernel.perf_event_paranoid` setting)
- Optional: Kepler deployed in the VM for process CPU seconds

## Usage

### Basic Usage

```bash
# Collect features for 5 minutes, save to JSON
python3 src/vm_feature_collector.py --duration 300 --output data/vm_features.json

# Collect with custom interval and verbose logging
python3 src/vm_feature_collector.py --duration 600 --interval 0.5 --verbose
```

### Stress Workload Integration

The VM Feature Collector includes built-in stress-ng integration to generate diverse CPU utilization patterns during feature collection. This is **critical** for training robust power prediction models across different load levels.

```bash
# CPU load cycling from 0% to 100% and back down
python3 src/vm_feature_collector.py --stress-workload cpu_cycling --duration 600

# High CPU utilization with computational patterns
python3 src/vm_feature_collector.py --stress-workload cpu_intensive --duration 300

# Mixed CPU, memory, and I/O stress
python3 src/vm_feature_collector.py --stress-workload mixed_workload --duration 450

# List all available stress workloads
python3 src/vm_feature_collector.py --list-workloads
```

#### Available Stress Workloads

- **`cpu_cycling`**: Smooth cycling from 0% to 100% CPU load and back down (multiple cycles)
- **`cpu_intensive`**: High CPU utilization with prime numbers, matrix multiplication, integer arithmetic
- **`memory_intensive`**: Memory allocation patterns, cache thrashing, sequential/random access
- **`mixed_workload`**: Combination of CPU, memory, and I/O stress patterns
- **`bursty_workload`**: Alternating high and low activity (15s high, 15s low)
- **`matrix_computation`**: Matrix multiplication and FFT operations
- **`branch_intensive`**: Branch prediction and conditional logic stress
- **`cache_thrashing`**: Cache miss patterns and memory hierarchy stress
- **`idle`**: No additional stress - system at natural load
- **`none`**: No stress workload (default)

#### Workload Sequences 🔄

You can specify **multiple workloads that cycle through** until the total duration ends:

```bash
# Cycle between CPU cycling (60s) and CPU intensive (45s) - repeats until duration ends
python3 src/vm_feature_collector.py --stress-workload "cpu_cycling:60,cpu_intensive:45" --duration 600

# Equal time distribution between workloads
python3 src/vm_feature_collector.py --stress-workload "cpu_cycling,cpu_intensive" --duration 480

# Complex multi-workload sequence
python3 src/vm_feature_collector.py --stress-workload "cpu_intensive:120,memory_intensive:90,mixed_workload:60" --duration 900
```

**Sequence Format:**
- `workload1:duration1,workload2:duration2` - Specific durations
- `workload1,workload2,workload3` - Equal time distribution
- Sequences **loop continuously** until total collection duration ends
- Perfect for comprehensive training data across multiple utilization patterns

#### Convenience Script

```bash
# Use the convenience script for easier stress workload management
scripts/run_with_stress.sh --workload cpu_cycling --duration 600 --verbose

# Run workload sequence with the convenience script
scripts/run_with_stress.sh --workload 'cpu_cycling:60,cpu_intensive:45' --duration 900

# Run comprehensive data collection with monitoring
scripts/run_with_stress.sh --workload mixed_workload --duration 900
```

### Command Line Options

```bash
python3 src/vm_feature_collector.py [OPTIONS]

Options:
  --duration SECONDS    Collection duration in seconds (default: 300)
  --output PATH         Output file path (default: data/vm_features.json)
  --kepler-url URL      VM Kepler metrics URL (default: http://localhost:28282/metrics)
  --interval SECONDS    Collection interval in seconds (default: 1.0)
  --verbose             Enable verbose logging
  --no-sync             Disable synchronized bracketed window collection
```

### Configuration

#### Performance Counter Setup

Enable performance counter access:

```bash
# Temporary (until reboot)
sudo sysctl kernel.perf_event_paranoid=1

# Permanent
echo 'kernel.perf_event_paranoid=1' | sudo tee -a /etc/sysctl.conf
```

#### Kepler in VM (Optional)

If Kepler is deployed in the VM, the collector will gather `kepler_process_cpu_seconds` as an additional feature:

```bash
# Check if Kepler is accessible
curl http://localhost:28282/metrics | grep kepler_process_cpu_seconds
```

## Output Format

The collector outputs data in both JSON and CSV formats:

### JSON Output Structure

```json
[
  {
    "timestamp": 1692984532.123,
    "timestamp_iso": "2023-08-25T12:35:32.123456",
    "vm_hostname": "test-vm-1",
    "target_zones": ["package", "core"],
    
    "cpu_cycles": 1234567890,
    "instructions": 987654321,
    "cache_references": 12345678,
    "cache_misses": 1234567,
    "branches": 123456789,
    "branch_misses": 1234567,
    "page_faults": 12345,
    "context_switches": 123456,
    
    "cpu_utilization": 45.2,
    "cpu_user_time": 25.1,
    "cpu_system_time": 15.3,
    "cpu_nice_time": 0.0,
    "cpu_iowait": 2.1,
    "cpu_irq": 0.1,
    "cpu_softirq": 0.3,
    "cpu_steal": 2.3,
    "cpu_idle": 54.8,
    
    "memory_usage_percent": 67.8,
    "memory_available_gb": 1.234,
    "disk_io_read_mb": 0.123,
    "disk_io_write_mb": 0.456,
    "network_bytes_sent": 12345,
    "network_bytes_recv": 54321,
    
    "process_count": 234,
    "load_average_1min": 1.23,
    "load_average_5min": 1.45,
    "load_average_15min": 1.67,
    
    "instructions_per_cycle": 0.789,
    "cache_miss_ratio": 0.123,
    "branch_miss_ratio": 0.045,
    "cpu_efficiency": 0.678,
    
    "node_process_cpu_seconds_total": 1234.56,
    "node_process_cpu_seconds_delta": 1.23,
    "node_process_cpu_seconds_rate": 1.23,
    
    "collection_interval": 1.0,
    "time_delta_seconds": 1.001
  }
]
```

## Integration with Training Pipeline

The VM Feature Collector is designed to work with external power measurement systems:

1. **VM Side**: Run `vm_feature_collector.py` to gather features
2. **Baremetal Side**: Run power measurement script to track QEMU process power
3. **Data Fusion**: Merge VM features with power measurements using timestamps
4. **Model Training**: Use combined dataset for training zone-specific power models

### Example Integration

```bash
# In VM: Collect features
python3 src/vm_feature_collector.py --duration 3600 --output vm_features.json

# On baremetal: Collect power (separate script)
python3 baremetal_power_collector.py --duration 3600 --vm-pid $(pgrep qemu)

# Merge datasets (separate script)
python3 merge_vm_power_data.py --vm-features vm_features.json --power-data power_data.json
```

## Collected Features

### Performance Counters (PMC)
- `cpu_cycles`: Total CPU cycles
- `instructions`: Instructions executed
- `cache_references`: Cache accesses
- `cache_misses`: Cache misses
- `branches`: Branch instructions
- `branch_misses`: Branch mispredictions
- `page_faults`: Memory page faults
- `context_switches`: Context switches

### OS-Level Metrics
- `cpu_utilization`: Overall CPU usage percentage
- `cpu_user_time`: User-space CPU time percentage
- `cpu_system_time`: Kernel-space CPU time percentage
- `cpu_steal`: Stolen CPU time (virtualization overhead)
- Memory usage and availability
- Disk I/O throughput
- Network I/O throughput
- System load averages
- Process count

### Derived Features
- `instructions_per_cycle`: IPC efficiency metric
- `cache_miss_ratio`: Cache efficiency metric
- `branch_miss_ratio`: Branch prediction efficiency
- `cpu_efficiency`: Active CPU time ratio

### Kepler Integration
- `node_process_cpu_seconds_total`: Sum of all process CPU seconds from VM Kepler
- `node_process_cpu_seconds_delta`: Change in process CPU seconds
- `node_process_cpu_seconds_rate`: Rate of process CPU seconds

## Troubleshooting

### Performance Counter Issues

```bash
# Check perf permissions
perf stat -e cpu-cycles true

# If access denied, adjust paranoid setting
sudo sysctl kernel.perf_event_paranoid=1
```

### Kepler Connection Issues

```bash
# Check if Kepler is running in VM
curl http://localhost:28282/metrics

# Check Kepler pod status (if using Kubernetes)
kubectl get pods -n kepler-system
```

### Missing Dependencies

```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install linux-tools-$(uname -r) python3-dev

# Install system dependencies (RHEL/Fedora)
sudo dnf install perf python3-devel
```

## Limitations

- **VM Environment Only**: Designed for virtual machine environments
- **Linux Only**: Currently supports Linux-based VMs
- **Performance Counter Availability**: Some PMCs may not be available in all VM configurations
- **No Hardware Power Access**: Cannot directly measure hardware power consumption
- **Zone Focus**: Currently focuses on package and core zones only

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is licensed under the Apache License 2.0. See the LICENSE file for details.

## Related Projects

- [Kepler](https://sustainable-computing.io/kepler/): Kubernetes-native energy monitoring
- [vm_energy_modeling](../vm_energy_modeling/): Complete VM energy modeling pipeline
- [model-server-research](../): Energy modeling research and development

## Support

For issues and questions:

- Create an issue in the [Kepler repository](https://github.com/sustainable-computing-io/kepler/issues)
- Join the [Kepler community discussions](https://github.com/sustainable-computing-io/kepler/discussions)
- Review the [Kepler documentation](https://sustainable-computing.io/kepler/)