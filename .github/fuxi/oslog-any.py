#!/usr/bin/env python3
"""oslog-any.py PATCH : Kerfand's zz-btd-oslog-probe.patch -> the process is chosen by boot-arg fuxi-oslog=<name> (exec basename and
p_comm); without the boot-arg it stays bluetoothd as before. In-line replacements only, so every hunk keeps its line count."""
import sys
p = sys.argv[1]; s = open(p).read()
GET = ('static char fo[32]; static int fs; if (!fs) { extern boolean_t PE_parse_boot_argn(const char *, void *, int); '
       'fs = (PE_parse_boot_argn("fuxi-oslog", fo, sizeof(fo) - 1) && fo[0]) ? 2 : 1; }')
rep = [
 ('strncmp(imgp->ip_strings + strlen(EXECUTABLE_KEY), "/usr/sbin/bluetoothd", 21) == 0 &&',
  '({ ' + GET.replace('extern boolean_t PE_parse_boot_argn(const char *, void *, int); ', '') + ' const char *ep = imgp->ip_strings + strlen(EXECUTABLE_KEY); size_t el = strlen(ep), fl = strlen(fo); '
  'fs == 2 ? (el > fl && ep[el - fl - 1] == \'/\' && strcmp(ep + el - fl, fo) == 0) : (strncmp(ep, "/usr/sbin/bluetoothd", 21) == 0); }) &&', 1),
 ('strncmp(p->p_comm, "bluetoothd", 10) != 0',
  '!({ ' + GET + ' strncmp(p->p_comm, fs == 2 ? fo : "bluetoothd", 16) == 0; })', 1),
 ('strncmp(p->p_comm, "bluetoothd", 10) == 0)',
  '({ ' + GET + ' strncmp(p->p_comm, fs == 2 ? fo : "bluetoothd", 16) == 0; }))', 1),
]
for old, new, n in rep:
    assert s.count(old) == n, (old, s.count(old))
    s = s.replace(old, new)
open(p, 'w').write(s)
print('oslog-any: fuxi-oslog=<process> selects the mirrored process (default bluetoothd)')
