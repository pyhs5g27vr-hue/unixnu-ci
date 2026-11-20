#!/usr/bin/env python3
"""fuxi 2026-11-20: XnuPrelink Layout.validate says only "Native __DATA overlaps a retained segment" (968 B13). Print the placement
first: the native segment's range and size, every retained range it overlaps, the free span before the first of them, and how many
bytes over that span it is. No check is relaxed (the upstream docs record the same diagnostics, sheng-dnuyasha 2026-11-15).
Usage: xnuprelink-diag.py <kits/XnuPrelink/fileset_layout.py>"""
import sys
p = sys.argv[1]; s = open(p).read()
if 'fuxi-layout-diag' in s:
    print(p, ': already'); sys.exit(0)
old = ("            if any(begin < e and b < end for b, e in self.occupied + placed):\n"
       "                raise ValueError(f'Native {segment[\"name\"]} overlaps a retained segment')\n")
new = ("            if any(begin < e and b < end for b, e in self.occupied + placed):\n"
       "                # fuxi-layout-diag\n"
       "                hits = sorted((b, e) for b, e in self.occupied + placed if begin < e and b < end)\n"
       "                first = hits[0][0]\n"
       "                print(f'fuxi layout: native {segment[\"name\"]} {begin:#x}-{end:#x} size {end - begin:#x}; '\n"
       "                      f'free before first overlap {max(0, first - begin):#x}; over by {end - first:#x}; '\n"
       "                      f'overlaps {len(hits)}: ' + ', '.join(f'{b:#x}-{e:#x}' for b, e in hits[:8]), flush=True)\n"
       "                for n2, s2 in sorted(self.roots.items(), key=lambda kv: kv[1]['va']):\n"
       "                    print(f'fuxi layout: root {n2} {s2[\"va\"]:#x} size {s2[\"size\"]:#x}', flush=True)\n"
       "                for s3 in self.native.segments:\n"
       "                    print(f'fuxi layout: native seg {s3[\"name\"]} size {s3[\"size\"]:#x}', flush=True)\n"
       "                # 968 B17: the CI shows only the log tail (the Traceback), so the summary rides in the exception text.\n"
       "                raise ValueError(f'Native {segment[\"name\"]} overlaps a retained segment: {begin:#x}-{end:#x} size {end - begin:#x}, '\n"
       "                                 f'free before first overlap {max(0, first - begin):#x}, over by {end - first:#x}, '\n"
       "                                 f'overlaps ' + ', '.join(f'{b:#x}-{e:#x}' for b, e in hits[:6]))\n")
assert s.count(old) == 1, 'validate anchor'
open(p, 'w').write(s.replace(old, new, 1)); print(p, ': layout diagnostics added')
