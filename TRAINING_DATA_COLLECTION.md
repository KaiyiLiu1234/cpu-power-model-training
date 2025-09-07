# Training Data Collection System

This document describes how to use the coordinated training data collection system for VM CPU power prediction models.

## Overview

The system consists of three main components:

1. **`orchestrate_training_data_collection.py`** - Main orchestrator that coordinates VM and baremetal data collection
2. **`merge_datasets.py`** - Merges VM features with baremetal power measurements by timestamp
3. **`bm_power_collector.py`** - Collects VM power metrics from Kepler on baremetal
4. **VM components** - `vm_feature_collector.py` and `stress_workloads.py` (run in VM)

## Prerequisites

### Baremetal Host
- Kepler running on `localhost:28283/metrics`
- SSH access to the target VM
- Python packages: `paramiko`, `pandas`, `numpy`, `requests`

### Virtual Machine
- VM accessible via SSH from baremetal
- Project deployed at `/root/cpu-power-model-training` (or custom path)
- Python packages: `psutil`, `requests`
- `stress-ng` installed for workload generation
- `perf` installed for performance counters

## Quick Start

### 1. Basic Collection

```bash
# Run coordinated data collection for VM 'fedora40'
python3 orchestrate_training_data_collection.py \
    --vm-name fedora40 \
    --vm-host 192.168.1.100 \
    --duration 800 \
    --workloads cycle,cpu_intensive \
    --cpu-intensive-duration 120
```

### 2. Merge the Datasets

```bash
# Merge VM features with baremetal power data
python3 merge_datasets.py \
    --vm-features data/vm_features_training_20241207_143022.json \
    --bm-power data/bm_power_training_20241207_143022.csv \
    --output data/training_dataset_20241207.csv
```

## Detailed Usage

### Orchestrate Data Collection

The orchestrator handles:
- Starting stress workloads in VM
- Starting synchronized feature and power collection
- Stopping all processes
- Copying VM data to baremetal

```bash
python3 orchestrate_training_data_collection.py \
    --vm-name fedora40 \                    # VM name for power filtering
    --vm-host 192.168.1.100 \               # VM IP/hostname
    --vm-user root \                        # SSH username (default: root)
    --vm-key-file ~/.ssh/vm_key \           # SSH private key (optional)
    --vm-project-path /root/cpu-power-model-training \  # Project path in VM
    --duration 800 \                        # Collection duration (seconds)
    --workloads cycle,cpu_intensive \       # Workload types
    --cpu-intensive-duration 120 \          # CPU intensive duration
    --output-prefix training \              # Output file prefix
    --interval 1.0 \                        # Collection interval (seconds)
    --kepler-url http://localhost:28283/metrics \  # Kepler endpoint
    --verbose                               # Enable verbose logging
```

### Merge Datasets

The merger aligns VM features with power measurements:

```bash
python3 merge_datasets.py \
    --vm-features data/vm_features_training_20241207.json \
    --bm-power data/bm_power_training_20241207.csv \
    --output data/training_dataset.csv \
    --time-tolerance 0.5 \                  # Max time diff for matching (seconds)
    --min-power-threshold 0.001 \           # Min power to include (watts)
    --power-zone core \                     # Power zone: 'core' or 'package'
    --verbose
```

## Manual Collection (Alternative)

If you prefer to run components separately:

### 1. Start VM Stress Workloads (in VM)
```bash
# SSH into VM and start stress workloads
python3 vm_feature_collector/src/stress_workloads.py \
    --workloads cycle,cpu_intensive \
    --cpu-intensive-duration 120
```

### 2. Start VM Feature Collection (in VM)
```bash
# In another terminal in VM
python3 vm_feature_collector/src/vm_feature_collector.py \
    --duration 800 \
    --interval 1.0 \
    --output data/vm_features_manual.json
```

### 3. Start Baremetal Power Collection (on baremetal)
```bash
# On baremetal host
python3 bm_power_collector.py \
    --vm-names fedora40 \
    --duration 800 \
    --interval 1.0 \
    --output data/bm_power_manual.csv
```

### 4. Merge the Datasets
```bash
python3 merge_datasets.py \
    --vm-features data/vm_features_manual.json \
    --bm-power data/bm_power_manual.csv \
    --output data/training_dataset_manual.csv
```

## Output Files

### VM Features (`vm_features_*.json`)
Contains per-second VM feature vectors:
- Performance counters (CPU cycles, instructions, cache metrics)
- OS metrics (CPU utilization, memory, I/O, network)
- System metrics (context switches, processes)
- Derived features (IPC, cache miss ratios)

### Baremetal Power (`bm_power_*.csv`)
Contains per-100ms power measurements:
- `total_cpu_watts_core` - Core zone CPU power for target VMs
- `total_cpu_watts_package` - Package zone CPU power for target VMs
- `vm_count` - Number of VMs contributing to total
- Timestamps aligned with VM collection

### Merged Training Dataset (`training_dataset_*.csv`)
Combined features and labels:
- All VM features as input variables
- `power_watts` as the target label (from selected zone)
- `time_diff` showing timestamp alignment quality
- Metadata about the merge process

## Data Quality

### Good Quality Indicators
- **Match rate > 90%** - Most VM features have corresponding power measurements
- **Average time diff < 0.2s** - Good timestamp synchronization
- **Power range appropriate** - Power values in expected range for workload

### Troubleshooting Poor Quality
- **Low match rate**: Check VM/BM clock synchronization
- **High time differences**: Reduce collection intervals or increase time tolerance
- **Missing power data**: Verify Kepler is running and VM name is correct
- **Low power values**: Check if VM is actually running workloads

## Best Practices

### Collection Parameters
- **Interval**: Use 1.0s for balanced resolution vs. data size
- **Duration**: 800s provides good workload coverage
- **Workloads**: `cycle,cpu_intensive` covers diverse CPU patterns

### VM Setup
- Ensure VM has sufficient resources (CPU, memory)
- Install required tools (`stress-ng`, `perf`)
- Verify performance counter access: `sudo sysctl kernel.perf_event_paranoid=1`

### Synchronization
- Start collections within 1-2 seconds of each other
- Use NTP for VM/baremetal clock synchronization
- Monitor collection progress to detect issues early

## Example End-to-End Workflow

```bash
# 1. Prepare VM (run once)
ssh root@192.168.1.100 "
    cd /root/cpu-power-model-training
    sudo sysctl kernel.perf_event_paranoid=1
    sudo dnf install stress-ng perf -y
"

# 2. Run coordinated collection
python3 orchestrate_training_data_collection.py \
    --vm-name fedora40 \
    --vm-host 192.168.1.100 \
    --duration 800 \
    --output-prefix experiment_001

# 3. Merge datasets (files auto-discovered from output)
python3 merge_datasets.py \
    --vm-features data/vm_features_experiment_001_*.json \
    --bm-power data/bm_power_experiment_001_*.csv \
    --output data/training_dataset_experiment_001.csv

# 4. Verify results
echo "Training dataset ready: data/training_dataset_experiment_001.csv"
head -5 data/training_dataset_experiment_001.csv
```

## Monitoring and Logs

- **Orchestrator logs**: `logs/orchestrator.log`
- **VM feature logs**: VM: `logs/vm_feature_collection.log` 
- **Baremetal power logs**: `logs/bm_power_collection.log`
- **Progress**: Real-time progress shown in console output

## Next Steps

After successful data collection:

1. **Data Analysis**: Load `training_dataset_*.csv` in pandas/sklearn
2. **Feature Engineering**: Analyze feature importance and correlations
3. **Model Training**: Train regression models to predict `power_watts`
4. **Model Validation**: Test model accuracy on held-out data
5. **Model Deployment**: Use trained model for VM power prediction

## Troubleshooting

### SSH Connection Issues
```bash
# Test SSH connectivity
ssh -v root@192.168.1.100 "echo 'SSH working'"

# Check SSH key authentication
ssh -i ~/.ssh/vm_key root@192.168.1.100 "whoami"
```

### Kepler Connectivity Issues
```bash
# Test Kepler endpoint
curl -s http://localhost:28283/metrics | grep kepler_vm_cpu_watts | head -5

# Check for target VM in metrics
curl -s http://localhost:28283/metrics | grep fedora40
```

### VM Project Issues
```bash
# Verify VM project structure
ssh root@192.168.1.100 "
    cd /root/cpu-power-model-training
    ls -la vm_feature_collector/src/
    python3 -c 'import psutil, requests'
"
```