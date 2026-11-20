#!/usr/bin/env python3
"""fsb v3 diagnostics on the 53f FuxiStatusBar.c (Claude 2026-11-20). DeepSeek's fsb-rebuild-nil.py meant to add an FSB:pc<k><n>
beacon per -_visualProviderClass call and an FSB:rb<k><n> beacon per rebuild, but its anchors are from another revision of the
file and did not match here (only its guard change applied). Same beacons on this file's text, plus whether the provider was nil.
Run after fsb-rebuild-nil.py. Usage: fsb-v3-diag.py <FuxiStatusBar.c> [...]"""
import sys
from pathlib import Path

CHOICE = '    Class chosen = ((Class (*)(id, SEL))gOrigProviderClass[k])(self, cmd);\n'
CHOICE_NEW = CHOICE + (
    '    /* fuxi-direct-3d: count calls (0 = this release never asks -_visualProviderClass) */\n'
    '    {\n'
    '        static unsigned calls[kKinds];\n'
    '        if (++calls[k] <= 24) {char d[32]; snprintf(d, sizeof d, "pc%d%u", k, calls[k]); fsbBeacon(d);}\n'
    '    }\n')
REBUILD = '    ++gRebuilds[k];\n    ((void (*)(id, SEL))objc_msgSend)(bar, sel_registerName("resetVisualProvider"));\n'
REBUILD_NEW = ('    ++gRebuilds[k];\n'
               '    {char d[32]; snprintf(d, sizeof d, "rb%d%d%s", k, gRebuilds[k], provider ? "" : "nil"); fsbBeacon(d);}\n'
               '    ((void (*)(id, SEL))objc_msgSend)(bar, sel_registerName("resetVisualProvider"));\n')

n = 0
for a in sys.argv[1:]:
    p = Path(a)
    if not p.is_file() or p.name != 'FuxiStatusBar.c':
        continue
    s = p.read_text(errors='replace')
    if 'fuxi-direct-3d' in s:
        print('  %s: already' % p); n += 1; continue
    # fsbBeacon comes from sb-avoid-edit.py and is already used by fsb v2 (FSB:nofb), so it is there on the CI copy.
    if s.count(CHOICE) != 1 or s.count(REBUILD) != 1 or 'fsbBeacon(' not in s:
        print('  !! %s: anchors (choice %d, rebuild %d)' % (p, s.count(CHOICE), s.count(REBUILD))); continue
    s = s.replace(CHOICE, CHOICE_NEW, 1).replace(REBUILD, REBUILD_NEW, 1)
    p.write_text(s); n += 1
    print('  %s: FSB:pc/rb beacons added' % p)
print('fsb v3 diag: %d file(s)' % n)
