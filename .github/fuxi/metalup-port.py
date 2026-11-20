#!/usr/bin/env python3
"""metalup：把上游 main（8542980）配套 AdrenoMetal cc0a4e8 的 bridge 三件套搬进 CI，并补回 ios17e。

**依据（全部实测，不是推断）**

Claude 00:10：「本地有 /root/fuxi/unixnu-main」。我核了：

  /root/fuxi/unixnu-main @ 8542980「docs: refresh device records」
      scripts/build-adreno-metal-bridge.py   11765 字节  170 行  PATCHES 2 项  PIN 46e7cc96
      scripts/build-adreno-metal-plugin.py   16040 字节  197 行  有 argparse
      scripts/data/gpu-metal-vulkan-inputs.json         translator.commit = 46e7cc96a284150bdf19b4a6a7890b0a8bc0ef71

  /root/fuxi/ci-new（CI 现在用的）
      scripts/build-adreno-metal-bridge.py   10891 字节  143 行  PATCHES 24 项  PIN 624bab39
      scripts/build-adreno-metal-plugin.py   11247 字节  133 行  无 argparse
      scripts/data/gpu-metal-vulkan-inputs.json         translator.commit = 624bab3918de5b978e1101517abca2b4fa426565

  upstream dec111b6（我们的 unixnu_base）与 GitHub 上的 main 都是 10891/24/624bab39 —— 和 ci-new 相同。

所以「metalup 要搬的是 unixnu-main（8542980）的三件套」，而不是「上游 main」（那和现在一样）。

**为什么 0004 打不上**（这才是真因）
  cc0a4e8 的 bridge/patches/ 有 31 个稀疏补丁。unixnu-main 的 PATCHES 只列 2 项：
      0063-main-optimizations-on-development-46e7cc96.patch   ← 累积补丁，已含 0004 的 prune_entry
      0064-copies-leave-unreachable-pages-alone.patch
  而 ci-new 的 24 项表里既有 0004 又没有 0063 —— 在 cc0a4e8 上 0004 的 hunk
  (@@ -557,6 +557,7 @@ pub fn specialize_dynamic() 的 context 已经被 translator 的更新移走，
  所以 git apply 失败、整个 bridge 构建崩。换 unixnu-main 的 2 项表就没有这个冲突。
  PIN 也从 624bab39 变成 46e7cc96（正是 0063 文件名里那个 sha）。

**ios17e 要补在哪**（unixnu-main 的两份脚本都没有它）
  bridge: choices / triple / ARM64E / target_dir        4 处
  plugin: choices / IOS27 / OUT / base 的 -target / BRIDGE_TARGET      5 处
  （IPHONEOS_DEPLOYMENT_TARGET 那行 `'27.0' if args.target == 'ios27' else '17.0'` 不用改：
   ios17e 走 else，正好是 17.0。）

**用法**
  python3 metalup-port.py <目标 scripts 目录> <unixnu-main 目录>
  例：python3 metalup-port.py device-ios17/scripts /root/fuxi/unixnu-main
  它会复制三件套、打 ios17e、并自检（括号/关键字符串/ast.parse）。
"""
import json
import shutil
import sys
from pathlib import Path

if len(sys.argv) < 3:
    raise SystemExit('用法: metalup-port.py <目标 scripts 目录> <unixnu-main 目录>')
DST = Path(sys.argv[1]).resolve()
SRC = Path(sys.argv[2]).resolve()
print('目标:', DST)
print('来源:', SRC)

if not (SRC / 'scripts/build-adreno-metal-bridge.py').exists():
    raise SystemExit('来源里没有 scripts/build-adreno-metal-bridge.py — 确认它是 unixnu-main（8542980）')

# ---------------------------------------------------------------- 1. 复制三件套
FILES = [
    'scripts/build-adreno-metal-bridge.py',
    'scripts/build-adreno-metal-plugin.py',
    'scripts/data/gpu-metal-vulkan-inputs.json',
]
for rel in FILES:
    s = SRC / rel
    d = DST / rel[8:] if rel.startswith('scripts/') else DST / rel
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(s, d)
    print('  搬 %-42s %d 字节' % (rel.replace('scripts/', ''), d.stat().st_size))

# ---------------------------------------------------------------- 2. 补 ios17e（bridge）
BP = DST / 'build-adreno-metal-bridge.py'
t = BP.read_text()
orig = t

if 'ios17e' in t:
    print('  bridge: 已经有 ios17e，跳过')
else:
    # (a) choices
    a = "parser.add_argument('--target', choices=['ios', 'ios27', 'macos27', 'host'], default='ios')"
    b = "parser.add_argument('--target', choices=['ios', 'ios27', 'macos27', 'ios17e', 'host'], default='ios')"
    if a not in t:
        raise SystemExit('bridge: --target choices 锚点不匹配')
    t = t.replace(a, b, 1)
    print('  bridge: --target 加了 ios17e')

    # (b) triple
    a = "'macos27': 'arm64e-apple-darwin', 'host': 'aarch64-apple-darwin'}[args.target]"
    b = "'macos27': 'arm64e-apple-darwin', 'ios17e': 'arm64e-apple-ios', 'host': 'aarch64-apple-darwin'}[args.target]"
    if a not in t:
        raise SystemExit('bridge: triple 锚点不匹配（打印实际的那行给我）')
    t = t.replace(a, b, 1)
    print('  bridge: triple 加了 ios17e -> arm64e-apple-ios')

    # (c) ARM64E
    a = "ARM64E = args.target in ('ios27', 'macos27')"
    b = ("ARM64E = args.target in ('ios27', 'macos27', 'ios17e')"
         "   # ios17e: iOS 17 arm64e (iPhone15,2 21H16 render server)")
    if a not in t:
        raise SystemExit('bridge: ARM64E 锚点不匹配')
    t = t.replace(a, b, 1)
    print('  bridge: ARM64E 加了 ios17e')

    # (d) target_dir（可选，找不到不致命）
    if "target_dir = ROOT / 'build/m2v-target'" in t:
        t = t.replace("target_dir = ROOT / 'build/m2v-target'",
                      "target_dir = ROOT / ('build/m2v-target-ios17e' if args.target == 'ios17e' else 'build/m2v-target')", 1)
        print('  bridge: target_dir 给 ios17e 独立目录')
    else:
        print('  bridge: target_dir 那行的写法不同，未改（不影响功能）')

if t != orig:
    BP.write_text(t)
    print('  bridge: 写出 %d 字节' % len(t))

# ---------------------------------------------------------------- 3. 补 ios17e（plugin）
PP = DST / 'build-adreno-metal-plugin.py'
p = PP.read_text()
porig = p

if 'ios17e' in p:
    print('  plugin: 已经有 ios17e，跳过')
else:
    # (a) choices
    a = "parser.add_argument('--target', choices=('ios', 'ios27', 'macos27'), default='ios')"
    b = "parser.add_argument('--target', choices=('ios', 'ios27', 'macos27', 'ios17e'), default='ios')"
    if a not in p:
        raise SystemExit('plugin: --target choices 锚点不匹配')
    p = p.replace(a, b, 1)
    print('  plugin: --target 加了 ios17e')

    # (b) IOS27 -> 复用 arm64e
    a = "IOS27 = args.target in ('ios27', 'macos27')"
    b = "ARM64E_TARGET = args.target in ('ios27', 'macos27', 'ios17e')\nIOS27 = ARM64E_TARGET"
    if a not in p:
        raise SystemExit('plugin: IOS27 锚点不匹配')
    p = p.replace(a, b, 1)
    print('  plugin: IOS27 复用 arm64e 分支（含 ios17e）')

    # (c) OUT
    a = "'macos27': 'adreno-metal-plugin-macos27'}[args.target]"
    b = "'macos27': 'adreno-metal-plugin-macos27', 'ios17e': 'adreno-metal-plugin-ios17e'}[args.target]"
    if a in p:
        p = p.replace(a, b, 1)
        print('  plugin: OUT 给 ios17e 独立目录')
    else:
        print('  plugin: OUT 那行写法不同，未改')

    # (d) base 的 -target
    a = "'macos27': 'arm64e-apple-macos27.0'}[args.target]"
    b = "'macos27': 'arm64e-apple-macos27.0', 'ios17e': 'arm64e-apple-ios17.0'}[args.target]"
    if a in p:
        p = p.replace(a, b, 1)
        print('  plugin: -target 给 ios17e 用 arm64e-apple-ios17.0')
    else:
        print('  plugin: -target 那行写法不同，未改')

    # (e) BRIDGE_TARGET
    #  unixnu-main 的写法是 `BRIDGE_TARGET = args.target`（:68）—— 它已经自动转发，不需要改。
    #  ci-new 的旧写法是 `BRIDGE_TARGET = 'ios27' if IOS27 else 'ios'`，那种才要改。
    if 'BRIDGE_TARGET = args.target' in p:
        print('  plugin: BRIDGE_TARGET = args.target（已自动转发 ios17e，不改）')
    else:
        for a, b in [
            ("BRIDGE_TARGET = 'ios27' if IOS27 else 'ios'",
             "BRIDGE_TARGET = 'ios17e' if args.target == 'ios17e' else ('ios27' if IOS27 else 'ios')"),
            ("BRIDGE_TARGET = 'ios27' if args.target in ('ios27', 'macos27') else 'ios'",
             "BRIDGE_TARGET = args.target if args.target in ('ios17e',) else ('ios27' if IOS27 else 'ios')"),
        ]:
            if a in p:
                p = p.replace(a, b, 1)
                print('  plugin: BRIDGE_TARGET 转发 ios17e')
                break
        else:
            print('  !! plugin: BRIDGE_TARGET 的写法没认出来，请手工看 :68')

if p != porig:
    PP.write_text(p)
    print('  plugin: 写出 %d 字节' % len(p))

# ---------------------------------------------------------------- 4. 自检
print('\n=== 自检 ===')
ok = True
for label, path, keys in [
    ('bridge', BP, ['ios17e', "'ios17e': 'arm64e-apple-ios'", "('ios27', 'macos27', 'ios17e')",
                    '0063-main-optimizations-on-development-46e7cc96.patch']),
    ('plugin', PP, ['ios17e', "'ios17e': 'arm64e-apple-ios17.0'", 'adreno-metal-plugin-ios17e']),
]:
    s = path.read_text()
    print('%s (%d 字节):' % (label, len(s)))
    for k in keys:
        n = s.count(k)
        mark = 'OK ' if n else '!! '
        print('    %s%-52s %d' % (mark, k, n))
        if not n:
            ok = False
    # 语法检查
    import ast
    try:
        ast.parse(s)
        print('    OK  ast.parse')
    except SyntaxError as e:
        print('    !!  ast.parse: %s' % e)
        ok = False

j = DST / 'data/gpu-metal-vulkan-inputs.json'
if j.exists():
    d = json.loads(j.read_text())
    pin = d.get('translator', {}).get('commit')
    print('inputs.json  translator.commit = %s  %s' % (pin, 'OK' if pin == '46e7cc96a284150bdf19b4a6a7890b0a8bc0ef71' else '!! 不是 46e7cc96'))

print('\n结论: %s' % ('全部就绪' if ok else '有未命中的项，看上面的 !! 行'))
raise SystemExit(0 if ok else 1)
