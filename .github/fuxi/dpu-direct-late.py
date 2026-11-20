#!/usr/bin/env python3
"""fuxi 2026-11-20: boot-ci-dpu (run 44635279910) opened the display bank window (serial "fuxi dpu: ... state 0x80000003",
fsr 0x400 = FORMAT AArch64, no fault in 50 ms), yet swapstat showed direct 0 / flip 0 / no fallbacks: the copy path only.
NativeLegacyDisplay::startDirect runs once, from start(); when the display starts before NativeUfs has opened the window
(native_ufs_dpu_state bit 31 still clear) it returns and direct scanout never comes on. Now:
  - the swap path calls startDirect again while it is off (at most 600 swaps),
  - startDirect says on serial why it stayed off (first and last try) and when it came on.
Usage: dpu-direct-late.py <NativeLegacyDisplay.cpp>"""
import re, sys
p = sys.argv[1]
s = open(p).read()
if 'fuxi-direct-late' in s:
    print(p, ': already patched'); sys.exit(0)
A = 'bool directOn=false,directBoot=true;'
B = 'if(mode<2 || !&native_ufs_dpu_map || !&native_ufs_dpu_state || !(native_ufs_dpu_state>>31) || !primary)return;'
# Upstream 19ef3a7: "...!half && !gpuBypass && latchRequest)stat(5);"; Kerfand's diff adds "!xr &&".
m = re.search(r'if\(directOn && !half && [^\n]*?latchRequest\)stat\(5\);', s)
C = m.group(0) if m else '<stat(5) line>'
D = 'directOn=true;gDirectDisplay=this;'
for a in (A, B, C, D):
    if s.count(a) != 1:
        print(p, ': anchor count', s.count(a), a[:60], file=sys.stderr); sys.exit(1)
s = s.replace(A, A + '\n    unsigned directTries=0; // fuxi-direct-late', 1)
s = s.replace(B,
    'if(mode<2 || !&native_ufs_dpu_map || !&native_ufs_dpu_state || !(native_ufs_dpu_state>>31) || !primary) {\n'
    '            if(mode>=2 && (directTries==0 || directTries==600))\n'
    '                printf("fuxi direct: off (try %u) map %d state %#x primary %d\\n",directTries,&native_ufs_dpu_map!=nullptr,\n'
    '                       &native_ufs_dpu_state?native_ufs_dpu_state:0xffffffffU,int(primary));\n'
    '            return;\n'
    '        }', 1)
s = s.replace(D, D + 'printf("fuxi direct: on (try %u)\\n",directTries);', 1)
s = s.replace(C, 'if(!directOn && directTries<600){++directTries;startDirect();}\n        ' + C, 1)
open(p, 'w').write(s)
print(p, ': direct scanout retried from the swap path')
