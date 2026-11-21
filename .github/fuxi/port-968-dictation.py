#!/usr/bin/env python3
"""Kerfand 968a7c6 keyboard-lag fix and wallpaper protection-class patch onto 53f, verbatim (Claude 2026-11-21; found by Gemini).

  dictation BootWatchdogPolicy.c...
    968's device/package/BootWatchdogPolicy.c lines 120-209: dictation_body, fuxi_same_bytes, fuxi_boot_dictation_cleanup() (removes the
    managed DictationLanguagesEnabled plists an earlier experiment wrote) and fuxi_boot_dictation_off() (managed
    com.apple.assistant.support.plist with "Dictation Enabled" and "Assistant Enabled" false: UIKeyboardInputMode stops asking for
    dictation availability, the updateEnabledDictationLanguages loop that held the app's main thread at 100 % while typing). Both run
    with sheng-data-skel=1; dictation-off is on by default, sheng-dictation-off=0 skips it. 968 calls the cleanup through
    fuxi_boot_dictation_prefs() (whose old write is opt-in only, sheng-dictation-prefs=1); here the cleanup is called directly,
    which is what that function does by default. Inserted before append_job; the calls after sheng_boot_keychains().
  protection PATCH_DIR
    968's unixnu/patches/xnu-10063-arm64e/zz-protection-class-none.patch into PATCH_DIR; the workflow's own fuxi-dataprot-none.patch
    step skips itself when this file is present (968's also covers setattrlist in vfs_attrlist.c)."""
import sys, urllib.request
from pathlib import Path

RAW = 'https://raw.githubusercontent.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17/968a7c62fec43e16b84e72822a008bb08ea787df/'

def get(path):
    err = None
    for _ in range(3):
        try: return urllib.request.urlopen(RAW + path, timeout=60).read().decode('utf-8', 'surrogateescape')
        except Exception as e: err = e
    raise SystemExit(f'fetch {path}: {err}')

def dictation(files):
    src = get('device/package/BootWatchdogPolicy.c')
    a = src.index('// With sheng-data-skel=1 (no boot-arg room for a switch of its own)')
    b = src.index('static int fuxi_boot_dictation_prefs(')
    block = src[a:b]
    assert 'fuxi_boot_dictation_cleanup(proc_t p' in block and 'fuxi_boot_dictation_off(proc_t p' in block, 'block'
    anchor = '// One comma-separated label at *c into the policy'
    call_at = ' (void)sheng_boot_keychains(p,scratch);\n'
    calls = (' // Kerfand 968a7c6: fuxi_boot_dictation_prefs() runs the cleanup by default, then dictation off.\n'
             ' (void)fuxi_boot_dictation_cleanup(p,scratch);\n (void)fuxi_boot_dictation_off(p,scratch);\n')
    n, seen = 0, set()
    for f in map(Path, files):
        if not f.is_file(): continue
        r = f.resolve()
        if r in seen: continue
        seen.add(r); s = r.read_text()
        if 'fuxi_boot_dictation_off' in s: print('dictation: already', f); n += 1; continue
        if s.count(anchor) != 1 or s.count(call_at) != 1: print('dictation: anchors not found', f); continue
        s = s.replace(anchor, '// Kerfand 968a7c6 device/package/BootWatchdogPolicy.c:120-209, verbatim.\n' + block + anchor, 1)
        s = s.replace(call_at, call_at + calls, 1)
        r.write_text(s); n += 1; print('dictation: cleanup + off added', f)
    assert n, 'no BootWatchdogPolicy.c took the dictation fix'

def protection(d):
    d = Path(d); d.mkdir(parents=True, exist_ok=True)
    t = get('unixnu/patches/xnu-10063-arm64e/zz-protection-class-none.patch')
    assert 'vfs_attrlist.c' in t and 'kern_descrip.c' in t
    (d / 'zz-protection-class-none.patch').write_text(t, encoding='utf-8', errors='surrogateescape')
    print('protection: 968 zz-protection-class-none.patch ->', d)

if __name__ == '__main__':
    {'dictation': lambda: dictation(sys.argv[2:]), 'protection': lambda: protection(sys.argv[2])}[sys.argv[1]]()
