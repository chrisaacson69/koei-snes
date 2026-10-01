# koei-snes — app-local rules

The shared KOEI SNES engine library (bytecode VM + native kernel + toolchain).
Obeys, outermost first:

1. **Kernel** — user-global `~/.claude/CLAUDE.md`: grounding (never fabricate;
   reuse/convert > rebuild; missing grounding → find it or ask); classify-before-method.
2. **Project SDK** — the vault's `projects/CLAUDE.md`: RE is multi-pass compilation
   backwards; a registry (`games.toml`, the opcode/syscall TOMLs) IS the symbol table;
   findings flow back to the vault.
3. **This file** — KOEI-SNES engine specifics.

## Engine specifics
- **Decode from the target ROM; compare to NES, never derive.** The bytecode engine
  drifts slightly between titles/platforms. Every address + opcode variant is read from
  the ROM being worked; the NES `rot3k2-decompiler` is a *cross-check* that catches drift.
- **All title-specific addresses live in `tools/games.toml`.** Tools are title-agnostic
  and take `--game`. Don't hardcode a game's addresses in a tool. There is **no default
  profile**: selection is `--game` / `$KOEI_SNES_GAME` / the ROM header, and every selection is
  checked against the ROM (`profile.check_rom`) -- never fall back to "the first profile".
- **The opcode *meanings* (`data/vm_opcode_names.toml`) are shared; addresses are not.** That
  file is the ONE source of opcode names, control-flow classes, operand layouts and lift
  templates, read only through `tools/vm_isa.py` — never add an opcode name/set/size table to a
  tool. Operand sizes stay ROM-derived (`vm_opcodes.py`, all handler paths) and `vm_isa.bind()`
  raises on any disagreement with the table: fix the table (with a CHANGELOG line), never the check.
  The `c` lift templates are also the lifter's register model (which op reads / writes regA and
  regC): a template must state every register side effect its handler has -- `bind()` checks the
  templates against the register bytes each handler reads / writes on all paths, and a
  conditional branch's `c` ("A" / "!A") against which regA value makes its handler write the PC.
- **Listings follow control flow, never address order.** A value an instruction receives (a
  syscall id, a regA width) comes from a dataflow over the routine CFG (`vm_lift`), never from the
  instruction that precedes it in the file: a jump can reach it with another value.
- **Ground hardware claims in the SNESdev wiki** (via `snes-decompiler`); don't write
  register/PPU/DMA behavior from memory.
- **ROMs are immutable input, never committed** (`.gitignore`).

## Depends on
`snes-decompiler` (sibling `../snes-decompiler`) — CPU decoder, mapper, header, `snes_regs`.

## Entry point
`docs/engine.md` (architecture) → `docs/koei-nes-vs-snes.md` (comparison) → `tools/`.
Per-title work happens in that title's repo (e.g. `rot3k2-snes-decompiler`), importing these tools.
