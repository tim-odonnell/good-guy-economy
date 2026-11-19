#!/usr/bin/env python3
"""Hermes no_agent entry for the scripted good-guy-economy-refine stage (see econ-scripted.py)."""
import runpy
from pathlib import Path


runpy.run_path(str(Path(__file__).resolve().with_name("econ-scripted.py")), run_name="__main__", init_globals={"FORCED_MODE": "REFINE"})
