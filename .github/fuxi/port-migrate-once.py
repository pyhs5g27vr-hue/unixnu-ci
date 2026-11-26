"""#12 widgets: upstream gts7xlwifi t970-migrate-once (dump/gemini/t970-migrate-once.patch, Gemini 2026-11-26) ported into our
zzy-staged-system-apps.patch after port-nodim-apps.py apps. Once the staged copy is complete, the Data com.apple.migration /
com.apple.DataMigration prefs are moved aside (.t970) once, so the next launchd runs the restore-style migration and
SystemAppMigrator really installs the 33 apps (their widget appex get registered). /private/var/db/.t970-migrate-once marks it done.
fuxi change: gated by fuxi-migrate-once=1..7 so daily images never trigger it. LastSystemVersion is not touched.
  =1: move migration plists once (respects .t970-migrate-once)
  =2: move migration plists ignoring .t970-migrate-once
  =3: move migration + purplebuddy plists aside
  =4: restore purplebuddy plists back from .t970
  =5: move migration + purplebuddy + installd SystemAppState/UninstalledApplications plists aside (logs exists/rc)
  =6: restore purplebuddy plists only (keep newly generated SystemAppState after successful migration)
  =7: full rollback: restore purplebuddy + SystemAppState + UninstalledApplications plists back from .t970"""
import sys
from pathlib import Path

FN = r'''/* gts7xlwifi t970-migrate-once (fuxi: only with fuxi-migrate-once=1..7): install the staged system apps. The copy alone registers
 * no widget extension; only SystemAppMigrator installs them, and it runs only in the first-boot data migration, which the seed
 * skips. Once the copy is complete this moves the migration preferences aside once, so the next launchd runs the migration as
 * after a restore. Counters: [0] stage (1 moved, 2 done before, 4/6/7 restored, -1 no complete copy, -2 marker failed), [1] moved, [2] error. */
volatile int native_t970_migrate[3] = {0, 0, 0};
static const char native_t970_migrate_marker[] = "/private/var/db/.t970-migrate-once";
static void
native_t970_migrate_once(proc_t p, user_addr_t scratch)
{
	static const char *const prefs[6] = {
		"/private/var/mobile/Library/Preferences/com.apple.migration.plist",
		"/private/var/mobile/Library/Preferences/com.apple.DataMigration.plist",
		"/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist",
		"/private/var/mobile/Library/Preferences/com.apple.purplebuddy.notbackedup.plist",
		"/private/var/installd/Library/MobileInstallation/SystemAppState.plist",
		"/private/var/installd/Library/MobileInstallation/UninstalledApplications.plist",
	};
	uint32_t enabled = 0;
	if (!PE_parse_boot_argn("fuxi-migrate-once", &enabled, sizeof(enabled)) || enabled < 1 || enabled > 7) {
		return;
	}
	vfs_context_t ctx = vfs_context_current();
	vnode_t vp = NULLVP;
	/* =3 moves migration+purplebuddy aside; =4 restores purplebuddy; =5 also moves installd SystemAppState/UninstalledApplications
	 * aside (with exists/rc diagnostics); =6 restores purplebuddy only (keeps new state); =7 rolls back purplebuddy+installd plists. */
	const bool back = (enabled == 4 || enabled == 6 || enabled == 7);
	const int first = back ? 2 : 0;
	const int last = (enabled == 5 || enabled == 7) ? 6 : (enabled == 3 || enabled == 4 || enabled == 6) ? 4 : 2;
	int diag_ex[2] = {-1, -1}, diag_rc[2] = {-1, -1};
	if (back) {
		native_t970_migrate[0] = (int)enabled;
		goto move;
	}
	/* fuxi-migrate-once=2/3/5: move the prefs aside again even after the marker (a migration under the union rewrote them). */
	if (enabled == 1 && !vnode_lookup(native_t970_migrate_marker, VNODE_LOOKUP_NOFOLLOW, &vp, ctx)) {
		vnode_put(vp);
		native_t970_migrate[0] = 2;
		goto out;
	}
	if (vnode_lookup(native_staged_apps_marker, VNODE_LOOKUP_NOFOLLOW, &vp, ctx)) {
		native_t970_migrate[0] = -1;
		goto out;
	}
	vnode_put(vp);
move:;
	char to[128];
	for (int i = first; i < last; i++) {
		/* The scratch is one 4 KiB page; the mount arguments end below 0xa00 and the staged-apps copy is finished. */
		struct rename_args request = {.from = scratch + 0xa00, .to = scratch + 0xc00};
		int32_t result = 0;
		snprintf(to, sizeof(to), "%s.t970", prefs[i]);
		const char *src = back ? to : prefs[i];
		const char *dst = back ? prefs[i] : to;
		if (i >= 4) {
			vnode_t probe = NULLVP;
			if (!vnode_lookup(src, VNODE_LOOKUP_NOFOLLOW, &probe, ctx)) {
				vnode_put(probe);
				diag_ex[i - 4] = 1;
			} else {
				diag_ex[i - 4] = 0;
			}
		}
		int error = copyout(src, request.from, strlen(src) + 1);
		if (!error) {
			error = copyout(dst, request.to, strlen(dst) + 1);
		}
		if (!error) {
			error = rename(p, &request, &result);
		}
		if (i >= 4) {
			diag_rc[i - 4] = error;
		}
		if (!error) {
			native_t970_migrate[1]++;
		} else if (error != ENOENT) {
			native_t970_migrate[2] = error;
		}
	}
	if (back) {
		goto out;
	}
	vnode_t marker = NULLVP;
	int error = vnode_open(native_t970_migrate_marker, O_CREAT | O_TRUNC | FWRITE | O_NOFOLLOW, 0644, 0, &marker, ctx);
	if (!error) {
		error = vnode_close(marker, FWRITE, ctx);
	}
	if (error) {
		native_t970_migrate[2] = error;
		native_t970_migrate[0] = -2;
	} else {
		native_t970_migrate[0] = (enabled == 5) ? 5 : 1;
	}
out:
	if (enabled == 5 || enabled == 7) {
		printf("fuxi migrate-once: stage %d moved %d err %d sas=ex%d/rc%d uninst=ex%d/rc%d\n",
		    native_t970_migrate[0], native_t970_migrate[1], native_t970_migrate[2],
		    diag_ex[0], diag_rc[0], diag_ex[1], diag_rc[1]);
	} else {
		printf("fuxi migrate-once: stage %d moved %d err %d\n",
		    native_t970_migrate[0], native_t970_migrate[1], native_t970_migrate[2]);
	}
}

'''


def recount(text):
    """Recompute every hunk header's new-side line count (old side unchanged)."""
    out, lines, i = [], text.split('\n'), 0
    import re
    while i < len(lines):
        m = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$', lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        j, old, new = i + 1, 0, 0
        while j < len(lines) and not lines[j].startswith(('@@', 'diff --git')):
            l = lines[j]
            if l.startswith('+'): new += 1
            elif l.startswith('-'): old += 1
            elif l.startswith(' ') or l == '': old += 1; new += 1
            j += 1
        # a trailing empty string from the final newline is not a context line
        if j == len(lines) and lines[-1] == '': old -= 1; new -= 1
        out.append('@@ -%s,%d +%s,%d @@%s' % (m.group(1), old, m.group(3), new, m.group(5)))
        out.extend(lines[i + 1:j]); i = j
    return '\n'.join(out)


def main(patch):
    p = Path(patch); s = p.read_text(encoding='utf-8', errors='surrogateescape')
    if 'native_t970_migrate_once' in s:
        print('migrate-once: already', p); return
    call_old = '+\tif (!error) native_staged_apps_union(p, scratch);\n'
    fn_at = ' static int\n native_owner_data_prepare(proc_t p, user_addr_t scratch)\n'
    assert s.count(call_old) == 1, 'migrate-once: call anchor (run after port-nodim-apps.py apps)'
    assert s.count(fn_at) == 1, 'migrate-once: function anchor changed'
    s = s.replace(call_old, call_old + '+\tif (!error) native_t970_migrate_once(p, scratch);\n')
    s = s.replace(fn_at, ''.join('+' + l + '\n' for l in FN.rstrip('\n').split('\n')).replace('+\n', '+\n') + '+\n' + fn_at)
    p.write_text(recount(s), encoding='utf-8', errors='surrogateescape')
    print('migrate-once: patched', p)


if __name__ == '__main__':
    main(sys.argv[1])
