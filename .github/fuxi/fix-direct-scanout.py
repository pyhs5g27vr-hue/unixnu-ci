#!/usr/bin/env python3
"""fuxi 2026-11-25: Restore 53f direct-scanout behavior on grandslam (607cb00).

Why:
- 53f kernels (next3 / next4m, run 44862903945) ran 597..7366 direct-scanout flips without reset.
- Grandslam kernels (Kerfand f0ae963b: v4-direct120, v4-direct-pure, r2-direct, smooth-dir)
  hard-reset without panic 1.5..4 s after SpringBoard starts scanning directSlots (0x12000000..0x16000000).
- Differences targeted here:
  1. GopFramebuffer: reset commits 0004..0010 back to 0003 (dropping SMMU FSR/FAR reads/clears on latch,
     250ms MDP MMIO heartbeat reads, 1s idle directToBoot flips, and 100k per-flip serial logs),
     keep 0009's directToBoot() console-stride fix, restore sheng-vsync-fixed=0 default (as in 53f/82e),
     and apply upstream df4a905 fence-wait & cancellation reset fix.
  2. Adreno740: in single-ring mode (!g.submit->preemption()), keep native_adreno_fences() lock-free via
     g.ring->lastSubmitted() / fenceValue() as in 53f instead of failing IOLockTryLock(g.lock)
     ("submitted 0 retired 0" seen in smooth-dir & r2-direct).

Usage: fix-direct-scanout.py <UniXNU/drivers/GopFramebuffer> <UniXNU/drivers/Adreno740>
"""
import pathlib
import subprocess
import sys


def git_dirty(repo: pathlib.Path) -> bool:
    out = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True)
    return bool(out.strip())


def patch_gop(gop_dir: pathlib.Path) -> None:
    # 1. Reset 0004..0010 back to 0003 if present
    log_out = subprocess.check_output(
        ['git', '-C', str(gop_dir), 'log', '--format=%H %s', '-n', '20'],
        text=True,
    )
    target_sha = None
    already = False
    for line in log_out.splitlines():
        sha, _, subj = line.partition(' ')
        if 'fuxi: 53f direct scanout' in subj:
            already = True
            break
        if 'fuxi: start direct scanout from the frames once' in subj:
            target_sha = sha
            break

    if not already:
        assert target_sha, f'commit 0003 not found in {gop_dir}:\n{log_out}'
        subprocess.run(['git', '-C', str(gop_dir), 'reset', '--hard', target_sha], check=True)
        print(f'{gop_dir}: reset back to 0003 ({target_sha[:8]})')
    else:
        print(f'{gop_dir}: already reset to 0003+df4a905')

    nld = gop_dir / 'NativeLegacyDisplay.cpp'
    s = nld.read_text(encoding='utf-8', errors='surrogateescape')

    # 2. Restore sheng-vsync-fixed=0 default (match 53f / 82e)
    old_vs = 'unsigned locked=1;PE_parse_boot_argn("sheng-vsync-fixed",&locked,sizeof(locked));   // fuxi: fixed by default'
    new_vs = 'unsigned locked=0;PE_parse_boot_argn("sheng-vsync-fixed",&locked,sizeof(locked));   // fuxi: 0 by default (match 53f)'
    if new_vs not in s:
        assert s.count(old_vs) == 1, f'sheng-vsync-fixed anchor count={s.count(old_vs)}'
        s = s.replace(old_vs, new_vs, 1)

    # 3. Keep 0009's directToBoot() console-stride fix (without 1s idle-return experiment)
    old_boot = '    void directToBoot() {\n        if(!directOn || directBoot)return;\n        flip(kBootIova,kBootStride);directBoot=true;shownSlot=-1;'
    new_boot = (
        '    void directToBoot() {\n'
        '        if(!directOn || directBoot)return;\n'
        '        PE_Video video={};const uint32_t stride=!PE_current_console(&video) && video.v_rowBytes?uint32_t(video.v_rowBytes):kBootStride;\n'
        '        flip(kBootIova,stride);directBoot=true;shownSlot=-1;'
    )
    if new_boot not in s:
        assert s.count(old_boot) == 1, f'directToBoot anchor count={s.count(old_boot)}'
        s = s.replace(old_boot, new_boot, 1)

    # 4. Apply df4a905 (0008) direct fence-wait & cancellation reset cleanly onto 0003
    if 'fenceCaptured' not in s:
        old_fields = '    uint64_t fenceSince=0;\n    IOTimerEventSource *fenceTimer=nullptr;'
        new_fields = (
            '    uint64_t fenceSince=0;\n'
            '    bool fenceCaptured=false,fenceSlow=false;   // upstream df4a905: keep first fence snapshot; 250ms no longer flips\n'
            '    IOTimerEventSource *fenceTimer=nullptr;'
        )
        assert s.count(old_fields) == 1, f'fields anchor count={s.count(old_fields)}'
        s = s.replace(old_fields, new_fields, 1)

        old_fn = (
            '    bool gpuWrote(const OriginalLegacySwapRequest *request) {\n'
            '        uint32_t submitted=0,retired=0;\n'
            '        if(!&native_adreno_fences || !native_adreno_fences(&submitted,&retired))return true;\n'
            '        if(fenceFor!=request) {\n'
            '            fenceFor=request;fenceTarget=submitted;fenceSince=0;\n'
            '        }\n'
            '        if(int32_t(retired-fenceTarget)>=0) {'
        )
        new_fn = (
            '    bool gpuWrote(const OriginalLegacySwapRequest *request) {\n'
            '        if(fenceFor!=request) {\n'
            '            fenceFor=request;fenceTarget=0;fenceSince=0;fenceCaptured=false;fenceSlow=false;\n'
            '        }\n'
            '        uint32_t submitted=0,retired=0;\n'
            '        if(!&native_adreno_fences)return true;\n'
            '        const bool known=native_adreno_fences(&submitted,&retired);\n'
            '        if(known && !fenceCaptured) {fenceTarget=submitted;fenceCaptured=true;}\n'
            '        if(known && fenceCaptured && int32_t(retired-fenceTarget)>=0) {'
        )
        assert s.count(old_fn) == 1, f'gpuWrote head anchor count={s.count(old_fn)}'
        s = s.replace(old_fn, new_fn, 1)

        old_250 = (
            '        if(ns>=250000000ull) {\n'
            '            native_legacy_direct[12]=native_legacy_direct[12]+1;\n'
            '            fenceFor=nullptr;return true;\n'
            '        }'
        )
        new_250 = (
            '        if(ns>=250000000ull && !fenceSlow) {\n'
            '            native_legacy_direct[12]=native_legacy_direct[12]+1;\n'
            '            fenceSlow=true;\n'
            '        }'
        )
        assert s.count(old_250) == 1, f'250ms anchor count={s.count(old_250)}'
        s = s.replace(old_250, new_250, 1)

        old_cancel = (
            '    bool cancelSwapsAfterTimeout() override {\n'
            '        native_legacy_swap_timeouts=native_legacy_swap_timeouts+1;\n'
            '        for(auto &entry: validated)entry=nullptr;'
        )
        new_cancel = (
            '    bool cancelSwapsAfterTimeout() override {\n'
            '        native_legacy_swap_timeouts=native_legacy_swap_timeouts+1;\n'
            '        if(fenceTimer)fenceTimer->cancelTimeout();\n'
            '        fenceFor=nullptr;fenceTarget=0;fenceSince=0;fenceCaptured=false;fenceSlow=false;\n'
            '        for(auto &entry: validated)entry=nullptr;'
        )
        assert s.count(old_cancel) == 1, f'cancel anchor count={s.count(old_cancel)}'
        s = s.replace(old_cancel, new_cancel, 1)

    nld.write_text(s, encoding='utf-8', errors='surrogateescape')
    if git_dirty(gop_dir):
        subprocess.run(
            ['git', '-C', str(gop_dir), 'add', 'NativeLegacyDisplay.cpp'],
            check=True,
        )
        subprocess.run(
            ['git', '-C', str(gop_dir), '-c', 'user.name=ci', '-c', 'user.email=ci@localhost',
             'commit', '-q', '-m', 'fuxi: 53f direct scanout (drop 0004-0007/0009-idle/0010, keep df4a905 + stride, vsync-fixed=0)'],
            check=True,
        )
    print(f'{gop_dir}: patched NativeLegacyDisplay.cpp OK')


def patch_adreno(a740_dir: pathlib.Path) -> None:
    pub = a740_dir / 'NativeAdrenoPublish.cpp'
    s = pub.read_text(encoding='utf-8', errors='surrogateescape')
    if 'fuxi: lock-free single-ring native_adreno_fences' not in s:
        old = (
            'extern "C" bool native_adreno_fences(uint32_t *submitted,uint32_t *retired)\n'
            '{\n'
            '    return native_adreno_fences_detail(submitted,retired,nullptr);\n'
            '}'
        )
        new = (
            'extern "C" bool native_adreno_fences(uint32_t *submitted,uint32_t *retired)\n'
            '{\n'
            '    /* fuxi: lock-free single-ring native_adreno_fences (match 53f): avoid IOLockTryLock contention causing submitted=0/retired=0 */\n'
            '    if(g.published && g.submit && !g.submit->preemption() && g.ring && submitted && retired) {\n'
            '        uint32_t value=0;\n'
            '        if(!g.ring->fenceValue(&value)) {\n'
            '            *submitted=g.ring->lastSubmitted();\n'
            '            *retired=value;\n'
            '            return true;\n'
            '        }\n'
            '    }\n'
            '    return native_adreno_fences_detail(submitted,retired,nullptr);\n'
            '}'
        )
        assert s.count(old) == 1, f'native_adreno_fences anchor count={s.count(old)}'
        pub.write_text(s.replace(old, new, 1), encoding='utf-8', errors='surrogateescape')
    if (a740_dir / '.git').exists() and git_dirty(a740_dir):
        subprocess.run(
            ['git', '-C', str(a740_dir), 'add', 'NativeAdrenoPublish.cpp'],
            check=True,
        )
        subprocess.run(
            ['git', '-C', str(a740_dir), '-c', 'user.name=ci', '-c', 'user.email=ci@localhost',
             'commit', '-q', '-m', 'fuxi: lock-free single-ring native_adreno_fences'],
            check=True,
        )
    print(f'{pub}: patched lock-free single-ring native_adreno_fences OK')


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f'usage: {sys.argv[0]} <GopFramebuffer-dir> <Adreno740-dir>')
    patch_gop(pathlib.Path(sys.argv[1]))
    patch_adreno(pathlib.Path(sys.argv[2]))


if __name__ == '__main__':
    main()
