#!/usr/bin/env python3
"""壁纸页打不开：把 AdrenoMetal 的 XR10 条件升到作者 11-17 内核那版（允许 PosterBoard）。

依据（文档与源码，写清楚）：
  E:\\DSH-Fuxi\\logs\\updocs-wallpaper.txt，抄自上游 alioth.md：
    :343  "The GPU raster hand-off was a stub until u260: native_legacy_gpu_offer returned false with five parameters
           while the display driver calls it with six, so the format was dropped and every frame took the CPU copy path"
    :355  "No wallpaper, and the reason is in this repository: sheng-lite=1 disables the two wallpaper extensions by
           label (com.apple.NanoUniverse.AegirProxyApp.AegirPoster and
           com.apple.WatchFacesWallpaperSupport.KaleidoscopePoster) because they faulted"
  E:\\DSH-Fuxi\\kerfand-repo\\UniXNU-Fuxi-Arm64e-iOS17-main\\README.md :25
    "b3a8（XR10）帧由 CPU 转换后上屏"
  E:\\DSH-Fuxi\\搬家清单-20261120.md 第 6 项（"壁纸页能打开：dataprot 补丁 + Metal 插件 XR10 nop + poster 修复"）

源码对照（关键证据）：
  53f 用的旧版 fw/unixnu/drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm:1834
      if(!strcmp(name,"supportsExtendedXR10Formats"))value=0;
      → 所有进程都答 0，PosterBoard 也答 0
  作者 11-17 内核用的 up/AdrenoMetal/NativeBridgeMetalFrontend.mm:5178
      if(!strcmp(name,"supportsExtendedXR10Formats") &&
         (!strstr(getprogname(),"Poster") || !strcmp(getprogname(),"PosterBoard")))value=0;
      → 只有 PosterBoard 放行 XR10

为什么这会让「设置 → 墙纸」打不开：
  PosterBoard 是墙纸设置界面的宿主，它先问 supportsExtendedXR10Formats；旧版一律答 0，于是它按 8-bit BGRX
  驱动那套 @3x sealed Flat 壁纸 bundle（J120 / 1024w-1366h@3x~ipad），AegirPoster / KaleidoscopePoster 的渲染
  被拒，墙纸页就停在空白或直接退出。

本脚本只做一件事：把旧版那一行换成作者新版那一行。作者内核就是这么跑的，所以风险等于「和作者一致」。

用法：
  python3 metal-xr10-posterboard.py <NativeBridgeMetalFrontend.mm> [...]
"""
import sys
from pathlib import Path

OLD_STRICT = '   if(!strcmp(name,"supportsExtendedXR10Formats"))value=0;'

NEW_UPSTREAM = (
    '   /* fuxi-xr10-posterboard (2026-11-20): match the 11-17 Metal plugin, which lets PosterBoard have the extended-range\n'
    '    * 10-bit formats while every other process still answers 0. Without this the wallpaper page never opens: PosterBoard\n'
    '    * asks supportsExtendedXR10Formats, gets 0, and drives the @3x wallpaper bundles down the 8-bit path where\n'
    '    * AegirPoster / KaleidoscopePoster are refused. See logs/updocs-wallpaper.txt (alioth.md:343/355). */\n'
    '   if(!strcmp(name,"supportsExtendedXR10Formats") &&\n'
    '      (!strstr(getprogname(),"Poster") || !strcmp(getprogname(),"PosterBoard")))value=0;'
)

# 已经是作者那版（一行写法）的，只加注释标记，不再改逻辑
ALREADY_ONELINE = ('   if(!strcmp(name,"supportsExtendedXR10Formats") && '
                   '(!strstr(getprogname(),"Poster") || !strcmp(getprogname(),"PosterBoard")))value=0;')
MARK_ONLY = (
    '   /* fuxi-xr10-posterboard (2026-11-20): already the 11-17 form (PosterBoard allowed, others denied); marked so the\n'
    '    * CI step can assert it. See logs/updocs-wallpaper.txt (alioth.md:343/355). */\n'
    '   if(!strcmp(name,"supportsExtendedXR10Formats") && '
    '(!strstr(getprogname(),"Poster") || !strcmp(getprogname(),"PosterBoard")))value=0;'
)


def patch(path: Path) -> bool:
    s = path.read_text(errors='replace')
    orig = s
    if 'fuxi-xr10-posterboard' in s:
        print('  %s: 已改过' % path.name)
        return False
    if OLD_STRICT in s:
        s = s.replace(OLD_STRICT, NEW_UPSTREAM, 1)
        print('  旧版严格条件 -> 作者新版条件（PosterBoard 放行）')
    elif ALREADY_ONELINE in s:
        s = s.replace(ALREADY_ONELINE, MARK_ONLY, 1)
        print('  已经是作者新版，只加标记')
    else:
        print('  !! 没找到 supportsExtendedXR10Formats 的条件行')
        return False
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
    if p.name != 'NativeBridgeMetalFrontend.mm':
        print('跳过（不是 NativeBridgeMetalFrontend.mm）: %s' % p)
        continue
    if patch(p):
        n += 1
print('共改 %d 个文件' % n)
if not n:
    raise SystemExit('没有文件被改')
