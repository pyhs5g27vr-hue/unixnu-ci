// SPDX-License-Identifier: BSD-2-Clause-Patent
// fuxi 14 Pro island status bar on the 1080x2400 direct panel (360x800 pt), 2026-11-20 (sb14p, DeepSeek sb-14pro-plan.md).
// The author's first-form text fixups (pack-ios17-hidpath.py, 2026-11-12: Phone +0x38 tbz -> b +0x14) make UIKit and SystemStatusUI
// take the DynamicSplit branch themselves, which picks DynamicSplitMedium (the iPhone 14 Pro provider) for a screen up to 393 pt.
// On 21H16 neither -_visualProviderClass nor +visualProviderSubclassForScreen:visualProviderInfo: of DynamicSplit is ever called
// (fsb3/fsb4w beacons), so no provider is replaced and no bar is rebuilt. This library only puts the author's three pieces from
// FuxiStatusBar.c (Kerfand 53f1320c) on DynamicSplitMedium itself: +referenceScreenScale = 3.0, -sensorAreaRect = the panel's island
// {118,12,125,36} pt (21H16's own reads -[UIScreen _exclusionArea], empty on this screen), and the empty aperture frame for
// -_needsUpdateOfConstraintsForAvoidanceFrame:cutoutOffset:cutoutWidth: (2026-11-16, the time sat 18 pt left). Skipped in backboardd.
#include <objc/runtime.h>
#include <objc/message.h>
#include <dispatch/dispatch.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

typedef struct { double x, y, w, h; } FsbRect;   // CGRect's layout (two CGPoint/CGSize double pairs)

enum { kUI = 0, kST = 1, kKinds = 2, kInstallTries = 30 };
static const char *const kBase[kKinds] = {"_UIStatusBarVisualProvider_DynamicSplitMedium", "STUIStatusBarVisualProvider_DynamicSplitMedium"};
static bool gDone[kKinds];

static double fsbReferenceScreenScale(id self, SEL cmd) { (void)self; (void)cmd; return 3.0; }
// The island on this panel, in points, as measured on the fuxi screenshots of the iPadOS fix.
static FsbRect fsbSensorAreaRect(id self, SEL cmd) { (void)self; (void)cmd; return (FsbRect){118, 12, 125, 36}; }

// fuxi 2026-11-16: ignore the aperture frame (see the CI step "fuxi status bar centring").
typedef bool (*FsbNeedsUpdate)(id, SEL, FsbRect, double *, double *);
static FsbNeedsUpdate gOrigNeedsUpdate[2];
static bool fsbNeedsUpdate(int k, id self, SEL cmd, FsbRect frame, double *offset, double *width) {
    (void)frame;
    return gOrigNeedsUpdate[k](self, cmd, (FsbRect){0, 0, 0, 0}, offset, width);
}
static bool fsbNeedsUpdateUI(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(0, self, cmd, f, o, w); }
static bool fsbNeedsUpdateST(id self, SEL cmd, FsbRect f, double *o, double *w) { return fsbNeedsUpdate(1, self, cmd, f, o, w); }

static void fsbInstall(int k) {
    if (gDone[k]) return;
    Class base = objc_getClass(kBase[k]);
    if (!base) return;   // SystemStatusUI may load after this library
    SEL needs = sel_registerName("_needsUpdateOfConstraintsForAvoidanceFrame:cutoutOffset:cutoutWidth:");
    if (class_getInstanceMethod(base, needs)) {
        gOrigNeedsUpdate[k] = (FsbNeedsUpdate)class_getMethodImplementation(base, needs);   // inherited or own, before the replace
        class_replaceMethod(base, needs, k == kUI ? (IMP)fsbNeedsUpdateUI : (IMP)fsbNeedsUpdateST, "B64@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16^d48^d56");
    }
    class_replaceMethod(object_getClass((id)base), sel_registerName("referenceScreenScale"), (IMP)fsbReferenceScreenScale, "d16@0:8");
    class_replaceMethod(base, sel_registerName("sensorAreaRect"), (IMP)fsbSensorAreaRect, "{CGRect={CGPoint=dd}{CGSize=dd}}16@0:8");
    gDone[k] = true;
}

static int gTick;
static void fsbTick(void *context) {
    (void)context;
    for (int k = 0; k < kKinds; ++k) fsbInstall(k);
    if (!(gDone[kUI] && gDone[kST]) && ++gTick < kInstallTries)
        dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), NULL, fsbTick);
}

__attribute__((constructor)) static void fsbStart(void) {
    const char *name = getprogname();
    if (name && !strcmp(name, "backboardd")) return;
    for (int k = 0; k < kKinds; ++k) fsbInstall(k);
    if (!(gDone[kUI] && gDone[kST]))
        dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), NULL, fsbTick);
}
