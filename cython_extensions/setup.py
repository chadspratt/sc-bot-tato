"""
Setup script to compile Cython extensions for cython_extensions package.

Usage:
    python cython_extensions/setup.py build_ext --inplace

    Must be run from the parent directory (the bot root) so that
    ``build_ext --inplace`` places .so/.pyd files into cython_extensions/
    and Cython resolves ``cimport cython_extensions.X`` correctly.

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
# Must run from the parent directory so build_ext --inplace puts .so files
# into cython_extensions/ and Cython can resolve package-level .pxd files.
PARENT = HERE.parent
os.chdir(PARENT)

PKG = "cython_extensions"

# Define extensions — full package names are required so Cython generates
# __pyx_capi__ exports for cimported symbols (cpdef functions, public cdef vars).
extensions = [
    # Bootstrap - must be first, has no dependencies
    Extension(
        f"{PKG}.bootstrap",
        sources=[str(HERE / "bootstrap.pyx")],
        language="c",
    ),
    # Ability mapping - no numpy dependency
    Extension(
        f"{PKG}.ability_mapping",
        sources=[str(HERE / "ability_mapping.pyx")],
        language="c",
    ),
    # Geometry - no numpy dependency
    Extension(
        f"{PKG}.geometry",
        sources=[str(HERE / "geometry.pyx")],
        language="c",
    ),
    # General utils - needs numpy
    Extension(
        f"{PKG}.general_utils",
        sources=[str(HERE / "general_utils.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    # Turn rate - no numpy dependency
    Extension(
        f"{PKG}.turn_rate",
        sources=[str(HERE / "turn_rate.pyx")],
        language="c",
    ),
    # Unit data - no numpy dependency
    Extension(
        f"{PKG}.unit_data",
        sources=[str(HERE / "unit_data.pyx")],
        language="c",
    ),
    # Ability order tracker
    Extension(
        f"{PKG}.ability_order_tracker",
        sources=[str(HERE / "ability_order_tracker.pyx")],
        language="c",
    ),
    # Numpy-dependent extensions
    Extension(
        f"{PKG}.numpy_helper",
        sources=[str(HERE / "numpy_helper.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        f"{PKG}.combat_utils",
        sources=[str(HERE / "combat_utils.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        f"{PKG}.units_utils",
        sources=[str(HERE / "units_utils.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        f"{PKG}.dijkstra",
        sources=[str(HERE / "dijkstra.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        f"{PKG}.map_analysis",
        sources=[str(HERE / "map_analysis.pyx")],
        include_dirs=[np.get_include()],
        language="c",
    ),
    Extension(
        f"{PKG}.placement_solver",
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
        packages=[PKG],
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
            include_path=[str(HERE.parent)],
        ),
        zip_safe=False,
    )
