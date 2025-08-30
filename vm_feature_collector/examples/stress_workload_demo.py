#!/usr/bin/env python3
"""
Stress Workload Demo for VM Feature Collector

This script demonstrates how to use stress workloads with the VM feature collector
to generate comprehensive training data. It shows various usage patterns and 
integration approaches.

Usage:
    python3 examples/stress_workload_demo.py --demo-type basic
    python3 examples/stress_workload_demo.py --demo-type cycling
    python3 examples/stress_workload_demo.py --demo-type comprehensive
"""

import sys
import os
import time
import logging
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vm_feature_collector import VMFeatureCollector
from stress_workloads import StressWorkloadManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def demo_basic_stress_integration():
    """Demo: Basic stress workload integration"""
    print("\n" + "="*60)
    print("DEMO: Basic Stress Workload Integration")
    print("="*60)
    
    # Create stress manager
    stress_manager = StressWorkloadManager()
    
    # List available workloads
    print("\nAvailable stress workloads:")
    for workload in stress_manager.get_available_workloads():
        info = stress_manager.get_workload_info(workload)
        print(f"  {workload}: {info}")
    
    # Demo short stress test
    print("\nRunning 30-second CPU intensive stress test...")
    
    with stress_manager.run_workload("cpu_intensive", duration=30):
        # Monitor system during stress
        for i in range(6):  # 6 iterations, 5 seconds each
            metrics = stress_manager.monitor_system_load()
            print(f"System metrics (t+{i*5}s): {metrics}")
            time.sleep(5)
    
    print("Basic stress integration demo completed!")

def demo_cpu_cycling():
    """Demo: CPU load cycling workload"""
    print("\n" + "="*60)
    print("DEMO: CPU Load Cycling (0-100% and back)")
    print("="*60)
    
    # Create stress manager
    stress_manager = StressWorkloadManager()
    
    print("Running 2-minute CPU cycling demo...")
    print("Watch CPU utilization cycle from 0% to 100% and back down")
    
    with stress_manager.run_workload("cpu_cycling", duration=120):
        # Monitor every 10 seconds
        for i in range(12):  # 12 iterations, 10 seconds each
            metrics = stress_manager.monitor_system_load()
            cpu_pct = metrics.get('cpu_percent', 0)
            load_1min = metrics.get('load_1min', 0)
            print(f"t+{i*10}s: CPU={cpu_pct:.1f}% Load={load_1min:.2f}")
            time.sleep(10)
    
    print("CPU cycling demo completed!")

def demo_vm_collector_with_stress():
    """Demo: VM feature collector with stress workload"""
    print("\n" + "="*60)
    print("DEMO: VM Feature Collector with Stress Workload")
    print("="*60)
    
    # Create VM feature collector with stress workload
    collector = VMFeatureCollector(
        collection_interval=2.0,  # Collect every 2 seconds
        stress_workload="mixed_workload"  # Use mixed workload
    )
    
    print("Collecting VM features with mixed stress workload for 60 seconds...")
    print("This generates both features and stress simultaneously")
    
    # Collect features - stress workload will run automatically
    features = collector.collect_vm_features(
        duration=60,
        output_file="examples/demo_mixed_workload.json"
    )
    
    print(f"Collected {len(features)} feature points with stress workload")
    
    # Show sample feature point
    if features:
        sample = features[-1]  # Last collected point
        print(f"\nSample feature point:")
        print(f"  Timestamp: {sample.timestamp_iso}")
        print(f"  CPU Utilization: {sample.cpu_utilization:.1f}%")
        print(f"  Instructions/Cycle: {sample.instructions_per_cycle:.3f}")
        print(f"  Cache Miss Ratio: {sample.cache_miss_ratio:.3f}")
        print(f"  Stress Workload: {sample.stress_workload}")

def demo_comprehensive_collection():
    """Demo: Comprehensive data collection with multiple workloads"""
    print("\n" + "="*60)
    print("DEMO: Comprehensive Multi-Workload Collection")
    print("="*60)
    
    workloads = [
        ("idle", 30),
        ("cpu_intensive", 45),
        ("memory_intensive", 45),
        ("mixed_workload", 45),
        ("bursty_workload", 60)
    ]
    
    all_features = []
    
    for workload_name, duration in workloads:
        print(f"\nCollecting features with '{workload_name}' workload for {duration}s...")
        
        # Create collector for this workload
        collector = VMFeatureCollector(
            collection_interval=1.0,
            stress_workload=workload_name
        )
        
        # Collect features
        features = collector.collect_vm_features(
            duration=duration,
            output_file=f"examples/demo_{workload_name}.json"
        )
        
        all_features.extend(features)
        print(f"  Collected {len(features)} points for {workload_name}")
        
        # Brief pause between workloads
        if workload_name != workloads[-1][0]:  # Not the last workload
            print("  Cooling down for 10 seconds...")
            time.sleep(10)
    
    print(f"\nComprehensive collection completed!")
    print(f"Total feature points: {len(all_features)}")
    print("This data can be used for training robust power models")

def demo_stress_only():
    """Demo: Stress workloads without feature collection"""
    print("\n" + "="*60)
    print("DEMO: Stress Workloads Only (Testing)")
    print("="*60)
    
    stress_manager = StressWorkloadManager()
    
    test_workloads = [
        ("cpu_intensive", 20),
        ("matrix_computation", 15),
        ("branch_intensive", 15)
    ]
    
    for workload_name, duration in test_workloads:
        print(f"\nTesting '{workload_name}' stress for {duration}s...")
        
        with stress_manager.run_workload(workload_name, duration):
            # Monitor the stress
            for i in range(duration // 5):
                metrics = stress_manager.monitor_system_load()
                print(f"  t+{i*5}s: CPU={metrics.get('cpu_percent', 0):.1f}% "
                      f"Load={metrics.get('load_1min', 0):.2f}")
                time.sleep(5)
        
        print(f"  {workload_name} test completed")
        time.sleep(5)  # Brief cooldown

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="VM Feature Collector Stress Workload Demo")
    parser.add_argument('--demo-type', type=str, default='basic',
                       choices=['basic', 'cycling', 'collector', 'comprehensive', 'stress-only'],
                       help='Type of demo to run')
    parser.add_argument('--output-dir', type=str, default='examples',
                       help='Output directory for demo files')
    
    args = parser.parse_args()
    
    # Create output directory
    Path(args.output_dir).mkdir(exist_ok=True)
    
    print("VM Feature Collector - Stress Workload Demo")
    print("=" * 50)
    print(f"Demo type: {args.demo_type}")
    print(f"Output directory: {args.output_dir}")
    
    try:
        if args.demo_type == 'basic':
            demo_basic_stress_integration()
        elif args.demo_type == 'cycling':
            demo_cpu_cycling()
        elif args.demo_type == 'collector':
            demo_vm_collector_with_stress()
        elif args.demo_type == 'comprehensive':
            demo_comprehensive_collection()
        elif args.demo_type == 'stress-only':
            demo_stress_only()
        
        print("\n" + "="*60)
        print("DEMO COMPLETED SUCCESSFULLY!")
        print("="*60)
        print("\nKey takeaways:")
        print("1. Stress workloads generate diverse CPU utilization patterns")
        print("2. CPU cycling provides smooth 0-100% utilization sweeps")
        print("3. Different workloads stress different system components")
        print("4. Combined stress + feature collection creates rich training data")
        print("5. This data enables training robust power prediction models")
        
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"\nDemo failed: {e}")
        logger.exception("Demo error details:")

if __name__ == "__main__":
    main()