# KOEI's engine: NES vs SNES

The same engine *design* on two machines — decoded independently on each side
(`rot3k2-decompiler` for NES, this line for SNES), then compared. The through-line is a
register-machine bytecode VM with a native kernel and a param-block syscall ABI; the
mechanisms were rebuilt for each machine's hardware.

| aspect | NES (`koei-nes`) | SNES (`koei-snes`) |
|--------|------------------|--------------------|
| CPU | 6502 (8-bit) | 65C816 (16-bit, 24-bit addr) |
| Program delivery | bytecode in **MMC5-switched** banks | **resource archive → WRAM relocation** (no banking) |
| Native kernel | fixed bank `$E000-$FFFF` | fixed bank `$00` (`$800C-$B20A`) |
| Syscall dispatch | **fake-BRK** (`PHP+JMP ($FFFE)`) | **`JSL` into the `$00:8000` ABI table** |
| Syscall param passing | **22-byte param block**, return via pointer | **22-byte param block**, work buffer `$52` |
| Syscall count | ~23-31 | **69** (richer hardware surface) |
| VM model | register machine, DP registers | register machine, DP registers |
| Opcode count | 217-219 | **218** (256 − 38 nop slots) |
| Frame-local ops | `$00-3F` matrix | `$00-3F` matrix |
| Extended prefix | `$B7` → 32-bit-math subtable | `$B7` → 32-bit-math subtable |
| Host-call opcode | `$E9` | `$E9` |
| Graphics API | PPU writes | PPU + **DMA**, Mode 7, byte-plane VRAM |
| Audio | on-CPU APU | mailboxed **SPC700** (queue → `$2140`) |

## What ported (design)
- The **VM instruction set**: frame matrix, stack, ALU, compares-as-booleans, the `$B7`
  extended 32-bit subtable, the `$E9` host-call. Opcode *numbers* line up, not just shapes.
- The **syscall convention**: a 22-byte parameter block selecting a handler from a table.
- The **program/kernel split**: bytecode modules over a native kernel + a stable ABI.

## What was rebuilt (mechanism, forced by hardware)
- **Program delivery**: MMC5 bank-switching (NES has a 16-bit address bus) → a resource
  archive + WRAM relocation (the 65C816 addresses 16 MB directly; WRAM is big enough to
  hold and run a module).
- **Syscall entry**: fake-BRK → `JSL` (the 65C816 has real long call/return).
- **The hardware syscalls themselves**: entirely different silicon (SNES PPU/DMA/Mode 7/
  SPC700 vs NES PPU/APU), so the ~69 SNES syscalls are largely new services.

## Method note
Decoded each SNES handler as native code and **compared** to the NES — never derived
from it. The engine drifts slightly between titles/platforms, so the exact table is
always read from the target ROM; the NES is the cross-check that catches drift, not the
source of truth. The 218-vs-217/219 and per-opcode matches are *confirmations*.
