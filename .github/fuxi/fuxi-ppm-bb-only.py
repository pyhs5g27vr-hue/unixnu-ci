#!/usr/bin/env python3
"""Gemini 2026-11-28: fuxi-ppm-bb-only.py ROOT... : narrow ApplePPM's CPMSSupported bitmask in coachz_baseband.cpp
from 0xffffffff (all 32 clients) to 0x80 (bit 7 = CPMSClientIdBaseband only; verified in 21H16 CPMS.framework:
0x1d8481c10 lsr w8, w8, w0; and w0, w8, #1; client 7=baseband, client 8=speaker).
Prevents audiomxd (speaker=bit 8) from opening ApplePPM and asserting 'Empty powerlevels dictionary', so baseband and
audio coexist cleanly. Usage: fuxi-ppm-bb-only.py ROOT..."""
import pathlib
import sys

OLD1 = 'ppm->setProperty("CPMSSupported", 0xffffffffULL, 32);'
NEW1 = 'ppm->setProperty("CPMSSupported", 0x80ULL, 32);  // bit 7 = baseband only (bit 8 = speaker breaks audiomxd)'
OLD2 = 'CPMSSupported 0xffffffff\\n'
NEW2 = 'CPMSSupported 0x80 (baseband only)\\n'

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('coachz_baseband.cpp')):
        s = p.read_text()
        if '0x80ULL' in s and 'CPMSSupported' in s:
            print('ppm-bb-only: already', p)
            n += 1
            continue
        if s.count(OLD1) != 1:
            print('ppm-bb-only: skip', p, 'anchor count', s.count(OLD1))
            continue
        s = s.replace(OLD1, NEW1, 1).replace(OLD2, NEW2, 1)
        p.write_text(s)
        n += 1
        print('ppm-bb-only:', p)
assert n >= 1, 'no coachz_baseband.cpp patched'
