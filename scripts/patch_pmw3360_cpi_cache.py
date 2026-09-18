#!/usr/bin/env python3
"""Fix for KOHSUK/zmk-pmw3360-driver, applied by the CI workflow
(.github/workflows/build.yml) right after `west update` checks the driver
out, before it's compiled.

Bug: set_cpi() writes the CPI register but never updates data->curr_cpi.
Because of that, set_cpi_if_needed() - called from pmw3360_report_data() on
every single motion sample - always thinks the configured CPI differs from
the current one and re-issues a full SPI register write to reconfigure CPI
on every report while the ball is moving, instead of once at init. That
adds needless blocking SPI I/O to the interrupt-driven report path on every
sample, for as long as the driver is in use, at any CPI.

This was first noticed while diagnosing an unrelated "no cursor movement"
issue (which turned out to be a physical lens-to-ball distance problem) and
was, at the time, judged "harmless to correctness, just wasteful" - see the
old scripts/patch_pmw3360_debug.py, since removed. It's a real bug worth
fixing on its own regardless of that diagnosis, so it's patched here
permanently rather than left in the vendored driver.

Upstream: https://github.com/KOHSUK/zmk-pmw3360-driver (branch: pmw3360)

Usage: patch_pmw3360_cpi_cache.py <path-to-pmw3360.c>
"""

import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-pmw3360.c>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        src = f.read()

    old_sig = (
        "static int set_cpi(const struct device *dev, uint32_t cpi) {\n"
        "    /* Set resolution with CPI step of 100 cpi"
    )
    new_sig = (
        "static int set_cpi(const struct device *dev, uint32_t cpi) {\n"
        "    struct pixart_data *data = dev->data; // PATCH: cache cpi below\n"
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
        "        data->curr_cpi = cpi; // PATCH: avoid rewriting this every report\n"
        "    }\n"
        "\n"
        "    return err;\n"
        "}"
    )
    if old_write not in src:
        print("ERROR: set_cpi() body not found - upstream driver may have changed", file=sys.stderr)
        return 1
    src = src.replace(old_write, new_write, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"Patched {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
