"""#12 widgets: upstream gts7xlwifi t970-migrate-once (dump/gemini/t970-migrate-once.patch, Gemini 2026-11-26) ported into our
zzy-staged-system-apps.patch after port-nodim-apps.py apps. Once the staged copy is complete, the Data com.apple.migration /
com.apple.DataMigration prefs are moved aside (.t970) once, so the next launchd runs the restore-style migration and
SystemAppMigrator really installs the 33 apps (their widget appex get registered). /private/var/db/.t970-migrate-once marks it done.
fuxi change: gated by fuxi-migrate-once=1 (=2 ignores the done marker) so daily images never trigger it. LastSystemVersion is not touched."""
import sys
from pathlib import Path

FN = r'''/* gts7xlwifi t970-migrate-once (fuxi: only with fuxi-migrate-once=1): install the staged system apps. The copy alone registers
 * no widget extension; only SystemAppMigrator installs them, and it runs only in the first-boot data migration, which the seed
 * skips. Once the copy is complete this moves the migration preferences aside once, so the next launchd runs the migration as
 * after a restore. Counters: [0] stage (1 moved, 2 done before, -1 no complete copy, -2 marker failed), [1] moved, [2] error. */
volatile int native_t970_migrate[3] = {0, 0, 0};
static const char native_t970_migrate_marker[] = "/private/var/db/.t970-migrate-once";
static void
native_t970_migrate_once(proc_t p, user_addr_t scratch)
{
	static const char *const prefs[2] = {
		"/private/var/mobile/Library/Preferences/com.apple.migration.plist",
		"/private/var/mobile/Library/Preferences/com.apple.DataMigration.plist",
	};
	uint32_t enabled = 0;
	if (!PE_parse_boot_argn("fuxi-migrate-once", &enabled, sizeof(enabled)) || (enabled != 1 && enabled != 2)) {
		return;
	}
	vfs_context_t ctx = vfs_context_current();
	vnode_t vp = NULLVP;
	/* fuxi-migrate-once=2: move the prefs aside again even after the marker (a migration under the union rewrote them). */
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
	char to[128];
	for (int i = 0; i < 2; i++) {
		/* The scratch is one 4 KiB page; the mount arguments end below 0xa00 and the staged-apps copy is finished. */
		struct rename_args request = {.from = scratch + 0xa00, .to = scratch + 0xc00};
		int32_t result = 0;
		snprintf(to, sizeof(to), "%s.t970", prefs[i]);
		int error = copyout(prefs[i], request.from, strlen(prefs[i]) + 1);
		if (!error) {
			error = copyout(to, request.to, strlen(to) + 1);
		}
		if (!error) {
			error = rename(p, &request, &result);
		}
		if (!error) {
			native_t970_migrate[1]++;
		} else if (error != ENOENT) {
			native_t970_migrate[2] = error;
		}
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
		native_t970_migrate[0] = 1;
	}
out:
	printf("fuxi migrate-once: stage %d moved %d err %d\n", native_t970_migrate[0], native_t970_migrate[1], native_t970_migrate[2]);
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
