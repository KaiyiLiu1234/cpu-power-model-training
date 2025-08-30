"""
VM Feature Collector
A tool for collecting virtual machine performance metrics for CPU power prediction.
"""

__version__ = "1.0.0"
__author__ = "Kaiyi Liu"
__email__ = "kaiyi@example.com"

from .vm_feature_collector import VMFeatureCollector, VMFeaturePoint

__all__ = ["VMFeatureCollector", "VMFeaturePoint"]