"""Wi-Fi Settings row: upstream opi5plus_wipe_mobilegestalt() (Hange777/UniXNU-opi5plus ecd0df26, patches/xnu/0002-mount-data-volume.patch,
as UniXNU-evb10 does after its Data mount) ported into zzy-staged-system-apps.patch after port-migrate-once.py.
Why (UniXNU docs devices/evb10.md:463): Settings shows the Wi-Fi row only if MobileGestalt's wifi capability is true; under vmm-present it
reads /chosen mac-address-wifi0, and it caches the answer on Data at the first boot. Our Data was rebuilt on 11-25 by migstub-reset (15ec
kernel, no Wi-Fi), so it keeps answering false although FuxiWifi publishes mac-address-wifi0 now.
fuxi change: upstream wipes on every boot; here only with fuxi-mg-wipe=1 (a one-off boot), so daily images never touch the files.
The three paths and the unlink are upstream's, unchanged. Claude 2026-11-28."""
import sys
from pathlib import Path

FN = r'''/* opi5plus_wipe_mobilegestalt (fuxi: only with fuxi-mg-wipe=1): MobileGestalt's caches are dropped, so it reads /chosen and the ADT
 * again (the Wi-Fi capability among them); the files are rewritten on the next query. */
static void
native_fuxi_mg_wipe(proc_t p, user_addr_t scratch)
{
	static const char *const caches[] = {
		"/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist",
		"/private/var/mobile/Library/Preferences/com.apple.MobileGestalt.plist",
		"/private/var/mobile/Library/Preferences/com.apple.mobilegestalt.plist",
	};
	uint32_t enabled = 0;
	if (!PE_parse_boot_argn("fuxi-mg-wipe", &enabled, sizeof(enabled)) || enabled != 1) {
		return;
	}
	for (unsigned i = 0; i < sizeof(caches) / sizeof(caches[0]); ++i) {
		/* The scratch is one 4 KiB page; the mount arguments end below 0xa00. */
		struct unlink_args request = {.path = scratch + 0xa00};
		int32_t result = 0;
		int error = copyout(caches[i], request.path, strlen(caches[i]) + 1);

		if (error == 0) {
			error = unlink(p, &request, &result);
		}
		printf("fuxi mg-wipe: %s -> %d\n", caches[i], error);
	}
}

'''

sys.path.insert(0, str(Path(__file__).parent))
from importlib.util import spec_from_file_location, module_from_spec
_spec = spec_from_file_location('mo', str(Path(__file__).parent / 'port-migrate-once.py'))
_mo = module_from_spec(_spec); _spec.loader.exec_module(_mo)
recount = _mo.recount


def main(patch):
    p = Path(patch); s = p.read_text(encoding='utf-8', errors='surrogateescape')
    if 'native_fuxi_mg_wipe' in s:
        print('mg-wipe: already', p); return
    call_old = '+\tif (!error) native_t970_migrate_once(p, scratch);\n'
    fn_at = ' static int\n native_owner_data_prepare(proc_t p, user_addr_t scratch)\n'
    assert s.count(call_old) == 1, 'mg-wipe: call anchor (run after port-migrate-once.py)'
    assert s.count(fn_at) == 1, 'mg-wipe: function anchor changed'
    s = s.replace(call_old, call_old + '+\tif (!error) native_fuxi_mg_wipe(p, scratch);\n')
    s = s.replace(fn_at, ''.join('+' + l + '\n' for l in FN.rstrip('\n').split('\n')) + '+\n' + fn_at)
    p.write_text(recount(s), encoding='utf-8', errors='surrogateescape')
    print('mg-wipe: patched', p)


if __name__ == '__main__':
    main(sys.argv[1])
