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
  and take `--game`. Don't hardcode a game's addresses in a tool.
- **The opcode *meanings* (`data/vm_opcode_names.toml`) are shared; addresses are not.**
- **Ground hardware claims in the SNESdev wiki** (via `snes-decompiler`); don't write
  register/PPU/DMA behavior from memory.
- **ROMs are immutable input, never committed** (`.gitignore`).

## Depends on
`snes-decompiler` (sibling `../snes-decompiler`) — CPU decoder, mapper, header, `snes_regs`.

## Entry point
`docs/engine.md` (architecture) → `docs/koei-nes-vs-snes.md` (comparison) → `tools/`.
Per-title work happens in that title's repo (e.g. `rot3k2-snes-decompiler`), importing these tools.
