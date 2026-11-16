#!/usr/bin/env python3
"""fuxi status bar (2026-11-16): the DynamicSplit provider moves its cutout to the status bar's avoidance frame (SpringBoard's system
aperture) whenever that frame is wider than the sensor + 20 pt. On this panel that frame is not the island (measured x 74..242,
centre 158), which put the time about 18 pt left of the left ear's centre and the battery 5 pt left of the right ear's.
The FuxiStatusBar subclass hands its superclass an empty frame, both at -avoidanceFrameUpdatedFromFrame:withAnimationSettings:options:
(the entry point) and at -_needsUpdateOfConstraintsForAvoidanceFrame:cutoutOffset:cutoutWidth:, so the cutout follows -sensorAreaRect.
The first run (ci-k4, 2026-11-16) still showed the time at 41 pt in Settings, so this version also reports what it sees: an IOKit name
lookup "FSB:<text>" that the kernel's unixnu-iokit-probe logs (IOKit is reached through dlopen, so no new link dependency).
Usage: sb-avoid-edit.py FuxiStatusBar.c [...]  (edits in place; refuses a file whose anchors are missing)"""
import sys
INC = '#include <string.h>\n'
INC_ADD = '#include <stdio.h>\n#include <dlfcn.h>\n#include <unistd.h>\n'
BLOCK = r'''
// fuxi 2026-11-16: ignore the aperture frame (see the CI step "fuxi status bar centring"), and report what happens.
static void fsbBeacon(const char *text) {
    static void *(*matching)(const char *);
    static unsigned (*get)(unsigned, void *);
    static int (*release)(unsigned);
    static int tried;
    if (!tried) {
        tried = 1;
        void *h = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_LAZY);
        if (h) {
            matching = (void *(*)(const char *))dlsym(h, "IOServiceNameMatching");
            get = (unsigned (*)(unsigned, void *))dlsym(h, "IOServiceGetMatchingService");
            release = (int (*)(unsigned))dlsym(h, "IOObjectRelease");
        }
    }
    if (!matching || !get) return;
    char name[128];
    snprintf(name, sizeof name, "FSB:%s:%d:%s", getprogname() ? getprogname() : "?", getpid(), text);
    void *dict = matching(name);
    if (!dict) return;
    unsigned s = get(0, dict);   // consumes dict; the service does not exist
    if (s && release) release(s);
}
typedef bool (*FsbNeedsUpdate)(id, SEL, FsbRect, double *, double *);
typedef void (*FsbFrameUpdated)(id, SEL, FsbRect, id, unsigned long);
static FsbNeedsUpdate gOrigNeedsUpdate[2];
static FsbFrameUpdated gOrigFrameUpdated[2];
static int gNeedsSeen[2], gFrameSeen[2];
static bool fsbNeedsUpdate(int k, id self, SEL cmd, FsbRect frame, double *offset, double *width) {
    bool r = gOrigNeedsUpdate[k](self, cmd, (FsbRect){0, 0, 0, 0}, offset, width);
    if (gNeedsSeen[k] < 6) {
        ++gNeedsSeen[k];
        char t[96];
        snprintf(t, sizeof t, "nu%d:%.0f,%.0f,%.0f,%.0f>%d,%.1f,%.1f", k, frame.x, frame.y, frame.w, frame.h, (int)r,
                 offset ? *offset : -1.0, width ? *width : -1.0);
        fsbBeacon(t);
    }
    return r;
}
static bool fsbNeedsUpdateUI(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(0, self, cmd, f, o, w); }
static bool fsbNeedsUpdateST(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(1, self, cmd, f, o, w); }
static void fsbFrameUpdated(int k, id self, SEL cmd, FsbRect frame, id settings, unsigned long options) {
    if (gFrameSeen[k] < 6) {
        ++gFrameSeen[k];
        char t[96];
        snprintf(t, sizeof t, "fu%d:%.0f,%.0f,%.0f,%.0f/%lu", k, frame.x, frame.y, frame.w, frame.h, options);
        fsbBeacon(t);
    }
    gOrigFrameUpdated[k](self, cmd, (FsbRect){0, 0, 0, 0}, settings, options);
}
static void fsbFrameUpdatedUI(id self, SEL cmd, FsbRect f, id s, unsigned long o) { fsbFrameUpdated(0, self, cmd, f, s, o); }
static void fsbFrameUpdatedST(id self, SEL cmd, FsbRect f, id s, unsigned long o) { fsbFrameUpdated(1, self, cmd, f, s, o); }
'''
A1 = 'static FsbRect fsbSensorAreaRect(id self, SEL cmd) { (void)self; (void)cmd; return (FsbRect){118, 12, 125, 36}; }\n'
A2 = '    Class sub = objc_getClass(kSub[k]);\n'
A2_ADD = ('    SEL needs = sel_registerName("_needsUpdateOfConstraintsForAvoidanceFrame:cutoutOffset:cutoutWidth:");\n'
          '    SEL framed = sel_registerName("avoidanceFrameUpdatedFromFrame:withAnimationSettings:options:");\n'
          '    if (class_getInstanceMethod(base, needs)) gOrigNeedsUpdate[k] = (FsbNeedsUpdate)class_getMethodImplementation(base, needs);\n'
          '    if (class_getInstanceMethod(base, framed)) gOrigFrameUpdated[k] = (FsbFrameUpdated)class_getMethodImplementation(base, framed);\n'
          '    { char t[64]; snprintf(t, sizeof t, "inst%d:%d%d%d", k, sub != 0, gOrigNeedsUpdate[k] != 0, gOrigFrameUpdated[k] != 0); fsbBeacon(t); }\n')
A3 = '        class_addMethod(sub, sel_registerName("sensorAreaRect"), (IMP)fsbSensorAreaRect, "{CGRect={CGPoint=dd}{CGSize=dd}}16@0:8");\n'
A3_ADD = ('        if (gOrigNeedsUpdate[k]) class_addMethod(sub, needs, k == kUI ? (IMP)fsbNeedsUpdateUI : (IMP)fsbNeedsUpdateST,'
          ' "B64@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16^d48^d56");\n'
          '        if (gOrigFrameUpdated[k]) class_addMethod(sub, framed, k == kUI ? (IMP)fsbFrameUpdatedUI : (IMP)fsbFrameUpdatedST,'
          ' "v64@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16@48Q56");\n')
# which provider class a bar really got (first two per kind)
A4 = '    Class chosen = ((Class (*)(id, SEL))gOrigProviderClass[k])(self, cmd);\n'
A4_ADD = ('    { static int seen[2]; if (seen[k] < 2) { ++seen[k]; char t[96]; snprintf(t, sizeof t, "choice%d:%s", k, chosen ? class_getName(chosen) : "nil"); fsbBeacon(t); } }\n')
for p in sys.argv[1:]:
    s = open(p).read()
    if 'fsbNeedsUpdate' in s:
        print(p, 'already patched'); continue
    for a in (INC, A1, A2, A3, A4):
        assert s.count(a) == 1, (p, a)
    s = s.replace(INC, INC + INC_ADD, 1).replace(A1, A1 + BLOCK).replace(A2, A2 + A2_ADD).replace(A3, A3 + A3_ADD).replace(A4, A4 + A4_ADD)
    open(p, 'w').write(s); print(p, 'patched')
