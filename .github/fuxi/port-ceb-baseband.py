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

# 5. (ours, claude 2026-11-27) FuxiModemProbe.cpp waitEvents() never blocked: assert_wait_timeout() returns THREAD_WAITING (-1),
#    so `if (!assert_wait_timeout(...))` was always false, no thread_block() followed, and serviceLink()'s for(;;) spun one core
#    (bb15: kernel_task 104-109% from the first sample; btturbo without the modem: 4-6%). Same code in ceb99ca, e2fd999, ljh V2 0645bfd.
#    The wait now blocks until wake() (thread_wakeup on &gOwner.pending) or the timeout; the return contract is unchanged.
WAIT_OLD = '''    if (!assert_wait_timeout(reinterpret_cast<event_t>(&gOwner.pending), THREAD_UNINT, ms, kMillisecondScale)) {'''
WAIT_NEW = '''    // claude 2026-11-27: assert_wait_timeout() returns THREAD_WAITING on success and does not block by itself; without the
    // thread_block() below this function never slept and serviceLink() spun a core (kernel_task ~105%).
    if (assert_wait_timeout(reinterpret_cast<event_t>(&gOwner.pending), THREAD_UNINT, ms, kMillisecondScale) == THREAD_WAITING) {
        bits = __atomic_exchange_n(&gOwner.pending, 0, __ATOMIC_ACQ_REL);
        if (bits) {
            clear_wait(current_thread(), THREAD_AWAKENED);
            return bits;
        }
        (void)thread_block(THREAD_CONTINUE_NULL);
        return __atomic_exchange_n(&gOwner.pending, 0, __ATOMIC_ACQ_REL);
    }
    if (false) {'''
for d in pkgs:
    p = d / 'FuxiModemProbe.cpp'
    s = p.read_text()
    if 'claude 2026-11-27: assert_wait_timeout' in s: continue
    s = sub(s, WAIT_OLD, WAIT_NEW, p)
    p.write_text(s)
    print(f'baseband: {p}: waitEvents blocks (thread_block)')

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

# 6. (ours, claude 2026-11-27) after the SIM is READY, put the modem ONLINE over DMS and read the mode back.
#    bb15w: DMS Get Operating Mode answered result 1 / error 0x4a at bring-up (asked 1.7 s before the USIM was ready), the
#    serving system stays "searching, radio interface NO_SVC" and the signal answers error 0x4a. Nothing else sets the mode:
#    upstream leaves ONLINE to CommCenter, which never starts here (HasBaseband 0). Late (~SIM READY + 5 s), not early boot.
#    sheng-bb-online=0 turns it off. Also NAS Set System Selection Preference (0x33): mode GSM/UMTS/LTE/NR, roaming any, CS+PS,
#    until power cycle (ljhhkx529 unixnu-fuxi ed473e4: the modem registered right after CommCenter sent 0x33).
ONLINE_FN = r'''// claude 2026-11-27: SIM READY + 5 s -> DMS Set Operating Mode ONLINE (0x2e, TLV 0x01 = 0), 3 s later read the mode and the
// system selection back; the register poll is restarted so the serving system is logged for another minute.
static uint8_t bb_online_state;
static uint32_t bb_online_at, bb_online_txn = 0x4e00u;
static void bb_online_step(void)
{
  if (bb_online_state >= 3u || !bb_uim_ready) return;
  const uint32_t now = bb_now_ms();
  if (bb_online_state == 0u) {
    uint32_t on = 1;
    if (PE_parse_boot_argn("sheng-bb-online", &on, sizeof on) && on == 0) { bb_online_state = 3u; printf("COACHZ online: off (sheng-bb-online=0)\n"); return; }
    bb_online_at = now + 5000u; bb_online_state = 1u; return;
  }
  if (now < bb_online_at) return;
  const struct cbq_server *server = cbq_server_find(&bb_qmux, BB_DMS);
  if (!server) return;
  if (bb_dms_slot < 0) bb_dms_slot = cbq_client_alloc(&bb_qmux, CBQ_INTERNAL, BB_DMS);
  if (bb_dms_slot < 0) return;
  uint8_t sdu[16];
  uint32_t n;
  if (bb_online_state == 1u) {
    /* NAS Set System Selection Preference (0x33, libqmi qmi-service-nas.json), the request ljhhkx529's run saw CommCenter
       send right before the modem registered (unixnu-fuxi ed473e4). bb15w's 0x34 read roaming 0 and no mode TLV; the
       user's card is a China Mobile SIM roaming in Japan. Mode GSM|UMTS|LTE|NR (0x5c), roaming any (0xff), CS+PS (2),
       change duration 0 = until power cycle: nothing is written to the modem's NV. */
    const struct cbq_server *nas = cbq_server_find(&bb_qmux, CBN_SVC_NAS);
    if (nas && bb_reg_slot >= 0) {
      uint8_t sel[48];
      uint32_t off = 0;
      const uint8_t mode[2] = {0x5c, 0x00}, roam[2] = {0xff, 0x00}, dom[4] = {0x02, 0, 0, 0}, dur = 0;
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x11, mode, 2);
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x14, roam, 2);
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x17, &dur, 1);
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x18, dom, 4);
      const uint32_t m = cbd_request(sel, ++bb_reg_txn, 0x0033u, off);
      bb_queue_tx(CBQ_PORT_BASE + (uint32_t)bb_reg_slot, nas->node, nas->port, sel, m);
      printf("COACHZ online: NAS set system selection (mode 0x5c, roaming any, CS+PS, until power cycle), txn 0x%x\n", bb_reg_txn);
    }
    const uint8_t online = 0;
    n = cbd_request(sdu, ++bb_online_txn, BB_DMS_SET_MODE, cbd_tlv(sdu + 7, sizeof sdu - 7u, 0x01, &online, 1));
    printf("COACHZ online: DMS set operating mode ONLINE, txn 0x%x, t %u\n", bb_online_txn, now);
    bb_online_at = now + 3000u; bb_online_state = 2u;
  } else {
    n = cbd_request(sdu, ++bb_online_txn, BB_DMS_GET_MODE, 0);
    printf("COACHZ online: DMS get operating mode again, txn 0x%x, t %u\n", bb_online_txn, now);
    const struct cbq_server *nas = cbq_server_find(&bb_qmux, CBN_SVC_NAS);
    if (nas && bb_reg_slot >= 0) {
      uint8_t sel[32];
      const uint32_t m = cbn_build_request(sel, sizeof sel, ++bb_reg_txn, CBN_NAS_GET_SYSTEM_SELECTION);
      if (m) bb_queue_tx(CBQ_PORT_BASE + (uint32_t)bb_reg_slot, nas->node, nas->port, sel, m);
    }
    bb_reg_tries = 0;   /* another minute of serving-system polls */
    bb_online_state = 3u;
  }
  bb_queue_tx(CBQ_PORT_BASE + (uint32_t)bb_dms_slot, server->node, server->port, sdu, n);
}

'''
RADIO_ANCHOR = '// The three requests, in the order they are worth asking in.\nstatic void bb_radio_step(void)\n'
LOOP_OLD = '  if (bb_lpm_pending == 1) { bb_lpm_pending = 2; bb_lpm_send(); }\n'
LOOP_NEW = LOOP_OLD + '  bb_online_step();   // claude 2026-11-27\n'
for d in pkgs:
    p = d / 'coachz_baseband.cpp'
    if not p.exists(): continue
    s = p.read_text()
    if 'bb_online_step' in s: continue
    s = sub(s, RADIO_ANCHOR, ONLINE_FN + RADIO_ANCHOR, p)
    s = sub(s, LOOP_OLD, LOOP_NEW, p)
    p.write_text(s)
    print(f'baseband: {p}: DMS online after SIM ready')