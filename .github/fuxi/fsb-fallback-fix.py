#!/usr/bin/env python3
"""让 FuxiStatusBar 在 1080x2400 下也装上（方案 B）。

问题：1080x2400 面板在 3x 下是 360x800 pt，不是任何 iPhone 的尺寸，UIKit 选它的 Fallback provider
（只画红条）。原代码只在 `chosen == Fallback` 时换成自己的 subclass —— 如果框架答的不是那个确切
的类（或者 Fallback 类名在 17.7 变了），就永远装不上。

改动：
1. fsbProviderClass 无条件返回 subclass（只要有），不再比对类名
2. fsbRebuild 的守卫反过来：provider 不是我们的 subclass 就重建
3. kBase / kFallback 改成候选链，取第一个存在的
4. fsbInstall 失败时用 beacon 打出缺哪个类，便于上机诊断

用法：python3 fsb-fallback-fix.py <FuxiStatusBar.c> [...]
"""
import sys
from pathlib import Path


def patch(path: Path) -> bool:
    s = path.read_text(errors='replace')
    orig = s

    # ---------------------------------------------- 1) 候选链取代单一类名
    old_base = ('static const char *const kBase[kKinds] = '
                '{"_UIStatusBarVisualProvider_DynamicSplitMedium", "STUIStatusBarVisualProvider_DynamicSplitMedium"};')
    new_base = '''/* fuxi-direct: the 1080x2400 panel at 3x is 360x800 pt, which no iPhone has, so the framework answers its
 * Fallback provider (a red strip). Try the 1080-wide provider first, then narrower ones, so a release that lacks one
 * of them still gets a Split-family bar instead of the strip. */
static const char *const kBaseCand[kKinds][4] = {
    {"_UIStatusBarVisualProvider_DynamicSplitMedium", "_UIStatusBarVisualProvider_DynamicSplit",
     "_UIStatusBarVisualProvider_Split", "_UIStatusBarVisualProvider_Phone"},
    {"STUIStatusBarVisualProvider_DynamicSplitMedium", "STUIStatusBarVisualProvider_DynamicSplit",
     "STUIStatusBarVisualProvider_Split", "STUIStatusBarVisualProvider_Phone"},
};
static Class gBase[kKinds];'''
    if old_base in s:
        s = s.replace(old_base, new_base, 1)
    else:
        print('  !! kBase 声明未匹配')

    # ---------------------------------------------- 2) fsbProviderClass 无条件替换
    old_ret = 'return (chosen == gFallback[k] && gSub[k]) ? gSub[k] : chosen;'
    new_ret = '''/* fuxi-direct: answer our subclass whatever the framework chose. The panel's 360x800 pt is not a size any iPhone
     * has, so the framework answers Fallback (a red strip) and a comparison against that one class name is what kept the
     * bar red on the direct-scanout build; the subclass already carries referenceScreenScale 3 and the island rect. */
    return gSub[k] ? gSub[k] : chosen;'''
    if old_ret in s:
        s = s.replace(old_ret, new_ret, 1)
    else:
        print('  !! fsbProviderClass 返回值未匹配')

    # ---------------------------------------------- 3) fsbRebuild 守卫反过来
    old_g = ('    if (!provider || object_getClass(provider) != gFallback[k]) return;')
    new_g = ('    /* fuxi-direct: rebuild any bar not holding our subclass, not only one holding the exact Fallback class. */\n'
             '    if (!provider || object_getClass(provider) == gSub[k]) return;')
    if old_g in s:
        s = s.replace(old_g, new_g, 1)
    else:
        print('  !! fsbRebuild 守卫未匹配')

    # ---------------------------------------------- 4) fsbInstall 加诊断 + 候选链
    old_install_head = '''    Class bar = objc_getClass(kBar[k]), fallback = objc_getClass(kFallback[k]), base = objc_getClass(kBase[k]);
    if (!bar || !fallback || !base) return false;'''
    new_install_head = '''    Class bar = objc_getClass(kBar[k]), fallback = objc_getClass(kFallback[k]), base = Nil;
    for (int c = 0; c < 4 && !base; ++c) base = objc_getClass(kBaseCand[k][c]);
    /* fuxi-direct: nothing is version-specific here beyond the names, so a miss is reported as a beacon
     * (FSB:miss<b><f><B>; the kernel's IOKit probe logs FSB lookups when unixnu-iokit-probe=1). */
    if (!bar || !fallback || !base) {
        char d[32];
        snprintf(d, sizeof d, "miss%d%d%d", !bar, !fallback, !base);
        fsbBeacon(d);
        return false;
    }'''
    if old_install_head in s:
        s = s.replace(old_install_head, new_install_head, 1)
    else:
        print('  !! fsbInstall 头部未匹配')

    # gBase 记录下来，供调试
    old_assign = '    gBar[k] = bar; gFallback[k] = fallback; gSub[k] = sub;'
    new_assign = '    gBar[k] = bar; gFallback[k] = fallback; gSub[k] = sub; gBase[k] = base;'
    if old_assign in s:
        s = s.replace(old_assign, new_assign, 1)
    else:
        print('  !! gBar 赋值未匹配')

    # 记下 base 的类名，上机一看就知道用的哪个 provider
    old_installed = '    fsbBeacon(k == kUI ? "installed0" : "installed1");'
    new_installed = '''    {
        char d[96];
        snprintf(d, sizeof d, "inst%d:%s", k, class_getName(base));
        fsbBeacon(d);
    }
    fsbBeacon(k == kUI ? "installed0" : "installed1");'''
    if old_installed in s:
        s = s.replace(old_installed, new_installed, 1)
    else:
        print('  !! installed beacon 未匹配')

    if s == orig:
        print('  %s: 无改动' % path)
        return False
    path.write_text(s)
    print('  改好 %s (%d 字节)' % (path, len(s)))
    return True


n = 0
for arg in sys.argv[1:]:
    p = Path(arg)
    if not p.exists():
        print('跳过（不存在）: %s' % p)
        continue
    if patch(p):
        n += 1
print('共改 %d 个文件' % n)
if not n:
    raise SystemExit('没有任何文件被改，检查锚点')
