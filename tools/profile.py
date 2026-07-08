#!/usr/bin/env python3
"""
Load a KOEI SNES title profile from games.toml.

The bytecode VM engine is shared across KOEI SNES titles; only the addresses move.
The engine tools import this to stay title-agnostic:

    from profile import load
    P = load("rot3k2")          # or load() for the first/only profile
    P["primary_table"], P["fetch_helpers"], ...

Python 3.11+ has tomllib; older falls back to a tiny parser for this file's subset.
"""
import os

_GAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games.toml")


def _parse_min(text):
    """Minimal TOML reader for games.toml (tables, int/str/list/inline-table)."""
    import re
    games, cur = {}, None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"\[(\w+)\]$", line)
        if m:
            cur = games.setdefault(m.group(1), {})
            continue
        if cur is None or "=" not in line:
            continue
        k, v = (s.strip() for s in line.split("=", 1))
        cur[k] = _val(v)
    return games


def _val(v):
    import re
    v = v.strip()
    if v.startswith('"'):
        return v.strip('"')
    if v.startswith("{"):                       # inline table (fetch_helpers)
        d = {}
        for pair in v.strip("{} ").split(","):
            if "=" in pair:
                kk, vv = (s.strip() for s in pair.split("=", 1))
                d[_num(kk)] = _num(vv)
        return d
    if v.startswith("["):
        return [_num(x.strip()) for x in v.strip("[] ").split(",") if x.strip()]
    return _num(v)


def _num(s):
    s = s.strip()
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except ValueError:
        return s


def load(game=None):
    with open(_GAMES, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import tomllib
        games = tomllib.loads(text)
        # tomllib keys inline-table hex as strings -> normalize fetch_helpers keys to int
        for g in games.values():
            fh_ = g.get("fetch_helpers")
            if isinstance(fh_, dict):
                g["fetch_helpers"] = {int(k, 0) if isinstance(k, str) else k: v for k, v in fh_.items()}
    except Exception:
        games = _parse_min(text)
    if game:
        return games[game]
    return next(iter(games.values()))
