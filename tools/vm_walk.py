"""vm_walk.py: moved to emu_harness.vm.koei.snes.vm_walk (emu-harness MIGRATION.md row F, SNES half). This file is an alias:
`import vm_walk` gives that module itself, and `py tools/vm_walk.py ...` runs it as before."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emu_harness.vm.koei.snes.vm_walk", run_name="__main__", alter_sys=True)
else:
    sys.modules[__name__] = importlib.import_module("emu_harness.vm.koei.snes.vm_walk")
