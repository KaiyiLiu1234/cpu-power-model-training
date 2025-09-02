#!/usr/bin/env python3
"""
Virtual Machine Feature Collector
Collects VM-accessible performance metrics for CPU power prediction

This module runs inside a virtual machine to collect features that can be used
for CPU power estimation. Unlike the baremetal data_collector.py which collects
training data, this script focuses on feature collection for inference.

Key differences from baremetal data_collector.py:
1. Runs inside VM (not on baremetal)
2. Collects features only (no power ground truth)
3. Includes kepler_process_cpu_seconds aggregation as a feature
4. Focuses on package and core zones only
5. Records timestamps for synchronization with external power measurements

Usage:
    python3 vm_feature_collector.py --duration 3600 --output vm_features.json
    python3 vm_feature_collector.py --kepler-url http://localhost:28282/metrics --interval 1.0
"""

import subprocess
import time
import json
import requests
import argparse
import logging
import signal
import sys
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import psutil
import threading
from pathlib import Path
from datetime import datetime
import os

# Configure logging - find logs directory relative to script location
script_dir = Path(__file__).parent
logs_dir = script_dir.parent / 'logs'
logs_dir.mkdir(exist_ok=True)
log_file = logs_dir / 'vm_feature_collection.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class VMFeaturePoint:
    """Single VM feature data point for power prediction"""
    timestamp: float
    timestamp_iso: str
    
    # VM-compatible PMC features (inputs for prediction)
    cpu_cycles: int
    instructions: int
    cache_references: int
    cache_misses: int
    branches: int
    branch_misses: int
    page_faults: int
    context_switches: int
    
    # OS-level features (always available in VMs)
    cpu_utilization: float
    cpu_user_time: float
    cpu_system_time: float
    cpu_nice_time: float
    cpu_iowait: float
    cpu_irq: float
    cpu_softirq: float
    cpu_steal: float
    cpu_idle: float
    
    # Memory and I/O features
    memory_usage_percent: float
    memory_available_gb: float
    disk_io_read_mb: float
    disk_io_write_mb: float
    network_bytes_sent: float
    network_bytes_recv: float
    
    # Process count and system load
    process_count: int
    load_average_1min: float
    load_average_5min: float
    load_average_15min: float
    
    # Derived features (calculated on-the-fly)
    instructions_per_cycle: float
    cache_miss_ratio: float
    branch_miss_ratio: float
    cpu_efficiency: float
    
    # System-level CPU metrics from /proc/stat (delta values in seconds)
    # These replace the less accurate Kepler-based node_cpu_seconds
    sys_cpu_user_seconds: float = 0.0      # Delta of user CPU time
    sys_cpu_system_seconds: float = 0.0    # Delta of system CPU time  
    sys_cpu_total_seconds: float = 0.0     # Delta of total active CPU time (user + system + nice)
    
    # System activity metrics from /proc/stat (delta values)
    sys_context_switches: int = 0          # Delta of context switches
    sys_processes_created: int = 0         # Delta of processes created
    
    # Current system state (instantaneous values)
    sys_procs_running: int = 0             # Number of currently running processes
    sys_procs_blocked: int = 0             # Number of blocked processes
    
    # Metadata
    collection_interval: float = 1.0
    time_delta_seconds: float = 0.0
    vm_hostname: str = ""
    target_zones: List[str] = None  # ["package", "core"]
    
    def __post_init__(self):
        if self.target_zones is None:
            self.target_zones = ["package", "core"]

class VMFeatureCollector:
    """Collects VM features for CPU power prediction"""
    
    def __init__(self, kepler_url="http://localhost:28282/metrics", 
                 collection_interval=1.0, max_retries=3, synchronized=True,
):
        self.kepler_url = kepler_url
        self.collection_interval = collection_interval
        self.max_retries = max_retries
        self.synchronized = synchronized
        
        # Data storage
        self.feature_data: List[VMFeaturePoint] = []
        self.collection_active = False
        
        # Performance counter availability
        self.available_pmcs = self._check_pmc_availability()
        
        # Previous values for delta calculations
        self.prev_disk_io = None
        self.prev_network = None
        self.prev_proc_stat = None  # Previous /proc/stat snapshot for delta calculations
        self.prev_collection_time = 0.0
        
        # VM metadata
        self.vm_hostname = self._get_vm_hostname()
        
        # Signal handling for graceful shutdown
        self._shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Initialized VM feature collector on {self.vm_hostname}")
        logger.info(f"Available PMCs: {len(self.available_pmcs)}")
        logger.info(f"System metrics source: /proc/stat (direct system measurement)")
        logger.info(f"Target zones: package, core")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        if self._shutdown_requested:
            # Second Ctrl+C - force exit immediately
            logger.warning("Force shutdown requested - killing all processes immediately!")
            self._force_cleanup()
            sys.exit(1)
        
        logger.info(f"Received signal {signum}, stopping feature collection...")
        self._shutdown_requested = True
        self.collection_active = False
        
        
        logger.info("Shutdown initiated - press Ctrl+C again to force quit")
    
    def _force_cleanup(self):
        """Force cleanup of all processes"""
        try:
            pass  # No stress processes to clean up
        except Exception as e:
            logger.debug(f"Force cleanup error: {e}")
    
    def _get_vm_hostname(self) -> str:
        """Get VM hostname for identification"""
        try:
            import socket
            return socket.gethostname()
        except Exception:
            return "unknown-vm"
    
    def _check_pmc_availability(self) -> List[str]:
        """Check which performance counters are available in this VM"""
        candidate_events = [
            'cpu-cycles', 'instructions', 'cache-references', 'cache-misses',
            'branches', 'branch-misses', 'page-faults', 'context-switches'
        ]
        
        available_events = []
        
        for event in candidate_events:
            test_cmd = ['perf', 'stat', '-e', event, 'true']
            try:
                result = subprocess.run(test_cmd, capture_output=True, timeout=5)
                if result.returncode == 0:
                    available_events.append(event)
                    logger.debug(f"PMC available in VM: {event}")
                else:
                    logger.warning(f"PMC not available in VM: {event}")
            except Exception as e:
                logger.warning(f"Error testing PMC {event} in VM: {e}")
        
        if not available_events:
            logger.warning("No performance counters available in VM! Check perf permissions.")
            logger.info("Try: sudo sysctl kernel.perf_event_paranoid=1")
        
        return available_events
    
    def _read_proc_stat(self) -> Dict[str, any]:
        """Read and parse /proc/stat for system-wide metrics.
        
        Returns dict with parsed metrics, gracefully handling missing fields.
        This works in both VMs and bare metal environments.
        """
        try:
            with open('/proc/stat', 'r') as f:
                content = f.read()
            
            metrics = {}
            
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                parts = line.split()
                if not parts:
                    continue
                    
                # Parse aggregated CPU line (first line: "cpu ...")
                if parts[0] == 'cpu':
                    # CPU fields: user nice system idle iowait irq softirq steal guest guest_nice
                    cpu_fields = ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal', 'guest', 'guest_nice']
                    cpu_values = {}
                    
                    for i, field in enumerate(cpu_fields):
                        if i + 1 < len(parts):
                            try:
                                cpu_values[field] = int(parts[i + 1])
                            except (ValueError, IndexError):
                                cpu_values[field] = 0
                        else:
                            cpu_values[field] = 0
                    
                    metrics['cpu'] = cpu_values
                    
                # Parse context switches
                elif parts[0] == 'ctxt' and len(parts) >= 2:
                    try:
                        metrics['context_switches'] = int(parts[1])
                    except ValueError:
                        pass
                        
                # Parse processes created
                elif parts[0] == 'processes' and len(parts) >= 2:
                    try:
                        metrics['processes_created'] = int(parts[1])
                    except ValueError:
                        pass
                        
                # Parse currently running processes
                elif parts[0] == 'procs_running' and len(parts) >= 2:
                    try:
                        metrics['procs_running'] = int(parts[1])
                    except ValueError:
                        pass
                        
                # Parse blocked processes
                elif parts[0] == 'procs_blocked' and len(parts) >= 2:
                    try:
                        metrics['procs_blocked'] = int(parts[1])
                    except ValueError:
                        pass
            
            return metrics
            
        except (IOError, OSError, PermissionError) as e:
            logger.warning(f"Cannot access /proc/stat: {e} - system metrics will be unavailable")
            return {}
        except Exception as e:
            logger.warning(f"Failed to parse /proc/stat: {e} - continuing with available metrics")
            return {}
    
    def _compute_proc_stat_deltas(self, prev_stat: Dict, curr_stat: Dict, time_delta: float) -> Dict[str, float]:
        """Compute delta metrics from /proc/stat snapshots.
        
        Args:
            prev_stat: Previous /proc/stat snapshot
            curr_stat: Current /proc/stat snapshot  
            time_delta: Time between snapshots in seconds
            
        Returns:
            Dict with computed delta metrics and utilization percentages
        """
        deltas = {}
        
        if not prev_stat or not curr_stat:
            logger.debug("Missing /proc/stat data for delta computation")
            return deltas
            
        try:
            # CPU time deltas (convert from jiffies to seconds)
            # Note: jiffies are typically 1/100th of a second, but we get the actual delta
            prev_cpu = prev_stat.get('cpu', {})
            curr_cpu = curr_stat.get('cpu', {})
            
            if prev_cpu and curr_cpu:
                # Calculate deltas in jiffies, then convert to seconds
                # Get the actual system clock ticks per second
                try:
                    import os
                    jiffies_per_second = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                except (KeyError, AttributeError, OSError):
                    # Fallback to standard value if sysconf fails
                    jiffies_per_second = 100  # Standard USER_HZ value
                    logger.debug("Could not determine system clock ticks, using default 100 Hz")
                
                cpu_deltas = {}
                total_delta = 0
                
                for field in ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal']:
                    prev_val = prev_cpu.get(field, 0)
                    curr_val = curr_cpu.get(field, 0)
                    delta_jiffies = max(0, curr_val - prev_val)
                    delta_seconds = delta_jiffies / jiffies_per_second
                    cpu_deltas[field] = delta_seconds
                    total_delta += delta_jiffies
                
                # Store delta values in seconds
                deltas['sys_cpu_user_seconds'] = cpu_deltas['user']
                deltas['sys_cpu_system_seconds'] = cpu_deltas['system']
                deltas['sys_cpu_total_seconds'] = cpu_deltas['user'] + cpu_deltas['system'] + cpu_deltas['nice']
                
                # Calculate CPU utilization as a percentage
                if total_delta > 0:
                    # total_delta is already in jiffies, cpu_deltas['idle'] is in seconds
                    idle_jiffies = cpu_deltas['idle'] * jiffies_per_second
                    active_jiffies = total_delta - idle_jiffies
                    deltas['sys_cpu_utilization'] = (active_jiffies / total_delta) * 100.0
                else:
                    deltas['sys_cpu_utilization'] = 0.0
                    
                # Store individual CPU time percentages for compatibility
                if total_delta > 0:
                    for field in ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal']:
                        field_jiffies = cpu_deltas[field] * jiffies_per_second
                        percentage = (field_jiffies / total_delta) * 100.0
                        deltas[f'sys_cpu_{field}_percent'] = percentage
            
            # Context switches delta
            prev_ctxt = prev_stat.get('context_switches', 0)
            curr_ctxt = curr_stat.get('context_switches', 0)
            deltas['sys_context_switches'] = max(0, curr_ctxt - prev_ctxt)
            
            # Processes created delta  
            prev_procs = prev_stat.get('processes_created', 0)
            curr_procs = curr_stat.get('processes_created', 0)
            deltas['sys_processes_created'] = max(0, curr_procs - prev_procs)
            
            # Current system state (instantaneous)
            deltas['sys_procs_running'] = curr_stat.get('procs_running', 0)
            deltas['sys_procs_blocked'] = curr_stat.get('procs_blocked', 0)
            
        except Exception as e:
            logger.error(f"Failed to compute /proc/stat deltas: {e}")
            
        return deltas
    
    def collect_kepler_process_metrics(self) -> Dict[str, float]:
        """Collect Kepler process CPU seconds from VM-deployed Kepler.
        
        In the VM, Kepler tracks processes but cannot measure hardware power.
        We collect the process CPU seconds total as a feature for prediction.
        This represents the total CPU utilization tracked by Kepler in the VM.
        """
        for attempt in range(self.max_retries):
            try:
                response = requests.get(self.kepler_url, timeout=5)
                response.raise_for_status()
                
                metrics: Dict[str, float] = {}
                process_cpu_seconds_total = 0.0
                
                for line in response.text.split('\n'):
                    # Sum all process CPU seconds total from VM Kepler
                    if line.startswith('kepler_process_cpu_seconds_total'):
                        try:
                            value = float(line.split()[-1])
                            process_cpu_seconds_total += value
                        except (ValueError, IndexError):
                            continue
                
                # Store aggregated process cpu seconds total at node level
                if process_cpu_seconds_total > 0:
                    metrics['node_process_cpu_seconds_total'] = process_cpu_seconds_total
                    logger.debug(f"VM Kepler process CPU seconds total: {process_cpu_seconds_total}")
                else:
                    logger.debug("No Kepler process CPU seconds found in VM")
                
                return metrics
                
            except requests.RequestException as e:
                logger.warning(f"VM Kepler request failed (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                else:
                    logger.warning("Cannot access VM Kepler metrics - continuing without")
                    return {}
            except Exception as e:
                logger.error(f"Unexpected error collecting VM Kepler metrics: {e}")
                return {}
        
        return {}
    
    def collect_pmc_metrics(self) -> Dict[str, int]:
        """Collect VM-accessible performance counters"""
        if not self.available_pmcs:
            logger.debug("No PMCs available in VM, skipping PMC collection")
            return {}
        
        perf_cmd = [
            'perf', 'stat', '-a', '-e', ','.join(self.available_pmcs),
            '-x', ',', 'sleep', str(self.collection_interval)
        ]
        
        try:
            result = subprocess.run(perf_cmd, capture_output=True, text=True, timeout=self.collection_interval + 5)
            
            if result.returncode != 0:
                logger.warning(f"VM perf command failed: {result.stderr}")
                return {}
            
            return self._parse_perf_output(result.stderr)
            
        except subprocess.TimeoutExpired:
            logger.error("VM PMC collection timed out")
            return {}
        except Exception as e:
            logger.error(f"VM PMC collection failed: {e}")
            return {}
    
    def _parse_perf_output(self, stderr_output: str) -> Dict[str, int]:
        """Parse perf stat output into metrics dictionary"""
        metrics = {}
        
        for line in stderr_output.split('\n'):
            if ',' in line and line.strip():
                parts = line.split(',')
                if len(parts) >= 3:
                    try:
                        # perf output format: value,unit,event,running,ratio
                        value_str = parts[0].strip()
                        if value_str == '<not supported>':
                            continue
                            
                        value = int(value_str.replace(',', ''))  # Remove thousands separators
                        event = parts[2].strip()
                        
                        # Map perf event names to our feature names
                        event_map = {
                            'cpu-cycles': 'cpu_cycles',
                            'instructions': 'instructions',
                            'cache-references': 'cache_references',
                            'cache-misses': 'cache_misses',
                            'branches': 'branches',
                            'branch-misses': 'branch_misses',
                            'page-faults': 'page_faults',
                            'context-switches': 'context_switches'
                        }
                        
                        if event in event_map:
                            metrics[event_map[event]] = value
                            
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Error parsing VM perf line '{line}': {e}")
                        continue
        
        return metrics
    
    def _snapshot_os_counters(self) -> Dict[str, float]:
        """Snapshot OS cumulative counters for later delta computation in VM."""
        snapshot = {}
        try:
            cpu_times = psutil.cpu_times()  # Cumulative seconds since boot
            snapshot['cpu_times'] = cpu_times._asdict()
            
            disk_io = psutil.disk_io_counters()
            if disk_io:
                snapshot['disk_io'] = {
                    'read_bytes': getattr(disk_io, 'read_bytes', 0),
                    'write_bytes': getattr(disk_io, 'write_bytes', 0)
                }
            
            net_io = psutil.net_io_counters()
            if net_io:
                snapshot['net_io'] = {
                    'bytes_sent': getattr(net_io, 'bytes_sent', 0),
                    'bytes_recv': getattr(net_io, 'bytes_recv', 0)
                }
            
            mem = psutil.virtual_memory()
            snapshot['memory'] = {
                'percent': mem.percent,
                'available_gb': mem.available / (1024**3)
            }
            
            snapshot['process_count'] = len(psutil.pids())
            try:
                la = psutil.getloadavg()
                snapshot['load_avg'] = {
                    'la1': la[0], 'la5': la[1], 'la15': la[2]
                }
            except Exception:
                snapshot['load_avg'] = {'la1': 0.0, 'la5': 0.0, 'la15': 0.0}
            
        except Exception as e:
            logger.error(f"VM OS snapshot failed: {e}")
        return snapshot

    def _compute_os_metrics_from_snapshots(self, snap0: Dict, snap1: Dict, time_delta: float) -> Dict[str, float]:
        """Compute per-interval OS metrics aligned to the same window in VM."""
        metrics: Dict[str, float] = {}
        try:
            # CPU percentages from deltas
            t0 = snap0.get('cpu_times', {})
            t1 = snap1.get('cpu_times', {})
            keys = ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal']
            deltas = {k: max(0.0, float(t1.get(k, 0.0)) - float(t0.get(k, 0.0))) for k in keys}
            total = sum(deltas.values()) or time_delta or 1.0
            
            for k in keys:
                metrics_map = {
                    'user': 'cpu_user_time',
                    'nice': 'cpu_nice_time',
                    'system': 'cpu_system_time',
                    'idle': 'cpu_idle',
                    'iowait': 'cpu_iowait',
                    'irq': 'cpu_irq',
                    'softirq': 'cpu_softirq',
                    'steal': 'cpu_steal'
                }
                metrics[metrics_map[k]] = (deltas[k] / total) * 100.0
            metrics['cpu_utilization'] = 100.0 - metrics.get('cpu_idle', 0.0)
            
            # Disk deltas (MB per interval)
            d0 = snap0.get('disk_io', {})
            d1 = snap1.get('disk_io', {})
            read_mb = (max(0, int(d1.get('read_bytes', 0)) - int(d0.get('read_bytes', 0))) / (1024 * 1024))
            write_mb = (max(0, int(d1.get('write_bytes', 0)) - int(d0.get('write_bytes', 0))) / (1024 * 1024))
            metrics['disk_io_read_mb'] = read_mb
            metrics['disk_io_write_mb'] = write_mb
            
            # Network deltas (bytes per interval)
            n0 = snap0.get('net_io', {})
            n1 = snap1.get('net_io', {})
            metrics['network_bytes_sent'] = max(0, int(n1.get('bytes_sent', 0)) - int(n0.get('bytes_sent', 0)))
            metrics['network_bytes_recv'] = max(0, int(n1.get('bytes_recv', 0)) - int(n0.get('bytes_recv', 0)))
            
            # Memory snapshot (instantaneous at end of window)
            mem1 = snap1.get('memory', {})
            metrics['memory_usage_percent'] = float(mem1.get('percent', 0.0))
            metrics['memory_available_gb'] = float(mem1.get('available_gb', 0.0))
            
            # Process count and load averages (instantaneous at end)
            metrics['process_count'] = int(snap1.get('process_count', 0))
            la1 = snap1.get('load_avg', {})
            metrics['load_average_1min'] = float(la1.get('la1', 0.0))
            metrics['load_average_5min'] = float(la1.get('la5', 0.0))
            metrics['load_average_15min'] = float(la1.get('la15', 0.0))
        except Exception as e:
            logger.error(f"VM OS metrics delta computation failed: {e}")
        return metrics

    def calculate_derived_features(self, pmc_data: Dict, os_data: Dict) -> Dict[str, float]:
        """Calculate derived features from raw PMC and OS data in VM"""
        derived = {}
        
        # PMC-based derived features
        if pmc_data.get('cpu_cycles', 0) > 0:
            derived['instructions_per_cycle'] = (
                pmc_data.get('instructions', 0) / pmc_data['cpu_cycles']
            )
        else:
            derived['instructions_per_cycle'] = 0.0
            
        if pmc_data.get('cache_references', 0) > 0:
            derived['cache_miss_ratio'] = (
                pmc_data.get('cache_misses', 0) / pmc_data['cache_references']
            )
        else:
            derived['cache_miss_ratio'] = 0.0
            
        if pmc_data.get('branches', 0) > 0:
            derived['branch_miss_ratio'] = (
                pmc_data.get('branch_misses', 0) / pmc_data['branches']
            )
        else:
            derived['branch_miss_ratio'] = 0.0
        
        # OS-based derived features
        total_active = os_data.get('cpu_user_time', 0) + os_data.get('cpu_system_time', 0)
        derived['cpu_efficiency'] = total_active / 100.0
        
        return derived
    
    def collect_feature_point(self) -> Optional[VMFeaturePoint]:
        """Collect a single VM feature data point for power prediction.
        Uses synchronized collection to align all metrics to the same time window.
        """
        try:
            if self.synchronized:
                # T0 snapshots
                t0 = time.time()
                proc_stat0 = self._read_proc_stat()  # /proc/stat snapshot at T0
                os0 = self._snapshot_os_counters()
                
                # PMCs over the exact window [T0, T1]
                pmc_data = self.collect_pmc_metrics()
                
                # Ensure we always wait for the collection interval, even if PMCs fail
                t_after_pmc = time.time()
                elapsed = t_after_pmc - t0
                if elapsed < self.collection_interval:
                    remaining_sleep = self.collection_interval - elapsed
                    time.sleep(remaining_sleep)
                
                # T1 snapshots
                t1 = time.time()
                proc_stat1 = self._read_proc_stat()  # /proc/stat snapshot at T1
                os1 = self._snapshot_os_counters()
                
                # Compute aligned deltas
                time_delta = max(1e-6, t1 - t0)
                
                # System CPU metrics from /proc/stat deltas
                # This replaces the Kepler-based approach with direct system measurement
                system_deltas = self._compute_proc_stat_deltas(proc_stat0, proc_stat1, time_delta)
                
                # Store current /proc/stat for next iteration (for additional metrics if needed)
                self.prev_proc_stat = proc_stat1
                self.prev_collection_time = t1
                
                aligned_os = self._compute_os_metrics_from_snapshots(os0, os1, time_delta)
                
                # Derived features from PMCs
                derived_data = self.calculate_derived_features(pmc_data, aligned_os)
                
                # Create timestamp in ISO format for external synchronization
                timestamp_iso = datetime.fromtimestamp(t1).isoformat()
                
                # Compose feature point (timestamp at T1)
                point = VMFeaturePoint(
                    timestamp=t1,
                    timestamp_iso=timestamp_iso,
                    # System-level CPU metrics from /proc/stat (delta during interval)
                    sys_cpu_user_seconds=system_deltas.get('sys_cpu_user_seconds', 0.0),
                    sys_cpu_system_seconds=system_deltas.get('sys_cpu_system_seconds', 0.0),
                    sys_cpu_total_seconds=system_deltas.get('sys_cpu_total_seconds', 0.0),
                    # System activity metrics from /proc/stat (delta during interval)  
                    sys_context_switches=system_deltas.get('sys_context_switches', 0),
                    sys_processes_created=system_deltas.get('sys_processes_created', 0),
                    # Current system state (instantaneous)
                    sys_procs_running=system_deltas.get('sys_procs_running', 0),
                    sys_procs_blocked=system_deltas.get('sys_procs_blocked', 0),
                    # PMC features
                    cpu_cycles=pmc_data.get('cpu_cycles', 0),
                    instructions=pmc_data.get('instructions', 0),
                    cache_references=pmc_data.get('cache_references', 0),
                    cache_misses=pmc_data.get('cache_misses', 0),
                    branches=pmc_data.get('branches', 0),
                    branch_misses=pmc_data.get('branch_misses', 0),
                    page_faults=pmc_data.get('page_faults', 0),
                    context_switches=pmc_data.get('context_switches', 0),
                    # OS features (aligned to window)
                    cpu_utilization=aligned_os.get('cpu_utilization', 0.0),
                    cpu_user_time=aligned_os.get('cpu_user_time', 0.0),
                    cpu_system_time=aligned_os.get('cpu_system_time', 0.0),
                    cpu_nice_time=aligned_os.get('cpu_nice_time', 0.0),
                    cpu_iowait=aligned_os.get('cpu_iowait', 0.0),
                    cpu_irq=aligned_os.get('cpu_irq', 0.0),
                    cpu_softirq=aligned_os.get('cpu_softirq', 0.0),
                    cpu_steal=aligned_os.get('cpu_steal', 0.0),
                    cpu_idle=aligned_os.get('cpu_idle', 0.0),
                    memory_usage_percent=aligned_os.get('memory_usage_percent', 0.0),
                    memory_available_gb=aligned_os.get('memory_available_gb', 0.0),
                    disk_io_read_mb=aligned_os.get('disk_io_read_mb', 0.0),
                    disk_io_write_mb=aligned_os.get('disk_io_write_mb', 0.0),
                    network_bytes_sent=aligned_os.get('network_bytes_sent', 0.0),
                    network_bytes_recv=aligned_os.get('network_bytes_recv', 0.0),
                    process_count=aligned_os.get('process_count', 0),
                    load_average_1min=aligned_os.get('load_average_1min', 0.0),
                    load_average_5min=aligned_os.get('load_average_5min', 0.0),
                    load_average_15min=aligned_os.get('load_average_15min', 0.0),
                    # Derived features
                    instructions_per_cycle=derived_data.get('instructions_per_cycle', 0.0),
                    cache_miss_ratio=derived_data.get('cache_miss_ratio', 0.0),
                    branch_miss_ratio=derived_data.get('branch_miss_ratio', 0.0),
                    cpu_efficiency=derived_data.get('cpu_efficiency', 0.0),
                    # Metadata
                    collection_interval=self.collection_interval,
                    time_delta_seconds=time_delta,
                    vm_hostname=self.vm_hostname,
                )
                return point
            else:
                # Non-synchronized collection (legacy)
                timestamp = time.time()
                timestamp_iso = datetime.fromtimestamp(timestamp).isoformat()
                
                # Get current /proc/stat snapshot
                current_proc_stat = self._read_proc_stat()
                
                # Calculate system deltas if we have previous data
                system_deltas = {}
                if self.prev_proc_stat:
                    system_deltas = self._compute_proc_stat_deltas(self.prev_proc_stat, current_proc_stat, self.collection_interval)
                else:
                    logger.debug("First collection in non-synchronized mode, system deltas set to 0")
                
                self.prev_proc_stat = current_proc_stat
                
                pmc_data = self.collect_pmc_metrics()
                os_data = self.collect_os_metrics()
                derived_data = self.calculate_derived_features(pmc_data, os_data)
                
                point = VMFeaturePoint(
                    timestamp=timestamp,
                    timestamp_iso=timestamp_iso,
                    # System-level CPU metrics from /proc/stat
                    sys_cpu_user_seconds=system_deltas.get('sys_cpu_user_seconds', 0.0),
                    sys_cpu_system_seconds=system_deltas.get('sys_cpu_system_seconds', 0.0),
                    sys_cpu_total_seconds=system_deltas.get('sys_cpu_total_seconds', 0.0),
                    # System activity metrics
                    sys_context_switches=system_deltas.get('sys_context_switches', 0),
                    sys_processes_created=system_deltas.get('sys_processes_created', 0),
                    # Current system state
                    sys_procs_running=system_deltas.get('sys_procs_running', 0),
                    sys_procs_blocked=system_deltas.get('sys_procs_blocked', 0),
                    cpu_cycles=pmc_data.get('cpu_cycles', 0),
                    instructions=pmc_data.get('instructions', 0),
                    cache_references=pmc_data.get('cache_references', 0),
                    cache_misses=pmc_data.get('cache_misses', 0),
                    branches=pmc_data.get('branches', 0),
                    branch_misses=pmc_data.get('branch_misses', 0),
                    page_faults=pmc_data.get('page_faults', 0),
                    context_switches=pmc_data.get('context_switches', 0),
                    cpu_utilization=os_data.get('cpu_utilization', 0.0),
                    cpu_user_time=os_data.get('cpu_user_time', 0.0),
                    cpu_system_time=os_data.get('cpu_system_time', 0.0),
                    cpu_nice_time=os_data.get('cpu_nice_time', 0.0),
                    cpu_iowait=os_data.get('cpu_iowait', 0.0),
                    cpu_irq=os_data.get('cpu_irq', 0.0),
                    cpu_softirq=os_data.get('cpu_softirq', 0.0),
                    cpu_steal=os_data.get('cpu_steal', 0.0),
                    cpu_idle=os_data.get('cpu_idle', 0.0),
                    memory_usage_percent=os_data.get('memory_usage_percent', 0.0),
                    memory_available_gb=os_data.get('memory_available_gb', 0.0),
                    disk_io_read_mb=os_data.get('disk_io_read_mb', 0.0),
                    disk_io_write_mb=os_data.get('disk_io_write_mb', 0.0),
                    network_bytes_sent=os_data.get('network_bytes_sent', 0.0),
                    network_bytes_recv=os_data.get('network_bytes_recv', 0.0),
                    process_count=os_data.get('process_count', 0),
                    load_average_1min=os_data.get('load_average_1min', 0.0),
                    load_average_5min=os_data.get('load_average_5min', 0.0),
                    load_average_15min=os_data.get('load_average_15min', 0.0),
                    instructions_per_cycle=derived_data.get('instructions_per_cycle', 0.0),
                    cache_miss_ratio=derived_data.get('cache_miss_ratio', 0.0),
                    branch_miss_ratio=derived_data.get('branch_miss_ratio', 0.0),
                    cpu_efficiency=derived_data.get('cpu_efficiency', 0.0),
                    collection_interval=self.collection_interval,
                    vm_hostname=self.vm_hostname,
                )
                return point
        except Exception as e:
            logger.error(f"Failed to collect VM feature point: {e}")
            return None

    def collect_os_metrics(self) -> Dict[str, float]:
        """Collect OS-level CPU and system metrics in VM (non-synchronized mode)"""
        try:
            # CPU times with specified interval
            cpu_times = psutil.cpu_times_percent(interval=None)  # Non-blocking
            
            # Memory statistics
            memory = psutil.virtual_memory()
            
            # Disk I/O statistics
            disk_io = psutil.disk_io_counters()
            
            # Network statistics
            network = psutil.net_io_counters()
            
            # System load
            load_avg = psutil.getloadavg()
            
            # Process count
            process_count = len(psutil.pids())
            
            # Calculate I/O deltas if we have previous values
            disk_read_mb = 0.0
            disk_write_mb = 0.0
            net_sent = 0.0
            net_recv = 0.0
            
            if disk_io:
                if self.prev_disk_io:
                    disk_read_mb = (disk_io.read_bytes - self.prev_disk_io.read_bytes) / (1024 * 1024)
                    disk_write_mb = (disk_io.write_bytes - self.prev_disk_io.write_bytes) / (1024 * 1024)
                self.prev_disk_io = disk_io
            
            if network:
                if self.prev_network:
                    net_sent = network.bytes_sent - self.prev_network.bytes_sent
                    net_recv = network.bytes_recv - self.prev_network.bytes_recv
                self.prev_network = network
            
            return {
                'cpu_utilization': 100.0 - cpu_times.idle,
                'cpu_user_time': cpu_times.user,
                'cpu_system_time': cpu_times.system,
                'cpu_nice_time': getattr(cpu_times, 'nice', 0.0),
                'cpu_iowait': getattr(cpu_times, 'iowait', 0.0),
                'cpu_irq': getattr(cpu_times, 'irq', 0.0),
                'cpu_softirq': getattr(cpu_times, 'softirq', 0.0),
                'cpu_steal': getattr(cpu_times, 'steal', 0.0),
                'cpu_idle': cpu_times.idle,
                'memory_usage_percent': memory.percent,
                'memory_available_gb': memory.available / (1024**3),
                'disk_io_read_mb': disk_read_mb,
                'disk_io_write_mb': disk_write_mb,
                'network_bytes_sent': net_sent,
                'network_bytes_recv': net_recv,
                'process_count': process_count,
                'load_average_1min': load_avg[0],
                'load_average_5min': load_avg[1],
                'load_average_15min': load_avg[2]
            }
            
        except Exception as e:
            logger.error(f"VM OS metrics collection failed: {e}")
            return {}
    
    def collect_vm_features(self, duration: int, output_file: str = None) -> List[VMFeaturePoint]:
        """Collect VM features for specified duration"""
        logger.info(f"Starting VM feature collection for {duration} seconds on {self.vm_hostname}")
        logger.info(f"Target zones: package, core")
        
        
        self.collection_active = True
        start_time = time.time()
        collection_count = 0
        error_count = 0
        
        while self.collection_active and (time.time() - start_time) < duration:
            try:
                point = self.collect_feature_point()
                
                if point:
                    self.feature_data.append(point)
                    collection_count += 1
                    
                    if collection_count % 10 == 0:
                        logger.info(f"Collected {collection_count} feature points, "
                                  f"latest CPU util: {point.cpu_utilization:.1f}%, "
                                  f"sys CPU seconds: {point.sys_cpu_total_seconds:.2f}s, "
                                  f"context switches: {point.sys_context_switches}")
                else:
                    error_count += 1
                    
                # Sleep until next collection interval
                next_collection = start_time + (collection_count + error_count + 1) * self.collection_interval
                sleep_time = next_collection - time.time()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                elif sleep_time < -0.5:  # If we're significantly behind schedule
                    logger.debug(f"Collection running {-sleep_time:.2f}s behind schedule")
                    
            except KeyboardInterrupt:
                logger.info("VM feature collection interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error during VM feature collection: {e}")
                error_count += 1
                time.sleep(self.collection_interval)
        
        self.collection_active = False
        
        
        logger.info(f"VM feature collection completed: {collection_count} points collected, {error_count} errors")
        
        # Save data if output file specified
        if output_file and self.feature_data:
            self.save_feature_data(output_file)
        
        return self.feature_data
    
    def save_feature_data(self, output_file: str) -> None:
        """Save collected VM feature data to file"""
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save as JSON for easy parsing and sharing
            with open(output_path, 'w') as f:
                json_data = [asdict(point) for point in self.feature_data]
                json.dump(json_data, f, indent=2)
            
            logger.info(f"Saved {len(self.feature_data)} VM feature points to {output_file}")
            
            # Also save CSV format for easy analysis
            csv_file = output_path.with_suffix('.csv')
            self._save_as_csv(csv_file)
            
        except Exception as e:
            logger.error(f"Failed to save VM feature data: {e}")
    
    def _save_as_csv(self, csv_file: Path) -> None:
        """Save feature data as CSV for analysis"""
        try:
            import csv
            
            if not self.feature_data:
                return
            
            # Get field names from first data point
            fieldnames = list(asdict(self.feature_data[0]).keys())
            
            with open(csv_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for point in self.feature_data:
                    writer.writerow(asdict(point))
            
            logger.info(f"Also saved VM features as CSV to {csv_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save CSV format: {e}")
    
    def print_collection_summary(self) -> None:
        """Print summary of collected VM feature data"""
        if not self.feature_data:
            logger.info("No VM feature data collected")
            return
        
        print("\n" + "="*60)
        print("VM FEATURE COLLECTION SUMMARY")
        print("="*60)
        
        print(f"VM Hostname: {self.vm_hostname}")
        print(f"Target zones: package, core")
        print(f"Total feature points: {len(self.feature_data)}")
        print(f"Collection duration: {self.feature_data[-1].timestamp - self.feature_data[0].timestamp:.1f} seconds")
        
        # CPU utilization statistics
        cpu_utils = [point.cpu_utilization for point in self.feature_data]
        print(f"\nCPU utilization range: {min(cpu_utils):.1f}% - {max(cpu_utils):.1f}%")
        
        # System CPU metrics (deltas from /proc/stat)
        sys_total_cpu_values = [point.sys_cpu_total_seconds for point in self.feature_data if point.sys_cpu_total_seconds > 0]
        if sys_total_cpu_values:
            print(f"System CPU seconds per interval range: {min(sys_total_cpu_values):.2f} - {max(sys_total_cpu_values):.2f}")
            print(f"Average system CPU seconds per interval: {sum(sys_total_cpu_values)/len(sys_total_cpu_values):.2f}")
        else:
            print("No system CPU time deltas collected (/proc/stat may be unavailable)")
        
        # Context switches activity
        ctx_switch_values = [point.sys_context_switches for point in self.feature_data if point.sys_context_switches > 0]
        if ctx_switch_values:
            print(f"Context switches per interval range: {min(ctx_switch_values)} - {max(ctx_switch_values)}")
            print(f"Average context switches per interval: {sum(ctx_switch_values)/len(ctx_switch_values):.0f}")
        
        # PMC availability statistics
        pmc_availability = {}
        for point in self.feature_data:
            for feature in ['cpu_cycles', 'instructions', 'cache_references', 'cache_misses']:
                value = getattr(point, feature, 0)
                if feature not in pmc_availability:
                    pmc_availability[feature] = 0
                if value > 0:
                    pmc_availability[feature] += 1
        
        print(f"\nPMC Feature Availability in VM:")
        for feature, count in pmc_availability.items():
            percentage = (count / len(self.feature_data)) * 100
            print(f"  {feature}: {percentage:.1f}% ({count}/{len(self.feature_data)})")

def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Collect VM features for CPU power prediction")
    parser.add_argument('--duration', type=int, default=300, 
                       help='Collection duration in seconds (default: 300)')
    parser.add_argument('--output', type=str, default='data/vm_features.json',
                       help='Output file path (default: data/vm_features.json)')
    parser.add_argument('--kepler-url', type=str, default='http://localhost:28282/metrics',
                        help='VM Kepler metrics URL (default: http://localhost:28282/metrics)')
    parser.add_argument('--interval', type=float, default=1.0,
                       help='Collection interval in seconds (default: 1.0)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--no-sync', action='store_true',
                        help='Disable synchronized bracketed window collection')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    
    
    # Create VM feature collector
    collector = VMFeatureCollector(
        kepler_url=args.kepler_url,
        collection_interval=args.interval,
        synchronized=not args.no_sync
    )
    
    # Test /proc/stat accessibility
    proc_stat_test = collector._read_proc_stat()
    if proc_stat_test and 'cpu' in proc_stat_test:
        logger.info(f"/proc/stat accessible - system metrics available")
        if 'context_switches' in proc_stat_test:
            logger.info(f"Additional metrics: context switches, process counts")
    else:
        logger.warning("/proc/stat not accessible - system metrics may be limited")
    
    try:
        # Collect VM features
        feature_data = collector.collect_vm_features(
            duration=args.duration,
            output_file=args.output
        )
        
        # Print summary
        collector.print_collection_summary()
        
        logger.info("VM feature collection completed successfully")
        
    except Exception as e:
        logger.error(f"VM feature collection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()