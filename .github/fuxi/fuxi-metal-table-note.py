#!/usr/bin/env python3
"""fuxi-metal-table-note.py (v3, Claude 11-26 22:10, from Gemini v2):
the [metal table] rows to COM3 over the one channel proven to reach it, streamText7 -> GpuPowerProbe "gpu report:".

Gemini v2 channel A (context.link.method(NativeAdrenoMethodNote, ...)) is dropped: NativeAdrenoAbiNote / NativeAdrenoMethodNote /
NativeAdrenoNoteWords are not defined in the AdrenoMetal user-space tree (compile error), and context.link is the 0x4148 scanout
client, not the publish client that handles Note.

1) NativeMetalBridgePhase.h serveScanout: at st.frames >= 900 the key table rows (S SA F SR P0 P1 W Wb N ROT) are cut into
   chunks of at most 58 chars ("T<i>:" prefix, 63-char streamText7 limit) - at most 32 chunks; one chunk replaces the PF line
   every 300 frames (> the probe's 2 s poll), PF resumes after the last one. A second snapshot at frames >= 6000.
2) NativeBridgeMetalFrontend.mm refuseSurface: the first 3 refusals go to noteProblem (lock released first), as in v1.

Usage: python3 fuxi-metal-table-note.py <NativeMetalBridgePhase.h> <NativeBridgeMetalFrontend.mm>
"""
from pathlib import Path
import sys

PHASE_ANCHOR = (
    '            uint64_t reportedFrames = 0, reportedFailures = 0;\n'
    '            while (client.serveOne(500)) {\n'
    '                const bool frame = st.frames && (st.frames == 1 || st.frames - reportedFrames >= 5);\n'
    '                if (frame || (st.failures && !reportedFailures)) {\n'
)

PHASE_REPLACEMENT = (
    '            uint64_t reportedFrames = 0, reportedFailures = 0;\n'
    '            static char fuxiChunk[32][64];\n'
    '            unsigned fuxiChunks = 0, fuxiNext = 0, fuxiSnap = 0;\n'
    '            uint64_t fuxiShownAt = 0;\n'
    '            while (client.serveOne(500)) {\n'
    '                if ((fuxiSnap == 0 && st.frames >= 900) || (fuxiSnap == 1 && st.frames >= 6000 && fuxiNext >= fuxiChunks)) {\n'
    '                    ++fuxiSnap; fuxiChunks = 0; fuxiNext = 0;\n'
    '                    static char fuxiTbl[8192];\n'
    '                    fuxiTbl[0] = 0;\n'
    '                    native_bridge_metal_telemetry(fuxiTbl, sizeof fuxiTbl);\n'
    '                    for (char *p = fuxiTbl; *p && fuxiChunks < 32; ) {\n'
    '                        char *nl = strchr(p, \'\\n\');\n'
    '                        if (nl) *nl = 0;\n'
    '                        if (!strncmp(p, "S ", 2) || !strncmp(p, "SA ", 3) || !strncmp(p, "F ", 2) || !strncmp(p, "SR ", 3) ||\n'
    '                            !strncmp(p, "P0 ", 3) || !strncmp(p, "P1 ", 3) || !strncmp(p, "W ", 2) || !strncmp(p, "Wb ", 3) ||\n'
    '                            !strncmp(p, "N ", 2) || !strncmp(p, "ROT ", 4)) {\n'
    '                            const size_t len = strlen(p);\n'
    '                            for (size_t off = 0; off < len && fuxiChunks < 32; off += 58, ++fuxiChunks)\n'
    '                                snprintf(fuxiChunk[fuxiChunks], sizeof fuxiChunk[0], "T%u%c%.58s", fuxiChunks, off ? \'+\' : \':\', p + off);\n'
    '                        }\n'
    '                        if (!nl) break;\n'
    '                        p = nl + 1;\n'
    '                    }\n'
    '                    if (!fuxiChunks) snprintf(fuxiChunk[fuxiChunks++], sizeof fuxiChunk[0], "T0:none f%llu", (unsigned long long)st.frames);\n'
    '                    fuxiShownAt = 0;\n'
    '                }\n'
    '                if (fuxiNext < fuxiChunks) {\n'
    '                    if (!fuxiShownAt || st.frames >= fuxiShownAt + 300) {\n'
    '                        streamText7(gpu, fuxiChunk[fuxiNext++]);\n'
    '                        fuxiShownAt = st.frames;\n'
    '                    }\n'
    '                    continue;\n'
    '                }\n'
    '                if (fuxiShownAt && st.frames < fuxiShownAt + 300) continue;\n'
    '                const bool frame = st.frames && (st.frames == 1 || st.frames - reportedFrames >= 5);\n'
    '                if (frame || (st.failures && !reportedFailures)) {\n'
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
        sys.exit(f"usage: {sys.argv[0]} <NativeMetalBridgePhase.h> <NativeBridgeMetalFrontend.mm>")
    patch_one(Path(sys.argv[1]), "fuxiChunk[32][64]", PHASE_ANCHOR, PHASE_REPLACEMENT, "phase serveScanout")
    patch_one(Path(sys.argv[2]), "fuxi surf-refuse", FRONTEND_ANCHOR, FRONTEND_REPLACEMENT, "frontend refuseSurface")


if __name__ == "__main__":
    main()
