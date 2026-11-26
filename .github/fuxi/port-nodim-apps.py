#!/usr/bin/env python3
"""#10 lock screen no dim and #11 system apps, from our own verified 11-18 kernels, moved from binary patches into source
(Claude 2026-11-21; plan checked by Gemini, dump/gemini/port-10-11.md).

  nodim BootWatchdogPolicy.c...
    boot2-nodim (sb-nodim.sh, 11-18): managed /private/var/Managed Preferences/mobile/com.apple.springboard.plist with
    SBDisableAutoDim, SBDontDimOrLockOnAC, SBDisableIdleSleep true (upstream guide/skip-setup.md --no-auto-dim). Written like 968's
    fuxi_boot_dictation_off (same directory, same open/write/fchown/close), every boot, with sheng-data-skel=1; sheng-nodim=0 skips it.
    Needs the 968 dictation port first (anchors on its call).
  apps PATCH
    zzy-staged-system-apps.patch (53f): 1) apps-wp3's call swap, native_staged_apps_prepare before native_gpu_addon_prepare, so the
    Data copy exists when the views mount; 2) apps-union's /private/var/staged_system_apps over /Applications (same lower/upper check
    entries as build-apps-union.sh), through the patch's own native_gpu_addon_mount, with sheng-staged-apps=1 only. Hunk counts are
    recomputed (the workflow's SA printf step edits the same file). The lsd fixup (apps-wp8) is an image-side text fixup."""
import re, sys
from pathlib import Path

NODIM = r'''// fuxi 2026-11-21 (#10, boot2-nodim 11-18 in source): without a working idle timer the display goes off ~30 s after SpringBoard
// starts and the system sleeps (upstream guide/skip-setup.md --no-auto-dim). Managed SpringBoard preferences, rewritten every boot.
static const char nodim_body[]=
  "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
  "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
  "<plist version=\"1.0\"><dict>"
  "<key>SBDisableAutoDim</key><true/>"
  "<key>SBDontDimOrLockOnAC</key><true/>"
  "<key>SBDisableIdleSleep</key><true/>"
  "</dict></plist>\n";
static int fuxi_boot_nodim(proc_t p,uint64_t scratch) {
 int on=0,nodim=1;int32_t result=0;
 if(!PE_parse_boot_argn("sheng-data-skel",&on,sizeof(on)) || on!=1)return 0;
 PE_parse_boot_argn("sheng-nodim",&nodim,sizeof(nodim));
 if(nodim!=1){printf("fuxi nodim: skipped\n");return 0;}
 static const char path[]="/private/var/Managed Preferences/mobile/com.apple.springboard.plist";
 int error=copyout(path,scratch,sizeof(path));
 int fd=-1;
 if(!error){struct open_args op={.path=scratch,.flags=O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,.mode=0644};error=open(p,&op,&result);if(!error)fd=result;}
 if(!error)error=copyout(nodim_body,scratch+0x200,sizeof(nodim_body)-1);
 if(!error){struct write_args wr={.fd=fd,.cbuf=scratch+0x200,.nbyte=sizeof(nodim_body)-1};user_ssize_t n=0;error=write(p,&wr,&n);
  if(!error && n!=(user_ssize_t)(sizeof(nodim_body)-1))error=EIO;}
 if(!error){struct fchown_args own={.fd=fd,.uid=0,.gid=0};error=fchown(p,&own,&result);}
 if(fd>=0){struct close_args cl={.fd=fd};int ce=sys_close(p,&cl,&result);if(!error)error=ce;}
 printf("fuxi nodim: managed springboard rc %d\n",error);
 return error;
}

'''

def nodim(files):
    anchor = '// One comma-separated label at *c into the policy'
    call_at = ' (void)fuxi_boot_dictation_off(p,scratch);\n'
    n, seen = 0, set()
    for f in map(Path, files):
        if not f.is_file(): continue
        r = f.resolve()
        if r in seen: continue
        seen.add(r); s = r.read_text()
        if 'fuxi_boot_nodim' in s: print('nodim: already', f); n += 1; continue
        if s.count(anchor) != 1 or s.count(call_at) != 1: print('nodim: anchors not found', f); continue
        s = s.replace(anchor, NODIM + anchor, 1).replace(call_at, call_at + ' (void)fuxi_boot_nodim(p,scratch);\n', 1)
        r.write_text(s); n += 1; print('nodim: added', f)
    assert n, 'no BootWatchdogPolicy.c took nodim'

UNION = [
    '/* fuxi 2026-11-21 (#11, apps-union 11-18 in source): the Data copy over /Applications as a read-only union, through the same',
    ' * native_gpu_addon_mount the addon views use, so the 33 staged apps show as built-in apps. With sheng-staged-apps=1 only. */',
    'volatile int native_staged_apps_union_stage = 0;',
    'volatile int native_staged_apps_union_status = -1;',
    'static void',
    'native_staged_apps_union(proc_t p, user_addr_t scratch)',
    '{',
    '\tuint32_t enabled = 0;',
    '\tif (!PE_parse_boot_argn("sheng-staged-apps", &enabled, sizeof(enabled)) || enabled != 1) {',
    '\t\treturn;',
    '\t}',
    '\t/* fuxi 2026-11-26 (#12 widgets, Gemini): fuxi-staged-union=0 leaves /Applications alone for the one migration boot, so',
    '\t * SystemAppMigrator sees the 33 apps as not installed and has installd install them (and register their appex). */',
    '\tuint32_t union_on = 1;',
    '\tPE_parse_boot_argn("fuxi-staged-union", &union_on, sizeof(union_on));',
    '\tif (union_on != 1) {',
    '\t\tprintf("SAU skipped (fuxi-staged-union=%u)\\n", union_on);',
    '\t\treturn;',
    '\t}',
    '\tstatic const char source[] = "/private/var/staged_system_apps", point[] = "/Applications";',
    '\tnative_gpu_addon_mount(p, scratch, 0xa00, source, sizeof(source), point, sizeof(point),',
    '\t    "/Applications/Preferences.app/Info.plist", "/Applications/Calculator.app",',
    '\t    &native_staged_apps_union_stage, &native_staged_apps_union_status);',
    '\tprintf("SAU %d %d\\n", native_staged_apps_union_stage, native_staged_apps_union_status);',
    '}',
    '']

def recount(text):
    out, lines, i = [], text.split('\n'), 0
    while i < len(lines):
        m = re.match(r'^@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$', lines[i])
        if not m: out.append(lines[i]); i += 1; continue
        j = i + 1; old = new = 0
        while j < len(lines) and not lines[j].startswith(('@@ ', 'diff --git ')):
            l = lines[j]
            if l.startswith('-'): old += 1
            elif l.startswith('+'): new += 1
            elif l.startswith(' ') or l == '': old += 1; new += 1
            j += 1
        # a trailing empty string from the final newline is not a context line
        if j == len(lines) and lines[j - 1] == '': old -= 1; new -= 1
        out.append('@@ -%s,%d +%s,%d @@%s' % (m.group(1), old, m.group(3), new, m.group(5)))
        out.extend(lines[i + 1:j]); i = j
    return '\n'.join(out)

def apps(patch):
    p = Path(patch); s = p.read_text(encoding='utf-8', errors='surrogateescape')
    if 'native_staged_apps_union' in s: print('apps: already', p); return
    swap_old = (' \tif (!error) native_gpu_addon_prepare(p, scratch);\n'
                '+\tif (!error) native_staged_apps_prepare(p, scratch, data_mount);\n')
    swap_new = ('+\tif (!error) native_staged_apps_prepare(p, scratch, data_mount);\n'
                ' \tif (!error) native_gpu_addon_prepare(p, scratch);\n'
                '+\tif (!error) native_staged_apps_union(p, scratch);\n')
    fn_at = '+\tvnode_put(vp);\n+}\n+\n static int\n native_owner_data_prepare(proc_t p, user_addr_t scratch)\n'
    assert s.count(swap_old) == 1, 'apps: call anchor changed'
    assert s.count(fn_at) == 1, 'apps: function anchor changed'
    s = s.replace(swap_old, swap_new, 1)
    s = s.replace(fn_at, '+\tvnode_put(vp);\n+}\n+\n' + ''.join('+' + l + '\n' for l in UNION) + ' static int\n'
                  ' native_owner_data_prepare(proc_t p, user_addr_t scratch)\n', 1)
    s = recount(s)
    p.write_text(s, encoding='utf-8', errors='surrogateescape'); print('apps: call swap + /Applications union ->', p)

if __name__ == '__main__':
    {'nodim': lambda: nodim(sys.argv[2:]), 'apps': lambda: apps(sys.argv[2])}[sys.argv[1]]()
