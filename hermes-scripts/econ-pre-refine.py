#!/usr/bin/env python3
"""Pre-run context for the good-guy-economy-refine job (see econ-pre.py)."""
import runpy
import sys
from pathlib import Path


runpy.run_path(str(Path(__file__).resolve().with_name("econ-pre.py")), run_name="__main__", init_globals={"FORCED_MODE": "REFINE"})
