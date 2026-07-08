# The KOEI SNES engine

The shared engine behind KOEI's SNES strategy titles — a **register-machine bytecode
VM** driven by a native 65C816 kernel. Reversed from *Romance of the Three Kingdoms II
(USA)*; this doc is the title-agnostic architecture (per-title addresses live in
`tools/games.toml`). It is the SNES sibling of the `koei-nes` engine.

## Layers (outermost = hardware)

1. **BIOS / boot** — native, fixed bank `$00`. RESET → native-mode + PPU/DMA/CGRAM/OAM
   init, then load the `root` module into WRAM and enter it.
2. **Resource archive + WRAM overlays** — a named-blob directory (`resource_archive`,
   e.g. `$00:F800`): 16-byte entries `[8-char name][bank][addr][len]`. Blobs (`root`,
   `comroot`=AI, `excsub1-6`, `sdata`=sound, …) are block-copied into WRAM on demand by a
   cross-bank copier that builds a self-modifying `MVN` in RAM. Each module's WRAM base is
   its header `JMP base+3`. Modules share fixed WRAM **overlay slots** (one loaded at a
   time) — the segmented-memory equivalent of MMC5 bank-switching: instead of mapping a
   ROM bank into a window, copy a resource into its slot. `root` is the resident main; the
   rest overlay (see the title's module map).
3. **The ABI** — a `JMP`-trampoline table at `abi_table` (`$00:8000`), the 4 VM services
   the modules call via `JSL`: **run-VM**, **syscall**, **ext-op** ×2.
4. **The bytecode VM** — `interpreter_loop` (`$9A8F`): `LDA [$06]` (PC) → `INC $06` →
   `JMP (primary_table, X)`. 256-entry `primary_table`; opcode `$B7` = prefix →
   `ext_interpreter` → `extended_table` (32-bit math). `invalid_handler` fills unused
   slots (→ ~218 real opcodes).
5. **Syscalls** — `syscall_dispatch` reads the first byte of a 22-byte parameter block
   into a work buffer, then `JSR (syscall_table, X)` — the native hardware/game-state API.

## The VM

Register machine, state in the direct page: `regA=$0A regB=$0C regC=$0E reg32=$12-15`,
frame pointer `$04`, PC `$06:$08`, operand stack via `PHA/PLA`. "Generic C engine":
opcodes are loads/stores over a frame, an operand stack, arithmetic, and calls into
native services. Opcode families (see `data/vm_opcode_names.toml` for the full table):

- `$00-3F` frame-local matrix (load regA / load regC / store regA / push) · `$40-7F` small const
- `$80-90` load/store/push (global + immediate) · `$A0-AB` frame-local byte/word
- arithmetic `add/sub/and/or/xor/mul/div/mod`, unary `neg/not/inc/dec/shl`, compares (→ 0/1)
- `$AE/AF` `sp_adj` (reserve stack = C prologue) · control `jmp/brel/brz/brnz/switch`
- `$AC/E9` `call.n`/`hostcall` (call native routine at operand address) · `$CF` `ret`
- `$B7` → extended 32-bit set (`add32/sub32/mul32/div32/cmp32/…`)

## Tools (this repo; depend on `snes-decompiler` for the CPU + `games.toml` for addresses)

| tool | does |
|------|------|
| `profile.py` | loads a title profile from `games.toml` (all addresses are here) |
| `vm_opcodes.py` | classify handlers → exact operand sizes (via fetch-helper analysis) |
| `vm_disasm.py` | linear bytecode disassembler (named opcodes) |
| `vm_walk.py` | recursive-descent bytecode walker (code-vs-data by reachability) |
| `vm_semantics.py` | fingerprint handlers (reg/stack/ALU) for naming |
| `syscall_probe.py` | fingerprint syscall handlers by hardware touched (via `snes_regs`) |
| `native_floor.py` | walk all native engine code in bank `$00`, report coverage |

## Porting to a new KOEI SNES title

Add a `games.toml` block: find the `$8000` ABI, the interpreter loop + its 256-entry
table, the `$B7` extended table, the syscall table (after the 22-byte param copy), and
the fetch helpers. The opcode *meanings* (`vm_opcode_names.toml`) are shared; only
addresses and any drifted opcode variants change.
