#!/usr/bin/env python3
"""fuxi 2026-11-20: install the GPU restart hook (boot-ci-usb2 GPUHANG test: 45 x "fuxi hang: detect", 0 recover).
nativeAdrenoHangcheck only calls NativeAdrenoSubmit::recover when g.restart is set, and only native_adreno_set_restart sets it.
This base's GpuPowerProbe.cpp never calls it; matejkoo217/UniXNU-fuxi's does (gpuRestart: a6xx_recover's GBIF drain + RBBM_SW_RESET,
then hw_init, ring restart, cp_init, zap secure mode). gpu-restart.inc.cpp carries those two functions; this script inserts them
before gpuStart and installs the hook right before publishAndWrapperTest.
Usage: gpu-restart-port.py FILE|DIR...   (every GpuPowerProbe.cpp under each DIR)"""
import pathlib, sys
INC = (pathlib.Path(__file__).parent / 'gpu-restart.inc.cpp').read_text()

def port(p):
    t = p.read_text()
    if 'native_adreno_set_restart' in t:
        print(p, ': already installs a restart hook'); return True
    a = '\nvoid gpuStart() {\n'
    b = '        publishAndWrapperTest(selftest);\n'
    if t.count(a) != 1 or t.count(b) != 1 or 'void gpuHwInit' in t or 'gpuRestart' in t:
        print(p, ': anchors', t.count(a), t.count(b), file=sys.stderr); return False
    decl = ('// fuxi-gpu-restart: defined by Adreno740 (NativeAdrenoPublish.cpp), always linked with this probe.\n'
            'extern "C" void native_adreno_set_restart(NativeAdrenoRestart, void *);\n')
    t = t.replace(a, '\n' + decl + INC.rstrip('\n') + '\n' + a.lstrip('\n'), 1)
    t = t.replace(b, '        native_adreno_set_restart(gpuRestart, nullptr);   // fuxi-gpu-restart\n' + b, 1)
    p.write_text(t); print(p, ': restart hook installed'); return True

ok, n = True, 0
for arg in sys.argv[1:]:
    q = pathlib.Path(arg)
    for p in ([q] if q.is_file() else q.rglob('GpuPowerProbe.cpp')):
        n += 1; ok &= port(p)
sys.exit(0 if ok and n else 1)
