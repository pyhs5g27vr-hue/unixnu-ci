#!/usr/bin/env python3
"""fuxi radios and audio from Kerfand 968a7c6 onto the CI's 53f1320c base, verbatim (Claude 2026-11-20, user rule: port, don't rewrite).
968a7c6 builds into the iOS 17 display archive: Wi-Fi (Ath12kWifi f6bf561 legacy runtime + the fuxi board code, firmware from the boot
GPU addon by FuxiWifiFwPart.cpp), Bluetooth (QcaBluetooth 22ff97f + FuxiBluetooth.cpp, firmware from the addon's bluetooth/ entries),
and the ADSP with audio and battery (AdspProbe, GLINK/QRTR/SMEM/SMP2P/QMP, GPR, AudioReach, CS35L41, audio service, battery manager).
The daily base image's addon already carries wifi/*, bluetooth/*, btd/bluetoothd and audio/ShengAudio.driver (make-ci-image.py keeps
them), so only the kernel side is missing here. This step:
  1. fetches the 968a7c6 device/package files of those drivers (the four FuxiWifi* files 968 changed included) into device/package;
  2. fetches ios17/scripts/build-native-wifi-ios17.py (the module build the display script calls) into device-ios17/scripts;
  3. copies 968a7c6's own build block ("# ---- WiFi:" up to "# ---- archive ----") into device-ios17's build-ios17-legacy-display.py,
     minus its two CPU frequency sources (cpufreq-ios17-build.py compiles CpuFreqProbe.cpp here), and links *wifi_objs, *adsp_objs;
  4. adds 968a7c6's late-probe calls (adsp, audio, battery, bluetooth, wifi, wifi link) after native_touch_probe();
  5. copies 968a7c6's xnu patches for the audio HAL mount and bluetoothd (launch constraint, os_log to serial) into PATCH_DIR.
adsp-port.py then finds AdspProbe.cpp and does nothing; battery-port.py keeps these battery files when FUXI_968_ADSP=1.
Starts only with sheng-adsp=2 / sheng-audio=1 / fuxi-bluetooth=1 / fuxi-wifi=5, as on 968.
Usage: port-968-radio.py DEVICE_DIR DEVICE_IOS17_DIR [PATCH_DIR]   (run from $GITHUB_WORKSPACE, before adsp-port.py)"""
import subprocess, sys, urllib.request
from pathlib import Path

COMMIT = '968a7c62fec43e16b84e72822a008bb08ea787df'
RAW = f'https://raw.githubusercontent.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17/{COMMIT}/'
PKG = [
    # Wi-Fi board code 968 changed or added
    'FuxiWifiFwPart.cpp', 'FuxiWifiLink.cpp', 'FuxiWifiNet.cpp', 'FuxiWifiNw21.cpp',
    # Bluetooth
    'FuxiBluetooth.cpp', 'FuxiBtFirmware.cpp', 'BluetoothFirmware.h', 'FuxiWcnPower.c', 'WcnPower.h',
    'Sm8550Gcc.c', 'Sm8550GeniUart.c', 'Sm8550GeniUart.h', 'Sm8550QupDma.c', 'Sm8550QupDma.h', 'AppsSmmuLock.h',
    # ADSP
    'AdspProbe.cpp', 'FuxiAdspFirmware.cpp', 'ShengAdsp.h', 'FatVolume.c', 'FatVolume.h',
    'QcomGlink.c', 'QcomGlink.h', 'QcomMdt.c', 'QcomMdt.h', 'QcomQmp.c', 'QcomQmp.h', 'QcomQrtr.c', 'QcomQrtr.h', 'QcomScm.h',
    'QcomSmem.c', 'QcomSmem.h', 'QcomSmp2p.c', 'QcomSmp2p.h', 'ShengQrtr.c',
    # audio
    'AudioProbe.cpp', 'ShengAudioService.cpp', 'ShengAudioAbi.h', 'ShengGpr.c', 'ShengGpr.h', 'ShengAudioReach.c', 'ShengAudioReach.h',
    'FuxiCs35l41.c', 'FuxiCs35l41.h', 'FuxiAudioRt.c',
    # battery
    'BatteryProbe.cpp', 'ShengBattery.cpp', 'ShengBattmgr.c', 'ShengBattmgr.h',
]
SCRIPTS = ['build-native-wifi-ios17.py']
PATCHES = ['ios17-zaudio-hal-mount.patch', 'zz-btd-launch-constraint.patch', 'zz-btd-oslog-probe.patch']

dev, ios17 = Path(sys.argv[1]), Path(sys.argv[2])
patch_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None


def get(path):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(RAW + path, timeout=60).read()
        except Exception as e:  # noqa: BLE001 - retried, then raised
            err = e
    raise SystemExit(f'fetch {path}: {err}')


def real_files(name):
    out = subprocess.run(['find', str(dev), str(ios17), '-name', name, '-type', 'f'], capture_output=True, text=True, check=True).stdout.split()
    return sorted(set(out))


# 1-2: files
for name in PKG:
    data = get('device/package/' + name)
    (dev / 'package' / name).write_bytes(data)
print(f'968: {len(PKG)} device/package files')
for name in SCRIPTS:
    (ios17 / 'scripts' / name).write_bytes(get('ios17/scripts/' + name))
    print('968: scripts/' + name)

# 3: the build block, verbatim from 968a7c6's display build
src968 = get('ios17/scripts/build-ios17-legacy-display.py').decode()
START, END = '# ---- WiFi: Ath12kWifi f6bf561', '# ---- archive ----'
block = src968[src968.index(START):src968.index(END)]
CPUFREQ = ("ROOT / 'kits/sheng/FuxiWifiNet.cpp',\n"
           "            # CPU frequency domains (sheng-cpufreq): CpuFreqProbe.cpp as the iPadOS build has it, polled by FuxiCpuFreqLog.cpp.\n"
           "            ROOT / 'kits/sheng/CpuFreqProbe.cpp', ROOT / 'kits/sheng/FuxiCpuFreqLog.cpp'):\n")
assert block.count(CPUFREQ) == 1, '968 Wi-Fi source list changed'
block = block.replace(CPUFREQ, "ROOT / 'kits/sheng/FuxiWifiNet.cpp'):\n"
                      "            # (968a7c6 also builds CpuFreqProbe.cpp + FuxiCpuFreqLog.cpp here; on this tree cpufreq-ios17-build.py does)\n", 1)
ar968 = '*backlight_objs, *wifi_objs, *adsp_objs, OUT'
assert ar968 in src968, '968 archive line'
n = 0
for p in real_files('build-ios17-legacy-display.py'):
    s = Path(p).read_text()
    if 'Ath12kWifi f6bf561 (legacy runtime) missing' in s:
        print('build already has the 968 block', p); n += 1; continue
    if s.count(END) != 1 or s.count('*backlight_objs, OUT') != 1 or 'adsp_objs' in s:
        print('!! build anchors', p); continue
    s = s.replace(END, '# ---- fuxi 2026-11-20: Kerfand 968a7c6 Wi-Fi, Bluetooth, ADSP/audio/battery block, verbatim (port-968-radio.py) ----\n'
                  + block + END, 1)
    s = s.replace('*backlight_objs, OUT', ar968, 1)
    Path(p).write_text(s); n += 1
    print('build: 968 block added', p)
assert n >= 1, 'no build-ios17-legacy-display.py patched'

# 4: late-probe calls, as 968a7c6 has them
EXT = ('extern "C" void sheng_bluetooth_probe(void);   // FuxiBluetooth.cpp (QcaBluetooth, fuxi 2026-11-15)\n'
       'extern "C" void fuxi_wifi_probe(void);        // fuxi-wifi=1: read-only look at the WCN7850 path\n'
       'extern "C" void sheng_battery_probe(void);    // sheng-adsp=2: the battery power source (BatteryProbe.cpp), power.md section 4\n'
       'extern "C" void sheng_audio_probe(void);      // sheng-audio=N: speakers, microphone, audio service (AudioProbe.cpp)\n'
       'extern "C" void sheng_adsp_probe(void);       // sheng-adsp=1/2: the audio DSP (AdspProbe.cpp), power.md section 3\n'
       'extern "C" void fuxi_wifi_link_probe(void);   // fuxi-wifi=2/3/5: power, PCIe0 link; 5 runs Ath12kWifi (FuxiWifiNw21)\n')
CALLS = '\tsheng_adsp_probe();\n\tsheng_audio_probe();\n\tsheng_battery_probe();\n\tsheng_bluetooth_probe();\n\tfuxi_wifi_probe();\n\tfuxi_wifi_link_probe();\n'
E_ANCHOR, C_ANCHOR = 'extern "C" void native_touch_probe(void);', '\tnative_touch_probe();\n'
m = 0
for p in real_files('Ios17LegacyDisplayProbe.cpp'):
    s = Path(p).read_text()
    if 'sheng_bluetooth_probe();' in s:
        print('probe already has the 968 calls', p); m += 1; continue
    if s.count(E_ANCHOR) != 1 or s.count(C_ANCHOR) != 1 or 'sheng_adsp_probe' in s:
        print('!! probe anchors', p); continue
    s = s.replace(E_ANCHOR, EXT + E_ANCHOR, 1).replace(C_ANCHOR, C_ANCHOR + CALLS, 1)
    Path(p).write_text(s); m += 1
    print('probe: 968 calls added', p)
assert m >= 1, 'no Ios17LegacyDisplayProbe.cpp patched'

# 5: xnu patches
if patch_dir:
    patch_dir.mkdir(parents=True, exist_ok=True)
    for name in PATCHES:
        (patch_dir / name).write_bytes(get('unixnu/patches/xnu-10063-arm64e/' + name))
        print('968 xnu patch:', patch_dir / name)
    # 968a7c6's fuxi-kernel-baseline.sh unwinds ios17-zaudio-hal-mount.patch before the wallpaper patch on the second (archive) pass,
    # otherwise offline-owner-systemos-mount.patch no longer applies (radio B2 44737262697: kern_exec.c:183). Same two lines here.
    LATE_OLD = 'for LATE_PATCH in "$ROOT/patches/xnu-10063-arm64e/ios17-wallpaper-iphone.patch"'
    LATE_NEW = ('# ios17-zaudio-hal-mount.patch adds lines right after the wallpaper patch\'s: it unwinds before it.\n'
                'for LATE_PATCH in "$ROOT/patches/xnu-10063-arm64e/ios17-zaudio-hal-mount.patch" "$ROOT/patches/xnu-10063-arm64e/ios17-wallpaper-iphone.patch"')
    k = 0
    for p in real_files('fuxi-kernel-baseline.sh'):
        s = Path(p).read_text()
        if 'ios17-zaudio-hal-mount.patch' in s:
            print('baseline already unwinds zaudio', p); k += 1; continue
        if s.count(LATE_OLD) != 1:
            print('!! baseline anchor', p); continue
        Path(p).write_text(s.replace(LATE_OLD, LATE_NEW, 1)); k += 1
        print('baseline: zaudio unwinds first', p)
    assert k >= 1, 'no fuxi-kernel-baseline.sh with the wallpaper LATE_PATCH line'
print('port-968-radio: done')
