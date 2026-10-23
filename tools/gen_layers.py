"""gen_layers.py: moved to emu_harness.vm.koei.snes.gen_layers (emu-harness MIGRATION.md row F, SNES half). This file is an alias:
`import gen_layers` gives that module itself, and `py tools/gen_layers.py ...` runs it as before."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emu_harness.vm.koei.snes.gen_layers", run_name="__main__", alter_sys=True)
else:
    sys.modules[__name__] = importlib.import_module("emu_harness.vm.koei.snes.gen_layers")
