#!/usr/bin/env python3
"""Gemini 2026-11-28 (bb9): fuxi-cpufreq-turbo-default.py ROOT... : default gTurbo=1 in CpuFreqProbe.cpp
so A715 reaches 2803 MHz and X3 reaches 3187 MHz (+231 MHz) without spending 22 boot-args bytes on
sheng-cpufreq-turbo=1. Boot-arg sheng-cpufreq-turbo=0 still disables turbo.
Usage: fuxi-cpufreq-turbo-default.py ROOT..."""
import pathlib
import sys

OLD = 'unsigned gTurbo;   // sheng-cpufreq-turbo=1 (fuxi 2026-11-26): turbo LUT rows allowed\n'
NEW = 'unsigned gTurbo = 1;   // sheng-cpufreq-turbo=0 disables; default 1 -> A715 2803 / X3 3187 MHz (gemini 11-28)\n'

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('CpuFreqProbe.cpp')):
        s = p.read_text()
        if 'unsigned gTurbo = 1;' in s:
            print('cpufreq-turbo-default: already', p)
            n += 1
            continue
        if s.count(OLD) != 1:
            print('cpufreq-turbo-default: skip', p, 'count', s.count(OLD))
            continue
        p.write_text(s.replace(OLD, NEW, 1))
        n += 1
        print('cpufreq-turbo-default:', p)
assert n >= 1, 'no CpuFreqProbe.cpp patched'
