#!/usr/bin/env python3
"""fuxi-metal-table-note.py : .github/fuxi/ anchor script for AdrenoMetal (b25e48e5).

1) NativeAdrenoMetalPlugin.mm (streamTelemetry, gated by row=1 / SHENG_STATUS=1):
   At pass == 3 (~23s) and pass == 8 (~53s), forward key [metal table] summary rows
   ("F ", "W ", "Wb ", "S ", "SA ", "N ") to COM3 via native_bridge_metal_note()
   (<=10 rows/pass, <=20 notes total, well within per-process fuxiSent<32 and kernel <256 caps).

2) NativeBridgeMetalFrontend.mm (refuseSurface):
   Release gProblemLock before calling noteProblem() for the first 3 IOSurface texture refusals,
   reporting step (1..5), IOSurface/descriptor pixel formats, planes, dimensions, offset, row, fbo.

Usage:
  python3 fuxi-metal-table-note.py <NativeAdrenoMetalPlugin.mm> <NativeBridgeMetalFrontend.mm>
"""
from pathlib import Path
import sys

PLUGIN_ANCHOR = '            if (pass % 5 == 0) os_log(OS_LOG_DEFAULT, "NativeAdrenoMetal table: %{public}s", line);\n'
PLUGIN_REPLACEMENT = (
    '            if (pass % 5 == 0) os_log(OS_LOG_DEFAULT, "NativeAdrenoMetal table: %{public}s", line);\n'
    '            if ((pass == 3 || pass == 8) && (strncmp(line, "S ", 2) == 0 || strncmp(line, "SA ", 3) == 0 ||\n'
    '                strncmp(line, "F ", 2) == 0 || strncmp(line, "W ", 2) == 0 || strncmp(line, "Wb ", 3) == 0 ||\n'
    '                strncmp(line, "N ", 2) == 0)) {\n'
    '                char fuxiRow[112];\n'
    '                snprintf(fuxiRow, sizeof fuxiRow, "fuxi-tbl p%u: %.90s", pass, line);\n'
    '                native_bridge_metal_note(fuxiRow);\n'
    '            }\n'
)

FRONTEND_ANCHOR = (
    ' std::lock_guard<std::mutex> lock(gProblemLock);gSurfaceLastRefusal=r;\n'
    '}\n'
)
FRONTEND_REPLACEMENT = (
    ' { std::lock_guard<std::mutex> lock(gProblemLock); gSurfaceLastRefusal=r; }\n'
    ' static std::atomic<int> fuxiSurfRefused{0};\n'
    ' if(fuxiSurfRefused.fetch_add(1)<3)\n'
    '  noteProblem([NSString stringWithFormat:@"fuxi surf-refuse step=%u sfmt=%#x dfmt=%u pl=%u/%u %lux%lu surf=%lux%lu off=%llu row=%llu fbo=%u",\n'
    '               r.step,r.format,r.pixelFormat,r.plane,r.planes,(unsigned long)r.width,(unsigned long)r.height,\n'
    '               (unsigned long)r.surfaceWidth,(unsigned long)r.surfaceHeight,(unsigned long long)r.offset,(unsigned long long)r.row,r.framebufferOnly?1u:0u]);\n'
    '}\n'
)


def patch_one(path: Path, marker: str, anchor: str, repl: str, label: str) -> None:
    s = path.read_text(encoding="utf-8")
    if marker in s:
        print(f"metal-table-note: already patched [{label}] {path}")
        return
    cnt = s.count(anchor)
    assert cnt == 1, f"{path} [{label}]: expected anchor count==1, got {cnt}"
    path.write_text(s.replace(anchor, repl, 1), encoding="utf-8")
    print(f"metal-table-note: patched [{label}] {path} (1/1 anchor)")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <NativeAdrenoMetalPlugin.mm> <NativeBridgeMetalFrontend.mm>")
    patch_one(Path(sys.argv[1]), "fuxi-tbl p%u:", PLUGIN_ANCHOR, PLUGIN_REPLACEMENT, "plugin streamTelemetry")
    patch_one(Path(sys.argv[2]), "fuxi surf-refuse", FRONTEND_ANCHOR, FRONTEND_REPLACEMENT, "frontend refuseSurface")


if __name__ == "__main__":
    main()
