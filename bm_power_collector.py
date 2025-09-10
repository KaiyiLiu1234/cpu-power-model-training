#!/usr/bin/env python3
"""
Bare Metal Power Collector for VM CPU Power Training
Collects power metrics from Kepler running on bare metal for VM training labels

This script runs on bare metal alongside the VM to collect ground truth power
measurements from Kepler. It complements the vm_feature_collector.py which 
runs inside the VM to collect features.

Key features:
- Collects kepler_vm_cpu_watts for target VMs by vm_name
- Supports VM filtering by name or name pattern
- Customizable collection interval (default 100ms)
- Automatic VM summation when multiple VMs are specified
- Synchronized timestamps for alignment with VM feature data
- Robust error handling and retry logic
- CSV and JSON output formats

Usage:
    # Collect power for all VMs (sum total)
    python3 bm_power_collector.py --output power_data.csv --duration 3600
    
    # Collect power for specific VM by name
    python3 bm_power_collector.py --vm-names fedora40 --output power_data.csv
    
    # Collect power for VMs matching pattern
    python3 bm_power_collector.py --vm-pattern "fedora.*" --interval 0.1 --output power_data.json
"""

import requests
import time
import csv
import json
import argparse
import logging
import signal
import sys
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set
from datetime import datetime
from pathlib import Path

# Configure logging
script_dir = Path(__file__).parent
logs_dir = script_dir / 'logs'
logs_dir.mkdir(exist_ok=True)
log_file = logs_dir / 'bm_power_collection.log'

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
class PowerDataPoint:
    """Single power measurement data point for training labels"""
    timestamp: float  # Relative timestamp from collection start
    timestamp_absolute: float  # Absolute system timestamp for reference
    timestamp_iso: str
    
    # Core power metrics (labels for training)
    total_cpu_watts_core: float = 0.0       # Sum of all VM CPU watts (core zone)
    total_cpu_watts_package: float = 0.0    # Sum of all VM CPU watts (package zone)
    vm_count: int = 0                        # Number of VMs contributing to total
    
    # Individual VM power data (for debugging/analysis)
    vms: List[Dict] = None
    
    # Collection metadata
    collection_interval: float = 0.1
    kepler_endpoint: str = ""
    vm_filter: Optional[str] = None
    
    def __post_init__(self):
        if self.vms is None:
            self.vms = []

class BaremetalPowerCollector:
    """Collects power metrics from Kepler on bare metal for VM training"""
    
    def __init__(self, kepler_url="http://localhost:28283/metrics", 
                 collection_interval=0.1, max_retries=3,
                 target_vms=None, vm_pattern=None, sync_start_time=None):
        self.kepler_url = kepler_url
        self.collection_interval = collection_interval
        self.max_retries = max_retries
        self.target_vms = set(target_vms) if target_vms else None
        self.vm_pattern = re.compile(vm_pattern) if vm_pattern else None
        self.sync_start_time = sync_start_time
        
        # Data storage
        self.power_data: List[PowerDataPoint] = []
        self.collection_active = False
        
        # Relative timing
        self.collection_start_time: Optional[float] = None
        
        # HTTP session for connection reuse to reduce latency
        self.session = requests.Session()
        
        # Signal handling for graceful shutdown
        self._shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Initialized bare metal power collector")
        logger.info(f"Kepler endpoint: {self.kepler_url}")
        logger.info(f"Collection interval: {self.collection_interval}s")
        if self.target_vms:
            logger.info(f"Target VMs: {list(self.target_vms)}")
        if self.vm_pattern:
            logger.info(f"VM pattern: {vm_pattern}")
        if not self.target_vms and not self.vm_pattern:
            logger.info("Collecting power for ALL VMs")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        if self._shutdown_requested:
            logger.warning("Force shutdown requested!")
            sys.exit(1)
        
        logger.info(f"Received signal {signum}, stopping power collection...")
        self._shutdown_requested = True
        self.collection_active = False
        logger.info("Shutdown initiated - press Ctrl+C again to force quit")
    
    def _wait_for_sync_start(self) -> float:
        """Wait for synchronized start time and return the exact start time"""
        if self.sync_start_time is None:
            # No sync time specified, start immediately
            start_time = time.time()
            logger.info(f"Starting collection immediately at: {start_time:.6f}")
        else:
            current_time = time.time()
            if current_time < self.sync_start_time:
                sleep_duration = self.sync_start_time - current_time
                logger.info(f"Waiting {sleep_duration:.3f}s for synchronized start at: {self.sync_start_time:.6f}")
                time.sleep(sleep_duration)
            else:
                logger.warning(f"Sync time {self.sync_start_time:.6f} has already passed, starting immediately")
            start_time = self.sync_start_time
        
        self.collection_start_time = start_time
        return start_time
    
    def _parse_vm_metrics(self, kepler_response: str) -> Dict[str, List[Dict]]:
        """Parse Kepler metrics response to extract VM power data
        
        Returns:
            Dict with 'core' and 'package' keys, each containing list of VM dicts
        """
        metrics = {'core': [], 'package': []}
        
        lines = kepler_response.split('\n')
        
        for line in lines:
            # Look for VM CPU watts metrics
            if line.startswith('kepler_vm_cpu_watts{'):
                try:
                    # Parse the metric line
                    # Format: kepler_vm_cpu_watts{labels} value
                    parts = line.split(' ')
                    if len(parts) != 2:
                        continue
                    
                    labels_part = parts[0]
                    value = float(parts[1])
                    
                    # Extract labels from the metric
                    # kepler_vm_cpu_watts{hypervisor="kvm",vm_name="fedora40",zone="core"} 0.5
                    labels_str = labels_part[labels_part.find('{')+1:labels_part.rfind('}')]
                    labels = {}
                    
                    # Parse individual labels
                    for label_pair in labels_str.split(','):
                        if '=' in label_pair:
                            key, val = label_pair.split('=', 1)
                            key = key.strip()
                            val = val.strip().strip('"')
                            labels[key] = val
                    
                    # Extract key VM information
                    vm_info = {
                        'vm_id': labels.get('vm_id', ''),
                        'vm_name': labels.get('vm_name', ''),
                        'hypervisor': labels.get('hypervisor', ''),
                        'node_name': labels.get('node_name', ''),
                        'zone': labels.get('zone', ''),
                        'watts': value,
                        'state': labels.get('state', '')
                    }
                    
                    # Group by zone
                    zone = vm_info['zone']
                    if zone in metrics:
                        metrics[zone].append(vm_info)
                        
                except (ValueError, IndexError) as e:
                    logger.debug(f"Error parsing metric line: {line[:100]}... Error: {e}")
                    continue
        
        return metrics
    
    def _filter_vms(self, vm_list: List[Dict]) -> List[Dict]:
        """Filter VMs based on target_vms or vm_pattern"""
        if not self.target_vms and not self.vm_pattern:
            # No filtering - return all VMs
            return vm_list
        
        filtered = []
        
        for vm in vm_list:
            include = False
            
            # Check target VMs (by vm_name, vm_id)
            if self.target_vms:
                if (vm['vm_name'] in self.target_vms or 
                    vm['vm_id'] in self.target_vms):
                    include = True
            
            # Check VM pattern (against vm_name or vm_id)
            if self.vm_pattern:
                search_fields = [vm['vm_name'], vm['vm_id']]
                if any(self.vm_pattern.search(field) for field in search_fields if field):
                    include = True
            
            if include:
                filtered.append(vm)
        
        return filtered
    
    def collect_power_metrics(self) -> Optional[PowerDataPoint]:
        """Collect power metrics from Kepler for target VMs"""
        for attempt in range(self.max_retries):
            try:
                # Use session for connection reuse and shorter timeout to reduce latency
                response = self.session.get(self.kepler_url, timeout=2)
                response.raise_for_status()
                
                # Parse VM metrics
                metrics = self._parse_vm_metrics(response.text)
                
                # Filter VMs for each zone
                filtered_core = self._filter_vms(metrics['core'])
                filtered_package = self._filter_vms(metrics['package'])
                
                # Calculate totals
                total_core_watts = sum(vm['watts'] for vm in filtered_core)
                total_package_watts = sum(vm['watts'] for vm in filtered_package)
                
                # Use core zone VM count (should be same as package)
                vm_count = len(filtered_core)
                
                # Create timestamp
                timestamp = time.time()
                
                # Initialize collection start time on first measurement
                if self.collection_start_time is None:
                    self.collection_start_time = timestamp
                    logger.info(f"BM collection started at absolute time: {timestamp:.6f}")
                
                # Calculate relative timestamp from collection start
                relative_timestamp = timestamp - self.collection_start_time
                timestamp_iso = datetime.fromtimestamp(timestamp).isoformat()
                
                # Combine VM data for storage
                all_vms = []
                for vm in filtered_core:
                    vm_entry = vm.copy()
                    vm_entry['zone'] = 'core'
                    all_vms.append(vm_entry)
                for vm in filtered_package:
                    vm_entry = vm.copy()
                    vm_entry['zone'] = 'package'
                    all_vms.append(vm_entry)
                
                # Create data point
                data_point = PowerDataPoint(
                    timestamp=relative_timestamp,  # Relative timestamp for merging
                    timestamp_absolute=timestamp,  # Absolute timestamp for reference
                    timestamp_iso=timestamp_iso,
                    total_cpu_watts_core=total_core_watts,
                    total_cpu_watts_package=total_package_watts,
                    vm_count=vm_count,
                    vms=all_vms,
                    collection_interval=self.collection_interval,
                    kepler_endpoint=self.kepler_url,
                    vm_filter=str(self.target_vms) if self.target_vms else 
                              self.vm_pattern.pattern if self.vm_pattern else "all"
                )
                
                logger.debug(f"Collected power: core={total_core_watts:.4f}W, "
                           f"package={total_package_watts:.4f}W, VMs={vm_count}")
                
                return data_point
                
            except requests.RequestException as e:
                logger.warning(f"Kepler request failed (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                else:
                    logger.error("Failed to collect power metrics after all retries")
                    return None
            except Exception as e:
                logger.error(f"Unexpected error collecting power metrics: {e}")
                return None
        
        return None
    
    def collect_power_metrics_with_timestamp(self, target_timestamp: float) -> Optional[PowerDataPoint]:
        """Collect power metrics with a specific timestamp for precise timing"""
        for attempt in range(self.max_retries):
            try:
                # Use session for connection reuse and shorter timeout to reduce latency
                response = self.session.get(self.kepler_url, timeout=2)
                response.raise_for_status()
                
                # Parse VM metrics
                metrics = self._parse_vm_metrics(response.text)
                
                # Filter VMs for each zone
                filtered_core = self._filter_vms(metrics['core'])
                filtered_package = self._filter_vms(metrics['package'])
                
                # Calculate totals
                total_core_watts = sum(vm['watts'] for vm in filtered_core)
                total_package_watts = sum(vm['watts'] for vm in filtered_package)
                
                # Use core zone VM count (should be same as package)
                vm_count = len(filtered_core)
                
                # Use provided target timestamp for precise timing
                timestamp = target_timestamp
                
                # Calculate relative timestamp from collection start
                relative_timestamp = timestamp - self.collection_start_time
                timestamp_iso = datetime.fromtimestamp(timestamp).isoformat()
                
                # Combine VM data for storage
                all_vms = []
                for vm in filtered_core:
                    vm_entry = vm.copy()
                    vm_entry['zone'] = 'core'
                    all_vms.append(vm_entry)
                for vm in filtered_package:
                    vm_entry = vm.copy()
                    vm_entry['zone'] = 'package'
                    all_vms.append(vm_entry)
                
                # Create data point
                data_point = PowerDataPoint(
                    timestamp=relative_timestamp,  # Relative timestamp for merging
                    timestamp_absolute=timestamp,  # Absolute timestamp for reference
                    timestamp_iso=timestamp_iso,
                    total_cpu_watts_core=total_core_watts,
                    total_cpu_watts_package=total_package_watts,
                    vm_count=vm_count,
                    vms=all_vms,
                    collection_interval=self.collection_interval,
                    kepler_endpoint=self.kepler_url,
                    vm_filter=str(self.target_vms) if self.target_vms else 
                              self.vm_pattern.pattern if self.vm_pattern else "all"
                )
                
                logger.debug(f"Collected power: core={total_core_watts:.4f}W, "
                           f"package={total_package_watts:.4f}W, VMs={vm_count}")
                
                return data_point
                
            except requests.RequestException as e:
                logger.warning(f"Kepler request failed (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                else:
                    logger.error("Failed to collect power metrics after all retries")
                    return None
            except Exception as e:
                logger.error(f"Unexpected error collecting power metrics: {e}")
                return None
        
        return None
    
    def collect_power_data(self, duration: int, output_file: str = None) -> List[PowerDataPoint]:
        """Collect power data for specified duration with precise timing"""
        logger.info(f"Starting power data collection for {duration} seconds")
        
        self.collection_active = True
        
        # Wait for synchronized start time and get exact start time
        start_time = self._wait_for_sync_start()
        collection_count = 0
        error_count = 0
        
        # Calculate the expected number of data points based on duration and interval
        expected_points = int(duration / self.collection_interval)
        logger.info(f"Target: {expected_points} data points over {duration}s at {self.collection_interval}s intervals")
        logger.info(f"Collection started at: {start_time:.6f}")
        
        # Use precise timing - calculate exact target times for each sample
        while self.collection_active and (time.time() - start_time) < duration:
            try:
                # Calculate exact target time for this sample
                target_time = start_time + (collection_count * self.collection_interval)
                current_time = time.time()
                
                # Sleep until target time if needed
                sleep_duration = target_time - current_time
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                elif sleep_duration < -0.1:  # Log if we're significantly behind
                    logger.debug(f"Collection {collection_count}: {abs(sleep_duration):.3f}s behind target")
                
                # Use target time for timestamp calculation (precise timing)
                target_timestamp = target_time
                
                data_point = self.collect_power_metrics_with_timestamp(target_timestamp)
                
                if data_point:
                    self.power_data.append(data_point)
                    collection_count += 1
                    
                    if collection_count % 50 == 0:  # Log every 5 seconds at 100ms interval
                        elapsed_time = time.time() - start_time
                        logger.info(f"Collected {collection_count} power measurements "
                                  f"({elapsed_time:.1f}s/{duration}s), "
                                  f"latest: core={data_point.total_cpu_watts_core:.4f}W, "
                                  f"package={data_point.total_cpu_watts_package:.4f}W, "
                                  f"VMs={data_point.vm_count}")
                else:
                    error_count += 1
                    # Still increment collection_count to maintain timing even with errors
                    collection_count += 1
                    logger.debug(f"Collection running {-sleep_time:.3f}s behind schedule")
                # Don't sleep if we're behind schedule, just continue immediately
                    
            except KeyboardInterrupt:
                logger.info("Power collection interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error during power collection: {e}")
                error_count += 1
                time.sleep(self.collection_interval)
        
        self.collection_active = False
        
        logger.info(f"Power collection completed: {collection_count} points collected, {error_count} errors")
        
        # Close HTTP session
        self.session.close()
        
        # Save data if output file specified
        if output_file and self.power_data:
            self.save_power_data(output_file)
        
        return self.power_data
    
    def save_power_data(self, output_file: str) -> None:
        """Save collected power data to both CSV and JSON formats"""
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Always save both formats
            if output_file.endswith('.json'):
                # If user specified JSON, save JSON as primary and CSV as secondary
                self._save_as_json(output_path)
                csv_path = output_path.with_suffix('.csv')
                self._save_as_csv(csv_path)
            else:
                # Default: save CSV as primary and JSON as secondary
                csv_path = output_path.with_suffix('.csv') if not output_file.endswith('.csv') else output_path
                json_path = output_path.with_suffix('.json')
                
                self._save_as_csv(csv_path)
                self._save_as_json(json_path)
            
        except Exception as e:
            logger.error(f"Failed to save power data: {e}")
    
    def _save_as_json(self, output_path: Path) -> None:
        """Save power data as JSON"""
        try:
            with open(output_path, 'w') as f:
                json_data = [asdict(point) for point in self.power_data]
                json.dump(json_data, f, indent=2)
            
            logger.info(f"Saved {len(self.power_data)} power measurements to JSON: {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to save JSON: {e}")
    
    def _save_as_csv(self, output_path: Path) -> None:
        """Save power data as CSV"""
        try:
            if not self.power_data:
                return
            
            with open(output_path, 'w', newline='') as f:
                # CSV header - main fields only (not individual process data)
                fieldnames = [
                    'timestamp', 'timestamp_iso', 'total_cpu_watts_core', 
                    'total_cpu_watts_package', 'vm_count', 'collection_interval',
                    'vm_filter'
                ]
                
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for point in self.power_data:
                    # Convert dataclass to dict and select only needed fields
                    point_dict = asdict(point)
                    row = {field: point_dict[field] for field in fieldnames if field in point_dict}
                    writer.writerow(row)
            
            logger.info(f"Saved {len(self.power_data)} power measurements to CSV: {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to save CSV: {e}")
    
    def print_collection_summary(self) -> None:
        """Print summary of collected power data"""
        if not self.power_data:
            logger.info("No power data collected")
            return
        
        print("\n" + "="*60)
        print("BARE METAL POWER COLLECTION SUMMARY")
        print("="*60)
        
        print(f"Kepler endpoint: {self.kepler_url}")
        print(f"Total power measurements: {len(self.power_data)}")
        print(f"Collection duration: {self.power_data[-1].timestamp - self.power_data[0].timestamp:.1f} seconds")
        print(f"Average collection interval: {self.collection_interval:.3f}s")
        
        # Power statistics
        core_watts = [point.total_cpu_watts_core for point in self.power_data]
        package_watts = [point.total_cpu_watts_package for point in self.power_data]
        vm_counts = [point.vm_count for point in self.power_data]
        
        print(f"\nCore Power Range: {min(core_watts):.4f}W - {max(core_watts):.4f}W")
        print(f"Package Power Range: {min(package_watts):.4f}W - {max(package_watts):.4f}W")
        print(f"Average Core Power: {sum(core_watts)/len(core_watts):.4f}W")
        print(f"Average Package Power: {sum(package_watts)/len(package_watts):.4f}W")
        
        print(f"\nVM Count Range: {min(vm_counts)} - {max(vm_counts)}")
        print(f"Average VM Count: {sum(vm_counts)/len(vm_counts):.1f}")
        
        # Filter summary
        filter_info = self.power_data[0].vm_filter if self.power_data else "unknown"
        print(f"VM Filter: {filter_info}")

def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Collect power metrics from Kepler for VM training")
    parser.add_argument('--duration', type=int, default=300,
                       help='Collection duration in seconds (default: 300)')
    parser.add_argument('--output', type=str, default='data/power_data.csv',
                       help='Output file path (default: data/power_data.csv)')
    parser.add_argument('--kepler-url', type=str, default='http://localhost:28283/metrics',
                       help='Kepler metrics URL (default: http://localhost:28283/metrics)')
    parser.add_argument('--interval', type=float, default=0.1,
                       help='Collection interval in seconds (default: 0.1)')
    parser.add_argument('--vm-names', type=str,
                       help='Comma-separated list of target VM names (by vm_name or vm_id)')
    parser.add_argument('--vm-pattern', type=str,
                       help='Regex pattern to match VM names (vm_name or vm_id)')
    parser.add_argument('--start-time', type=float,
                       help='Synchronized start time (Unix timestamp) for precise timing')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse target VMs
    target_vms = None
    if args.vm_names:
        target_vms = [vm.strip() for vm in args.vm_names.split(',') if vm.strip()]
    
    # Create power collector
    collector = BaremetalPowerCollector(
        kepler_url=args.kepler_url,
        collection_interval=args.interval,
        target_vms=target_vms,
        vm_pattern=args.vm_pattern,
        sync_start_time=args.start_time
    )
    
    try:
        # Test Kepler connectivity
        logger.info("Testing Kepler connectivity...")
        test_point = collector.collect_power_metrics()
        if test_point:
            logger.info(f"Kepler connection successful! Found {test_point.vm_count} target VMs")
            logger.info(f"Test measurement: core={test_point.total_cpu_watts_core:.4f}W, "
                       f"package={test_point.total_cpu_watts_package:.4f}W")
        else:
            logger.error("Failed to connect to Kepler or collect test data")
            sys.exit(1)
        
        # Collect power data
        power_data = collector.collect_power_data(
            duration=args.duration,
            output_file=args.output
        )
        
        # Print summary
        collector.print_collection_summary()
        
        logger.info("Power data collection completed successfully")
        
    except Exception as e:
        logger.error(f"Power collection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()