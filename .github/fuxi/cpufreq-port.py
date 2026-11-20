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

# ---------------------------------------------------- 2) sheng_cpu_idle_mach
IDLE_FUNC = '''
/*
 * Board CPU governor helper: a CPU's idle time so far in mach absolute time units (recount brings it up to now
 * while the CPU idles), for board code that cannot see struct processor. 0 for a CPU number without a processor.
 */
uint64_t sheng_cpu_idle_mach(int cpu);
uint64_t
sheng_cpu_idle_mach(int cpu)
{
	processor_t p = cpu_to_processor(cpu);
	if (p == PROCESSOR_NULL) {
		return 0;
	}
	struct recount_usage usage = {};
	uint64_t idle = 0;
	recount_processor_usage(&p->pr_recount, &usage, &idle);
	return idle;
}
'''

patched = 0
for proc in WS.rglob('osfmk/kern/processor.c'):
    t = proc.read_text(errors='replace')
    if 'sheng_cpu_idle_mach' in t:
        print('跳过（已有）: %s' % proc)
        patched += 1
        continue
    # 追加到文件末尾（作者补丁的位置就是末尾的 #endif 之后）
    proc.write_text(t + IDLE_FUNC)
    print('追加 sheng_cpu_idle_mach: %s' % proc)
    patched += 1
if not patched:
    print('!! 没找到 osfmk/kern/processor.c（XNU 树可能还没展开）')

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
        command += ['-xc++', '-std=gnu++17', '-fno-exceptions', '-fno-rtti',
                    '-I', str(ROOT / '.cache/xnu-work/iokit'),
                    '-I', str(ROOT / '.cache/xnu-work/iokit/IOKit'),
                    '-I', str(ROOT / '.cache/xnu-work/osfmk'),
                    '-I', str(ROOT / '.cache/xnu-work/bsd'),
                    '-I', str(ROOT / '.cache/xnu-work/libkern'),
                    '-I', str(ROOT / '.cache/xnu-work/pexpert'),
                    '-I', str(ROOT / 'kits/sheng')]
        subprocess.run(command, cwd=record['directory'], check=True, timeout=180)
        return destination
    cpufreq_obj = compile_cxx_like(policy_record, cpufreq_source, OUT / 'CpuFreqProbe.o')
    print('   built CpuFreqProbe.o')
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

print('\n=== 验证 ===')
for d in destinations:
    print('  %s : %d 行' % (d, len(d.read_text().split('\n'))))
print('  processor.c 补丁: %d 个文件' % patched)
print('  build-boot-progress.py 含 CpuFreqProbe: %s' % ('CpuFreqProbe' in script.read_text()))
