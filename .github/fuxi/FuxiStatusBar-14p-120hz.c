// SPDX-License-Identifier: BSD-2-Clause-Patent
// fuxi combined 14 Pro status bar (1080x2400 direct) + zizhan 120 Hz CADisplayLink unlock (2026-11-21).
//
// 1) Status bar (only when offline-legacy-logical-width= is NOT in kern.bootargs, i.e. 1080x2400 direct scanout):
//    DynamicSplitMedium gets +referenceScreenScale = 3.0, -sensorAreaRect = {118,12,125,36} pt, and empty avoidance frame.
//    When logical scaling (e.g. 1179x2556 = 393x852 pt iPhone 14 Pro) IS active, UIKit natively runs DynamicSplitMedium
//    with full Dynamic Island expansion, so status bar hooks are skipped automatically.
// 2) 120 Hz CADisplayLink (ported verbatim from qiumochen/UniXNU-zizhan 42629e5 / hakios 7caa457):
//    UIKit's UIViewInProcessAnimationManager / UIKit.InProcessAnimationManager throttles its CADisplayLink to 20..30 fps
//    during animations (Home swipe settling, etc.). Drop the cap on that display link only (other display links keep
//    their requested rate). Disable with fuxi-dl-full=0 in boot-args.
// Skipped in backboardd.
#include <objc/runtime.h>
#include <objc/message.h>
#include <dispatch/dispatch.h>
#include <sys/sysctl.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

typedef struct { double x, y, w, h; } FsbRect;
typedef struct { float minimum, maximum, preferred; } FsbFrameRateRange;

static bool fuxiBootArgHas(const char *needle) {
    char buf[1536];
    size_t sz = sizeof(buf) - 1;
    if (sysctlbyname("kern.bootargs", buf, &sz, NULL, 0) != 0) return false;
    if (sz >= sizeof(buf)) sz = sizeof(buf) - 1;
    buf[sz] = '\0';
    return strstr(buf, needle) != NULL;
}

/* ---- 1. 120 Hz CADisplayLink hook (zizhan 42629e5 / hakios 7caa457) ---- */
static id (*gOrigLinkWith)(id, SEL, id, SEL);
static void (*gOrigLinkFps)(id, SEL, long);
static void (*gOrigLinkRange)(id, SEL, FsbFrameRateRange);
static bool gDlFull;
static bool gDlInstalled;
static char gDlFullKey;

static bool fuxiLinkAtFullRate(id link) {
    return gDlFull && objc_getAssociatedObject(link, &gDlFullKey) != nil;
}

static id fuxiLinkWith(id self, SEL cmd, id target, SEL action) {
    id link = gOrigLinkWith(self, cmd, target, action);
    if (link && target) {
        const char *name = object_getClassName(target);
        if (name && (!strcmp(name, "UIViewInProcessAnimationManager") ||
                     !strcmp(name, "UIKit.InProcessAnimationManager"))) {
            objc_setAssociatedObject(link, &gDlFullKey, link, OBJC_ASSOCIATION_ASSIGN);
        }
    }
    return link;
}

static void fuxiLinkFps(id self, SEL cmd, long fps) {
    gOrigLinkFps(self, cmd, fuxiLinkAtFullRate(self) ? 0 : fps);
}

static void fuxiLinkRange(id self, SEL cmd, FsbFrameRateRange range) {
    if (fuxiLinkAtFullRate(self)) range = (FsbFrameRateRange){0.0f, 0.0f, 0.0f};
    gOrigLinkRange(self, cmd, range);
}

static void fuxiInstallDisplayLink(void) {
    if (gDlInstalled || !gDlFull) return;
    Class link = objc_getClass("CADisplayLink");
    if (!link) return;
    Method made = class_getClassMethod(link, sel_registerName("displayLinkWithTarget:selector:"));
    Method fps = class_getInstanceMethod(link, sel_registerName("setPreferredFramesPerSecond:"));
    Method range = class_getInstanceMethod(link, sel_registerName("setPreferredFrameRateRange:"));
    if (made) gOrigLinkWith = (id (*)(id, SEL, id, SEL))method_setImplementation(made, (IMP)fuxiLinkWith);
    if (fps) gOrigLinkFps = (void (*)(id, SEL, long))method_setImplementation(fps, (IMP)fuxiLinkFps);
    if (range) gOrigLinkRange = (void (*)(id, SEL, FsbFrameRateRange))method_setImplementation(range, (IMP)fuxiLinkRange);
    gDlInstalled = true;
}

/* ---- 2. 14 Pro status bar hooks (360 pt direct panel only) ---- */
enum { kUI = 0, kST = 1, kKinds = 2, kInstallTries = 30 };
static const char *const kBase[kKinds] = {
    "_UIStatusBarVisualProvider_DynamicSplitMedium",
    "STUIStatusBarVisualProvider_DynamicSplitMedium"
};
static bool gDone[kKinds];
static bool gNeedSbHooks;

static double fsbReferenceScreenScale(id self, SEL cmd) { (void)self; (void)cmd; return 3.0; }
static FsbRect fsbSensorAreaRect(id self, SEL cmd) { (void)self; (void)cmd; return (FsbRect){118, 12, 125, 36}; }

typedef bool (*FsbNeedsUpdate)(id, SEL, FsbRect, double *, double *);
static FsbNeedsUpdate gOrigNeedsUpdate[2];
static bool fsbNeedsUpdate(int k, id self, SEL cmd, FsbRect frame, double *offset, double *width) {
    (void)frame;
    return gOrigNeedsUpdate[k](self, cmd, (FsbRect){0, 0, 0, 0}, offset, width);
}
static bool fsbNeedsUpdateUI(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(0, self, cmd, f, o, w); }
static bool fsbNeedsUpdateST(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(1, self, cmd, f, o, w); }

static void fsbInstall(int k) {
    if (!gNeedSbHooks || gDone[k]) return;
    Class base = objc_getClass(kBase[k]);
    if (!base) return;
    SEL needs = sel_registerName("_needsUpdateOfConstraintsForAvoidanceFrame:cutoutOffset:cutoutWidth:");
    if (class_getInstanceMethod(base, needs)) {
        gOrigNeedsUpdate[k] = (FsbNeedsUpdate)class_getMethodImplementation(base, needs);
        class_replaceMethod(base, needs, k == kUI ? (IMP)fsbNeedsUpdateUI : (IMP)fsbNeedsUpdateST,
                            "B64@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16^d48^d56");
    }
    class_replaceMethod(object_getClass((id)base), sel_registerName("referenceScreenScale"),
                        (IMP)fsbReferenceScreenScale, "d16@0:8");
    class_replaceMethod(base, sel_registerName("sensorAreaRect"),
                        (IMP)fsbSensorAreaRect, "{CGRect={CGPoint=dd}{CGSize=dd}}16@0:8");
    gDone[k] = true;
}

static int gTick;
static void fsbTick(void *context) {
    (void)context;
    fuxiInstallDisplayLink();
    for (int k = 0; k < kKinds; ++k) fsbInstall(k);
    bool sbReady = !gNeedSbHooks || (gDone[kUI] && gDone[kST]);
    bool dlReady = !gDlFull || gDlInstalled;
    if (!(sbReady && dlReady) && ++gTick < kInstallTries)
        dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), NULL, fsbTick);
}

__attribute__((constructor)) static void fsbStart(void) {
    const char *name = getprogname();
    if (name && !strcmp(name, "backboardd")) return;
    gDlFull = !fuxiBootArgHas("fuxi-dl-full=0");
    gNeedSbHooks = !fuxiBootArgHas("offline-legacy-logical-width=");
    fuxiInstallDisplayLink();
    for (int k = 0; k < kKinds; ++k) fsbInstall(k);
    bool sbReady = !gNeedSbHooks || (gDone[kUI] && gDone[kST]);
    bool dlReady = !gDlFull || gDlInstalled;
    if (!(sbReady && dlReady))
        dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), NULL, fsbTick);
}
