#!/usr/bin/env python3
"""
Dataset Merger for VM CPU Power Training

Merges VM feature data with baremetal power data based on timestamps to create
training datasets for VM CPU power prediction models.

This script:
1. Loads VM feature data (JSON) and baremetal power data (CSV)
2. Aligns data points by timestamp using configurable tolerance
3. Combines features with corresponding power labels
4. Handles missing data and provides data quality statistics
5. Outputs merged training data in multiple formats (CSV, JSON, pandas-friendly)

Usage:
    # Basic merge
    python3 merge_datasets.py \
        --vm-features data/vm_features_training_20241207.json \
        --bm-power data/bm_power_training_20241207.csv \
        --output data/training_dataset_20241207.csv
    
    # Advanced merge with custom tolerance and filtering
    python3 merge_datasets.py \
        --vm-features data/vm_features.json \
        --bm-power data/bm_power.csv \
        --output data/training_dataset.csv \
        --time-tolerance 0.5 \
        --min-power-threshold 0.001 \
        --power-zone core \
        --verbose
"""

import json
import pandas as pd
import numpy as np
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class MergeStatistics:
    """Statistics about the dataset merge operation"""
    vm_feature_points: int = 0
    bm_power_points: int = 0
    matched_points: int = 0
    unmatched_vm_points: int = 0
    unmatched_bm_points: int = 0
    time_range_vm: Tuple[float, float] = (0.0, 0.0)
    time_range_bm: Tuple[float, float] = (0.0, 0.0)
    time_range_merged: Tuple[float, float] = (0.0, 0.0)
    power_range: Tuple[float, float] = (0.0, 0.0)
    average_time_diff: float = 0.0
    max_time_diff: float = 0.0

class DatasetMerger:
    """Merges VM feature data with baremetal power data for training"""
    
    def __init__(self, time_tolerance: float = 0.2, min_power_threshold: float = 0.0,
                 power_zone: str = "core"):
        """
        Initialize the dataset merger
        
        Args:
            time_tolerance: Maximum time difference in seconds to consider a match
            min_power_threshold: Minimum power value to include (filters noise)
            power_zone: Which power zone to use as label ('core' or 'package')
        """
        self.time_tolerance = time_tolerance
        self.min_power_threshold = min_power_threshold
        self.power_zone = power_zone
        
        self.vm_data: List[Dict] = []
        self.bm_data: List[Dict] = []
        self.merged_data: List[Dict] = []
        self.statistics = MergeStatistics()
        
        logger.info(f"Initialized dataset merger:")
        logger.info(f"  Time tolerance: {time_tolerance}s")
        logger.info(f"  Min power threshold: {min_power_threshold}W")
        logger.info(f"  Power zone: {power_zone}")
    
    def load_vm_features(self, vm_features_file: str) -> bool:
        """Load VM feature data from JSON file"""
        try:
            vm_path = Path(vm_features_file)
            if not vm_path.exists():
                logger.error(f"VM features file not found: {vm_features_file}")
                return False
            
            with open(vm_path, 'r') as f:
                self.vm_data = json.load(f)
            
            if not self.vm_data:
                logger.error("VM features file is empty")
                return False
            
            # Sort by timestamp for efficient merging
            self.vm_data.sort(key=lambda x: x['timestamp'])
            
            self.statistics.vm_feature_points = len(self.vm_data)
            self.statistics.time_range_vm = (
                self.vm_data[0]['timestamp'],
                self.vm_data[-1]['timestamp']
            )
            
            logger.info(f"Loaded {len(self.vm_data)} VM feature points")
            logger.info(f"VM time range: {self.statistics.time_range_vm[1] - self.statistics.time_range_vm[0]:.1f}s")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load VM features: {e}")
            return False
    
    def load_bm_power(self, bm_power_file: str) -> bool:
        """Load baremetal power data from CSV file"""
        try:
            bm_path = Path(bm_power_file)
            if not bm_path.exists():
                logger.error(f"Baremetal power file not found: {bm_power_file}")
                return False
            
            # Load CSV data
            df = pd.read_csv(bm_path)
            
            if df.empty:
                logger.error("Baremetal power file is empty")
                return False
            
            # Convert to list of dictionaries
            self.bm_data = df.to_dict('records')
            
            # Sort by timestamp for efficient merging
            self.bm_data.sort(key=lambda x: x['timestamp'])
            
            self.statistics.bm_power_points = len(self.bm_data)
            self.statistics.time_range_bm = (
                self.bm_data[0]['timestamp'],
                self.bm_data[-1]['timestamp']
            )
            
            logger.info(f"Loaded {len(self.bm_data)} baremetal power points")
            logger.info(f"BM time range: {self.statistics.time_range_bm[1] - self.statistics.time_range_bm[0]:.1f}s")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load baremetal power data: {e}")
            return False
    
    def _find_closest_power_point(self, target_timestamp: float, bm_start_idx: int = 0) -> Tuple[Optional[Dict], int]:
        """Find the closest power measurement to the target timestamp"""
        closest_point = None
        closest_diff = float('inf')
        closest_idx = bm_start_idx
        
        # Search forward from the starting index
        for i in range(bm_start_idx, len(self.bm_data)):
            power_point = self.bm_data[i]
            time_diff = abs(power_point['timestamp'] - target_timestamp)
            
            if time_diff <= self.time_tolerance and time_diff < closest_diff:
                closest_point = power_point
                closest_diff = time_diff
                closest_idx = i
            elif power_point['timestamp'] > target_timestamp + self.time_tolerance:
                # We've gone too far, stop searching
                break
        
        return closest_point, closest_idx
    
    def _get_power_label(self, power_point: Dict) -> float:
        """Extract the appropriate power label based on zone selection"""
        if self.power_zone == "core":
            return power_point.get('total_cpu_watts_core', 0.0)
        elif self.power_zone == "package":
            return power_point.get('total_cpu_watts_package', 0.0)
        else:
            # Default to core if unknown zone
            logger.warning(f"Unknown power zone '{self.power_zone}', using core")
            return power_point.get('total_cpu_watts_core', 0.0)
    
    def merge_datasets(self) -> bool:
        """Merge VM features with baremetal power data based on timestamps"""
        if not self.vm_data or not self.bm_data:
            logger.error("Both VM features and baremetal power data must be loaded")
            return False
        
        logger.info("Starting dataset merge...")
        
        matched_count = 0
        time_diffs = []
        power_values = []
        bm_search_start = 0  # Optimization: start search from last matched index
        
        for i, vm_point in enumerate(self.vm_data):
            vm_timestamp = vm_point['timestamp']
            
            # Find closest power measurement
            power_point, search_idx = self._find_closest_power_point(vm_timestamp, bm_search_start)
            
            if power_point is not None:
                power_value = self._get_power_label(power_point)
                
                # Apply power threshold filter
                if power_value >= self.min_power_threshold:
                    # Create merged data point
                    merged_point = vm_point.copy()  # Start with all VM features
                    
                    # Add power labels
                    merged_point['power_watts'] = power_value
                    merged_point['power_zone'] = self.power_zone
                    merged_point['bm_timestamp'] = power_point['timestamp']
                    merged_point['time_diff'] = abs(vm_timestamp - power_point['timestamp'])
                    
                    # Add additional power metadata
                    merged_point['vm_count'] = power_point.get('vm_count', 1)
                    merged_point['bm_collection_interval'] = power_point.get('collection_interval', 0.1)
                    
                    self.merged_data.append(merged_point)
                    
                    # Update statistics
                    matched_count += 1
                    time_diffs.append(merged_point['time_diff'])
                    power_values.append(power_value)
                    
                    # Update search start position for efficiency
                    bm_search_start = max(0, search_idx - 1)
                else:
                    logger.debug(f"Filtered out low power value: {power_value:.6f}W < {self.min_power_threshold}W")
            
            # Progress logging
            if (i + 1) % 100 == 0:
                logger.info(f"Processed {i + 1}/{len(self.vm_data)} VM points, {matched_count} matches")
        
        # Update statistics
        self.statistics.matched_points = matched_count
        self.statistics.unmatched_vm_points = len(self.vm_data) - matched_count
        self.statistics.unmatched_bm_points = len(self.bm_data)  # Approximation
        
        if time_diffs:
            self.statistics.average_time_diff = np.mean(time_diffs)
            self.statistics.max_time_diff = np.max(time_diffs)
        
        if power_values:
            self.statistics.power_range = (np.min(power_values), np.max(power_values))
        
        if self.merged_data:
            merged_timestamps = [p['timestamp'] for p in self.merged_data]
            self.statistics.time_range_merged = (min(merged_timestamps), max(merged_timestamps))
        
        logger.info(f"Dataset merge completed: {matched_count} matched points out of {len(self.vm_data)} VM points")
        
        return matched_count > 0
    
    def save_merged_dataset(self, output_file: str, include_metadata: bool = True) -> bool:
        """Save merged dataset to file"""
        if not self.merged_data:
            logger.error("No merged data to save")
            return False
        
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if output_file.endswith('.json'):
                self._save_as_json(output_path, include_metadata)
            elif output_file.endswith('.csv'):
                self._save_as_csv(output_path, include_metadata)
            else:
                # Default to CSV
                csv_path = output_path.with_suffix('.csv')
                self._save_as_csv(csv_path, include_metadata)
                
                # Also save JSON version
                json_path = output_path.with_suffix('.json')
                self._save_as_json(json_path, include_metadata)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save merged dataset: {e}")
            return False
    
    def _save_as_json(self, output_path: Path, include_metadata: bool) -> None:
        """Save merged dataset as JSON"""
        try:
            output_data = {
                'data': self.merged_data,
                'statistics': self.statistics.__dict__ if include_metadata else None,
                'metadata': {
                    'merge_timestamp': datetime.now().isoformat(),
                    'power_zone': self.power_zone,
                    'time_tolerance': self.time_tolerance,
                    'min_power_threshold': self.min_power_threshold,
                    'total_points': len(self.merged_data)
                } if include_metadata else None
            }
            
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            logger.info(f"Saved {len(self.merged_data)} merged points to JSON: {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to save JSON: {e}")
    
    def _save_as_csv(self, output_path: Path, include_metadata: bool) -> None:
        """Save merged dataset as CSV"""
        try:
            if not self.merged_data:
                return
            
            # Convert to DataFrame for easy CSV export
            df = pd.DataFrame(self.merged_data)
            
            # Reorder columns to put important ones first
            important_cols = ['timestamp', 'timestamp_iso', 'power_watts', 'time_diff']
            feature_cols = [col for col in df.columns if col.startswith(('cpu_', 'memory_', 'disk_', 'network_', 'process_count', 'load_average', 'instructions_', 'cache_', 'branch_', 'sys_'))]
            metadata_cols = [col for col in df.columns if col not in important_cols + feature_cols]
            
            # Reorder columns
            ordered_cols = important_cols + feature_cols + metadata_cols
            ordered_cols = [col for col in ordered_cols if col in df.columns]
            df = df[ordered_cols]
            
            # Save CSV
            df.to_csv(output_path, index=False)
            
            logger.info(f"Saved {len(self.merged_data)} merged points to CSV: {output_path}")
            
            # Save metadata as separate file if requested
            if include_metadata:
                metadata_file = output_path.with_suffix('.metadata.json')
                metadata = {
                    'statistics': self.statistics.__dict__,
                    'merge_info': {
                        'merge_timestamp': datetime.now().isoformat(),
                        'power_zone': self.power_zone,
                        'time_tolerance': self.time_tolerance,
                        'min_power_threshold': self.min_power_threshold,
                        'total_points': len(self.merged_data),
                        'feature_columns': feature_cols,
                        'total_columns': len(df.columns)
                    }
                }
                
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                logger.info(f"Saved metadata to: {metadata_file}")
            
        except Exception as e:
            logger.error(f"Failed to save CSV: {e}")
    
    def print_merge_summary(self) -> None:
        """Print detailed summary of the merge operation"""
        print("\n" + "="*80)
        print("DATASET MERGE SUMMARY")
        print("="*80)
        
        print(f"Input Data:")
        print(f"  VM Feature Points: {self.statistics.vm_feature_points}")
        print(f"  BM Power Points: {self.statistics.bm_power_points}")
        
        print(f"\nTime Ranges:")
        if self.statistics.time_range_vm[0] > 0:
            vm_duration = self.statistics.time_range_vm[1] - self.statistics.time_range_vm[0]
            print(f"  VM Features: {vm_duration:.1f}s duration")
        
        if self.statistics.time_range_bm[0] > 0:
            bm_duration = self.statistics.time_range_bm[1] - self.statistics.time_range_bm[0]
            print(f"  BM Power: {bm_duration:.1f}s duration")
        
        print(f"\nMerge Results:")
        print(f"  Matched Points: {self.statistics.matched_points}")
        print(f"  Unmatched VM Points: {self.statistics.unmatched_vm_points}")
        print(f"  Match Rate: {(self.statistics.matched_points / max(1, self.statistics.vm_feature_points)) * 100:.1f}%")
        
        if self.statistics.matched_points > 0:
            print(f"\nTiming Accuracy:")
            print(f"  Average Time Difference: {self.statistics.average_time_diff:.3f}s")
            print(f"  Maximum Time Difference: {self.statistics.max_time_diff:.3f}s")
            print(f"  Time Tolerance Used: {self.time_tolerance}s")
            
            print(f"\nPower Label Statistics:")
            print(f"  Power Zone: {self.power_zone}")
            print(f"  Power Range: {self.statistics.power_range[0]:.6f}W - {self.statistics.power_range[1]:.6f}W")
            print(f"  Min Power Threshold: {self.min_power_threshold}W")
            
            if self.statistics.time_range_merged[0] > 0:
                merged_duration = self.statistics.time_range_merged[1] - self.statistics.time_range_merged[0]
                print(f"  Merged Data Duration: {merged_duration:.1f}s")
        
        print(f"\nDataset Quality:")
        if self.statistics.matched_points > 0:
            data_quality = (self.statistics.matched_points / max(1, self.statistics.vm_feature_points)) * 100
            if data_quality >= 90:
                quality_rating = "Excellent"
            elif data_quality >= 80:
                quality_rating = "Good"
            elif data_quality >= 60:
                quality_rating = "Fair"
            else:
                quality_rating = "Poor"
            
            print(f"  Quality Rating: {quality_rating} ({data_quality:.1f}% match rate)")
            
            if data_quality < 80:
                print(f"\nRecommendations:")
                if self.statistics.average_time_diff > self.time_tolerance * 0.5:
                    print(f"  - Consider increasing time tolerance (current: {self.time_tolerance}s)")
                if self.statistics.unmatched_vm_points > self.statistics.matched_points * 0.2:
                    print(f"  - Check synchronization between VM and BM collection")
                if self.statistics.power_range[1] < 0.01:
                    print(f"  - Very low power values detected, consider reducing min_power_threshold")

def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Merge VM features with baremetal power data")
    parser.add_argument('--vm-features', type=str, required=True,
                       help='VM features JSON file path')
    parser.add_argument('--bm-power', type=str, required=True,
                       help='Baremetal power CSV file path')
    parser.add_argument('--output', type=str, required=True,
                       help='Output file path for merged dataset')
    parser.add_argument('--time-tolerance', type=float, default=0.2,
                       help='Maximum time difference for matching (seconds, default: 0.2)')
    parser.add_argument('--min-power-threshold', type=float, default=0.0,
                       help='Minimum power value to include (watts, default: 0.0)')
    parser.add_argument('--power-zone', type=str, default='core', choices=['core', 'package'],
                       help='Power zone to use as label (default: core)')
    parser.add_argument('--no-metadata', action='store_true',
                       help='Exclude metadata from output files')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create merger
    merger = DatasetMerger(
        time_tolerance=args.time_tolerance,
        min_power_threshold=args.min_power_threshold,
        power_zone=args.power_zone
    )
    
    try:
        # Load data
        logger.info("Loading VM features...")
        if not merger.load_vm_features(args.vm_features):
            sys.exit(1)
        
        logger.info("Loading baremetal power data...")
        if not merger.load_bm_power(args.bm_power):
            sys.exit(1)
        
        # Merge datasets
        logger.info("Merging datasets...")
        if not merger.merge_datasets():
            logger.error("Dataset merge failed or produced no results")
            sys.exit(1)
        
        # Save merged dataset
        logger.info("Saving merged dataset...")
        if not merger.save_merged_dataset(args.output, include_metadata=not args.no_metadata):
            sys.exit(1)
        
        # Print summary
        merger.print_merge_summary()
        
        logger.info("Dataset merge completed successfully!")
        
    except Exception as e:
        logger.error(f"Dataset merge failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()