#!/usr/bin/env python3
"""fuxi-mig-sentinel.py : .github/fuxi-ready anchor patch for device/package/BootWatchdogPolicy.c.

Adds boot-arg `fuxi-mig-sentinel=1` (default 0):
  - When fuxi-mig-sentinel=1: mkdir("/private/var/datamigrator", 0755) + create empty
    "/private/var/datamigrator/migrate" (O_CREAT|O_WRONLY, 0644), logging:
      "fuxi mig sentinel: created rc %d"
  - When fuxi-mig-sentinel=0 (normal / subsequent boot): probe whether the sentinel still exists,
    logging:
      "fuxi mig sentinel: present=%d" (0 proves datamigrator's removeSentinelIfPresent ran).

Usage:
  python3 fuxi-mig-sentinel.py path/to/BootWatchdogPolicy.c          # apply in-place
  python3 fuxi-mig-sentinel.py --check path/to/BootWatchdogPolicy.c  # dry-run verify anchors
"""
from pathlib import Path
import sys

ANCHOR_FUNC = (
    '  printf("fuxi state aside: %s -> %s rc %d\\n", dirs[i], error ? "-" : to, error);\n'
    ' }\n'
    '}\n'
)

ADD_FUNC = (
    '\n'
    '// fuxi 2026-11-26: official DataMigrator sentinel (/private/var/datamigrator/migrate) without touching LastSystemVersion.\n'
    '// fuxi-mig-sentinel=1 creates the sentinel so datamigrator runs on ephemeral-storage=0; =0 probes if it was consumed.\n'
    'static void fuxi_boot_mig_sentinel(proc_t p, uint64_t scratch) {\n'
    ' int want = 0;\n'
    ' PE_parse_boot_argn("fuxi-mig-sentinel", &want, sizeof(want));\n'
    ' static const char dir[] = "/private/var/datamigrator";\n'
    ' static const char file[] = "/private/var/datamigrator/migrate";\n'
    ' int32_t res = 0;\n'
    ' if (want == 1) {\n'
    '  int err = copyout(dir, scratch, sizeof(dir));\n'
    '  if (!err) {\n'
    '   struct mkdir_args mk = {.path = scratch, .mode = 0755};\n'
    '   err = mkdir(p, &mk, &res);\n'
    '   if (err == EEXIST) err = 0;\n'
    '  }\n'
    '  if (!err) err = copyout(file, scratch, sizeof(file));\n'
    '  if (!err) {\n'
    '   struct open_args op = {.path = scratch, .flags = O_CREAT | O_WRONLY | O_NOFOLLOW, .mode = 0644};\n'
    '   err = open(p, &op, &res);\n'
    '   if (!err) {\n'
    '    struct close_args cl = {.fd = res};\n'
    '    (void)sys_close(p, &cl, &res);\n'
    '   }\n'
    '  }\n'
    '  printf("fuxi mig sentinel: created rc %d\\n", err);\n'
    '  return;\n'
    ' }\n'
    ' int present = 0;\n'
    ' if (!copyout(file, scratch, sizeof(file))) {\n'
    '  struct open_args op = {.path = scratch, .flags = O_RDONLY | O_NOFOLLOW, .mode = 0};\n'
    '  if (!open(p, &op, &res)) {\n'
    '   present = 1;\n'
    '   struct close_args cl = {.fd = res};\n'
    '   (void)sys_close(p, &cl, &res);\n'
    '  }\n'
    ' }\n'
    ' printf("fuxi mig sentinel: present=%d\\n", present);\n'
    '}\n'
)

ANCHOR_CALL = ' fuxi_boot_state_aside(p,scratch);\n'
ADD_CALL = ' fuxi_boot_mig_sentinel(p,scratch);\n'


def main():
    args = sys.argv[1:]
    check_only = False
    if '--check' in args:
        check_only = True
        args.remove('--check')
    if len(args) != 1:
        sys.exit('usage: fuxi-mig-sentinel.py [--check] path/to/BootWatchdogPolicy.c')
    p = Path(args[0])
    s = p.read_text()
    c1 = s.count(ANCHOR_FUNC)
    c2 = s.count(ANCHOR_CALL)
    assert c1 == 1, f'ANCHOR_FUNC count={c1} in {p}'
    assert c2 == 1, f'ANCHOR_CALL count={c2} in {p}'
    s = s.replace(ANCHOR_FUNC, ANCHOR_FUNC + ADD_FUNC, 1)
    s = s.replace(ANCHOR_CALL, ANCHOR_CALL + ADD_CALL, 1)
    if check_only:
        print(f'OK [--check] {p} (2/2 anchors count==1)')
    else:
        p.write_text(s)
        print(f'PATCHED {p} (fuxi-mig-sentinel=1 added)')


if __name__ == '__main__':
    main()
