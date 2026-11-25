#!/usr/bin/env python3
"""metalup2-port-fixed.py: Port UniXNU b04f131 GPU build scripts + 26 Mesa patches with full ios17e support.

Fixes over dump/deepseek/metalup2-port.py:
  1. Copies scripts/check-metal-runtime-interface.py (required by b04f131 build-adreno-metal-bridge.py:55).
  2. Patches ios17e into scripts/build-turnip-darwin.py (choices, OUT, sdk/triple, and Kerfand's -Wl,-fixup_chains
     for 21H16 dyld withChainStarts 512 KB thread-stack overflow fix).
  3. Uses Kerfand's IOS17E/ARM64E split in scripts/build-adreno-metal-plugin.py so:
     - PAC boundary & arm64e Mach-O subtype=2 run for ios17e (via ARM64E),
     - Info.plist MinimumOSVersion stays '17.0' (via IOS27 = ios27/macos27 only, NOT '27.0'!),
     - -DNATIVE_ADRENO_IOS17_ARM64E=1 is passed (guards iPadOS 27 24A446 hardcoded QuartzCore addresses).

Usage:
  python3 metalup2-port-fixed.py <target scripts dir> <unixnu-main git dir> [ref=b04f131]
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

if len(sys.argv) < 3:
    raise SystemExit('usage: metalup2-port-fixed.py <target scripts dir> <unixnu-main git dir> [ref]')

DST = Path(sys.argv[1]).resolve()
SRC = Path(sys.argv[2]).resolve()
REF = sys.argv[3] if len(sys.argv) > 3 else 'b04f131'

print('target:', DST)
print('source:', SRC, '@', REF)


def blob(rel: str) -> bytes:
    r = subprocess.run(['git', '-C', str(SRC), 'show', f'{REF}:{rel}'], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f'cannot read {REF}:{rel}\n{r.stderr.decode()[:300]}')
    return r.stdout


# 0. Verify source structure
probe = blob('scripts/build-adreno-metal-bridge.py').decode()
if 'PATCHES = [ROOT' not in probe:
    raise SystemExit('unexpected build-adreno-metal-bridge.py layout; expected b04f131 or newer')

# 1. Copy 7 scripts + data files
FILES = [
    'scripts/build-adreno-metal-bridge.py',
    'scripts/build-adreno-metal-plugin.py',
    'scripts/build-turnip-darwin.py',
    'scripts/macho-self-bind-weak-imports.py',
    'scripts/check-metal-runtime-interface.py',
    'scripts/data/gpu-metal-vulkan-inputs.json',
    'scripts/data/adreno-compiler-inputs.json',
]
for rel in FILES:
    data = blob(rel)
    d = DST / rel[len('scripts/'):]
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_bytes(data)
    print(f'  copy {rel[len("scripts/"):]:44s} {len(data):7d} B')

# 2. Copy all patches/mesa/*.patch
listing = subprocess.check_output(
    ['git', '-C', str(SRC), 'ls-tree', '-r', '--name-only', REF, '--', 'patches/mesa'],
    text=True,
).split()
mesa_dst = DST.parent / 'patches' / 'mesa'
mesa_dst.mkdir(parents=True, exist_ok=True)
n_mesa = 0
for rel in listing:
    if not rel.endswith('.patch'):
        continue
    (mesa_dst / Path(rel).name).write_bytes(blob(rel))
    n_mesa += 1
print(f'  copy patches/mesa/*.patch ({n_mesa} files) -> {mesa_dst}')


def patch_target(text: str, name: str, replacements: list[tuple[str, str, str]]) -> str:
    for anchor, repl, note in replacements:
        if repl in text:
            print(f'  {name}: {note} (already present)')
            continue
        cnt = text.count(anchor)
        if cnt != 1:
            raise SystemExit(f'{name}: anchor count={cnt} for {note}\n  anchor={anchor!r}')
        text = text.replace(anchor, repl, 1)
        print(f'  {name}: {note}')
    return text


# 3a. Patch build-adreno-metal-bridge.py
BP = DST / 'build-adreno-metal-bridge.py'
BP.write_text(patch_target(BP.read_text(), 'bridge', [
    (
        "parser.add_argument('--target', choices=['ios', 'ios27', 'macos27', 'host'], default='ios')",
        "parser.add_argument('--target', choices=['ios', 'ios27', 'macos27', 'ios17e', 'host'], default='ios')",
        '--target choices + ios17e',
    ),
    (
        "'macos27': 'arm64e-apple-darwin', 'host': 'aarch64-apple-darwin'}[args.target]",
        "'macos27': 'arm64e-apple-darwin', 'ios17e': 'arm64e-apple-ios', 'host': 'aarch64-apple-darwin'}[args.target]",
        'triple + ios17e -> arm64e-apple-ios',
    ),
    (
        "ARM64E = args.target in ('ios27', 'macos27')",
        "ARM64E = args.target in ('ios27', 'macos27', 'ios17e')",
        'ARM64E + ios17e',
    ),
]))

# 3b. Patch build-turnip-darwin.py (including Kerfand -Wl,-fixup_chains for 21H16 dyld)
TP = DST / 'build-turnip-darwin.py'
TP.write_text(patch_target(TP.read_text(), 'turnip', [
    (
        "parser.add_argument('--target', choices=('host', 'ios', 'ios27', 'macos27'), default='host')",
        "parser.add_argument('--target', choices=('host', 'ios', 'ios27', 'macos27', 'ios17e'), default='host')",
        '--target choices + ios17e',
    ),
    (
        "OUT = ROOT / {'host': 'build/mesa-tu', 'ios': 'build/mesa-tu-ios', 'ios27': 'build/mesa-tu-ios27', 'macos27': 'build/mesa-tu-macos27'}[args.target]",
        "OUT = ROOT / {'host': 'build/mesa-tu', 'ios': 'build/mesa-tu-ios', 'ios27': 'build/mesa-tu-ios27', 'macos27': 'build/mesa-tu-macos27', 'ios17e': 'build/mesa-tu-ios17e'}[args.target]",
        'OUT + ios17e -> build/mesa-tu-ios17e',
    ),
    (
        "if args.target in ('ios', 'ios27', 'macos27'):",
        "if args.target in ('ios', 'ios27', 'macos27', 'ios17e'):",
        'cross block + ios17e',
    ),
    (
        "triple = {'ios': 'arm64-apple-ios17.0', 'ios27': 'arm64e-apple-ios27.0', 'macos27': 'arm64e-apple-macos27.0'}[args.target]",
        "triple = {'ios': 'arm64-apple-ios17.0', 'ios27': 'arm64e-apple-ios27.0', 'macos27': 'arm64e-apple-macos27.0', 'ios17e': 'arm64e-apple-ios17.0'}[args.target]",
        'triple + ios17e -> arm64e-apple-ios17.0',
    ),
    (
        "        ''.join('%s = %r\\n' % (k, flags) for k in ('c_args', 'cpp_args', 'objc_args', 'c_link_args', 'cpp_link_args',\n"
        "                                                    'objc_link_args')))\n"
        "    setup += ['--cross-file', cross]",
        "        ''.join('%s = %r\\n' % (k, flags) for k in ('c_args', 'cpp_args', 'objc_args')) +\n"
        "        # ios17e: chained fixups (21H16 dyld withChainStarts 512 KB stack overflow fix).\n"
        "        ''.join('%s = %r\\n' % (k, flags + (['-Wl,-fixup_chains'] if args.target == 'ios17e' else []))\n"
        "                for k in ('c_link_args', 'cpp_link_args', 'objc_link_args')))\n"
        "    setup += ['--cross-file', cross]\n"
        "    if args.target == 'ios17e':\n"
        "        options += ['-D%s=%r' % (k, flags + ['-Wl,-fixup_chains']) for k in ('c_link_args', 'cpp_link_args', 'objc_link_args')]",
        'ios17e -Wl,-fixup_chains',
    ),
]))

# 3c. Patch build-adreno-metal-plugin.py (IOS17E / ARM64E split, keeping MinimumOSVersion='17.0')
PL = DST / 'build-adreno-metal-plugin.py'
PL.write_text(patch_target(PL.read_text(), 'plugin', [
    (
        "parser.add_argument('--target', choices=('ios', 'ios27', 'macos27'), default='ios')",
        "parser.add_argument('--target', choices=('ios', 'ios27', 'macos27', 'ios17e'), default='ios')",
        '--target choices + ios17e',
    ),
    (
        "IOS27 = args.target in ('ios27', 'macos27')\n"
        "OUT = ROOT / 'build' / {'ios': 'adreno-metal-plugin', 'ios27': 'adreno-metal-plugin27', 'macos27': 'adreno-metal-plugin-macos27'}[args.target]",
        "IOS27 = args.target in ('ios27', 'macos27')\n"
        "IOS17E = args.target == 'ios17e'\n"
        "ARM64E = IOS27 or IOS17E\n"
        "OUT = ROOT / 'build' / {'ios': 'adreno-metal-plugin', 'ios27': 'adreno-metal-plugin27', 'macos27': 'adreno-metal-plugin-macos27', 'ios17e': 'adreno-metal-plugin17e'}[args.target]",
        'IOS17E/ARM64E split + OUT ios17e',
    ),
    (
        "'ios27': 'arm64e-apple-ios27.0', 'macos27': 'arm64e-apple-macos27.0'}[args.target]",
        "'ios27': 'arm64e-apple-ios27.0', 'macos27': 'arm64e-apple-macos27.0', 'ios17e': 'arm64e-apple-ios17.0'}[args.target]",
        'clang -target + ios17e',
    ),
    (
        "        '-fstack-protector-strong']\n",
        "        '-fstack-protector-strong']\n"
        "if IOS17E:\n"
        "    base += ['-Wno-unknown-warning-option', '-Wno-unused-but-set-global', '-DNATIVE_ADRENO_IOS17_ARM64E=1']\n",
        'IOS17E -DNATIVE_ADRENO_IOS17_ARM64E=1',
    ),
    (
        "if IOS27:\n    objcopy =",
        "if ARM64E:\n    objcopy =",
        'PAC objcopy guard -> ARM64E',
    ),
    (
        "if IOS27:\n    subprocess.run([sys.executable, ROOT / 'scripts/rust-pac-rewrite.py'",
        "if ARM64E:\n    subprocess.run([sys.executable, ROOT / 'scripts/rust-pac-rewrite.py'",
        'rust-pac-rewrite guard -> ARM64E',
    ),
    (
        "assert (magic, cputype, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 2 if IOS27 else 0), 'expected an arm64e (27) or ARM64 (17) Mach-O'",
        "assert (magic, cputype, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 2 if ARM64E else 0), 'expected an arm64e (27, 17e) or ARM64 (17) Mach-O'",
        'arm64e Mach-O subtype check -> ARM64E',
    ),
]))

# 4. Self-checks
print('\n=== self-check ===')
for p in (BP, TP, PL, DST / 'check-metal-runtime-interface.py'):
    src = p.read_text()
    ast.parse(src)
    print(f'  {p.name:36s} ast.parse OK ({len(src)} B)')

pt = PL.read_text()
assert "IOS27 = args.target in ('ios27', 'macos27')" in pt, 'IOS27 must NOT contain ios17e (keeps MinimumOSVersion=17.0)'
assert "ARM64E = IOS27 or IOS17E" in pt, 'ARM64E missing'
assert "'MinimumOSVersion': '27.0' if IOS27 else '17.0'" in pt, 'MinimumOSVersion check changed'
assert "-DNATIVE_ADRENO_IOS17_ARM64E=1" in pt, 'NATIVE_ADRENO_IOS17_ARM64E missing'
tt = TP.read_text()
assert "'ios17e': 'build/mesa-tu-ios17e'" in tt, 'turnip OUT ios17e missing'
assert "-Wl,-fixup_chains" in tt, 'turnip -Wl,-fixup_chains missing'
m = re.search(r'PATCHES = \[.*?\]', BP.read_text(), re.S)
assert m and m.group(0).count('.patch') == 0, 'bridge PATCHES expected empty on b04f131'
print('  ALL CHECKS PASSED (MinimumOSVersion=17.0 for ios17e, ARM64E PAC on, Turnip fixup_chains on, PATCHES=0)')
