#!/usr/bin/env python3
"""Gemini 2026-11-28 (bb13): fuxi-ppm-bb-only.py ROOT... : set ApplePPM's CPMSSupported property
in coachz_baseband.cpp to an OSArray of [7, 8] (PPM client IDs for baseband) instead of an OSNumber.

Verified in 21H16 CPMS.framework (dyld_shared_cache_arm64e.27):
- 0x1d8481cd4..0x1d8481d08: if CPMSSupported is a CFNumber (OSNumber), ANY non-zero value (even 0x80)
  unconditionally sets gCPMSSupported = 0xffffffff (ALL 32 clients enabled), causing audiomxd
  (CPMS client 5 -> PPM client 9) to register with an empty powerlevels dictionary and assert/crash!
- 0x1d8481d60..0x1d8481df8: if CPMSSupported is a CFArray (OSArray) of CFNumbers, CPMS.framework sets
  gCPMSSupported |= (1u << id) for each id <= 19.
- 0x1d8487360 (CPMSClientIdToPPMClientId): CPMS 1->PPM 8, CPMS 4->PPM 7, CPMS 5 (audiomxd)->PPM 9.
Setting OSArray [7, 8] gives gCPMSSupported = 0x180: CommCenter's sharedCPMSAgent succeeds while
audiomxd (bit 9 = 0) skips CPMS cleanly and never hits 'Empty powerlevels dictionary'.
Usage: fuxi-ppm-bb-only.py ROOT..."""
import pathlib
import sys

OLD1 = '      ppm->setProperty("CPMSSupported", 0xffffffffULL, 32);'
NEW1 = '''      if (OSArray *cpms = OSArray::withCapacity(2)) {  // gemini bb13: OSArray [7,8] -> bitmask 0x180 (excludes audiomxd PPM 9)
        if (OSNumber *n7 = OSNumber::withNumber(7ULL, 32)) { cpms->setObject(n7); n7->release(); }
        if (OSNumber *n8 = OSNumber::withNumber(8ULL, 32)) { cpms->setObject(n8); n8->release(); }
        ppm->setProperty("CPMSSupported", cpms);
        cpms->release();
      }'''
OLD2 = 'CPMSSupported 0xffffffff\\n'
NEW2 = 'CPMSSupported OSArray [7, 8] (baseband only, excludes audiomxd)\\n'

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('coachz_baseband.cpp')):
        s = p.read_text()
        if 'OSArray::withCapacity(2)' in s and 'CPMSSupported' in s:
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
