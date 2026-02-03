"""
Setup script to compile Cython extensions for cython_extensions package.

Usage:
    cd bot/cython_extensions
    python setup.py build_ext --inplace

Requirements:
    - Cython
    - numpy
    - A C compiler (Visual Studio Build Tools on Windows)
"""

import os
import sys
from pathlib import Path

import numpy as np
from Cython.Build import cythonize
from setuptools import Extension, setup

# Get the directory containing this setup.py
HERE = Path(__file__).parent.absolute()

# Define extensions
# Note: All modules are built without package prefix since they're in the cython_extensions directory
# The bootstrap finder handles making them accessible as cython_extensions.module_name
extensions = [
    # Bootstrap - must be first, has no dependencies
    Extension(
        "bootstrap",
        sources=[str(HERE / "bootstrap.pyx")],
        language="c",
    ),
    # Ability mapping - no numpy dependency
    Extension(
        "ability_mapping",
        sources=[str(HERE / "ability_mapping.pyx")],
        language="c",
    ),
    # Geometry - no numpy dependency
    Extension(
        "geometry",
        sources=[str(HERE / "geometry.pyx")],
        language="c",
    ),
    # General utils - needs numpy
    Extension(
        "general_utils",
        sources=[str(HERE / "general_utils.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    # Turn rate - no numpy dependency
    Extension(
        "turn_rate",
        sources=[str(HERE / "turn_rate.pyx")],
        language="c",
    ),
    # Unit data - no numpy dependency
    Extension(
        "unit_data",
        sources=[str(HERE / "unit_data.pyx")],
        language="c",
    ),
    # Ability order tracker
    Extension(
        "ability_order_tracker",
        sources=[str(HERE / "ability_order_tracker.pyx")],
        language="c",
    ),
    # Numpy-dependent extensions
    Extension(
        "numpy_helper",
        sources=[str(HERE / "numpy_helper.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        "combat_utils",
        sources=[str(HERE / "combat_utils.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        "units_utils",
        sources=[str(HERE / "units_utils.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        "dijkstra",
        sources=[str(HERE / "dijkstra.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        "map_analysis",
        sources=[str(HERE / "map_analysis.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        "placement_solver",
        sources=[str(HERE / "placement_solver.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
]

# Filter out extensions for files that don't exist
existing_extensions = []
for ext in extensions:
    source_file = Path(ext.sources[0])
    if source_file.exists():
        existing_extensions.append(ext)
    else:
        print(f"Warning: Skipping {ext.name}, source file not found: {source_file}")

if __name__ == "__main__":
    setup(
        name="cython_extensions",
        ext_modules=cythonize(
            existing_extensions,
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,
                "wraparound": False,
                "initializedcheck": False,
                "nonecheck": False,
            },
            annotate=False,  # Set to True to generate HTML annotation files
        ),
        zip_safe=False,
    )
