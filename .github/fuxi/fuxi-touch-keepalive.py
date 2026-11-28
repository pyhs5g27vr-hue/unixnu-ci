#!/usr/bin/env python3
"""Gemini 2026-11-28 (bb10): fuxi-touch-keepalive.py ROOT... : in FuxiTouchProbe.cpp, if no FTM5 touch event
arrives for fuxi-touch-keepalive seconds (default 20 s, 0=off, 0 boot-args bytes) while no finger is down
(native_touch_contacts == 0), re-issue the exact upstream fts_start_sensing(&s->chip) (and fts_reset if that
fails) so a silently stalled ST FTM5 panel recovers within <=20 s instead of staying dead for minutes.
Usage: fuxi-touch-keepalive.py ROOT..."""
import pathlib
import sys

INIT_ANCHOR = '        uint32_t leavesBefore = 0;\n'
INIT_ADD = '''        unsigned keepaliveSec = 20;
        PE_parse_boot_argn("fuxi-touch-keepalive", &keepaliveSec, sizeof keepaliveSec);
        uint32_t lastEv = s->drained;
        uint64_t lastEvMs = nowMs();
'''

LOOP_ANCHOR = '            if (!drain(*s)) break;\n'
LOOP_ADD = '''            if (s->drained != lastEv) {
                lastEv = s->drained;
                lastEvMs = nowMs();
            } else if (keepaliveSec && native_touch_contacts == 0) {
                const uint64_t now = nowMs();
                if (now - lastEvMs >= (uint64_t)keepaliveSec * 1000) {
                    ++s->rearms;
                    s->senseRc = fts_start_sensing(&s->chip);
                    if (s->senseRc) {
                        s->resetRc = fts_reset(&s->chip);
                        s->senseRc = fts_start_sensing(&s->chip);
                    }
                    lastEvMs = nowMs();
                }
            }
'''

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('FuxiTouchProbe.cpp')):
        s = p.read_text()
        if 'fuxi-touch-keepalive' in s:
            print('touch-keepalive: already', p)
            n += 1
            continue
        if s.count(INIT_ANCHOR) != 1 or s.count(LOOP_ANCHOR) != 1:
            print('touch-keepalive: skip', p, s.count(INIT_ANCHOR), s.count(LOOP_ANCHOR))
            continue
        s = s.replace(INIT_ANCHOR, INIT_ANCHOR + INIT_ADD, 1).replace(LOOP_ANCHOR, LOOP_ANCHOR + LOOP_ADD, 1)
        p.write_text(s)
        n += 1
        print('touch-keepalive:', p)
assert n >= 1, 'no FuxiTouchProbe.cpp patched'
