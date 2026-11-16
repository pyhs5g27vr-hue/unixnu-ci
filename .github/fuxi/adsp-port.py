#!/usr/bin/env python3
"""fuxi ADSP stack (2026-11-16) on the CI's Kerfand base 53f1320c, which predates it. The battery (battery-port.py) talks to the ADSP's
battery manager over GLINK/QRTR, so this step brings Kerfand 82e4615's ADSP files (no audio) into device/package, compiles them in the
iOS 17 legacy display build like 82e4615 does, and calls sheng_adsp_probe() after native_touch_probe() in the late probe. The probe
only does anything with sheng-adsp=1/2. Files are fetched at the pinned commit (the commit pins the content).
Usage: adsp-port.py DEVICE_DIR [DEVICE_IOS17_DIR]   (run from $GITHUB_WORKSPACE, before battery-port.py)"""
import subprocess, sys, urllib.request
from pathlib import Path
COMMIT = '82e46156e8e0cebd331a8e152954b5ca3ffff7c7'
CXX = ['AdspProbe.cpp', 'FuxiAdspFirmware.cpp']
C = ['QcomGlink.c', 'QcomMdt.c', 'QcomQmp.c', 'QcomSmem.c', 'QcomSmp2p.c', 'QcomQrtr.c', 'ShengQrtr.c', 'FatVolume.c']
H = ['ShengAdsp.h', 'QcomGlink.h', 'QcomMdt.h', 'QcomQmp.h', 'QcomQrtr.h', 'QcomScm.h', 'QcomSmem.h', 'QcomSmp2p.h', 'FatVolume.h']
dirs = [Path(d) for d in sys.argv[1:]]
pkg = dirs[0] / 'package'

def real_files(name):
    out = subprocess.run(['find', *map(str, dirs), '-name', name, '-type', 'f'], capture_output=True, text=True, check=True).stdout.split()
    return sorted(set(out))

if real_files('AdspProbe.cpp'):
    print('ADSP stack already in the tree; nothing to do'); sys.exit(0)
for name in CXX + C + H:
    if (pkg / name).exists():
        print('keep existing', name); continue
    url = f'https://raw.githubusercontent.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17/{COMMIT}/device/package/{name}'
    data = urllib.request.urlopen(url, timeout=60).read()
    assert len(data) > 200, (name, len(data))
    (pkg / name).write_bytes(data); print('fetched', name, len(data))

# FuxiAdspFirmware.cpp reads the firmware from the modem partition through native_ufs_part_find/read, which 82e4615 appended to
# drivers/NativeUfs/NativeUfs.cpp (80 lines, read-only GPT lookup + READ(10)); 53f's NativeUfs.cpp ends just before them
# (run 43797509258: undefined _native_ufs_part_find/_native_ufs_part_read). Append the same section.
ufs_new = urllib.request.urlopen(f'https://raw.githubusercontent.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17/{COMMIT}/device/drivers/NativeUfs/NativeUfs.cpp',
                                 timeout=60).read().decode()
mark = '// ---- Read-only access to named partitions (board drivers)'
assert ufs_new.count(mark) == 1, 'NativeUfs.cpp section'
section = '\n\n' + ufs_new[ufs_new.index(mark):]
u = 0
for p in real_files('NativeUfs.cpp'):
    s = Path(p).read_text()
    if 'native_ufs_part_find' in s:
        print('NativeUfs already has the partition reads', p); u += 1; continue
    assert 'hostRead4k' in s and 'rootCrc32' in s, ('NativeUfs anchors', p)
    Path(p).write_text(s.rstrip('\n') + section); print('NativeUfs partition reads appended', p); u += 1
assert u >= 1, 'no NativeUfs.cpp'

# The late probe: declare and call sheng_adsp_probe() after the touch probe.
n = 0
for p in real_files('Ios17LegacyDisplayProbe.cpp'):
    s = Path(p).read_text()
    if 'sheng_adsp_probe();' in s:
        print('probe already calls it', p); n += 1; continue
    ext = 'extern "C" void native_touch_probe(void);\n'
    call = '\tnative_touch_probe();\n'
    assert s.count(ext) == 1 and s.count(call) == 1, ('probe anchors', p)
    s = s.replace(ext, ext + 'extern "C" void sheng_adsp_probe(void);       // sheng-adsp=1/2: the audio DSP (AdspProbe.cpp), fuxi 2026-11-16\n', 1)
    s = s.replace(call, call + '\tsheng_adsp_probe();\n', 1)
    Path(p).write_text(s); print('probe patched', p); n += 1
assert n >= 1, 'no Ios17LegacyDisplayProbe.cpp'

# The build: 82e4615's adsp_objs block without the audio sources, before the archive, and *adsp_objs in the archive.
BLOCK = '''# ---- the audio DSP (sheng-adsp=1 survey, 2 start + GLINK + IPC router), from Kerfand 82e4615 without audio (fuxi 2026-11-16) ----
adsp_objs = []
for src in (ROOT / 'kits/sheng/AdspProbe.cpp', ROOT / 'kits/sheng/FuxiAdspFirmware.cpp'):
    obj = OUT / (src.stem + '.ios17.o')
    subprocess.run([str(src) if a == str(probe_src) else str(obj) if a == str(probe_obj) else a for a in cmd] + touch_includes,
                   cwd=record['directory'], check=True)
    adsp_objs.append(obj)
for src in ('QcomGlink.c', 'QcomMdt.c', 'QcomQmp.c', 'QcomSmem.c', 'QcomSmp2p.c', 'QcomQrtr.c', 'ShengQrtr.c', 'FatVolume.c'):
    src = ROOT / 'kits/sheng' / src
    obj = OUT / (src.stem + '.ios17.o')
    sargs, scmd, k = startup_record['arguments'], [], 0
    while k < len(sargs):
        a = sargs[k]
        if a == startup_record['file']:
            scmd.append(str(src))
        elif a == '-o':
            scmd += ['-o', str(obj)]; k += 1
        elif a in ('-MF', '-MT', '-MJ'):
            k += 1
        elif a == '-Xclang' and sargs[k + 1].startswith('-W'):
            k += 1
        elif not a.startswith('-W'):
            scmd.append(a)
        k += 1
    subprocess.run(scmd + ['-mgeneral-regs-only', '-I', str(ROOT / '.cache/xnu-work/osfmk'), '-I', str(ROOT / 'kits/sheng')],
                   cwd=startup_record['directory'], check=True)
    adsp_objs.append(obj)
print(f'adsp: {len(adsp_objs)} objects')

'''
m = 0
for p in real_files('build-ios17-legacy-display.py'):
    s = Path(p).read_text()
    if 'adsp_objs' in s:
        print('build already has adsp_objs', p); m += 1; continue
    arch = '# ---- archive ----\n'
    tail = "*backlight_objs, OUT / 'legacy-original-bindings.o'"
    assert s.count(arch) == 1 and s.count(tail) == 1 and 'startup_record =' in s and 'touch_includes =' in s, ('build anchors', p)
    s = s.replace(arch, BLOCK + arch, 1)
    s = s.replace(tail, "*backlight_objs, *adsp_objs, OUT / 'legacy-original-bindings.o'", 1)
    Path(p).write_text(s); print('build patched', p); m += 1
assert m >= 1, 'no build-ios17-legacy-display.py'
