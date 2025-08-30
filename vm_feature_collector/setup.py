#!/usr/bin/env python3
"""
Setup script for VM Feature Collector
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text() if (this_directory / "README.md").exists() else ""

setup(
    name="vm-feature-collector",
    version="1.0.0",
    description="Virtual Machine Feature Collector for CPU Power Prediction",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Kaiyi Liu",
    author_email="kaiyi@example.com",
    url="https://github.com/sustainable-computing-io/kepler",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.7",
    install_requires=[
        "psutil>=5.8.0",
        "requests>=2.25.0",
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "black>=21.0",
            "flake8>=3.8",
        ],
    },
    entry_points={
        "console_scripts": [
            "vm-feature-collector=vm_feature_collector:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators", 
        "Topic :: System :: Monitoring",
        "Topic :: System :: Hardware",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: POSIX :: Linux",
    ],
    keywords="energy monitoring, cpu power, virtual machines, performance counters",
    project_urls={
        "Bug Reports": "https://github.com/sustainable-computing-io/kepler/issues",
        "Source": "https://github.com/sustainable-computing-io/kepler",
        "Documentation": "https://sustainable-computing.io/kepler/",
    },
)