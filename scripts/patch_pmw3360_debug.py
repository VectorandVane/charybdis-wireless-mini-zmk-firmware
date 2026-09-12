#!/usr/bin/env python3
"""TEMPORARY patch for KOHSUK/zmk-pmw3360-driver, applied by the CI workflow
(.github/workflows/build.yml) right after `west update` checks the driver
out, before it's compiled.

Why: while diagnosing "PMW3360 sensor produces zero cursor movement",
we found two things worth patching in the vendored driver source itself:

1. A real bug: set_cpi() writes the CPI register but never updates
   data->curr_cpi, so set_cpi_if_needed() thinks the CPI is always stale
   and rewrites the register on every single motion sample instead of
   once at init. Harmless to correctness but wasteful (extra SPI traffic
   + battery drain per sample, plus log spam once debug logging is on).

2. No visibility: the driver never logs the computed X/Y delta, so there
   was no way to tell whether real per-sample motion deltas were being
   computed (and just not reaching HID) versus always coming back zero.
   (Confirmed via this patch: always zero, even while moving the ball.)
   Now also logs the raw Motion status byte (bit7/0x80 = MOT, set only
   when the chip itself measured real displacement) to tell apart "IRQ
   firing from real chip-detected motion that nonetheless nets to zero"
   from "IRQ firing from something else entirely" (electrical noise, a
   bad/floating connection) with MOT never actually set.

Delete this script (and the CI step that calls it) once the PMW3360 issue
is resolved - it patches an external module, not our own code, and isn't
meant to be a permanent fixture.

Usage: patch_pmw3360_debug.py <path-to-pmw3360.c>
"""

import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-pmw3360.c>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        src = f.read()

    # --- Patch 1: cache curr_cpi so it's only written once at init -------
    old_sig = (
        "static int set_cpi(const struct device *dev, uint32_t cpi) {\n"
        "    /* Set resolution with CPI step of 100 cpi"
    )
    new_sig = (
        "static int set_cpi(const struct device *dev, uint32_t cpi) {\n"
        "    struct pixart_data *data = dev->data; // TEMP-DEBUG-PATCH\n"
        "    /* Set resolution with CPI step of 100 cpi"
    )
    if old_sig not in src:
        print("ERROR: set_cpi() signature not found - upstream driver may have changed", file=sys.stderr)
        return 1
    src = src.replace(old_sig, new_sig, 1)

    old_write = (
        "    int err = reg_write(dev, PMW3360_REG_CONFIG1, value);\n"
        "    if (err) {\n"
        "        LOG_ERR(\"Failed to change CPI\");\n"
        "    }\n"
        "\n"
        "    return err;\n"
        "}"
    )
    new_write = (
        "    int err = reg_write(dev, PMW3360_REG_CONFIG1, value);\n"
        "    if (err) {\n"
        "        LOG_ERR(\"Failed to change CPI\");\n"
        "    } else {\n"
        "        data->curr_cpi = cpi; // TEMP-DEBUG-PATCH: cache it, don't rewrite every sample\n"
        "    }\n"
        "\n"
        "    return err;\n"
        "}"
    )
    if old_write not in src:
        print("ERROR: set_cpi() body not found - upstream driver may have changed", file=sys.stderr)
        return 1
    src = src.replace(old_write, new_write, 1)

    # --- Patch 2: log the computed delta AND the raw Motion status byte --
    # buf[0] is the burst-read Motion register mirror (PMW3360 datasheet:
    # bit7/0x80 = MOT, set only when the chip itself measured non-zero
    # displacement since the last read). If MOT is never set on samples
    # triggered by touching/moving the ball, the IRQ line is firing from
    # something other than genuine chip-detected motion (electrical noise,
    # a bad/floating connection) rather than an optics/tracking problem.
    old_check = "    if (x != 0 || y != 0) {\n        if (input_mode != SCROLL) {"
    new_check = (
        "    LOG_INF(\"TEMP-DEBUG raw delta x=%d y=%d motion_reg=0x%02x\", x, y, buf[0]);\n"
        "    if (x != 0 || y != 0) {\n        if (input_mode != SCROLL) {"
    )
    if old_check not in src:
        print("ERROR: report_data() x/y check not found - upstream driver may have changed", file=sys.stderr)
        return 1
    src = src.replace(old_check, new_check, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"Patched {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
