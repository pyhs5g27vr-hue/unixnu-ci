#!/usr/bin/env python3
"""状态栏红条 v4：hook 21H16 真正使用的 provider 选择入口（类方法）。

依据（先看文档，写清楚）：
  E:\\DSH-Fuxi\\logs\\sb16-list.txt 与 sb16-layout.txt（21H16 dyld cache 的 SystemStatusUI / UIKitCore 实测导出）：
    _UIStatusBarVisualProvider_DynamicSplit
        class ['baseFontSize', 'expandedFontSize', 'height', 'visualProviderSubclassForScreen:visualProviderInfo:']
    _UIStatusBarVisualProvider_Split
        class ['LTEAPlusFontSize', 'baseFontSize', 'expandedEdgeInset', 'expandedFontSize', 'height',
               'intrinsicContentSizeForOrientation:', 'scalesWithScreenNativeScale',
               'showsLargeBatteryChargingAnimation', 'shrinksSingleCharacterTypes',
               'visualProviderSubclassForScreen:visualProviderInfo:']
    _UIStatusBarVisualProvider_DynamicSplitMedium
        class ['baseFontSize', 'expandedFontSize']          ← 只有两个，选 provider 的方法靠继承
    STUIStatusBarVisualProvider_DynamicSplit / _Split    ← SystemStatusUI 里同样有这个方法
  也就是说：21H16 里含 "visualProvider" 的选择器**只有一个**，而且是**类方法**
  +visualProviderSubclassForScreen:visualProviderInfo:。

  E:\\DSH-Fuxi\\电池与状态栏-20261116.md 第 6-12 行：岛帧 / sensorAreaRect / 左右区居中的常数都是 360 pt 宽下的，
  而 1080/3 = 360 pt，所以 provider 与 sensorAreaRect 都不用改 —— 问题只在「选 provider 的入口」。

  实测（Claude 20:35 / 20:50 上机 boot-ci-fsb3.img 56257db6）：
    FSB:pc  0 条            → 21H16 根本不调实例方法 -_visualProviderClass（作者那版包的就是它）
    FSB:rb11..rb112 十几条  → 重建在反复执行，但每次重建后仍是 Fallback
  所以作者 FuxiStatusBar.c 的 hook 点在这版 iOS 上不对，必须包类方法。

本版只加不删：
  A) 声明 gOrigSubclass[kKinds] / gSubclassCalls[kKinds] 与 fsbProviderSubclass()；
  B) 在 fsbInstall 拿到 base 之后，把 base 继承到的类方法
     +visualProviderSubclassForScreen:visualProviderInfo: 换成我们的实现
     （class_getClassMethod 沿继承链找到父类 DynamicSplit 的那一个，改它即覆盖 DynamicSplitMedium）；
  C) 原返回值是 Fallback 或 Nil 时返回我们的子类，其它原样返回；
  D) 前 24 次调用打 FSB:vsc<k>:<类名或 nil>，用于确认这条新入口真的被调用。

用法（必须按 CI 顺序：sb-avoid → v1 → v2 → v3 → 本版）：
  python3 fsb-v4-subclass-hook.py <FuxiStatusBar.c> [...]
"""
import sys
from pathlib import Path

DECL = '''/* fuxi-v4: 21H16 选 provider 的入口是类方法 +visualProviderSubclassForScreen:visualProviderInfo:
 * （依据 logs/sb16-list.txt / sb16-layout.txt：_UIStatusBarVisualProvider_DynamicSplit 与 _Split 的
 * class 方法表里都有它，DynamicSplitMedium 只有 baseFontSize/expandedFontSize，靠继承）。
 * 作者那版包的是实例方法 -_visualProviderClass，21H16 不调它（FSB:pc 0 条），所以红条一直不变。
 * 这里包类方法：原返回值是 Fallback 或 Nil 时给我们的子类，其它原样返回。 */
static IMP gOrigSubclass[kKinds];
static unsigned gSubclassCalls[kKinds];
static Class fsbProviderSubclass(int k, id self, SEL cmd, id screen, id info)
{
    Class chosen = gOrigSubclass[k]
        ? ((Class (*)(id, SEL, id, id))gOrigSubclass[k])(self, cmd, screen, info) : Nil;
    if (++gSubclassCalls[k] <= 24) {
        char d[96];
        snprintf(d, sizeof d, "vsc%d:%s", k, chosen ? class_getName(chosen) : "nil");
        fsbBeacon(d);
    }
    if (!chosen || chosen == gFallback[k]) return gSub[k] ? gSub[k] : chosen;
    return chosen;
}
static Class fsbProviderSubclassUI(id self, SEL cmd, id s, id i) { return fsbProviderSubclass(kUI, self, cmd, s, i); }
static Class fsbProviderSubclassST(id self, SEL cmd, id s, id i) { return fsbProviderSubclass(kST, self, cmd, s, i); }

'''

ANCHOR_INSTALL = 'static bool fsbInstall(int k) {'

# 装在拿到 base 之后、构造 sub 之前（那时 base/gSub 语义都已明确）
ANCHOR_AFTER_BASE = '''    Class sub = objc_getClass(kSub[k]);'''

HOOK = '''    /* fuxi-v4: the real chooser on 21H16 is the class method below; wrap it on the base provider (DynamicSplit),
     * which DynamicSplitMedium inherits. class_getClassMethod walks the superclass chain, so this replaces the one
     * method both classes answer. */
    {
        SEL vsc = sel_registerName("visualProviderSubclassForScreen:visualProviderInfo:");
        Method subclassChooser = class_getClassMethod(base, vsc);
        /* Claude: fsbInstall is retried (kInstallTries) and can fail after this point; wrap only once, or the second
         * wrap would save our own function as the original and recurse. */
        if (gOrigSubclass[k]) {
        } else if (subclassChooser) {
            gOrigSubclass[k] = method_setImplementation(subclassChooser,
                k == kUI ? (IMP)fsbProviderSubclassUI : (IMP)fsbProviderSubclassST);
            fsbBeacon(k == kUI ? "vsc0in" : "vsc1in");
        } else {
            fsbBeacon(k == kUI ? "vsc0miss" : "vsc1miss");
        }
    }
    Class sub = objc_getClass(kSub[k]);'''


def patch(path: Path) -> bool:
    s = path.read_text(errors='replace')
    orig = s
    if 'fuxi-v4' in s:
        print('  %s: 已改过' % path.name)
        return False
    if ANCHOR_INSTALL not in s:
        print('  !! fsbInstall 的签名不匹配')
        return False
    if ANCHOR_AFTER_BASE not in s:
        print('  !! "Class sub = objc_getClass(kSub[k]);" 不匹配（v1 没打上？）')
        return False
    s = s.replace(ANCHOR_INSTALL, DECL + ANCHOR_INSTALL, 1)
    print('  插入 gOrigSubclass / fsbProviderSubclass')
    s = s.replace(ANCHOR_AFTER_BASE, HOOK, 1)
    print('  fsbInstall 里挂上类方法 hook')
    if s != orig:
        path.write_text(s)
        print('  改好 %s (%d 字节)' % (path, len(s)))
        return True
    return False


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
