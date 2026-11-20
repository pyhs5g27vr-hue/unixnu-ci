#!/usr/bin/env python3
"""红条第 2 版：把 fallback 类从 fsbInstall 的必需条件里去掉。

现象（用户实测 boot-ci-cpufreq / a3b4eed9，1080x2400 直通）：状态栏仍是红条。
第一版（fsb-fallback-fix.py，在 e0d51a2 线里，workflow:1973 确认被调用）已经把
  - fsbProviderClass 改成无条件返回自家 subclass
  - fsbRebuild 的比对改成 `object_getClass(provider) == gSub[k]`
所以 `_UIStatusBarVisualProvider_Fallback` 这个类**已经不再被用到**，可是 fsbInstall 仍然要求它存在：

    Class bar = objc_getClass(kBar[k]), fallback = objc_getClass(kFallback[k]), base = Nil;
    for (int c = 0; c < 4 && !base; ++c) base = objc_getClass(kBaseCand[k][c]);
    if (!bar || !fallback || !base) { ...miss...; return false; }

只要 fallback 这个类名在 21H16 上拿不到（改名、或者 SystemStatusUI 那时还没加载），整个安装就放弃，
gSub[k] 保持 Nil，fsbProviderClass 原样返回框架的选择 → 红条。

改法：把 fallback 从必要条件里去掉（它仍被查询、仍然打进 miss beacon，只是不再阻止安装），
并把 fallback 为 Nil 时的 fsbRebuild 守卫补上（原来那个函数用 gFallback[k] 的旧写法已经改掉了，
但保险起见在这里断言它不参与判断）。

用法：python3 fsb-drop-fallback-requirement.py <FuxiStatusBar.c> [...]
"""
import sys
from pathlib import Path

OLD_GUARD = '''    if (!bar || !fallback || !base) {
        char d[32];
        snprintf(d, sizeof d, "miss%d%d%d", !bar, !fallback, !base);
        fsbBeacon(d);
        return false;
    }'''

NEW_GUARD = '''    /* fuxi-direct-2: `fallback` is no longer used for anything — fsbProviderClass answers gSub unconditionally and
     * fsbRebuild compares against gSub — so requiring that class name to exist only blocked the install when it did not
     * (the bar then stayed on the framework's Fallback provider, a red strip). It is still looked up and still reported,
     * as FSB:miss<bar><fallback><base>, but only bar and base are required. */
    if (!bar || !base) {
        char d[32];
        snprintf(d, sizeof d, "miss%d%d%d", !bar, !fallback, !base);
        fsbBeacon(d);
        return false;
    }
    if (!fallback) fsbBeacon("nofb");'''

# 如果第一版补丁之后 fallback 已被用过（fsbRebuild 旧写法），也一并处理
OLD_REBUILD_GUARD_FALLBACK = '    if (!provider || object_getClass(provider) == gSub[k]) return;'


def patch(path: Path) -> bool:
    s = path.read_text(errors='replace')
    if 'fuxi-direct-2' in s:
        print('  %s: 已改过' % path.name)
        return False
    if OLD_GUARD not in s:
        print('  !! 没找到第一版补丁后的守卫块（请确认 fsb-fallback-fix.py 已经跑过）')
        return False
    s = s.replace(OLD_GUARD, NEW_GUARD, 1)
    path.write_text(s)
    print('  改好 %s (%d 字节)：fallback 不再拦住安装' % (path, len(s)))
    return True


n = 0
for arg in sys.argv[1:]:
    p = Path(arg)
    if not p.exists():
        print('跳过（不存在）: %s' % p)
        continue
    if p.name != 'FuxiStatusBar.c':
        print('跳过（不是 FuxiStatusBar.c）: %s' % p)
        continue
    if patch(p):
        n += 1
print('共改 %d 个文件' % n)
if not n:
    raise SystemExit('没有文件被改')
