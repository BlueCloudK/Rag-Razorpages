"""Wrapper for the demo benchmark runner.

The canonical script remains at ``AIServices/AiService/run_demo_benchmark.py``
so existing README commands continue to work.
"""

from pathlib import Path
import runpy
import sys


if __name__ == "__main__":
    root_runner = Path(__file__).resolve().parents[1] / "run_demo_benchmark.py"
    sys.path.insert(0, str(root_runner.parent))
    runpy.run_path(str(root_runner), run_name="__main__")
