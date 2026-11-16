#!/usr/bin/env python3
"""fuxi status bar (2026-11-16): the DynamicSplit provider moves its cutout to the status bar's avoidance frame (SpringBoard's system
aperture) whenever that frame is wider than the sensor + 20 pt. On this panel that frame is not the island (measured x 74..242,
centre 158), which put the time about 18 pt left of the left ear's centre and the battery 5 pt left of the right ear's.
The FuxiStatusBar subclass now hands its superclass an empty frame, so the cutout always follows -sensorAreaRect; the first two
frames seen are reported as FSB:avoid beacons.
Usage: sb-avoid-edit.py FuxiStatusBar.c [...]  (edits in place; refuses a file whose anchors are missing)"""
import sys
BLOCK = r'''
// fuxi 2026-11-16: ignore the aperture frame (see the CI step "fuxi status bar centring").
typedef bool (*FsbNeedsUpdate)(id, SEL, FsbRect, double *, double *);
static FsbNeedsUpdate gOrigNeedsUpdate[2];
static int gAvoidReported[2];
static bool fsbNeedsUpdate(int k, id self, SEL cmd, FsbRect frame, double *offset, double *width) {
    if (gAvoidReported[k] < 2 && frame.w > 0) {
        char what[96];
        snprintf(what, sizeof what, "avoid%d:%.1f,%.1f,%.1f,%.1f", k, frame.x, frame.y, frame.w, frame.h);
        ++gAvoidReported[k]; fsbBeacon(what);
    }
    return gOrigNeedsUpdate[k](self, cmd, (FsbRect){0, 0, 0, 0}, offset, width);
}
static bool fsbNeedsUpdateUI(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(0, self, cmd, f, o, w); }
static bool fsbNeedsUpdateST(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(1, self, cmd, f, o, w); }
'''
SEL = '"_needsUpdateOfConstraintsForAvoidanceFrame:cutoutOffset:cutoutWidth:"'
A1 = 'static FsbRect fsbSensorAreaRect(id self, SEL cmd) { (void)self; (void)cmd; return (FsbRect){118, 12, 125, 36}; }\n'
A2 = '    Class sub = objc_getClass(kSub[k]);\n'
A2_ADD = ('    SEL needs = sel_registerName(%s);\n'
          '    if (class_getInstanceMethod(base, needs)) gOrigNeedsUpdate[k] = (FsbNeedsUpdate)class_getMethodImplementation(base, needs);\n' % SEL)
A3 = '        class_addMethod(sub, sel_registerName("sensorAreaRect"), (IMP)fsbSensorAreaRect, "{CGRect={CGPoint=dd}{CGSize=dd}}16@0:8");\n'
A3_ADD = ('        if (gOrigNeedsUpdate[k]) class_addMethod(sub, needs, k == kUI ? (IMP)fsbNeedsUpdateUI : (IMP)fsbNeedsUpdateST,'
          ' "B64@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16^d48^d56");\n')
for p in sys.argv[1:]:
    s = open(p).read()
    if 'fsbNeedsUpdate' in s:
        print(p, 'already patched'); continue
    for a in (A1, A2, A3):
        assert s.count(a) == 1, (p, a)
    s = s.replace(A1, A1 + BLOCK).replace(A2, A2 + A2_ADD).replace(A3, A3 + A3_ADD)
    open(p, 'w').write(s); print(p, 'patched')
