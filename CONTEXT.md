# CONTEXT — koei-snes entry point

**What:** the shared KOEI SNES engine library — the reversed register-machine bytecode
VM + native 65C816 kernel, plus the title-agnostic toolchain to decode any KOEI SNES
title. SNES sibling of `koei-nes`. Extracted from the ROTK2-SNES reverse-engineering.

**Where it sits:** sibling of the vault and of `snes-decompiler` / the title repos.
Depends on `snes-decompiler` (CPU/hardware substrate). Title repos (e.g.
`rot3k2-snes-decompiler`) depend on this.

## Read order
1. This file.
2. `docs/engine.md` — the engine architecture (BIOS / resource archive / ABI / VM / syscalls).
3. `docs/koei-nes-vs-snes.md` — what ported vs what was rebuilt vs the NES.
4. `data/vm_opcode_names.toml` — the opcode table (the cornerstone reference).
5. `tools/games.toml` — per-title addresses; `tools/profile.py` loads them.

## State (from the ROTK2 reversal)
- ✅ Native engine fully mapped: bank $00 code = `$800C-$B20A` (rest of bank = data),
  reachable from reset + NMI/IRQ + every VM/syscall entry (`native_floor.py`).
- ✅ Bytecode VM: 256-entry primary + 48 extended tables; 218 real opcodes named
  (frame/load/store/ALU/compares/control/call/ret + 32-bit ext set). Exact operand
  sizes from the fetch-helper family. Disassembler + recursive-descent walker built.
- ✅ Syscall table (69) named to hardware (via `snes_regs`); the 22-byte-param ABI.
- ✅ Profile mechanism (`games.toml`) — profiles `[rot3k2]` and `[gemfire]`.
- ✅ Per-routine native trampoline decoded + made profile-driven
  (`routine_sig`/`routine_body_offset`): each bytecode routine is a 5-byte `JSR <launcher>`
  stub, body at `+5`. One walker handles both titles (fixed ROTK2's offset-0 bug).

## Toolchain (decode → symbol table → layered source)
- `native_floor.py` / `vm_walk.py` / `vm_callgraph.py` — reachability + call-graph walk (→ `data/<mod>/routines.toml`).
- `vm_disasm.py` / `vm_opcodes.py` — the bytecode decoder + operand-size derivation.
- `syscall_probe.py` / `data_walk.py` — syscall naming + string/data recovery.
- **Layered source (the deliverable):** `gen_layers.py <rom> <title-repo>` drives all three layers
  from the ROM's `$00:F800` archive — `gen_native.py` (assembly: native kernel), `gen_source.py`
  (bytecode: per-module `.src`), `vm_lift.py` (C: `.c`; `vm_struct.py` = goto-less). `gen_mlb.py`
  emits Mesen labels. Output lands in the title repo's `src/` (see its `src/README.md`).

## Next
- Add the next KOEI SNES title's profile and validate the toolchain ports (Uncharted Waters is the NES finale; SNES titles TBD).
- Pin the few medium-confidence opcode variants; extend `native.asm` labelling for non-Gemfire titles.
