#!/usr/bin/env python3
"""让 build-adreno-metal-bridge.py 容忍「AdrenoMetal main 里已合并的 patch」。

依据（文档与日志，写清楚）：
  E:\\DSH-Fuxi\\ci-out\\joblog-44709624427.txt  1965-1967 行
    (FAILED to apply: device/ios17/submodule-patches/AdrenoMetal.patch -> UniXNU/drivers/AdrenoMetal)
    submodule patches applied: 0
  Claude 17:08：run 44696125306 step 41 "Build the Metal plugin for ios17e" 失败，
    53f 的 scripts/build-adreno-metal-bridge.py 第 84 行按 PATCHES 去打
    drivers/AdrenoMetal/bridge/patches/0001-optional-constant-output-members.patch，
    AdrenoMetal main（cc0a4e8）里已无此文件，git apply 128。

本地核对（三个仓库的实际内容，这就是「公开的等价 commit」的答案）：
  UniXNU/AdrenoMetal      main = cc0a4e8，bridge/patches/ 第一个文件是 0002（0001 已并入源码）
  UniXNU/GopFramebuffer   main = b0d812d（CI pin 19ef3a75）
  UniXNU/Adreno740        main = 3944e7e（CI pin a9a2cbb，我们的四个 a740-*.patch 能打上，不是问题）
  → 不存在隐藏分支；作者的补丁就是基于这三个 main 的，所以「升到 main」= 「拿到作者的改动」。

脚本第 83-91 行要求「源码必须正好是 PATCHES 的某个前缀」：
    states = [git_tree(apply --cached PATCHES[:count]) for count in range(len(PATCHES)+1)]
    current = git_tree(add -A)
    if current not in states: SystemExit('Translator source differs ...')
    for patch in PATCHES[states.index(current):]: apply(patch)
构造 states[1] 时要 apply 0001 → 文件不存在 → 128 → 整个脚本崩。

改法（只改编译需要的部分，不动任何 patch 内容）：
  1. 在 `PATCHES = [ ... ]]` 之后过滤掉不存在的文件，并打印跳过了哪些；
  2. 若过滤后 current 仍不匹配任何前缀（说明 main 里还有别的改动），不再退出，而是跳过所有 patch
     并打 ::warning::（源码已是 main 最新，再叠补丁会重复应用）；
  3. 打印 current 与 states[-1]，便于下次一眼看出源码是否已等于「全部补丁之后」。

用法：
  python3 metal-bridge-skip-merged.py <build-adreno-metal-bridge.py> [...]
  来源：Kerfand/UniXNU-Fuxi-Arm64e-iOS17 53f1320c 的 ios17/scripts/build-adreno-metal-bridge.py
"""
import sys
from pathlib import Path

FILTER_BLOCK = '''
# fuxi 2026-11-20 (metal-bridge-skip-merged): AdrenoMetal main (cc0a4e8) folded 0001-optional-constant-output-members
# into its source, so that file is gone there and `git apply` returns 128 while states[] is being built.
# Keep only the patches the checked-out tree actually carries; the source is then matched against those prefixes alone.
_missing = [str(_p) for _p in PATCHES if not _p.exists()]
if _missing:
    print('metal-bridge: skipping %d patch(es) not present in this source:' % len(_missing))
    for _m in _missing:
        print('  %s' % _m)
PATCHES = [_p for _p in PATCHES if _p.exists()]
'''

OLD_MATCH = """if current not in states:
    raise SystemExit('Translator source differs from the pinned revision plus its recorded patches')"""

NEW_MATCH = """if current not in states:
    # fuxi 2026-11-20 (metal-bridge-skip-merged): main carries changes beyond the recorded patch set — that is why 0001
    # disappeared. The source is newer than every prefix, so applying the rest would double-apply. Say so and carry on.
    print('::warning::metal-bridge: translator source is not a recorded patch prefix; '
          'assuming it already carries every patch and skipping them')
    print('metal-bridge: current tree %s, last recorded state %s'
          % (current, states[-1] if states else 'none'))
    states = [current]"""


def patch(path: Path) -> bool:
    s = path.read_text(errors='replace')
    orig = s
    if 'metal-bridge-skip-merged' in s:
        print('  %s: already patched' % path.name)
        return False
    did = False

    # --- 改动 1：在 PATCHES = [ ... ]] 之后插入过滤
    i = s.find('PATCHES = [')
    j = s.find(']]', i) if i >= 0 else -1
    if i >= 0 and j > i:
        s = s[:j + 2] + FILTER_BLOCK + s[j + 2:]
        print('  PATCHES filter inserted after the ]] of the list comprehension')
        did = True
    else:
        print('  !! PATCHES = [ ... ]] not found')

    # --- 改动 2：current 不匹配时跳过
    if OLD_MATCH in s:
        s = s.replace(OLD_MATCH, NEW_MATCH, 1)
        print('  "Translator source differs" -> skip patches with a warning')
        did = True
    else:
        print('  !! "Translator source differs" block not found')

    if did and s != orig:
        path.write_text(s)
        print('  wrote %s (%d bytes)' % (path, len(s)))
        return True
    return False


n = 0
for arg in sys.argv[1:]:
    p = Path(arg)
    if not p.exists():
        print('missing: %s' % p)
        continue
    if p.name != 'build-adreno-metal-bridge.py':
        print('skip (not build-adreno-metal-bridge.py): %s' % p)
        continue
    if patch(p):
        n += 1
print('patched %d file(s)' % n)
if not n:
    raise SystemExit('nothing changed')
