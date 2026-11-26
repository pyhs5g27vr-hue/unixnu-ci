#!/usr/bin/env python3
"""fuxi-xr550-fallback.py (v2): .github/fuxi/ anchor script for NativeBridgeMetalFrontend.mm (b25e48e5).

When nmb_render_pipeline_new_with_options() refuses a pipeline whose color attachments use any
Apple extended-range 10-bit format (550..555: RGB10A8_2P_XR10[_sRGB], BGR10_XR[_sRGB],
BGRA10_XR[_sRGB]) — e.g. QuartzCore WarmupShaders framebuffer-fetch pipelines refused by
metal2vulkan 87a869f7 — retry once with those color attachments remapped to
MTLPixelFormatRGBA16Float (115).

v2 changes vs v1 (0a15c15):
- Expand 550/551 -> 550..555 (covers BGR10_XR 552/553 and BGRA10_XR 554/555 from WarmupShaders).
- Do NOT call noteProblem() when fallback succeeds, so we don't burn kernel fuxi_note_logged<64
  slots before COM3 opens (v1 burned 3 ok-notes + 5 refusal-notes = 8/launch * 8 = 64!).

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
    '  for(unsigned i=0;i<8;i++){if(p->colors[i].format>=550 && p->colors[i].format<=555){p->colors[i].format=115;xrFallback=true;}}\n'
    '  if(xrFallback) {\n'
    '   handle=nmb_render_pipeline_new_with_options(gDevice,p,&creation);\n'
    '   if(!handle)noteProblem([NSString stringWithFormat:@"fallback xr550..555->115 fail frag %@",d.fragmentFunction.name]);\n'
    '  }\n'
    ' }\n'
)

def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <NativeBridgeMetalFrontend.mm>")
    p = Path(sys.argv[1])
    s = p.read_text(encoding="utf-8")
    if 'xr550..555->115' in s:
        print(f"xr550-fallback: already patched (v2) {p}")
        return
    cnt = s.count(ANCHOR)
    assert cnt == 1, f"{p}: expected anchor count==1, got {cnt}"
    p.write_text(s.replace(ANCHOR, REPLACEMENT, 1), encoding="utf-8")
    print(f"xr550-fallback: patched v2 {p} (1/1 anchor)")

if __name__ == "__main__":
    main()
