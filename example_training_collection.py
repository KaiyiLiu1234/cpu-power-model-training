#!/usr/bin/env python3
"""
Example Training Data Collection Script

This script demonstrates how to use the training data collection system
to generate a complete dataset for VM CPU power prediction models.

Usage:
    python3 example_training_collection.py --vm-name fedora40 --vm-host 192.168.1.100
"""

import subprocess
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime
import glob

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_command(cmd, description):
    """Run a command and handle errors"""
    logger.info(f"Running: {description}")
    logger.debug(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"✓ {description} completed successfully")
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ {description} failed:")
        logger.error(f"Exit code: {e.returncode}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        return None

def find_latest_files(pattern):
    """Find the most recent files matching pattern"""
    files = glob.glob(pattern)
    if files:
        return max(files, key=lambda x: Path(x).stat().st_mtime)
    return None

def main():
    parser = argparse.ArgumentParser(description="Example training data collection")
    parser.add_argument('--vm-name', type=str, required=True,
                       help='VM name (must match Kepler vm_name)')
    parser.add_argument('--vm-host', type=str, required=True,
                       help='VM IP address or hostname')
    parser.add_argument('--vm-user', type=str, default='root',
                       help='SSH username (default: root)')
    parser.add_argument('--duration', type=int, default=600,
                       help='Collection duration in seconds (default: 600)')
    parser.add_argument('--skip-collection', action='store_true',
                       help='Skip collection, only merge existing data')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_name = f"example_{timestamp}"
    
    logger.info("="*60)
    logger.info(f"TRAINING DATA COLLECTION EXAMPLE")
    logger.info("="*60)
    logger.info(f"VM: {args.vm_name} @ {args.vm_host}")
    logger.info(f"Duration: {args.duration}s")
    logger.info(f"Experiment: {experiment_name}")
    logger.info("="*60)
    
    try:
        # Step 1: Run orchestrated collection (unless skipped)
        if not args.skip_collection:
            logger.info("STEP 1: Running orchestrated data collection")
            
            collection_cmd = [
                "python3", "orchestrate_training_data_collection.py",
                "--vm-name", args.vm_name,
                "--vm-host", args.vm_host,
                "--vm-user", args.vm_user,
                "--duration", str(args.duration),
                "--workloads", "cycle,cpu_intensive",
                "--cpu-intensive-duration", "120",
                "--output-prefix", experiment_name,
                "--interval", "1.0"
            ]
            
            if args.verbose:
                collection_cmd.append("--verbose")
            
            result = run_command(collection_cmd, "Orchestrated data collection")
            if result is None:
                logger.error("Collection failed, aborting")
                sys.exit(1)
        else:
            logger.info("STEP 1: Skipping collection (--skip-collection specified)")
        
        # Step 2: Find the generated files
        logger.info("STEP 2: Locating generated data files")
        
        vm_features_pattern = f"data/vm_features_{experiment_name}_*.json"
        bm_power_pattern = f"data/bm_power_{experiment_name}_*.csv"
        
        if args.skip_collection:
            # Look for any recent files if skipping collection
            vm_features_pattern = "data/vm_features_*.json"
            bm_power_pattern = "data/bm_power_*.csv"
        
        vm_features_file = find_latest_files(vm_features_pattern)
        bm_power_file = find_latest_files(bm_power_pattern)
        
        if not vm_features_file:
            logger.error(f"No VM features file found matching: {vm_features_pattern}")
            sys.exit(1)
        
        if not bm_power_file:
            logger.error(f"No baremetal power file found matching: {bm_power_pattern}")
            sys.exit(1)
        
        logger.info(f"✓ Found VM features: {vm_features_file}")
        logger.info(f"✓ Found BM power: {bm_power_file}")
        
        # Step 3: Merge the datasets
        logger.info("STEP 3: Merging datasets")
        
        training_dataset_file = f"data/training_dataset_{experiment_name}.csv"
        
        merge_cmd = [
            "python3", "merge_datasets.py",
            "--vm-features", vm_features_file,
            "--bm-power", bm_power_file,
            "--output", training_dataset_file,
            "--time-tolerance", "0.5",
            "--min-power-threshold", "0.001",
            "--power-zone", "core"
        ]
        
        if args.verbose:
            merge_cmd.append("--verbose")
        
        result = run_command(merge_cmd, "Dataset merge")
        if result is None:
            logger.error("Dataset merge failed")
            sys.exit(1)
        
        # Step 4: Verify the results
        logger.info("STEP 4: Verifying results")
        
        if not Path(training_dataset_file).exists():
            logger.error(f"Training dataset file not created: {training_dataset_file}")
            sys.exit(1)
        
        # Get file sizes and row counts
        vm_size = Path(vm_features_file).stat().st_size / (1024 * 1024)  # MB
        bm_size = Path(bm_power_file).stat().st_size / (1024 * 1024)  # MB
        training_size = Path(training_dataset_file).stat().st_size / (1024 * 1024)  # MB
        
        # Count rows in training dataset
        try:
            with open(training_dataset_file, 'r') as f:
                row_count = sum(1 for line in f) - 1  # Subtract header
        except:
            row_count = "unknown"
        
        # Step 5: Display summary
        logger.info("="*60)
        logger.info("TRAINING DATA COLLECTION COMPLETED SUCCESSFULLY!")
        logger.info("="*60)
        
        print(f"\nGenerated Files:")
        print(f"  VM Features:      {vm_features_file} ({vm_size:.1f} MB)")
        print(f"  BM Power:         {bm_power_file} ({bm_size:.1f} MB)")
        print(f"  Training Dataset: {training_dataset_file} ({training_size:.1f} MB)")
        
        print(f"\nDataset Info:")
        print(f"  Training Samples: {row_count}")
        print(f"  Collection Duration: {args.duration}s")
        print(f"  VM Target: {args.vm_name}")
        
        print(f"\nNext Steps:")
        print(f"  1. Analyze the training dataset:")
        print(f"     python3 -c \"import pandas as pd; df=pd.read_csv('{training_dataset_file}'); print(df.head()); print(df.describe())\"")
        print(f"")
        print(f"  2. Train a model:")
        print(f"     # Load {training_dataset_file} in your ML framework")
        print(f"     # Use all columns except 'power_watts' as features")
        print(f"     # Use 'power_watts' as the target variable")
        print(f"")
        print(f"  3. Check data quality:")
        print(f"     # Review the merge statistics in the output above")
        print(f"     # Ensure good match rate and low time differences")
        
        logger.info("Example completed successfully!")
        
    except KeyboardInterrupt:
        logger.info("Example interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Example failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()