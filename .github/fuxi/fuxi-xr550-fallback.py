#!/usr/bin/env python3
"""fuxi-xr550-fallback.py : .github/fuxi/ anchor script for NativeBridgeMetalFrontend.mm (b25e48e5).

When nmb_render_pipeline_new_with_options() refuses a pipeline whose color attachments use
MTLPixelFormatRGB10A8_2P_XR10 (550) or MTLPixelFormatRGB10A8_2P_XR10_sRGB (551)
(e.g. QuartzCore WarmupShaders luma_boost_lph with framebuffer fetch), retry once with
550/551 remapped to MTLPixelFormatRGBA16Float (115) and emit a COM3 metal-note via noteProblem().

Usage:
  python3 fuxi-xr550-fallback.py <path/to/NativeBridgeMetalFrontend.mm>
"""
from pathlib import Path
import sys

ANCHOR = ' NmbRenderPipeline *handle=nmb_render_pipeline_new_with_options(gDevice,p,&creation);gTimePipeline.add(pipelineBegan);\n'
REPLACEMENT = (
    ' NmbRenderPipeline *handle=nmb_render_pipeline_new_with_options(gDevice,p,&creation);gTimePipeline.add(pipelineBegan);\n'
    ' if(!handle) {\n'
    '  bool xrFallback=false;\n'
    '  for(unsigned i=0;i<8;i++){if(p->colors[i].format==550 || p->colors[i].format==551){p->colors[i].format=115;xrFallback=true;}}\n'
    '  if(xrFallback) {\n'
    '   handle=nmb_render_pipeline_new_with_options(gDevice,p,&creation);\n'
    '   noteProblem([NSString stringWithFormat:@"fallback 550->115 %s frag %@",handle?"ok":"fail",d.fragmentFunction.name]);\n'
    '  }\n'
    ' }\n'
)

def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <NativeBridgeMetalFrontend.mm>")
    p = Path(sys.argv[1])
    s = p.read_text(encoding="utf-8")
    if 'fallback 550->115' in s:
        print(f"xr550-fallback: already patched {p}")
        return
    cnt = s.count(ANCHOR)
    assert cnt == 1, f"{p}: expected anchor count==1, got {cnt}"
    p.write_text(s.replace(ANCHOR, REPLACEMENT, 1), encoding="utf-8")
    print(f"xr550-fallback: patched {p} (1/1 anchor)")

if __name__ == "__main__":
    main()
