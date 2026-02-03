__version__ = "0.13.1"

# bootstrap is the only module which
# can be loaded with default Python-machinery
# because the resulting extension is called `bootstrap`:
from . import bootstrap

# injecting our finders into sys.meta_path
# after that all other submodules can be loaded
bootstrap.bootstrap_cython_submodules()

# Import configuration functions from the safe module
from cython_extensions.type_checking import (
    disable_safe_mode,
    enable_safe_mode,
    get_safe_mode_status,
    is_safe_mode_enabled,
    safe_mode_context,
)

# Import all functions from the safe wrappers module
# These handle the conditional validation internally
from cython_extensions.type_checking.wrappers import *

# __version__ = "0.13.0"

# import importlib.util
# import os
# import sys

# _initialized = False


# def _ensure_initialized():
#     global _initialized
#     if _initialized:
#         return
    
#     # Find and load bootstrap directly without using relative imports
#     # This avoids circular import issues
#     package_dir = os.path.dirname(__file__)
    
#     # Look for compiled bootstrap module
#     bootstrap_module = None
#     for filename in os.listdir(package_dir):
#         if filename.startswith('bootstrap') and (filename.endswith('.pyd') or filename.endswith('.so')):
#             bootstrap_path = os.path.join(package_dir, filename)
#             spec = importlib.util.spec_from_file_location("cython_extensions.bootstrap", bootstrap_path)
#             if spec and spec.loader:
#                 bootstrap_module = importlib.util.module_from_spec(spec)
#                 sys.modules["cython_extensions.bootstrap"] = bootstrap_module
#                 spec.loader.exec_module(bootstrap_module)
#                 break
    
#     if bootstrap_module is None:
#         # Try loading bootstrap.pyx as a regular Python file won't work
#         # Need to compile Cython extensions first
#         raise ImportError(
#             f"No compiled bootstrap module found for your platform in {package_dir}. "
#             f"Found files: {[f for f in os.listdir(package_dir) if f.startswith('bootstrap')]}. "
#             f"You need to compile the Cython extensions for your platform (Windows/Python {sys.version_info.major}.{sys.version_info.minor}). "
#             f"Run: pip install cython && python setup.py build_ext --inplace"
#         )
    
#     # injecting our finders into sys.meta_path
#     # after that all other submodules can be loaded
#     bootstrap_module.bootstrap_cython_submodules()
#     _initialized = True


# # Call initialization immediately
# _ensure_initialized()


# # Lazy imports to avoid circular dependency issues
# def __getattr__(name):
#     # Import configuration functions from the safe module
#     if name in (
#         "disable_safe_mode",
#         "enable_safe_mode",
#         "get_safe_mode_status",
#         "is_safe_mode_enabled",
#         "safe_mode_context",
#     ):
#         from cython_extensions.type_checking import (
#             disable_safe_mode,
#             enable_safe_mode,
#             get_safe_mode_status,
#             is_safe_mode_enabled,
#             safe_mode_context,
#         )
#         return locals()[name]

#     # Import from wrappers module
#     try:
#         from cython_extensions.type_checking import wrappers

#         if hasattr(wrappers, name):
#             return getattr(wrappers, name)
#     except (ImportError, AttributeError):
#         pass

#     raise AttributeError(f"module 'cython_extensions' has no attribute '{name}'")
