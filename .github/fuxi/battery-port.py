#!/usr/bin/env python3
"""fuxi battery (2026-11-16): the upstream fuxi record (UniXNU docs/devices/fuxi.md, Power) publishes the battery as an IOPMPowerSource
from the ADSP battery manager over PMIC GLINK (PMIC_RTR_ADSP_APPS), started with sheng-adsp=2. Kerfand's tree already builds the same
ADSP stack (AdspProbe, GLINK, QRTR; ShengAdsp.h/ShengQrtr.c/QcomGlink.c are byte-identical upstream) but lacks the four battery files.
This step fetches them from matejkoo217/UniXNU-fuxi at a pinned commit (sha256-checked) into device/package, calls
sheng_battery_probe() right after sheng_adsp_probe() in the iOS 17 late probe, and compiles them in build-ios17-legacy-display.py
(ShengBattery.cpp's static initializer is taken out of __mod_init_func, as for ShengAudioService; BatteryProbe.cpp calls it).
sheng-battery=0 keeps it off; without sheng-adsp=2 it never starts.
Usage: battery-port.py DEVICE_DIR [DEVICE_IOS17_DIR]   (run from $GITHUB_WORKSPACE)"""
import hashlib, subprocess, sys, urllib.request
from pathlib import Path
COMMIT = 'b76a1679433b0ab5386ac9957715f5e3fecdf46e'
FILES = {'ShengBattmgr.c': 'b1d2868033bc357b89f6d252c218ddfb42e1f576d812d5efc3ef2f64dea09174',
         'ShengBattmgr.h': 'fece7fe150f98fa9a51ffbba7c8e76eed7ace50b1c00c5c9b5a64202283706a0',
         'ShengBattery.cpp': '927b80404b91904d529e7852b1d4ef46ddc7a17c24d589f8bf7132c5dd58cca0',
         'BatteryProbe.cpp': '78b424629824d3cb0260c27cac588711fbaa8f298bad1886407ad4ee9a5ea47d'}
dirs = [Path(d) for d in sys.argv[1:]]
pkg = dirs[0] / 'package'
for name, want in FILES.items():
    url = f'https://raw.githubusercontent.com/matejkoo217/UniXNU-fuxi/{COMMIT}/package/{name}'
    data = urllib.request.urlopen(url, timeout=60).read()
    got = hashlib.sha256(data).hexdigest()
    assert got == want, (name, got)
    (pkg / name).write_bytes(data); print('fetched', name, got[:12])

def real_files(name):
    out = subprocess.run(['find', *map(str, dirs), '-name', name, '-type', 'f'], capture_output=True, text=True, check=True).stdout.split()
    return sorted(set(out))

n = 0
for p in real_files('Ios17LegacyDisplayProbe.cpp'):
    s = Path(p).read_text()
    if 'sheng_battery_probe' in s:
        print('probe already patched', p); n += 1; continue
    ext = 'extern "C" void sheng_adsp_probe(void);'
    call = '\tsheng_adsp_probe();\n'
    assert s.count(ext) == 1 and s.count(call) == 1, ('probe anchors', p)
    s = s.replace(ext, 'extern "C" void sheng_battery_probe(void);   // the battery power source (BatteryProbe.cpp, fuxi 2026-11-16)\n' + ext, 1)
    s = s.replace(call, call + '\tsheng_battery_probe();\n', 1)
    Path(p).write_text(s); print('probe patched', p); n += 1
assert n >= 1, 'no Ios17LegacyDisplayProbe.cpp'

m = 0
for p in real_files('build-ios17-legacy-display.py'):
    s = Path(p).read_text()
    if 'ShengBattery' in s:
        print('build already patched', p); m += 1; continue
    a1 = "ROOT / 'kits/sheng/AudioProbe.cpp', ROOT / 'kits/sheng/ShengAudioService.cpp'):"
    a2 = "    if src.stem == 'ShengAudioService':\n"
    a3 = "            'ShengGpr.c', 'ShengAudioReach.c', 'FuxiCs35l41.c', 'FuxiAudioRt.c'):"
    a4 = "        late_obj = OUT / 'ShengAudioService.late.o'\n        run(['llvm-objcopy', '--remove-section=__DATA,__mod_init_func', '--globalize-symbol=__GLOBAL__sub_I_ShengAudioService.cpp', obj, late_obj])\n"
    for a in (a1, a2, a3, a4):
        assert s.count(a) == 1, ('build anchors', p, a[:60])
    s = s.replace(a1, "ROOT / 'kits/sheng/AudioProbe.cpp', ROOT / 'kits/sheng/ShengAudioService.cpp',\n"
                      "            # the battery (fuxi 2026-11-16, upstream matejkoo217/UniXNU-fuxi)\n"
                      "            ROOT / 'kits/sheng/BatteryProbe.cpp', ROOT / 'kits/sheng/ShengBattery.cpp'):", 1)
    s = s.replace(a2, "    if src.stem in ('ShengAudioService', 'ShengBattery'):\n", 1)
    s = s.replace(a4, "        late_obj = OUT / (src.stem + '.late.o')\n"
                      "        run(['llvm-objcopy', '--remove-section=__DATA,__mod_init_func', '--globalize-symbol=__GLOBAL__sub_I_' + src.stem + '.cpp', obj, late_obj])\n", 1)
    s = s.replace(a3, "            'ShengGpr.c', 'ShengAudioReach.c', 'FuxiCs35l41.c', 'FuxiAudioRt.c', 'ShengBattmgr.c'):", 1)
    Path(p).write_text(s); print('build patched', p); m += 1
assert m >= 1, 'no build-ios17-legacy-display.py'

# COM3 row: upstream reads the battery through BootLog.c's [battery] row, which this tree does not have. Kerfand's fuxi-adsp-log thread
# (AdspProbe.cpp) prints every 250 ms while something changes; add the power source's stage, percent, mV, mA and flags to it.
# native_battery_stats is defined in BatteryProbe.cpp; weak, so a link without it still works (the row is then skipped).
la = 'extern "C" {extern volatile int32_t native_qrtr_stats[16]; extern char native_qrtr_text[96];}'
lb = 'q[0], q[1], q[2], q[3], q[4], q[5], q[6], q[7], q[8], q[9], q[10], q[11], q[12], native_qrtr_text);\n'
for p in real_files('AdspProbe.cpp'):
    s = Path(p).read_text()
    if 'fuxi battery:' in s:
        print('adsp log already patched', p); continue
    if s.count(la) != 1 or s.count(lb) != 1:
        print('adsp log anchors missing, no battery row', p); continue
    s = s.replace(la, la + '\nextern "C" {extern volatile int32_t native_battery_stats[16] __attribute__((weak));}', 1)
    s = s.replace(lb, lb + '        if (&native_battery_stats[0] != nullptr) IOLog("fuxi battery: stage %d pct %d mv %d ma %d temp %d flags %#x ans %d to %#x\\n",\n'
                           '              native_battery_stats[0], native_battery_stats[1], native_battery_stats[2], native_battery_stats[3],\n'
                           '              native_battery_stats[4], native_battery_stats[5], native_battery_stats[7], native_battery_stats[8]);\n', 1)
    Path(p).write_text(s); print('adsp log patched', p)

# Wallpaper (2026-11-16): the workflow's earlier poster-grant edit looked for scripts/build-ios17-legacy-display.py under UniXNU/ before
# the tree existed and was skipped in every run ("not found; poster grant skipped"). The grant list is a plain line of the source, outside
# the build script's checked replacements, so the source itself gets the poster extensions that do the rendering (AegirPoster,
# KaleidoscopePoster; MACF refused AegirPoster in the t50 log).
old = '"backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard"'
new = '"backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard,AegirPoster,KaleidoscopePoster"'
g = 0
for p in real_files('GpuPowerProbe.cpp'):
    s = Path(p).read_text()
    if new in s:
        print('poster grant already there', p); g += 1; continue
    if s.count(old) == 1:
        Path(p).write_text(s.replace(old, new, 1)); print('poster grant added', p); g += 1
print('GpuPowerProbe.cpp with the poster grant:', g)
