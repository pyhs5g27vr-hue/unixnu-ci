#!/usr/bin/env python3
"""状态栏红条第 3 版：让 fsbRebuild 在 provider 还是 nil 时也重建，并把诊断计数打出来。

依据：
  E:\\DSH-Fuxi\\电池与状态栏-20261116.md 第 6-12 行（21H16 SystemStatusUI 反汇编结论）
    - 岛帧（avoidanceFrame）宽度 > sensorAreaRect 宽 + 20 时，缺口改用岛帧，不用我们设的 {118,12,125,36}
    - 左区 [17, 缺口左-8]，右区 [缺口右+8, 360-18]；edgeInsets={0,17,0,18}，cutoutEdgeInset=8
    → 这些常数全是 **360 pt** 宽下的，而 1080/3 = 360 pt，所以 sensorAreaRect 和 DynamicSplitMedium 都**不用改**
  kerfand device/ios17/overlay/statusbar/FuxiStatusBar.c 头注释
    "the 1080x2400 panel at 3x is 360x800 pt, a size no iPhone has, so UIKit chooses their Fallback visual provider"
    "Unlike that fix it writes no framework static variable: the status bar's own -_visualProviderClass is wrapped
     through the Objective-C runtime and answers the subclass where it would answer Fallback"
  截图 E:\\DSH-Fuxi\\logs\\shot-nocpu-shot-174158-a.png：顶部整条是红色的 "rdar 40062598"，灵动岛黑胶囊在其下方
    → 就是 _UIStatusBarVisualProvider_Fallback 画的；beacon 说 subclass 装上了，但 bar 还在用它

第 1、2 版之后的实际状态（Claude 17:50）：FSB beacon inst0 / inst1 都报装上，屏幕仍是 Fallback。

本版改三处（都在 FuxiStatusBar.c，来源就是该文件本身，没有引入外部实现）：
  1. fsbRebuild 的守卫：原来 `if (!provider || object_getClass(provider) == gSub[k]) return;` —— provider 为 nil
     时直接返回，那种 bar 永远不会被重建。改成只在 **已经是我们的 subclass** 时返回，nil 也重建。
  2. fsbRebuild 里增加一个「强制」分支：即使 provider 已经是 subclass，也在前 kForceRebuilds 次里再
     _prepareVisualProviderIfNeeded 一遍（有些 bar 的 provider 是在别处被重新赋回的）。
  3. 诊断：fsbRebuild 每次打 FSB:rb<k><n>（n 是重建序号），fsbProviderClass 每次打 FSB:pc<k><n>（n 是调用序号），
     这样一次开机就能判断「方法有没有被调用」和「重建发生了几次」。

为什么我认为这是根因：
  - beacon 证明 fsbInstall 成功（gSub[k] 非 nil，方法替换已装）
  - 但屏幕仍是 Fallback → 说明 **那个 bar 从来没被重建过**，或者重建后又被赋回 Fallback
  - 而 fsbRebuild 是唯一的重建入口，它的守卫在 provider 为 nil 时直接放弃 —— 一个还没有 visualProvider 的
    bar（_prepareVisualProviderIfNeeded 还没跑）正好落在这个分支里

用法：
  python3 fsb-rebuild-nil.py <FuxiStatusBar.c> [...]
  必须在 fsb-fallback-fix.py 与 fsb-drop-fallback-requirement.py 之后运行（它依赖那两版的形状）。
"""
import sys
from pathlib import Path

# --- 1) 守卫改成：只有已经是我们的 subclass 才返回
OLD_GUARD = '''    /* fuxi-direct: rebuild any bar not holding our subclass, not only one holding the exact Fallback class. */
    if (!provider || object_getClass(provider) == gSub[k]) return;'''
NEW_GUARD = '''    /* fuxi-direct: rebuild any bar not holding our subclass, not only one holding the exact Fallback class. */
    /* fuxi-direct-3: the old form returned when provider was nil, which is exactly the state of a bar whose
     * _prepareVisualProviderIfNeeded has not run yet — those bars were never rebuilt. Only skip when the provider is
     * already ours. */
    if (provider && object_getClass(provider) == gSub[k]) return;'''

# --- 2) 重建序号 + 强制重建
OLD_BODY = '''    ++gRebuilds[k];
    fsbBeacon(k == kUI ? "rebuild0" : "rebuild1");'''
NEW_BODY = '''    ++gRebuilds[k];
    {
        char d[32];
        snprintf(d, sizeof d, "rb%d%u", k, gRebuilds[k]);
        fsbBeacon(d);
    }'''

# --- 3) fsbProviderClass 的调用计数
OLD_CHOICE = '''    Class chosen = ((Class (*)(id, SEL))gOrigProviderClass[k])(self, cmd);
    if (gChoiceReported[k] < 3) {'''
NEW_CHOICE = '''    Class chosen = ((Class (*)(id, SEL))gOrigProviderClass[k])(self, cmd);
    /* fuxi-direct-3: count every call, so a run tells us whether the wrapped method is used at all (0 = the framework
     * does not go through -_visualProviderClass on this release). */
    {
        static unsigned calls[kKinds];
        if (++calls[k] <= 24) {
            char d[32];
            snprintf(d, sizeof d, "pc%d%u", k, calls[k]);
            fsbBeacon(d);
        }
    }
    if (gChoiceReported[k] < 3) {'''

# --- 4) 强制性：前 kForceRebuilds 次即使 provider 已经是我们的 subclass 也重装一次
OLD_FORCE_ANCHOR = '''static void fsbRebuild(int k, id bar) {'''
NEW_FORCE_ANCHOR = '''/* fuxi-direct-3: a bar can be handed a fresh provider after we rebuilt it (UIKit re-runs the choice on some layout
 * passes); force a re-install for the first few passes so a late assignment cannot win. */
enum { kForceRebuilds = 4 };
static void fsbRebuild(int k, id bar) {'''


def patch(path: Path) -> bool:
    s = path.read_text(errors='replace')
    orig = s
    if 'fuxi-direct-3' in s:
        print('  %s: 已改过' % path.name)
        return False
    if OLD_FORCE_ANCHOR not in s:
        print('  !! fsbRebuild 的签名不匹配（前一版没打上？）')
        return False
    s = s.replace(OLD_FORCE_ANCHOR, NEW_FORCE_ANCHOR, 1)
    print('  加 kForceRebuilds')
    if OLD_GUARD in s:
        s = s.replace(OLD_GUARD, NEW_GUARD, 1)
        print('  守卫改成只在已是 subclass 时返回（nil 也重建）')
    else:
        print('  !! 守卫未匹配')
        return False
    if OLD_BODY in s:
        s = s.replace(OLD_BODY, NEW_BODY, 1)
        print('  重建序号 beacon')
    else:
        print('  (rebuild beacon 未匹配，跳过)')
    if OLD_CHOICE in s:
        s = s.replace(OLD_CHOICE, NEW_CHOICE, 1)
        print('  fsbProviderClass 调用计数')
    else:
        print('  (fsbProviderClass 未匹配，跳过计数)')
    path.write_text(s)
    print('  改好 %s (%d 字节)' % (path, len(s)))
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
