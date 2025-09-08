#!/usr/bin/env python3
"""
Stress Workloads Module - Standalone CPU Stress Testing

This module provides two types of stress workloads:
1. cycle: CPU load cycling from 0% to 100% in 5% steps (15 seconds each)
2. cpu_intensive: Fixed-duration intensive CPU workload using prime numbers and matrix multiplication

The script runs workloads sequentially based on a provided list and operates independently
from vm_feature_collector.py to allow separate execution.

Usage:
    python3 stress_workloads.py --workloads cycle
    python3 stress_workloads.py --workloads cycle,cpu_intensive,cycle --cpu-intensive-duration 60
    python3 stress_workloads.py --workloads cpu_intensive --cpu-intensive-duration 120
"""

import subprocess
import time
import logging
import signal
import sys
import argparse
import psutil
from typing import List, Optional
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class WorkloadConfig:
    """Configuration for stress workloads"""
    name: str
    description: str

class StressWorkloadRunner:
    """Manages sequential execution of stress workloads"""
    
    def __init__(self):
        self.num_cpus = psutil.cpu_count(logical=True)
        self.active_processes: List[subprocess.Popen] = []
        self.running = True
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Check stress-ng availability
        self._check_stress_ng()
        
        # Available workload configurations
        self.workload_configs = {
            "cycle": WorkloadConfig(
                name="cycle",
                description="CPU load cycling from 0% to 100% in 5% steps (15 seconds each)"
            ),
            "cpu_intensive": WorkloadConfig(
                name="cpu_intensive", 
                description="Fixed-duration intensive CPU workload with prime numbers and matrix multiplication"
            )
        }
        
        logger.info(f"Initialized StressWorkloadRunner with {self.num_cpus} CPUs")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        self._cleanup_processes()
        sys.exit(0)
    
    def _check_stress_ng(self):
        """Check if stress-ng is available"""
        try:
            result = subprocess.run(['stress-ng', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                logger.info("stress-ng is available")
            else:
                logger.error("stress-ng command failed")
                sys.exit(1)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"stress-ng not found: {e}")
            logger.error("Install with: sudo dnf install stress-ng  # or apt-get install stress-ng")
            sys.exit(1)
    
    def _cleanup_processes(self):
        """Clean up all active stress processes"""
        logger.info("Cleaning up stress processes...")
        
        # Terminate processes we started
        for proc in self.active_processes:
            try:
                if proc.poll() is None:  # Still running
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.warning("Process didn't terminate, killing forcefully")
                        proc.kill()
                        proc.wait()
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
        
        self.active_processes.clear()
        
        # Kill any remaining stress-ng processes
        try:
            subprocess.run(['pkill', '-f', 'stress-ng'], capture_output=True, timeout=3)
        except Exception as e:
            logger.debug(f"pkill stress-ng failed: {e}")
        
        logger.info("Process cleanup completed")
    
    def run_cycle_workload(self):
        """Run CPU load cycling from 0% to 100% and back down in 5% steps"""
        logger.info("Starting cycle workload: 0% -> 100% -> 0% in 5% steps (15s each)")
        
        total_steps = 0
        
        # Ramp up: 0% to 100%
        logger.info("Cycle workload: Ramping up 0% -> 100%")
        for load in range(0, 101, 5):
            if not self.running:
                break
            self._set_cpu_load(load, 15)
            total_steps += 1
        
        # Ramp down: 100% to 0% 
        if self.running:
            logger.info("Cycle workload: Ramping down 100% -> 0%")
            for load in range(100, -1, -5):
                if not self.running:
                    break
                self._set_cpu_load(load, 15)
                total_steps += 1
        
        total_duration = total_steps * 15
        logger.info(f"Cycle workload completed ({total_steps} steps, {total_duration} seconds)")
    
    def _set_cpu_load(self, target_load: int, duration: float):
        """Set CPU load to target percentage using stress-ng --cpu-load"""
        if not self.running:
            return
            
        # Clean up any existing stress processes first
        self._cleanup_processes()
        
        if target_load <= 0:
            logger.info(f"CPU load: {target_load}% (idle) for {duration}s")
            time.sleep(duration)
            return
        
        # Clamp target load
        target_load = max(0, min(100, target_load))
        
        # Use all CPUs for more stable load control
        num_workers = self.num_cpus
        
        cmd = [
            'stress-ng',
            '--cpu', str(num_workers),
            '--cpu-load', str(target_load),
            '--timeout', f"{duration}s",
            '--quiet'
        ]
        
        try:
            logger.info(f"CPU load: {target_load}% for {duration}s")
            proc = subprocess.Popen(cmd)
            self.active_processes.append(proc)
            
            # Wait for the duration
            proc.wait()
            
        except Exception as e:
            logger.error(f"Failed to set CPU load {target_load}%: {e}")
    
    def run_cpu_intensive_workload(self, duration: int):
        """Run CPU intensive workload with diverse sequential stress patterns"""
        logger.info(f"Starting CPU intensive workload for {duration} seconds (sequential execution)")
        
        # Sequential stress methods - each runs for a portion of the total duration
        stress_methods = [
            {
                'method': 'prime',
                'workers': self.num_cpus,
                'description': 'Prime number computation (CPU-bound, integer arithmetic)',
                'focus': 'Integer ALU, branch prediction'
            },
            {
                'method': 'matrixprod', 
                'workers': self.num_cpus,
                'description': 'Matrix multiplication (FPU-intensive, cache patterns)',
                'focus': 'Floating-point units, memory hierarchy'
            },
            {
                'method': 'fft',
                'workers': self.num_cpus,
                'description': 'Fast Fourier Transform (complex math, memory access)',
                'focus': 'FPU, complex operations, memory bandwidth'
            },
            {
                'method': 'fibonacci',
                'workers': self.num_cpus,
                'description': 'Fibonacci sequence (recursive computation)',
                'focus': 'Function calls, stack operations, recursion'
            },
            {
                'method': 'correlate',
                'workers': self.num_cpus,
                'description': 'Correlation computation (statistical operations)',
                'focus': 'Floating-point, statistical math'
            },
            {
                'method': 'crc16',
                'workers': self.num_cpus,
                'description': 'CRC16 checksum (bit manipulation, loops)',
                'focus': 'Bit operations, tight loops'
            },
            {
                'method': 'djb2a',
                'workers': self.num_cpus,
                'description': 'Hash computation (string processing)',
                'focus': 'Hash functions, data processing'
            },
            {
                'method': 'gray',
                'workers': self.num_cpus,
                'description': 'Gray code generation (bit patterns)',
                'focus': 'Bit manipulation, pattern generation'
            }
        ]
        
        # Calculate time per method
        time_per_method = duration / len(stress_methods)
        logger.info(f"Running {len(stress_methods)} methods sequentially, {time_per_method:.1f}s each")
        
        start_time = time.time()
        total_elapsed = 0
        
        # Run each stress method sequentially
        for i, method_config in enumerate(stress_methods):
            if not self.running:
                break
            
            method_start = time.time()
            remaining_time = duration - total_elapsed
            
            if remaining_time < 5:  # Skip if less than 5 seconds remaining
                logger.info(f"Skipping {method_config['description']} - insufficient time remaining")
                break
            
            # Use remaining time or allocated time, whichever is smaller
            method_duration = min(time_per_method, remaining_time)
            
            logger.info(f"Step {i+1}/{len(stress_methods)}: {method_config['description']}")
            logger.info(f"  Focus: {method_config['focus']}")
            logger.info(f"  Duration: {method_duration:.1f}s with {method_config['workers']} workers")
            
            cmd = [
                'stress-ng',
                '--cpu', str(method_config['workers']),
                '--cpu-method', method_config['method'],
                '--timeout', f"{method_duration:.0f}s",
                '--quiet'
            ]
            
            try:
                proc = subprocess.Popen(cmd)
                self.active_processes.append(proc)
                
                # Wait for this specific method to complete
                proc.wait()
                
                method_elapsed = time.time() - method_start
                total_elapsed = time.time() - start_time
                
                logger.info(f"  Completed in {method_elapsed:.1f}s (total elapsed: {total_elapsed:.1f}s)")
                
                # Brief pause between methods
                if i < len(stress_methods) - 1 and self.running:
                    time.sleep(1)
                    total_elapsed += 1
                
            except Exception as e:
                logger.error(f"Failed to run {method_config['description']}: {e}")
        
        # Clean up any remaining processes
        self._cleanup_processes()
        
        actual_duration = time.time() - start_time
        logger.info(f"CPU intensive workload completed ({actual_duration:.1f} seconds, {len(stress_methods)} methods)")
    
    def run_workload_sequence(self, workload_list: List[str], cpu_intensive_duration: int = 60, total_duration: int = None):
        """Run a sequence of workloads, looping until total_duration is reached"""
        if total_duration:
            logger.info(f"Starting workload sequence: {', '.join(workload_list)} - looping for {total_duration} seconds")
        else:
            logger.info(f"Starting workload sequence: {', '.join(workload_list)} - single run")
            
        start_time = time.time()
        cycle_count = 0
        
        while self.running:
            cycle_count += 1
            cycle_start = time.time()
            
            # Check if we've reached total duration before starting new cycle
            if total_duration and (time.time() - start_time) >= total_duration:
                break
                
            logger.info(f"Starting workload cycle {cycle_count}")
            
            for i, workload_name in enumerate(workload_list):
                if not self.running:
                    break
                    
                # Check duration before each workload
                if total_duration and (time.time() - start_time) >= total_duration:
                    logger.info(f"Total duration reached during cycle {cycle_count}, stopping")
                    break
                    
                if workload_name not in self.workload_configs:
                    logger.error(f"Unknown workload: {workload_name}")
                    continue
                
                logger.info(f"Running workload {i+1}/{len(workload_list)}: {workload_name}")
                
                if workload_name == "cycle":
                    self.run_cycle_workload()
                elif workload_name == "cpu_intensive":
                    self.run_cpu_intensive_workload(cpu_intensive_duration)
                
                # Brief pause between workloads
                if i < len(workload_list) - 1 and self.running:
                    logger.info("Pausing 3 seconds between workloads...")
                    time.sleep(3)
            
            cycle_duration = time.time() - cycle_start
            logger.info(f"Workload cycle {cycle_count} completed in {cycle_duration:.1f} seconds")
            
            # If no total duration specified, run only once
            if not total_duration:
                break
                
            # Brief pause between cycles if continuing
            if self.running and total_duration and (time.time() - start_time) < total_duration:
                logger.info("Pausing 5 seconds between cycles...")
                time.sleep(5)
        
        total_elapsed = time.time() - start_time
        logger.info(f"Workload sequence completed: {cycle_count} cycles in {total_elapsed:.1f} seconds")
    
    def list_available_workloads(self):
        """List all available workloads"""
        print("Available workloads:")
        for name, config in self.workload_configs.items():
            print(f"  {name}: {config.description}")
    
    def get_system_info(self):
        """Display system information"""
        cpu_count = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        memory = psutil.virtual_memory()
        
        logger.info(f"System Info:")
        logger.info(f"  CPUs: {cpu_count} logical, {cpu_count_physical} physical")
        logger.info(f"  Memory: {memory.total / (1024**3):.1f} GB total")
        logger.info(f"  Current CPU usage: {psutil.cpu_percent(interval=1):.1f}%")


def main():
    """Main function to handle command line arguments and run workloads"""
    parser = argparse.ArgumentParser(description="Standalone CPU stress workload runner")
    parser.add_argument('--workloads', type=str,
                       help='Comma-separated list of workloads to run (e.g., "cycle,cpu_intensive,cycle")')
    parser.add_argument('--cpu-intensive-duration', type=int, default=60,
                       help='Duration for cpu_intensive workload in seconds (default: 60)')
    parser.add_argument('--total-duration', type=int,
                       help='Total duration to run workloads (loops sequence until duration met)')
    parser.add_argument('--list', action='store_true',
                       help='List available workloads and exit')
    parser.add_argument('--system-info', action='store_true',
                       help='Show system information and exit')
    
    args = parser.parse_args()
    
    runner = StressWorkloadRunner()
    
    if args.list:
        runner.list_available_workloads()
        return
    
    if args.system_info:
        runner.get_system_info()
        return
    
    # Check if workloads argument is provided when needed
    if not args.workloads:
        parser.error("--workloads is required unless using --list or --system-info")
    
    # Parse workload list
    workload_list = [w.strip() for w in args.workloads.split(',')]
    
    # Validate workloads
    invalid_workloads = [w for w in workload_list if w not in runner.workload_configs]
    if invalid_workloads:
        logger.error(f"Invalid workloads: {', '.join(invalid_workloads)}")
        runner.list_available_workloads()
        sys.exit(1)
    
    try:
        runner.run_workload_sequence(workload_list, args.cpu_intensive_duration, args.total_duration)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error running workloads: {e}")
        sys.exit(1)
    finally:
        runner._cleanup_processes()


if __name__ == "__main__":
    main()