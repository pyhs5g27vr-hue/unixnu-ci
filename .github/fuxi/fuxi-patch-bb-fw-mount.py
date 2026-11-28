#!/usr/bin/env python3
"""Gemini 2026-11-28: fuxi-patch-bb-fw-mount.py PATCH_FILE... : append the 3 single-copy Mav16 baseband firmware
union-mounts (Kerfand 2a1c720 zz-xpc-manifest-mount.patch, firmware/preboot parts only) DIRECTLY inside
ios17-zaudio-hal-mount.patch (updating its @@ hunk new-count +20).
Why inline instead of a separate zzz-*.patch: build-xnu-4k-baseline.sh runs TWICE (bootstrap + final) and tests
`git apply --reverse --check` on each patch on pass 2; a separate patch inserting into ios17-zaudio-hal-mount's
hunk breaks ios17-zaudio-hal-mount's reverse check on pass 2!"""
import pathlib
import re
import sys

ANCHOR = '+\tprintf("fuxi btd mount: stage %d status %d\\n", btd_stage, btd_status);\n'
ADD_LINES = [
    '+\t/* fuxi baseband firmware mounts (Kerfand 2a1c720 zz-xpc-manifest-mount.patch, firmware/preboot parts only):',
    '+\t * 1) BootControllerLegacy::prepare reads /usr/standalone/firmware/Baseband/Mav16/Info.plist',
    '+\t * 2) capabilities::radio::personalizedFirmwarePath() stats /private/preboot/<boot-manifest-hash>/usr/local/standalone/firmware/Baseband/Mav16',
    '+\t * 3) Mount the single Mav16 bundle over the preboot placeholder so only one copy is needed. */',
    '+\tstatic volatile int fw_stage = 0, fw_status = -1;',
    '+\tstatic const char fw_source[] = "/private/var/ngpu/owner-apps/firmware", fw_point[] = "/usr/standalone/firmware";',
    '+\tnative_gpu_addon_mount(p, scratch, 0xe00, fw_source, sizeof(fw_source), fw_point, sizeof(fw_point),',
    '+\t    "/usr/standalone/firmware", "/usr/standalone/firmware/Baseband/Mav16/Info.plist", &fw_stage, &fw_status);',
    '+\tprintf("fuxi baseband firmware mount: stage %d status %d\\n", fw_stage, fw_status);',
    '+\tstatic volatile int pb_stage = 0, pb_status = -1;',
    '+\tstatic const char pb_source[] = "/private/var/ngpu/p", pb_point[] = "/private/preboot";',
    '+\tnative_gpu_addon_mount(p, scratch, 0xe00, pb_source, sizeof(pb_source), pb_point, sizeof(pb_point),',
    '+\t    "/private/preboot", "/private/preboot/1FBB9ACDD5C306ED7FA7867D859167CAAF78E7F7834A6845CFFC32D023AB5194D6AB82271C70B2822499F6A7B9C31276/usr/local/standalone/firmware/Baseband/Mav16/.fuxi-mount", &pb_stage, &pb_status);',
    '+\tprintf("fuxi preboot firmware mount: stage %d status %d\\n", pb_stage, pb_status);',
    '+\tstatic volatile int pf_stage = 0, pf_status = -1;',
    '+\tstatic const char pf_source[] = "/private/var/ngpu/owner-apps/firmware/Baseband/Mav16",',
    '+\t    pf_point[] = "/private/preboot/1FBB9ACDD5C306ED7FA7867D859167CAAF78E7F7834A6845CFFC32D023AB5194D6AB82271C70B2822499F6A7B9C31276/usr/local/standalone/firmware/Baseband/Mav16";',
    '+\tnative_gpu_addon_mount(p, scratch, 0xe00, pf_source, sizeof(pf_source), pf_point, sizeof(pf_point),',
    '+\t    pf_point, "/private/preboot/1FBB9ACDD5C306ED7FA7867D859167CAAF78E7F7834A6845CFFC32D023AB5194D6AB82271C70B2822499F6A7B9C31276/usr/local/standalone/firmware/Baseband/Mav16/Info.plist", &pf_stage, &pf_status);',
    '+\tprintf("fuxi preboot firmware bundle mount: stage %d status %d\\n", pf_stage, pf_status);',
]
ADD = '\n'.join(ADD_LINES) + '\n'
HUNK_RE = re.compile(r'^(@@ -\d+,\d+ \+\d+,)(\d+)( @@.*)$', re.M)

n = 0
for arg in sys.argv[1:]:
    p = pathlib.Path(arg)
    if not p.is_file():
        continue
    s = p.read_text()
    if 'fuxi preboot firmware bundle mount' in s:
        print('bb-fw-mount-patch: already', p)
        n += 1
        continue
    assert s.count(ANCHOR) == 1, f'{p}: anchor count={s.count(ANCHOR)}'
    # Find the @@ hunk header immediately preceding ANCHOR
    ai = s.index(ANCHOR)
    hunks = [m for m in HUNK_RE.finditer(s) if m.start() < ai]
    assert hunks, f'{p}: no @@ hunk header before anchor'
    hm = hunks[-1]
    old_cnt = int(hm.group(2))
    new_cnt = old_cnt + len(ADD_LINES)
    s = s[:hm.start(2)] + str(new_cnt) + s[hm.end(2):]
    s = s.replace(ANCHOR, ANCHOR + ADD, 1)
    p.write_text(s)
    n += 1
    print(f'bb-fw-mount-patch: {p} (hunk +{old_cnt} -> +{new_cnt})')
assert n >= 1, 'no ios17-zaudio-hal-mount.patch patched'
