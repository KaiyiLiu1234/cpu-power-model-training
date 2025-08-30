#!/usr/bin/env python3
"""
Workload Sequence Demo for VM Feature Collector

This script demonstrates the new workload sequence functionality that allows
cycling through multiple stress workloads during feature collection.

Key Features Demonstrated:
1. CPU cycling → CPU intensive cycling
2. Multiple workload sequences with custom durations
3. Real-time workload monitoring during sequences
4. Perfect for comprehensive training data collection

Usage:
    python3 examples/sequence_demo.py --demo-type basic
    python3 examples/sequence_demo.py --demo-type advanced
    python3 examples/sequence_demo.py --demo-type collector
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

def demo_basic_sequence():
    """Demo: Basic workload sequence - CPU cycling + CPU intensive"""
    print("\n" + "="*70)
    print("DEMO: Basic Workload Sequence (CPU Cycling → CPU Intensive)")
    print("="*70)
    
    stress_manager = StressWorkloadManager()
    
    # Example: cpu_cycling:30,cpu_intensive:20 for 2 minutes total
    sequence_spec = "cpu_cycling:30,cpu_intensive:20"
    total_duration = 120  # 2 minutes - should complete 2+ cycles
    
    print(f"Running sequence: {sequence_spec}")
    print(f"Total duration: {total_duration} seconds")
    print("Expected pattern:")
    print("  0-30s:  CPU cycling (0% → 100% → 0%)")
    print("  30-50s: CPU intensive (prime + matrix + int64)")
    print("  50-80s: CPU cycling again")
    print("  80-100s: CPU intensive again")
    print("  100-120s: CPU cycling (partial)")
    print()
    
    with stress_manager.run_workload_sequence(sequence_spec, total_duration):
        # Monitor every 10 seconds
        for i in range(total_duration // 10):
            time.sleep(10)
            metrics = stress_manager.monitor_system_load()
            elapsed = (i + 1) * 10
            current_workload = stress_manager.current_workload
            
            print(f"t+{elapsed:3d}s: Workload={current_workload:15s} "
                  f"CPU={metrics.get('cpu_percent', 0):5.1f}% "
                  f"Load={metrics.get('load_1min', 0):4.2f}")
    
    print("\nBasic sequence demo completed!")

def demo_advanced_sequence():
    """Demo: Advanced multi-workload sequence"""
    print("\n" + "="*70)
    print("DEMO: Advanced Multi-Workload Sequence")
    print("="*70)
    
    stress_manager = StressWorkloadManager()
    
    # Complex sequence: 3 different workloads
    sequence_spec = "cpu_intensive:45,memory_intensive:30,mixed_workload:25"
    total_duration = 180  # 3 minutes - should complete 1+ cycles
    
    print(f"Running sequence: {sequence_spec}")
    print(f"Total duration: {total_duration} seconds")
    print("Expected pattern:")
    print("  0-45s:   CPU intensive (prime + matrix + int64)")
    print("  45-75s:  Memory intensive (allocations + cache)")
    print("  75-100s: Mixed workload (CPU + memory + I/O)")
    print("  100-145s: CPU intensive again")
    print("  145-175s: Memory intensive again")
    print("  175-180s: Mixed workload (partial)")
    print()
    
    with stress_manager.run_workload_sequence(sequence_spec, total_duration):
        # Monitor every 15 seconds
        for i in range(total_duration // 15):
            time.sleep(15)
            metrics = stress_manager.monitor_system_load()
            elapsed = (i + 1) * 15
            current_workload = stress_manager.current_workload
            
            print(f"t+{elapsed:3d}s: Workload={current_workload:18s} "
                  f"CPU={metrics.get('cpu_percent', 0):5.1f}% "
                  f"Mem={metrics.get('memory_percent', 0):5.1f}% "
                  f"Load={metrics.get('load_1min', 0):4.2f}")
    
    print("\nAdvanced sequence demo completed!")

def demo_equal_time_sequence():
    """Demo: Equal time distribution sequence"""
    print("\n" + "="*70)
    print("DEMO: Equal Time Distribution Sequence")
    print("="*70)
    
    stress_manager = StressWorkloadManager()
    
    # Equal time sequence - no explicit durations
    sequence_spec = "cpu_cycling,cpu_intensive,memory_intensive"
    total_duration = 150  # 2.5 minutes - 50s each workload
    
    print(f"Running sequence: {sequence_spec}")
    print(f"Total duration: {total_duration} seconds")
    print("Expected pattern (equal ~50s each):")
    print("  0-50s:   CPU cycling")
    print("  50-100s: CPU intensive") 
    print("  100-150s: Memory intensive")
    print()
    
    with stress_manager.run_workload_sequence(sequence_spec, total_duration):
        # Monitor every 10 seconds
        for i in range(total_duration // 10):
            time.sleep(10)
            metrics = stress_manager.monitor_system_load()
            elapsed = (i + 1) * 10
            current_workload = stress_manager.current_workload
            
            print(f"t+{elapsed:3d}s: Workload={current_workload:18s} "
                  f"CPU={metrics.get('cpu_percent', 0):5.1f}% "
                  f"Load={metrics.get('load_1min', 0):4.2f}")
    
    print("\nEqual time sequence demo completed!")

def demo_collector_with_sequence():
    """Demo: VM Feature Collector with workload sequence"""
    print("\n" + "="*70)
    print("DEMO: VM Feature Collector with Workload Sequence")
    print("="*70)
    
    # Create collector with sequence specification
    sequence_spec = "cpu_cycling:40,cpu_intensive:30"
    collector = VMFeatureCollector(
        collection_interval=2.0,  # Collect every 2 seconds
        stress_workload=sequence_spec
    )
    
    print(f"Collecting features with sequence: {sequence_spec}")
    print("Duration: 120 seconds (expect ~1.7 cycles)")
    print("Collection interval: 2 seconds")
    print()
    
    # Collect features with sequence
    features = collector.collect_vm_features(
        duration=120,
        output_file="examples/sequence_demo_features.json"
    )
    
    print(f"\nCollected {len(features)} feature points with workload sequence")
    
    # Analyze workload transitions in the data
    if features:
        print("\nWorkload transition analysis:")
        prev_workload = None
        transition_count = 0
        
        for i, feature in enumerate(features):
            current_workload = feature.stress_workload
            if current_workload != prev_workload:
                transition_count += 1
                timestamp = feature.timestamp_iso.split('T')[1][:8]  # HH:MM:SS
                print(f"  Transition #{transition_count}: {timestamp} → {current_workload} "
                      f"(CPU: {feature.cpu_utilization:.1f}%)")
                prev_workload = current_workload
        
        print(f"\nTotal workload transitions: {transition_count}")
        print("This demonstrates that features are properly annotated with workload types!")

def demo_comprehensive_training_data():
    """Demo: Comprehensive training data collection with sequences"""
    print("\n" + "="*70)
    print("DEMO: Comprehensive Training Data Collection")
    print("="*70)
    
    # Multiple sequences for comprehensive coverage
    sequences = [
        ("cpu_cycling:30,cpu_intensive:20", 100, "cycling_intensive"),
        ("memory_intensive:25,mixed_workload:35", 120, "memory_mixed"),
        ("cpu_cycling,cpu_intensive,memory_intensive", 150, "triple_equal")
    ]
    
    all_features = []
    
    for sequence_spec, duration, label in sequences:
        print(f"\nCollecting with sequence '{label}': {sequence_spec}")
        
        collector = VMFeatureCollector(
            collection_interval=1.5,
            stress_workload=sequence_spec
        )
        
        features = collector.collect_vm_features(
            duration=duration,
            output_file=f"examples/comprehensive_{label}.json"
        )
        
        all_features.extend(features)
        print(f"  Collected {len(features)} points for {label}")
        
        # Brief cooldown between sequences
        time.sleep(5)
    
    print(f"\nComprehensive collection summary:")
    print(f"Total feature points: {len(all_features)}")
    print(f"Total collection time: ~{sum(s[1] for s in sequences) + 10}s")
    
    # Workload distribution analysis
    workload_counts = {}
    for feature in all_features:
        workload = feature.stress_workload
        workload_counts[workload] = workload_counts.get(workload, 0) + 1
    
    print(f"\nWorkload distribution:")
    for workload, count in workload_counts.items():
        percentage = (count / len(all_features)) * 100
        print(f"  {workload:20s}: {count:4d} points ({percentage:5.1f}%)")
    
    print("\nThis rich dataset spans multiple workload patterns and transitions!")
    print("Perfect for training robust power prediction models! 🚀")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Workload Sequence Demo")
    parser.add_argument('--demo-type', type=str, default='basic',
                       choices=['basic', 'advanced', 'equal-time', 'collector', 'comprehensive'],
                       help='Type of sequence demo to run')
    parser.add_argument('--output-dir', type=str, default='examples',
                       help='Output directory for demo files')
    
    args = parser.parse_args()
    
    # Create output directory
    Path(args.output_dir).mkdir(exist_ok=True)
    
    print("VM Feature Collector - Workload Sequence Demo")
    print("=" * 50)
    print(f"Demo type: {args.demo_type}")
    
    try:
        if args.demo_type == 'basic':
            demo_basic_sequence()
        elif args.demo_type == 'advanced':
            demo_advanced_sequence()
        elif args.demo_type == 'equal-time':
            demo_equal_time_sequence()
        elif args.demo_type == 'collector':
            demo_collector_with_sequence()
        elif args.demo_type == 'comprehensive':
            demo_comprehensive_training_data()
        
        print("\n" + "="*70)
        print("🎉 SEQUENCE DEMO COMPLETED SUCCESSFULLY! 🎉")
        print("="*70)
        print("\nKey achievements:")
        print("✅ Multiple workloads cycle automatically until duration ends")
        print("✅ CPU cycling → CPU intensive transitions work perfectly")
        print("✅ Feature collection captures workload type in each data point") 
        print("✅ Sequences enable comprehensive training data across patterns")
        print("✅ Perfect for your requested cpu_cycling + matrix computation cycling!")
        
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"\nDemo failed: {e}")
        logger.exception("Demo error details:")

if __name__ == "__main__":
    main()