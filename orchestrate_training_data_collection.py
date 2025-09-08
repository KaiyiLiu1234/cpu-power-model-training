#!/usr/bin/env python3
"""
Training Data Collection Orchestrator

This script coordinates the collection of training data by:
1. Running stress workloads and feature collection in VM (via SSH)
2. Running power collection on baremetal (locally)
3. Synchronizing start/stop times
4. Merging the resulting datasets

Usage:
    # Basic usage with VM name
    python3 orchestrate_training_data_collection.py --vm-name fedora40 --duration 800
    
    # Full example with custom parameters
    python3 orchestrate_training_data_collection.py \
        --vm-name fedora40 \
        --vm-host 192.168.1.100 \
        --vm-user vagrant \
        --duration 800 \
        --workloads cycle,cpu_intensive \
        --cpu-intensive-duration 120 \
        --output-prefix training_data_20241207 \
        --interval 1.0
"""

import subprocess
import time
import argparse
import logging
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import paramiko

# Configure logging
script_dir = Path(__file__).parent
logs_dir = script_dir / 'logs'
logs_dir.mkdir(exist_ok=True)
log_file = logs_dir / 'orchestrator.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TrainingDataOrchestrator:
    """Orchestrates synchronized VM feature and baremetal power collection"""
    
    def __init__(self, vm_name: str, vm_host: str, vm_user: str = "root", 
                 vm_port: int = 22, vm_key_file: Optional[str] = None,
                 vm_project_path: str = "/root/cpu-power-model-training",
                 interval: float = 1.0, kepler_url: str = "http://localhost:28283/metrics"):
        
        self.vm_name = vm_name
        self.vm_host = vm_host
        self.vm_user = vm_user
        self.vm_port = vm_port
        self.vm_key_file = vm_key_file
        self.vm_project_path = vm_project_path
        self.interval = interval
        self.kepler_url = kepler_url
        
        # SSH connection
        self.ssh_client: Optional[paramiko.SSHClient] = None
        
        # Process tracking
        self.bm_power_process: Optional[subprocess.Popen] = None
        self.vm_stress_process = None
        self.vm_collector_process = None
        
        # Control flags
        self.collection_active = False
        self._shutdown_requested = False
        
        # Signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Initialized orchestrator for VM {vm_name} at {vm_host}")
        logger.info(f"Collection interval: {interval}s, Kepler: {kepler_url}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        if self._shutdown_requested:
            logger.warning("Force shutdown requested!")
            self._force_cleanup()
            sys.exit(1)
        
        logger.info(f"Received signal {signum}, stopping collection...")
        self._shutdown_requested = True
        self.collection_active = False
        logger.info("Shutdown initiated - press Ctrl+C again to force quit")
    
    def _force_cleanup(self):
        """Force cleanup of all processes"""
        try:
            self._stop_baremetal_collection()
            self._stop_vm_processes()
            self._disconnect_ssh()
        except Exception as e:
            logger.debug(f"Force cleanup error: {e}")
    
    def setup_ssh_connection(self) -> bool:
        """Establish SSH connection to VM"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connection parameters
            connect_params = {
                'hostname': self.vm_host,
                'port': self.vm_port,
                'username': self.vm_user,
                'timeout': 10
            }
            
            if self.vm_key_file:
                connect_params['key_filename'] = self.vm_key_file
            else:
                logger.info("No SSH key specified, will attempt password/agent authentication")
            
            self.ssh_client.connect(**connect_params)
            
            # Test connection
            _, stdout, stderr = self.ssh_client.exec_command('echo "SSH connection test"')
            result = stdout.read().decode().strip()
            
            if result == "SSH connection test":
                logger.info(f"SSH connection to {self.vm_host} established successfully")
                return True
            else:
                logger.error("SSH connection test failed")
                return False
                
        except Exception as e:
            logger.error(f"Failed to establish SSH connection to {self.vm_host}: {e}")
            return False
    
    def _disconnect_ssh(self):
        """Disconnect SSH connection"""
        if self.ssh_client:
            try:
                self.ssh_client.close()
                logger.info("SSH connection closed")
            except Exception as e:
                logger.debug(f"Error closing SSH connection: {e}")
            finally:
                self.ssh_client = None
    
    def _execute_vm_command(self, command: str, background: bool = False) -> tuple:
        """Execute command on VM via SSH"""
        if not self.ssh_client:
            raise RuntimeError("SSH connection not established")
        
        try:
            if background:
                # For background processes, use nohup and redirect output
                bg_command = f"cd {self.vm_project_path} && nohup {command} > /tmp/vm_process.log 2>&1 & echo $!"
                stdin, stdout, stderr = self.ssh_client.exec_command(bg_command)
                pid = stdout.read().decode().strip()
                logger.info(f"Started background VM process with PID: {pid}")
                return (pid, "", "")
            else:
                stdin, stdout, stderr = self.ssh_client.exec_command(f"cd {self.vm_project_path} && {command}")
                stdout_text = stdout.read().decode()
                stderr_text = stderr.read().decode()
                return_code = stdout.channel.recv_exit_status()
                return (return_code, stdout_text, stderr_text)
                
        except Exception as e:
            logger.error(f"Failed to execute VM command '{command}': {e}")
            raise
    
    def _check_vm_project_structure(self) -> bool:
        """Verify VM has the required project structure"""
        try:
            ret_code, stdout, stderr = self._execute_vm_command("ls -la")
            
            if ret_code != 0:
                logger.error(f"Failed to list VM project directory: {stderr}")
                return False
            
            required_files = ["vm_feature_collector/src/vm_feature_collector.py", 
                            "vm_feature_collector/src/stress_workloads.py"]
            
            for file_path in required_files:
                ret_code, _, _ = self._execute_vm_command(f"test -f {file_path}")
                if ret_code != 0:
                    logger.error(f"Required file not found in VM: {file_path}")
                    return False
            
            logger.info("VM project structure verified")
            return True
            
        except Exception as e:
            logger.error(f"Failed to verify VM project structure: {e}")
            return False
    
    def start_vm_stress_workloads(self, workloads: List[str], cpu_intensive_duration: int = 120, total_duration: int = None) -> bool:
        """Start stress workloads on VM"""
        try:
            workload_str = ",".join(workloads)
            stress_cmd = (f"python3 vm_feature_collector/src/stress_workloads.py "
                         f"--workloads {workload_str} --cpu-intensive-duration {cpu_intensive_duration}")
            
            # Add total duration if specified (stress workloads should run longer than collectors)
            if total_duration:
                stress_cmd += f" --total-duration {total_duration}"
            
            logger.info(f"Starting VM stress workloads: {workload_str} for {total_duration}s")
            self.vm_stress_process = self._execute_vm_command(stress_cmd, background=True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to start VM stress workloads: {e}")
            return False
    
    def start_vm_feature_collection(self, duration: int, output_file: str) -> bool:
        """Start feature collection on VM"""
        try:
            collector_cmd = (f"python3 vm_feature_collector/src/vm_feature_collector.py "
                           f"--duration {duration} --interval {self.interval} --output {output_file}")
            
            logger.info(f"Starting VM feature collection for {duration}s")
            self.vm_collector_process = self._execute_vm_command(collector_cmd, background=True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to start VM feature collection: {e}")
            return False
    
    def start_baremetal_power_collection(self, duration: int, output_file: str) -> bool:
        """Start power collection on baremetal"""
        try:
            power_cmd = [
                "python3", "bm_power_collector.py",
                "--duration", str(duration),
                "--interval", str(self.interval),
                "--vm-names", self.vm_name,
                "--kepler-url", self.kepler_url,
                "--output", output_file,
                "--verbose"
            ]
            
            logger.info(f"Starting baremetal power collection for {duration}s")
            self.bm_power_process = subprocess.Popen(
                power_cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to start baremetal power collection: {e}")
            return False
    
    def _stop_vm_processes(self):
        """Stop VM processes"""
        if not self.ssh_client:
            return
        
        try:
            # Kill stress workloads
            self._execute_vm_command("pkill -f stress_workloads.py")
            self._execute_vm_command("pkill -f stress-ng")
            
            # Kill feature collector
            self._execute_vm_command("pkill -f vm_feature_collector.py")
            
            logger.info("VM processes stopped")
            
        except Exception as e:
            logger.error(f"Error stopping VM processes: {e}")
    
    def _stop_baremetal_collection(self):
        """Stop baremetal power collection"""
        if self.bm_power_process:
            try:
                self.bm_power_process.terminate()
                try:
                    self.bm_power_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("Baremetal process didn't terminate, killing forcefully")
                    self.bm_power_process.kill()
                    self.bm_power_process.wait()
                
                logger.info("Baremetal power collection stopped")
                
            except Exception as e:
                logger.error(f"Error stopping baremetal power collection: {e}")
            finally:
                self.bm_power_process = None
    
    def copy_vm_data(self, vm_file_path: str, local_file_path: str) -> bool:
        """Copy collected data from VM to local machine"""
        try:
            if not self.ssh_client:
                logger.error("SSH connection not available for file copy")
                return False
            
            # Use SFTP to copy file
            sftp = self.ssh_client.open_sftp()
            sftp.get(f"{self.vm_project_path}/{vm_file_path}", local_file_path)
            sftp.close()
            
            logger.info(f"Copied {vm_file_path} from VM to {local_file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy file from VM: {e}")
            return False
    
    def orchestrate_collection(self, duration: int, workloads: List[str], 
                             cpu_intensive_duration: int, output_prefix: str) -> Dict[str, str]:
        """Orchestrate the complete data collection process"""
        
        # File paths
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        vm_features_file = f"data/vm_features_{output_prefix}_{timestamp}.json"
        bm_power_file = f"data/bm_power_{output_prefix}_{timestamp}.csv"
        local_vm_features_file = f"data/vm_features_{output_prefix}_{timestamp}.json"
        
        # Create data directory
        Path("data").mkdir(exist_ok=True)
        
        logger.info(f"Starting orchestrated data collection")
        logger.info(f"Duration: {duration}s, Workloads: {workloads}")
        logger.info(f"Output files: {vm_features_file}, {bm_power_file}")
        
        self.collection_active = True
        
        try:
            # 1. Setup SSH connection
            if not self.setup_ssh_connection():
                raise RuntimeError("Failed to establish SSH connection to VM")
            
            # 2. Verify VM project structure
            if not self._check_vm_project_structure():
                raise RuntimeError("VM project structure verification failed")
            
            # 3. Ensure VM data directory exists
            self._execute_vm_command("mkdir -p data")
            
            # 4. Start VM stress workloads first (they run continuously)
            # Give stress workloads extra time to ensure they outlast collectors
            stress_duration = duration + 10  # Extra 60 seconds
            if not self.start_vm_stress_workloads(workloads, cpu_intensive_duration, stress_duration):
                raise RuntimeError("Failed to start VM stress workloads")
            
            # 5. Start all three processes simultaneously as background processes
            logger.info("Starting all collection processes simultaneously...")
            
            # Start VM feature collection
            if not self.start_vm_feature_collection(duration, vm_features_file):
                raise RuntimeError("Failed to start VM feature collection")
            
            # Start baremetal power collection
            if not self.start_baremetal_power_collection(duration, bm_power_file):
                raise RuntimeError("Failed to start baremetal power collection")
            
            logger.info(f"All processes started - they will run for {duration}s and finish automatically")
            
            # Wait for baremetal process to complete (it will finish when done)
            if self.bm_power_process:
                self.bm_power_process.wait()
            
            # 9. Copy VM data to local machine
            logger.info("Copying VM data to local machine...")
            if not self.copy_vm_data(vm_features_file, local_vm_features_file):
                raise RuntimeError("Failed to copy VM feature data")
            
            logger.info("Data collection orchestration completed successfully")
            
            return {
                'vm_features_file': local_vm_features_file,
                'bm_power_file': bm_power_file,
                'duration': duration,
                'workloads': workloads,
                'timestamp': timestamp
            }
            
        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            # Cleanup on failure
            self._stop_vm_processes()
            self._stop_baremetal_collection()
            raise
        
        finally:
            self.collection_active = False
            self._disconnect_ssh()

def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Orchestrate training data collection")
    parser.add_argument('--vm-name', type=str, required=True,
                       help='VM name for power collection filtering')
    parser.add_argument('--vm-host', type=str, required=True,
                       help='VM IP address or hostname for SSH connection')
    parser.add_argument('--vm-user', type=str, default='root',
                       help='SSH username for VM (default: root)')
    parser.add_argument('--vm-port', type=int, default=22,
                       help='SSH port for VM (default: 22)')
    parser.add_argument('--vm-key-file', type=str,
                       help='SSH private key file for VM authentication')
    parser.add_argument('--vm-project-path', type=str, 
                       default='/root/cpu-power-model-training',
                       help='Project path on VM (default: /root/cpu-power-model-training)')
    parser.add_argument('--duration', type=int, default=800,
                       help='Collection duration in seconds (default: 800)')
    parser.add_argument('--workloads', type=str, default='cycle,cpu_intensive',
                       help='Comma-separated workloads (default: cycle,cpu_intensive)')
    parser.add_argument('--cpu-intensive-duration', type=int, default=120,
                       help='Duration for cpu_intensive workload (default: 120)')
    parser.add_argument('--output-prefix', type=str, default='training',
                       help='Output file prefix (default: training)')
    parser.add_argument('--interval', type=float, default=1.0,
                       help='Collection interval in seconds (default: 1.0)')
    parser.add_argument('--kepler-url', type=str, default='http://localhost:28283/metrics',
                       help='Kepler metrics URL (default: http://localhost:28283/metrics)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse workloads
    workloads = [w.strip() for w in args.workloads.split(',')]
    
    # Create orchestrator
    orchestrator = TrainingDataOrchestrator(
        vm_name=args.vm_name,
        vm_host=args.vm_host,
        vm_user=args.vm_user,
        vm_port=args.vm_port,
        vm_key_file=args.vm_key_file,
        vm_project_path=args.vm_project_path,
        interval=args.interval,
        kepler_url=args.kepler_url
    )
    
    try:
        # Run orchestrated collection
        result = orchestrator.orchestrate_collection(
            duration=args.duration,
            workloads=workloads,
            cpu_intensive_duration=args.cpu_intensive_duration,
            output_prefix=args.output_prefix
        )
        
        logger.info("="*60)
        logger.info("COLLECTION COMPLETED SUCCESSFULLY")
        logger.info("="*60)
        logger.info(f"VM Features: {result['vm_features_file']}")
        logger.info(f"BM Power: {result['bm_power_file']}")
        logger.info(f"Timestamp: {result['timestamp']}")
        logger.info("Next step: Run merge_datasets.py to combine the data")
        
    except Exception as e:
        logger.error(f"Training data collection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()