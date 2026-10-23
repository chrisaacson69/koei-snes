"""gen_mlb.py: moved to emu-harness `tools/gen_mlb_koei_snes.py` (MIGRATION.md row F, SNES half: a
label exporter imports the Mesen backend, so it is a tool beside the NES exporter, not part of the
VM package). This file runs it from the sibling emu-harness checkout:

    py -3.14 tools/gen_mlb.py --data <title>/data --out labels.mlb root comroot excsub1 [...]
"""
import runpy
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "emu-harness" / "tools" / "gen_mlb_koei_snes.py"

if __name__ == "__main__":
    sys.argv[0] = str(TOOL)
    runpy.run_path(str(TOOL), run_name="__main__")
