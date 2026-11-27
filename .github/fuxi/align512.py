#!/usr/bin/env python3
"""align512.py ADRENOMETAL_DIR : linear texture alignment at least 512 bytes (Claude + Gemini 2026-11-27).
CoreAnimation sizes the swap IOSurfaces from minimumLinearTextureAlignmentForPixelFormat:(BGRA8) = 256, so a 1179-wide
surface gets stride 4864. On the new GPU stack any stride that is not a multiple of 512 renders black (1152/4608 and
1280/5120 light, 1153..1216/4864 black). With 512 the 1179/1170 surfaces get stride 5120."""
import sys
from pathlib import Path
d = Path(sys.argv[1]) / 'bridge'
p = d / 'NativeMetalCapabilities.rs'; s = p.read_text()
a = '            .map_err(|e| format!("linear alignment: {e:?}"))?,\n        "deviceLinearReadOnlyTextureAlignmentBytes"'
assert s.count(a) == 1, 'capabilities anchor'
s = s.replace(a, '            .map_err(|e| format!("linear alignment: {e:?}"))?\n            .max(512),\n        "deviceLinearReadOnlyTextureAlignmentBytes"', 1)
p.write_text(s)
p = d / 'NativeMetalObjects.rs'; s = p.read_text()
a = '            .map_err(e("linear texture"))?;\n'
assert s.count(a) == 1, 'objects anchor'
s = s.replace(a, '            .map_err(e("linear texture"))?\n            .max(512);\n', 1)
p.write_text(s)
print('align512: minimumLinearTextureAlignmentForPixelFormat: and nmb_device_linear_bytes_per_row now >= 512')
