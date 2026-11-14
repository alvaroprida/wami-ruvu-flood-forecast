"""Import first: point PROJ/GDAL at the active Python environment, not at another install (e.g. PostgreSQL's) that sets PROJ_LIB globally."""
import os
import sys
import warnings

_prefixes = [sys.prefix, sys.base_prefix]       # a venv's PROJ data lives in its base (conda) environment
_bases = [os.path.join(p, sub) for p in _prefixes for sub in (os.path.join("Library", "share"), "share")]
for base in _bases:
    if os.path.exists(os.path.join(base, "proj", "proj.db")):
        os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"] = os.path.join(base, "proj")
        if os.path.isdir(os.path.join(base, "gdal")):
            os.environ["GDAL_DATA"] = os.path.join(base, "gdal")
        break
for _p in _prefixes:
    _bin = os.path.join(_p, "Library", "bin")
    if os.path.isdir(_bin):
        os.environ["PATH"] = _bin + os.pathsep + os.environ["PATH"]
        os.add_dll_directory(_bin)
warnings.filterwarnings("ignore")
