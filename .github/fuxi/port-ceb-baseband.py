#!/usr/bin/env python3
"""Baseband from Kerfand ceb99ca (layout-2026-11-26), verbatim (Claude 2026-11-27; user rule: port, don't rewrite).
ceb99ca ports ljhhkx529's modem bring-up (PAS, RMTFS, TFTP, modem GLINK/QRTR, IPA) and the COACHZ baseband bridge onto the iOS 17
fileset kernel; their evidence (S14c/S19b): USIM ready, 49 QMI services, 22 of 22 baseband services, radio online searching.
Starts only with fuxi-modem=1 (read-only look) / fuxi-modem=15 (bring-up) [+ coachz-baseband=1]; without them nothing runs.
This step, on every tree (device, device-ios17, UniXNU, kerfand) that has the files:
  1. writes ceb99ca's new modem files into each package dir that holds AdspProbe.cpp;
  2. replaces the shared files ceb99ca extended for the modem (AdspProbe, FatVolume, QcomMdt, QcomQrtr, QcomSmem, ShengQrtr)
     and Ath12kWifiLegacy nw_sta.c (g_bss to the heap: fileset __DATA room) with ceb99ca's - only when ours is still f0ae963's;
  3. applies ceb99ca's build-ios17-legacy-display.py hunks for the modem: ath12k_qmi demote_const, the modem C++/C sources in place of
     ModemProbe.cpp, policy_record for the BSD-side sources, __const -> __data for the modem objects, coachz late metaclass;
     NOT taken: QcomDwc3/UsbProbe/FuxiSensorProbe/AppleUSBXDCI_abi (USB/sensors, other work), and FuxiUcsiStubs.c stays (no QcomDwc3);
     ceb99ca's hard-coded /home/xiaomi/.../ld becomes the toolchain's ld;
  4. Ios17LegacyDisplayProbe.cpp: fuxi_modem_probe() -> native_fuxi_modem_probe().
Usage: port-ceb-baseband.py [ROOT...]   (default: device device-ios17 UniXNU kerfand under the cwd)"""
import hashlib, os, sys, urllib.request
from pathlib import Path

CEB = 'ceb99ca55318a17e8da4e2b66ef79c0c84105191'
F0A = 'f0ae963b674c53a9c1fa5836bfcf89d38bbf77c9'
RAW = 'https://raw.githubusercontent.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17/{}/{}'
NEW = ['FuxiAdspFirmware.h', 'FuxiModemAssign.h', 'FuxiModemFirmware.c', 'FuxiModemLowMeta.h', 'FuxiModemPas.h', 'FuxiModemProbe.cpp',
       'FuxiModemRmtfs.cpp', 'FuxiModemRmtfs.h', 'FuxiModemScm.h', 'FuxiModemStubs.c', 'FuxiModemTftp.cpp', 'FuxiModemTftp.h',
       'FuxiRpmhCorner.c', 'FuxiRpmhCorner.h', 'FuxiRscLayout.h', 'ModemGlink.c', 'ModemGlink.h', 'QcomBaseband.h',
       'coachz_baseband.cpp', 'coachz_bb_channels.h', 'coachz_bb_control.h', 'coachz_bb_data.h', 'coachz_bb_esim.h',
       'coachz_bb_nas_probe.h', 'coachz_bb_pdp.cpp', 'coachz_bb_pdp.h', 'coachz_bb_qmux.h', 'coachz_bb_sahara.h', 'coachz_bb_ssctl.h',
       'coachz_bb_uim_probe.h', 'coachz_ipa_qmi.h', 'fuxi_ipa.c', 'fuxi_ipa.h', 'fuxi_modem.c', 'fuxi_rmtfs.h', 'fuxi_servreg.h',
       'fuxi_tftp.h', 'modem_qrtr.c', 'modem_qrtr.h']
SHARED = ['AdspProbe.cpp', 'FatVolume.c', 'FatVolume.h', 'QcomMdt.c', 'QcomMdt.h', 'QcomQrtr.c', 'QcomQrtr.h', 'QcomSmem.c',
          'QcomSmem.h', 'ShengQrtr.c']
LOCAL = os.environ.get('KERFAND_GIT')   # local test: a Kerfand clone instead of raw.githubusercontent.com

_cache = {}
def fetch(commit, path):
    key = (commit, path)
    if key not in _cache:
        if LOCAL:
            import subprocess
            _cache[key] = subprocess.run(['git', '-C', LOCAL, 'show', f'{commit}:{path}'], capture_output=True, check=True).stdout
        else:
            req = urllib.request.Request(RAW.format(commit, path), headers={'User-Agent': 'fuxi-ci'})
            for i in range(4):
                try:
                    with urllib.request.urlopen(req, timeout=60) as r: _cache[key] = r.read(); break
                except Exception as e:
                    if i == 3: raise
                    print('retry', path, e)
    return _cache[key]
md5 = lambda b: hashlib.md5(b).hexdigest()

roots = [Path(a) for a in sys.argv[1:]] or [p for p in (Path('device'), Path('device-ios17'), Path('UniXNU'), Path('kerfand')) if p.is_dir()]
pkgs = sorted({p.parent for r in roots for p in r.rglob('AdspProbe.cpp') if '.git' not in p.parts})
assert pkgs, 'no package dir with AdspProbe.cpp'
for d in pkgs:
    for n in NEW:
        (d / n).write_bytes(fetch(CEB, 'package/' + n))
    for n in SHARED:
        cur = (d / n).read_bytes()
        new = fetch(CEB, 'package/' + n)
        if cur == new: continue
        assert md5(cur) == md5(fetch(F0A, 'device/package/' + n)), f'{d / n} is not f0ae963\'s: not replaced verbatim'
        (d / n).write_bytes(new)
    print(f'baseband: {d}: {len(NEW)} new files, shared files from ceb99ca')

for p in sorted({p for r in roots for p in r.rglob('nw_sta.c') if p.parent.parent.name == 'Ath12kWifiLegacy'}):
    cur, new = p.read_bytes(), fetch(CEB, 'drivers/Ath12kWifiLegacy/src/nw_sta.c')
    if cur != new:
        assert md5(cur) == md5(fetch(F0A, 'device/drivers/Ath12kWifiLegacy/src/nw_sta.c')), f'{p} is not f0ae963\'s'
        p.write_bytes(new)
    print(f'baseband: {p}: g_bss on the heap')

def sub(s, old, new, p, count=1):
    assert s.count(old) == count, (str(p), old[:80], s.count(old))
    return s.replace(old, new)

builds = sorted({p for r in roots for p in r.rglob('build-ios17-legacy-display.py')})
assert builds, 'no build-ios17-legacy-display.py'
for p in builds:
    s = p.read_text()
    if 'FUXI_MODEM_OBJECTS' in s: print(f'baseband: {p}: already'); continue
    s = sub(s, "wifi_module_objs = [demote_const(o) if o.name == 'ath12k_wmi.o' else o for o in wifi_module_objs]\n",
            "# fuxi 2026-11-26: ath12k_qmi too (3 KB), room for the baseband bridge's kalloc_type views\n"
            "wifi_module_objs = [demote_const(o) if o.name in ('ath12k_wmi.o', 'ath12k_qmi.o') else o for o in wifi_module_objs]\n", p)
    s = sub(s, "adsp_objs = []\nfor src in (ROOT / 'kits/sheng/AdspProbe.cpp', ROOT / 'kits/sheng/FuxiAdspFirmware.cpp',\n",
            "\n# fuxi 2026-11-26: the modem port's relocated constant tables (__DATA,__const, 0x230 bytes) put the kernel's __DATA_CONST 0x70 bytes\n"
            "# past a page, and the fileset's __LASTDATA_CONST then met the retained kext data. Those objects keep their tables in __DATA,__data\n"
            "# (writable, which they do not need to be), where __DATA has the room.\n"
            "FUXI_MODEM_OBJECTS = {'FuxiModemProbe', 'FuxiModemRmtfs', 'FuxiModemTftp', 'ModemGlink', 'modem_qrtr', 'fuxi_modem', 'fuxi_ipa',\n"
            "                      'FuxiModemFirmware', 'FuxiRpmhCorner', 'FuxiModemStubs', 'coachz_baseband'}\n"
            "def fuxi_modem_const_to_data(stem, obj):\n"
            "    if stem in FUXI_MODEM_OBJECTS:\n"
            "        # Apple ld64 renames Mach-O sections natively (llvm-objcopy reads the comma in \"__DATA,__const\" as a flag list).\n"
            "        tmp = Path(str(obj) + '.r.o')\n"
            "        import shutil as _sh   # claude 2026-11-27: the toolchain's ld (ceb99ca hard-codes /home/xiaomi/unixnu-linux/CommandLineTools/usr/bin/ld)\n"
            "        run([_sh.which('ld') or 'ld', '-r', '-arch', 'arm64e',\n"
            "             '-rename_section', '__DATA', '__const', '__DATA', '__data', str(obj), '-o', str(tmp)])\n"
            "        tmp.replace(obj)\n"
            "adsp_objs = []\nfor src in (ROOT / 'kits/sheng/AdspProbe.cpp', ROOT / 'kits/sheng/FuxiAdspFirmware.cpp',\n", p)
    s = sub(s, "            # fuxi 2026-11-18: the modem DSP (fuxi-modem=1/2), baseband phase 1\n            ROOT / 'kits/sheng/ModemProbe.cpp',\n",
            "            # fuxi 2026-11-26: ljhhkx529's modem bring-up (PAS, RMTFS, TFTP) in place of ModemProbe.cpp\n"
            "            ROOT / 'kits/sheng/FuxiModemProbe.cpp', ROOT / 'kits/sheng/FuxiModemRmtfs.cpp', ROOT / 'kits/sheng/FuxiModemTftp.cpp',\n"
            "            ROOT / 'kits/sheng/coachz_baseband.cpp',   # fuxi 2026-11-26: baseband stage 3, the CommCenter bridge\n", p)
    s = sub(s, "                   cwd=record['directory'], check=True)\n    if src.stem == 'ShengBattery':\n",
            "                   cwd=record['directory'], check=True)\n    fuxi_modem_const_to_data(src.stem, obj)\n    if src.stem == 'ShengBattery':\n", p)
    s = sub(s, "    if src.stem == 'ShengAudioService':\n",
            "    if src.stem == 'coachz_baseband':\n"
            "        # its metaclasses register late (FuxiModemProbe.cpp calls __GLOBAL__sub_I_coachz_baseband.cpp between pre/postModLoad)\n"
            "        late_obj = OUT / 'coachz_baseband.late.o'\n"
            "        run(['llvm-objcopy', '--remove-section=__DATA,__mod_init_func', '--globalize-symbol=__GLOBAL__sub_I_coachz_baseband.cpp', obj, late_obj])\n"
            "        obj = late_obj\n"
            "    if src.stem == 'ShengAudioService':\n", p)
    # the C loop: only inside it, startup_record -> srec
    a = s.index("'ShengBattmgr.c', 'ShengChargeAuth.c', 'FuxiUcsiStubs.c'):\n")
    b = s.index("print(f'adsp: {len(adsp_objs)} objects')", a)
    seg = s[a:b]
    seg = sub(seg, "'ShengBattmgr.c', 'ShengChargeAuth.c', 'FuxiUcsiStubs.c'):\n",
              "'ShengBattmgr.c', 'ShengChargeAuth.c', 'FuxiUcsiStubs.c',\n"
              "            'ModemGlink.c', 'modem_qrtr.c', 'fuxi_modem.c', 'fuxi_ipa.c', 'FuxiModemFirmware.c', 'FuxiRpmhCorner.c', 'FuxiModemStubs.c'):\n", p)
    seg = sub(seg, "    sargs, scmd, k = startup_record['arguments'], [], 0\n",
              "    # fuxi 2026-11-26: the modem adapter and the firmware reader use BSD's vnode/proc internals: kern_exec.o's command, not startup.o's.\n"
              "    srec = policy_record if src.name in ('fuxi_modem.c', 'fuxi_ipa.c', 'FuxiModemFirmware.c') else startup_record\n"
              "    sargs, scmd, k = srec['arguments'], [], 0\n", p)
    seg = sub(seg, "        if a == startup_record['file']:\n", "        if a == srec['file']:\n", p)
    seg = sub(seg, "    subprocess.run(scmd + ['-mgeneral-regs-only', '-I', str(ROOT / '.cache/xnu-work/osfmk'), '-I', str(ROOT / 'kits/sheng')],\n"
                   "                   cwd=startup_record['directory'], check=True)\n    adsp_objs.append(obj)\n",
              "    extra = [] if srec is policy_record else ['-I', str(ROOT / '.cache/xnu-work/osfmk')]\n"
              "    subprocess.run(scmd + ['-mgeneral-regs-only'] + extra + ['-I', str(ROOT / 'kits/sheng')],\n"
              "                   cwd=srec['directory'], check=True)\n    fuxi_modem_const_to_data(src.stem, obj)\n    adsp_objs.append(obj)\n", p)
    s = s[:a] + seg + s[b:]
    p.write_text(s)
    print(f'baseband: {p}: modem sources in the adsp objects')

probes = sorted({p for r in roots for p in r.rglob('Ios17LegacyDisplayProbe.cpp')})
assert probes, 'no Ios17LegacyDisplayProbe.cpp'
for p in probes:
    s = p.read_text()
    if 'native_fuxi_modem_probe' in s: print(f'baseband: {p}: already'); continue
    s = sub(s, 'extern "C" void fuxi_modem_probe(void);       // fuxi-modem=1/2: the modem DSP (ModemProbe.cpp), baseband phase 1\n',
            'extern "C" void native_fuxi_modem_probe(void);   // fuxi 2026-11-26: ljhhkx529 FuxiModemProbe (fuxi-modem=1/15), from ceb99ca\n', p)
    s = sub(s, '\tfuxi_modem_probe();\n', '\tnative_fuxi_modem_probe();\n', p)
    p.write_text(s)
    print(f'baseband: {p}: native_fuxi_modem_probe')
