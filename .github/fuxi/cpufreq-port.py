#!/usr/bin/env python3
"""把作者的 CPU 调频（sheng-cpufreq）移植进 53f 线。

三件事：
1. CpuFreqProbe.cpp 写进 device/package/ 和 device-ios17/package/
2. osfmk/kern/processor.c 追加 sheng_cpu_idle_mach（作者的 zzye-sheng-cpu-idle.patch 等价物）
3. device/scripts/build-boot-progress.py 加编译 CpuFreqProbe.o 并进 libBootProgress.a

用法（在 CI 的 $GITHUB_WORKSPACE 下）：
    python3 cpufreq.py . <CpuFreqProbe.cpp 的路径>
"""
import sys
from pathlib import Path

WS = Path(sys.argv[1]).resolve()
SRC = Path(sys.argv[2]) if len(sys.argv) > 2 else (WS / 'ci-self/.github/fuxi/CpuFreqProbe.cpp')

print('工作区: %s' % WS)
print('源文件: %s' % SRC)
if not SRC.exists():
    raise SystemExit('CpuFreqProbe.cpp 不存在: %s' % SRC)
cpp_text = SRC.read_text()

# ---------------------------------------------------------------- 1) 放源文件
destinations = []
for base in ('device', 'device-ios17'):
    pkg = WS / base / 'package'
    if pkg.is_dir():
        dst = pkg / 'CpuFreqProbe.cpp'
        dst.write_text(cpp_text)
        destinations.append(dst)
if not destinations:
    raise SystemExit('device/package 和 device-ios17/package 都不存在')
for d in destinations:
    print('写入 %s (%d 字节)' % (d, d.stat().st_size))

# ---------------------------------------------- 2) sheng_cpu_idle_mach：走 patch，不在这里改
# XNU 树是 `unixnu build kernel` 内部才展开的，而这个 step 在它之前跑；等树有了，processor.o 也已经
# 编好，改源码不生效（2026-11-20 Claude 在 CI 上确认：processor.c 补丁打了 0 个文件）。
# 所以 helper 由 UniXNU/patches/xnu-10063-arm64e/sheng-cpu-idle.patch 提供，在 XNU 编译前 apply。
# CpuFreqProbe.cpp 里 sheng_cpu_idle_mach 是 weak 引用：patch 没打上时 busy 读 100%，
# 所有域停在最高允许频率（governor 的激进端），不会链接失败。
print('  sheng_cpu_idle_mach: 由 sheng-cpu-idle.patch 提供（本脚本不再改 processor.c）')

# ------------------------------------- 3) build-boot-progress.py 加 C++ 编译
script = WS / 'device/scripts/build-boot-progress.py'
if not script.exists():
    print('!! 找不到 %s' % script)
    raise SystemExit(1)
s = script.read_text(errors='replace')
if 'CpuFreqProbe' in s:
    print('跳过（已有）: %s' % script)
else:
    anchor = "fault_source = ROOT / 'kits/sheng/BootFaultProbe.c'"
    if anchor not in s:
        print('!! build-boot-progress.py 里找不到 fault_source 锚点')
        raise SystemExit(1)
    addition = anchor + '''

# fuxi: the author's CPU frequency control (sheng-cpufreq). C++ (IOKit), so compiled with the same records but
# without the C-only register restriction, with the tree's IOKit and BSD headers in reach.
cpufreq_source = ROOT / 'kits/sheng/CpuFreqProbe.cpp'
cpufreq_obj = None
if cpufreq_source.exists():
    def compile_cxx_like(record, source, destination):
        command, index = [], 0
        arguments = record['arguments']
        while index < len(arguments):
            value = arguments[index]
            if value == record['file']:
                command.append(str(source))
            elif value == '-o':
                command += ['-o', str(destination)]
                index += 1
            elif value in ('-MF', '-MT', '-MJ'):
                index += 1
            elif value == '-Xclang' and arguments[index + 1].startswith('-W'):
                index += 1
            elif value == '-mgeneral-regs-only':
                pass
            elif value == '-D' and arguments[index + 1].startswith('XNU_BOOT_PROGRESS='):
                index += 1
            elif value.startswith('-DXNU_BOOT_PROGRESS='):
                pass
            elif not value.startswith('-W'):
                command.append(value)
            index += 1
        command += ['-DXNU_BOOT_PROGRESS=1']
        # The record's own -I list already names the XNU include roots (osfmk, bsd, libkern, ...). BootProgress.c
        # never includes IOKit, so 'iokit' is not among them; derive the tree root from whichever *osfmk entry the
        # record carries and add <root>/iokit, which is what XNU's own makefiles put on the line for <IOKit/...>.
        xnu_root = None
        for _i, _a in enumerate(command):
            if _a == '-I' and _i + 1 < len(command):
                _p = command[_i + 1]
                if _p.endswith('/osfmk'):
                    xnu_root = _p[: -len('/osfmk')]
                    break
        extra_incs = []
        if xnu_root:
            for _sub in ('iokit', ''):
                _cand = xnu_root + ('/' + _sub if _sub else '')
                if _cand not in command:
                    extra_incs += ['-I', _cand]
            print('   [diag] xnu root from record: %s' % xnu_root)
        else:
            print('   [diag] no .../osfmk in the record: IOKit include path unknown')
            for _i, _a in enumerate(command):
                if _a == '-I' and _i + 1 < len(command):
                    print('   [diag] -I %s' % command[_i + 1])
        command += ['-xc++', '-std=gnu++17', '-fno-exceptions', '-fno-rtti'] + extra_incs + [
            '-I', str(ROOT / 'kits/sheng')]
        _r = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True, timeout=180)
        if _r.returncode != 0:
            raise subprocess.CalledProcessError(_r.returncode, command, _r.stdout, _r.stderr)
        return destination
    # fuxi: a C++ probe that does not compile must not cost the whole kernel build. Report and carry on.
    # The IOKit headers live wherever the XNU tree put them; print what is actually there so the next
    # run's log says which -I is wrong instead of failing silently.
    import glob as _glob
    for _d in ('.cache/xnu-work', '.cache/xnu-work/iokit', 'build/xnu'):
        _p = ROOT / _d
        if _p.exists():
            _names = sorted(x.name for x in _p.iterdir())[:14]
            print('   [diag] %s: %s' % (_d, ' '.join(_names)))
        else:
            print('   [diag] %s: (missing)' % _d)
    for _pat in ('**/IOKit/IOService.h', '**/IOKit/IOLib.h'):
        _hits = _glob.glob(str(ROOT / _pat), recursive=True)[:3]
        print('   [diag] %s -> %s' % (_pat, _hits if _hits else 'none'))
    try:
        cpufreq_obj = compile_cxx_like(policy_record, cpufreq_source, OUT / 'CpuFreqProbe.o')
        print('   built CpuFreqProbe.o')
    except subprocess.CalledProcessError as _e:
        _err = (_e.stderr or _e.output or '') or ''
        _tail = [l for l in _err.splitlines() if l.strip()][-12:]
        print('   ::warning::CpuFreqProbe.o did not compile (rc=%s); sheng-cpufreq is absent from this kernel' % _e.returncode)
        for _l in _tail:
            print('   ::warning::  %s' % _l.strip()[:300])
        print('   --- full stderr tail ---')
        for _l in _tail:
            print('   %s' % _l.strip()[:400])
        cpufreq_obj = None
    except Exception as _e:
        print('   ::warning::CpuFreqProbe.o did not compile: %s' % _e)
        cpufreq_obj = None
'''
    s = s.replace(anchor, addition, 1)

    # 把 cpufreq_obj 加进 archive（找 ar 那一段）
    if 'ar' in s and 'fault_obj' in s:
        # archive 的构建通常在文件末尾，用 ar rcs 加进去
        s += '''

# fuxi: add the CPU frequency probe to the archive so BootProgress.c's weak reference resolves.
if cpufreq_obj is not None:
    subprocess.run(['llvm-ar', 'rs', str(archive), str(cpufreq_obj)], check=True, timeout=60)
    print('   archive += CpuFreqProbe.o')
'''
    script.write_text(s)
    print('改好 %s' % script)

# ------------------------------- 4) iOS 17 的 late probe 调 sheng_cpufreq_probe（Claude 2026-11-20）
# boot-ci-cpufreq 里根本没有 cpufreq 代码：iOS 17 的 Ios17LegacyDisplayProbe.cpp 从不调用 sheng_cpufreq_probe，
# 也不编译 CpuFreqProbe.cpp（编译由 cpufreq-ios17-build.py 在 kernel 步骤补上）。968 的探针自己有 fuxi_cpufreq_start，跳过。
probe_hits = 0
for f in list(WS.glob('device*/**/Ios17LegacyDisplayProbe.cpp')):
    t = f.read_text(errors='replace')
    if 'cpufreq' in t:
        print('跳过（已有 cpufreq）: %s' % f)
        probe_hits += 1
        continue
    decl = 'extern "C" void sheng_gpu_power_probe(void);\n'
    call = '\tsheng_gpu_power_probe();\n'
    if t.count(decl) != 1 or t.count(call) != 1:
        print('!! %s: 找不到 sheng_gpu_power_probe 的声明/调用（%d/%d）' % (f, t.count(decl), t.count(call)))
        raise SystemExit(1)
    t = t.replace(decl, decl + '// fuxi: CPU frequency domains (CpuFreqProbe.cpp, sheng-cpufreq=N); does nothing without the boot-arg.\n'
                  'extern "C" void sheng_cpufreq_probe(void);\n', 1)
    t = t.replace(call, call + '\tsheng_cpufreq_probe();\n', 1)
    f.write_text(t)
    print('late probe 加 sheng_cpufreq_probe: %s' % f)
    probe_hits += 1

print('\n=== 验证 ===')
for d in destinations:
    print('  %s : %d 行' % (d, len(d.read_text().split('\n'))))
print('  Ios17LegacyDisplayProbe.cpp: %d 个文件' % probe_hits)
print('  build-boot-progress.py 含 CpuFreqProbe: %s' % ('CpuFreqProbe' in script.read_text()))
