#!/usr/bin/env python3
"""53f iOS 17: put CpuFreqProbe.cpp into libNativeLegacyDisplay.late.a (archive-22).

boot-ci-cpufreq (53f run 44688198503, 2026-11-20) had no cpufreq code at all: the string "sheng-cpufreq" is not in the kernel.
cpufreq-port.py only taught device/scripts/build-boot-progress.py (the iPadOS recipe) to compile it, and the iOS 17 kernel builds
its board C++ in scripts/build-ios17-legacy-display.py. Kerfand 968 compiles kits/sheng/CpuFreqProbe.cpp there with the probe's own
command (its WiFi loop); this does the same after the backlight loop, and the object joins backlight_objs, which the archive takes.

Usage (working directory UniXNU, after defconfig): cpufreq-ios17-build.py scripts/build-ios17-legacy-display.py
"""
import sys
from pathlib import Path

def patch(p):
  if not p.is_file():
    print('cpufreq ios17: %s not found, skipped' % p)
    return 0
  if p.is_symlink():
    print('cpufreq ios17: %s is a link to %s' % (p, p.resolve()))
  s = p.read_text()
  if 'CpuFreqProbe' in s:
    print('cpufreq ios17: %s already compiles CpuFreqProbe' % p)
    return 1
  anchor = '# ---- archive ----\n'
  assert s.count(anchor) == 1, ('archive anchor', p)
  add = (
    "# fuxi 2026-11-20: CPU frequency domains (sheng-cpufreq), compiled like Kerfand 968 does (probe command + touch includes).\n"
    "cpufreq_src = ROOT / 'kits/sheng/CpuFreqProbe.cpp'\n"
    "require(cpufreq_src.is_file(), 'kits/sheng/CpuFreqProbe.cpp missing (cpufreq-port.py)')\n"
    "cpufreq_obj = OUT / 'CpuFreqProbe.ios17.o'\n"
    "subprocess.run([str(cpufreq_src) if a == str(probe_src) else str(cpufreq_obj) if a == str(probe_obj) else a for a in cmd] + touch_includes,\n"
    "               cwd=record['directory'], check=True)\n"
    "backlight_objs.append(cpufreq_obj)\n"
    "print('fuxi cpufreq: CpuFreqProbe.ios17.o built')\n\n"
)
  s = s.replace(anchor, add + anchor, 1)
  p.write_text(s)
  print('cpufreq ios17: %s compiles CpuFreqProbe.cpp into the late archive' % p)
  return 1

n = sum(patch(Path(a)) for a in sys.argv[1:])
print('cpufreq ios17: %d script(s) ready' % n)
if not n:
  print('::warning::cpufreq ios17: no build-ios17-legacy-display.py found, CpuFreqProbe stays out of the iOS 17 kernel')
