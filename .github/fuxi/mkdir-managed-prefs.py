#!/usr/bin/env python3
"""Ensure /private/var/Managed Preferences and /private/var/Managed Preferences/mobile
exist (root:wheel 0755, EEXIST ignored) before Managed Preferences plist writers run.

Run in CI after `port-nodim-apps.py nodim` on all BootWatchdogPolicy.c files.
"""
import sys
from pathlib import Path

HELPER = r'''// fuxi 2026-11-25: ensure /private/var/Managed Preferences/mobile exists (root:wheel 0755)
// before dictation_prefs / dictation_off / nodim / keyboards / captive write managed plists.
static int fuxi_ensure_managed_prefs_dir(proc_t p, uint64_t scratch) {
 static int ran = 0;
 if (ran) return 0;
 ran = 1;
 static const char *const dirs[] = {
  "/private/var/Managed Preferences",
  "/private/var/Managed Preferences/mobile",
  "/private/var/log",
  "/private/var/log/com.apple.xpc.launchd",
 };
 int32_t res = 0;
 int rcs[4] = {-1, -1, -1, -1};
 for (unsigned i = 0; i < 4; ++i) {
  int err = copyout(dirs[i], scratch, strlen(dirs[i]) + 1);
  if (!err) {
   struct mkdir_args md = {.path = scratch, .mode = 0755};
   err = mkdir(p, &md, &res);
   if (err == EEXIST) err = 0;
  }
  if (!err) {
   struct lchown_args own = {.path = scratch, .owner = 0, .group = 0};
   err = lchown(p, &own, &res);
  }
  if (!err) {
   struct chmod_args cm = {.path = scratch, .mode = 0755};
   err = chmod(p, &cm, &res);
  }
  rcs[i] = err;
 }
 printf("fuxi mprefs: mkdir rc %d %d log %d %d\n", rcs[0], rcs[1], rcs[2], rcs[3]);
 return rcs[0] ? rcs[0] : rcs[1];
}

'''

NODIM_FN_ANCHOR = 'static int fuxi_boot_nodim(proc_t p,uint64_t scratch) {\n'
NODIM_PATH_ANCHOR = ' static const char path[]="/private/var/Managed Preferences/mobile/com.apple.springboard.plist";\n'
POLICY_CALL_ANCHORS = (
    ' (void)fuxi_boot_dictation_prefs(p,scratch);\n',
    ' (void)fuxi_boot_dictation_off(p,scratch);\n',
)
CALL_LINE = ' (void)fuxi_ensure_managed_prefs_dir(p,scratch);\n'


def patch_file(p: Path) -> bool:
    if not p.is_file():
        return False
    s = p.read_text(encoding='utf-8', errors='surrogateescape')
    if 'fuxi_ensure_managed_prefs_dir' in s:
        print('mkdir-managed-prefs: already', p)
        return True
    assert s.count(NODIM_FN_ANCHOR) == 1, f'NODIM_FN_ANCHOR missing/ambiguous in {p}'
    assert s.count(NODIM_PATH_ANCHOR) == 1, f'NODIM_PATH_ANCHOR missing/ambiguous in {p}'

    s = s.replace(NODIM_FN_ANCHOR, HELPER + NODIM_FN_ANCHOR, 1)
    s = s.replace(NODIM_PATH_ANCHOR, CALL_LINE + NODIM_PATH_ANCHOR, 1)

    policy_anchor = next((a for a in POLICY_CALL_ANCHORS if s.count(a) == 1), None)
    assert policy_anchor is not None, f'POLICY_CALL_ANCHOR missing in {p}'
    s = s.replace(policy_anchor, CALL_LINE + policy_anchor, 1)

    p.write_text(s, encoding='utf-8', errors='surrogateescape')
    print('mkdir-managed-prefs: added', p)
    return True


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: mkdir-managed-prefs.py <BootWatchdogPolicy.c> [...]')
    n, seen = 0, set()
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.is_file():
            continue
        r = p.resolve()
        if r in seen:
            continue
        seen.add(r)
        if patch_file(p):
            n += 1
    assert n, 'no BootWatchdogPolicy.c patched'


if __name__ == '__main__':
    main()
