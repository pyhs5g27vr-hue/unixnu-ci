#!/usr/bin/env python3
"""Gemini 2026-11-28 (bb10): fuxi-battery-10s.py ROOT... : shorten ShengBattery.cpp fallback refresh timer
kRefreshMs from 60000 ms (60 s) to 10000 ms (10 s) so status-bar battery % stays up to date even when ADSP
does not push frequent PMIC notifications. Usage: fuxi-battery-10s.py ROOT..."""
import pathlib
import sys

OLD = 'kRefreshMs = 60000'
NEW = 'kRefreshMs = 10000'

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('ShengBattery.cpp')):
        s = p.read_text()
        if NEW in s:
            print('battery-10s: already', p)
            n += 1
            continue
        if s.count(OLD) != 1:
            print('battery-10s: skip', p, 'count', s.count(OLD))
            continue
        p.write_text(s.replace(OLD, NEW, 1))
        n += 1
        print('battery-10s:', p)
assert n >= 1, 'no ShengBattery.cpp patched'
