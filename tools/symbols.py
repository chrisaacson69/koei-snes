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
        self.tables, self.table_base = {}, {}      # name->{idx:label}, addr->name
        if data_dir:
            self.load(data_dir)

    def load(self, data_dir):
        self._load_dir(data_dir)
        # `root` is the RESIDENT shared library: overlays (comroot/settei/... at $7xxx+)
        # call root's routines directly by absolute address ($2xxx-$6xxx). Addresses are
        # disjoint, so also load root's symbols so cross-module calls render by name.
        if os.path.basename(os.path.normpath(data_dir)) != "root":
            root_dir = os.path.join(os.path.dirname(os.path.normpath(data_dir)), "root")
            if os.path.isdir(root_dir):
                self._load_dir(root_dir)

    def _load_dir(self, data_dir):
        # strings.toml + routines.toml both map addr -> label (strings/data/routine names)
        for fn in ("strings.toml", "routines.toml", "globals.toml"):
            p = os.path.join(data_dir, fn)
            if os.path.exists(p):
                for line in open(p, encoding="utf-8"):
                    line = line.split("#", 1)[0]
                    for a, name in _LINE.findall(line):
                        self.strings.setdefault(int(a, 0), name)
        ep = os.path.join(data_dir, "enums.py")
        if os.path.exists(ep):
            ns = {}
            exec(compile(open(ep, encoding="utf-8").read(), ep, "exec"), ns)
            if not self.syscalls:
                self.syscalls = ns.get("SYSCALLS", {})
            self.tables.update(ns.get("STRING_TABLES", {}))
            for name, base in ns.get("STRING_TABLE_BASE", {}).items():
                self.table_base[base] = name
                self.strings.setdefault(base, "tbl_" + name)   # base addr -> table name

    def string(self, addr):
        return self.strings.get(addr)

    def syscall(self, i):
        return self.syscalls.get(i)
