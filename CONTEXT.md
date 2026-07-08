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
- ✅ Profile mechanism (`games.toml`) — first profile `[rot3k2]`.

## Next
- Enumerate bytecode entry points from the native module trampolines (full module coverage).
- Pin the few medium-confidence opcode variants; render `hostcall` via syscall names.
- Add the next KOEI SNES title's profile and validate the toolchain ports.
