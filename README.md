# koei-snes

The shared **KOEI SNES engine** library — the reversed bytecode VM + native kernel
behind KOEI's SNES strategy titles, and the toolchain to decode any of them. The SNES
sibling of [`koei-nes`](https://github.com/chrisaacson69/koei-nes).

The engine (a register-machine bytecode VM over a native 65C816 kernel, with a
resource-archive loader and a 22-byte-param-block syscall ABI) is shared across titles;
only addresses move. Per-title addresses live in `tools/games.toml`; the tools take
`--game <name>`.

- **Architecture:** [`docs/engine.md`](docs/engine.md)
- **NES vs SNES comparison:** [`docs/koei-nes-vs-snes.md`](docs/koei-nes-vs-snes.md)
- **Opcode reference:** [`data/vm_opcode_names.toml`](data/vm_opcode_names.toml) (218 primary + 47 extended)

## Dependencies
- **`snes-decompiler`** (sibling `../snes-decompiler`) — the CPU/hardware substrate
  (65C816 disassembler, LoROM/HiROM mapper, header parser, SNES register map).

## Tools (`tools/`, `py -3`)
`profile.py` (games.toml loader) · `vm_opcodes.py` (handler classify → exact operand
sizes) · `vm_disasm.py` (bytecode disassembler) · `vm_walk.py` (recursive-descent
code/data walker) · `vm_semantics.py` (handler fingerprints) · `syscall_probe.py`
(syscall→hardware fingerprints) · `native_floor.py` (native coverage / completeness).

```
py -3 tools/vm_disasm.py   <rom> --start 01:8008 --base 7E:2008 --game rot3k2
py -3 tools/native_floor.py <rom> --game rot3k2 --gaps
```

## Titles
- **rot3k2** — Romance of the Three Kingdoms II (USA). First target; profile in
  `games.toml`. Title repo: `rot3k2-snes-decompiler` (ROM, syscall names, record schemas).

*ROMs are never committed.*
