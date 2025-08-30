#!/usr/bin/env python3
"""
Debug Stress Workloads

This script helps debug whether stress-ng processes are actually being created
and managed correctly by the VM Feature Collector.
"""

import sys
import time
import subprocess
import psutil
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from stress_workloads import StressWorkloadManager

def monitor_processes():
    """Monitor stress-ng processes in real-time"""
    print("=== Process Monitor ===")
    
    def get_stress_processes():
        """Get current stress-ng processes"""
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent']):
            try:
                if 'stress-ng' in proc.info['name'] or any('stress-ng' in arg for arg in proc.info['cmdline']):
                    processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return processes
    
    def print_processes():
        processes = get_stress_processes()
        print(f"\n[{time.strftime('%H:%M:%S')}] Found {len(processes)} stress-ng processes:")
        for proc in processes:
            cmdline = ' '.join(proc['cmdline'][:6])  # First 6 args
            print(f"  PID {proc['pid']}: {cmdline}")
        return len(processes)
    
    return print_processes

def test_stress_manager():
    """Test the StressWorkloadManager directly"""
    print("=== Testing StressWorkloadManager ===")
    
    # Create process monitor
    monitor = monitor_processes()
    
    try:
        # Create stress manager
        print("Creating StressWorkloadManager...")
        manager = StressWorkloadManager()
        
        # List available workloads
        print(f"Available workloads: {manager.get_available_workloads()}")
        
        # Test CPU intensive workload
        print("\nTesting cpu_intensive workload for 30 seconds...")
        print("Watch for stress-ng processes to appear:")
        
        monitor()  # Check initial state
        
        # Start workload
        manager.start_workload("cpu_intensive", 30)
        print("Workload started...")
        
        # Monitor for 30 seconds
        for i in range(15):  # Check every 2 seconds for 30 seconds
            time.sleep(2)
            count = monitor()
            if count == 0:
                print("⚠️  No stress-ng processes found!")
            else:
                print(f"✅ Found {count} stress-ng processes")
        
        # Stop workload
        print("\nStopping workload...")
        manager.stop_workload()
        
        time.sleep(2)
        final_count = monitor()
        if final_count == 0:
            print("✅ All stress-ng processes cleaned up")
        else:
            print(f"⚠️  {final_count} stress-ng processes still running")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def test_cpu_cycling():
    """Test CPU cycling specifically"""
    print("\n=== Testing CPU Cycling ===")
    
    monitor = monitor_processes()
    
    try:
        manager = StressWorkloadManager()
        
        print("Starting CPU cycling for 60 seconds...")
        print("You should see stress-ng processes change load levels every 15 seconds")
        
        monitor()  # Initial state
        
        # Start CPU cycling
        manager.start_workload("cpu_cycling", 60)
        
        # Monitor for 60 seconds
        for i in range(30):  # Check every 2 seconds
            time.sleep(2)
            count = monitor()
            
        manager.stop_workload()
        time.sleep(2)
        monitor()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def test_manual_stress():
    """Test stress-ng manually to verify it works"""
    print("\n=== Manual stress-ng Test ===")
    
    monitor = monitor_processes()
    
    print("Testing manual stress-ng command...")
    monitor()  # Before
    
    try:
        # Start a simple stress-ng command
        print("Running: stress-ng --cpu 2 --cpu-load 50 --timeout 20s")
        proc = subprocess.Popen(['stress-ng', '--cpu', '2', '--cpu-load', '50', '--timeout', '20s'])
        
        print("Process started, monitoring for 20 seconds...")
        for i in range(10):
            time.sleep(2)
            count = monitor()
            
        # Wait for process to complete
        proc.wait()
        print(f"Process completed with return code: {proc.returncode}")
        
        time.sleep(2)
        monitor()  # After
        
    except FileNotFoundError:
        print("❌ stress-ng command not found! Install with:")
        print("   sudo dnf install stress-ng")
        print("   # or")
        print("   sudo apt-get install stress-ng")
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Debug stress workloads")
    parser.add_argument('--test', choices=['manager', 'cycling', 'manual', 'all'], 
                       default='all', help='Which test to run')
    
    args = parser.parse_args()
    
    print("Stress Workload Debug Tool")
    print("=" * 30)
    
    if args.test in ['manual', 'all']:
        test_manual_stress()
    
    if args.test in ['manager', 'all']:
        test_stress_manager()
    
    if args.test in ['cycling', 'all']:
        test_cpu_cycling()
    
    print("\n" + "=" * 30)
    print("Debug completed!")
    print("If you saw stress-ng processes during the tests, the system is working.")
    print("If not, check:")
    print("1. Is stress-ng installed? (which stress-ng)")
    print("2. Are there permission issues?")
    print("3. Check logs for error messages")

if __name__ == "__main__":
    main()