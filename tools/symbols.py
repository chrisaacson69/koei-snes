#!/usr/bin/env python3
"""
Symbol layer for the KOEI SNES bytecode tools.

Loads a title's natural-language symbols so the disassembler/walker render addresses
and syscall ids as names:
  - strings.toml  -> {runtime_addr: label}  (e.g. $6D51 -> msg 'threaten_whom')
  - enums.py      -> {syscall_id: name}     (e.g. 0x32 -> 'sys_blit_rect')

    from symbols import Symbols
    S = Symbols("../rot3k2-snes-decompiler/data")
    S.string(0x6D51)   -> "threaten_whom"
    S.syscall(0x32)    -> "sys_blit_rect"
Both files are optional; missing ones just yield no annotations.
"""
import os
import re

_LINE = re.compile(r'(0x[0-9A-Fa-f]+)\s*=\s*"([^"]+)"')


class Symbols:
    def __init__(self, data_dir=None):
        self.strings, self.syscalls = {}, {}
        if data_dir:
            self.load(data_dir)

    def load(self, data_dir):
        sp = os.path.join(data_dir, "strings.toml")
        if os.path.exists(sp):
            for line in open(sp, encoding="utf-8"):
                line = line.split("#", 1)[0]
                for a, name in _LINE.findall(line):
                    self.strings[int(a, 0)] = name
        ep = os.path.join(data_dir, "enums.py")
        if os.path.exists(ep):
            ns = {}
            exec(compile(open(ep, encoding="utf-8").read(), ep, "exec"), ns)
            self.syscalls = ns.get("SYSCALLS", {})

    def string(self, addr):
        return self.strings.get(addr)

    def syscall(self, i):
        return self.syscalls.get(i)
