"""strings_snes.py: moved to emu_harness.vm.koei.snes.strings_snes (emu-harness MIGRATION.md row F, SNES half). This file is an alias:
`import strings_snes` gives that module itself, and `py tools/strings_snes.py ...` runs it as before."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emu_harness.vm.koei.snes.strings_snes", run_name="__main__", alter_sys=True)
else:
    sys.modules[__name__] = importlib.import_module("emu_harness.vm.koei.snes.strings_snes")
