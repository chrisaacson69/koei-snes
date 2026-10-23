"""listing.py: moved to emu_harness.vm.koei.snes.listing (emu-harness MIGRATION.md row F, SNES half). This file is an alias:
`import listing` gives that module itself, and `py tools/listing.py ...` runs it as before."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emu_harness.vm.koei.snes.listing", run_name="__main__", alter_sys=True)
else:
    sys.modules[__name__] = importlib.import_module("emu_harness.vm.koei.snes.listing")
