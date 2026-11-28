#!/usr/bin/env python3
"""Gemini 2026-11-28: fuxi-gpu-coherence-retry.py ROOT... : Kerfand 2a1c720 GpuPowerProbe.cpp (+10) verbatim.
Under the AMP Edge scheduler (zz-amp-edge, E/P clusters), coherenceProbe(vm) can transiently report io_coherent=0
due to core migration mid-setup, which drops HOST_CACHED memory types and breaks Vulkan device creation.
Retries coherenceProbe up to 3 times and prints each run's result. Usage: fuxi-gpu-coherence-retry.py ROOT..."""
import pathlib, sys

OLD = '    coherenceProbe(vm);\n'
NEW = (
    '    // fuxi 2026-11-27: A1 (Edge scheduler, E/P clusters) came up with io_coherent 0 where S18-S19 had 1, which took the\n'
    '    // HOST_CACHED memory types away and Vulkan device creation with them. The probe can fail on a transient (lines written\n'
    '    // back early, a migration mid-setup), so it runs up to three times, and every row is printed.\n'
    '    for (unsigned run = 0; run < 3; ++run) {\n'
    '        memset(native_gpu_coherence, 0, sizeof native_gpu_coherence);\n'
    '        coherenceProbe(vm);\n'
    '        printf("fuxi gpu coherence run %u: %s\\n", run, native_gpu_coherence_row);\n'
    '        if (!&native_adreno_io_coherent || native_adreno_io_coherent || native_gpu_coherence_row[2] == \'s\') break;\n'
    '    }\n'
)

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('GpuPowerProbe.cpp')):
        s = p.read_text()
        if 'fuxi gpu coherence run' in s:
            print('gpu-coherence-retry: already', p)
            n += 1
            continue
        if s.count(OLD) != 1:
            print('gpu-coherence-retry: skip', p, 'anchor count', s.count(OLD))
            continue
        p.write_text(s.replace(OLD, NEW, 1))
        n += 1
        print('gpu-coherence-retry:', p)
assert n >= 1, 'no GpuPowerProbe.cpp patched'
