#!/usr/bin/env python3
"""Sync the date/time on a 320f:5055 keyboard screen (Timeless82 / Zuoya GMK87 platform).

Protocol from Jochen Eisinger's zuoya_gmk87.py (BSD-3) and rusq/kbdctl, adapted to
hidapi so it works on macOS without detaching the kernel HID driver.
Vendor interface: usage page 0xFF1C, usage 0x92, report ID 4 (64B out / 8B in).
"""
import argparse
import datetime
import fcntl
import os
from pathlib import Path
import sys
import time

import hid

VID, PID = 0x320F, 0x5055
USAGE_PAGE, USAGE = 0xFF1C, 0x92
DATE_OFFSET = 35
STATE_DIR = Path(os.environ.get("TIMELESS82_STATE_DIR", Path(__file__).resolve().parent / ".runtime"))


def bcd(n):
    return (n // 10) << 4 | (n % 10)


def unbcd(b):
    return (b >> 4) * 10 + (b & 0xF)


class Kbd:
    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = (STATE_DIR / "hid.lock").open("a+")
        deadline = time.monotonic() + 180
        while True:
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._lock.close()
                    raise TimeoutError("keyboard is busy")
                time.sleep(0.05)
        try:
            self._open()
        except BaseException:
            self._lock.close()
            raise

    def _open(self):
        path = next((d["path"] for d in hid.enumerate(VID, PID)
                     if d["usage_page"] == USAGE_PAGE and d["usage"] == USAGE), None)
        if path is None:
            raise OSError("Keyboard vendor interface (320f:5055, page 0xFF1C) not found")
        self.path = path
        self.dev = hid.device()
        try:
            self.dev.open_path(path)
        except BaseException:
            self.dev.close()
            raise

    def close(self):
        try:
            self.dev.close()
        finally:
            self._lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def cmd(self, cid, data=(), pos=0):
        data = list(data)
        if len(data) > 56 or not 0 <= pos <= 0xFFFFFF:
            raise ValueError("invalid HID command payload or position")
        if cid == 2:
            time.sleep(0.1)
        buf = [0] * 64
        buf[0] = 0x04
        buf[3] = cid
        buf[4] = len(data)
        buf[5], buf[6], buf[7] = pos & 0xFF, (pos >> 8) & 0xFF, (pos >> 16) & 0xFF
        buf[8:8 + len(data)] = data
        ck = sum(buf[3:])
        buf[1], buf[2] = ck & 0xFF, (ck >> 8) & 0xFF
        if self.dev.write(buf) != len(buf):
            raise OSError("incomplete HID write")
        # Flash preparation can take much longer than a configuration read.
        deadline = time.monotonic() + (30 if cid == 0x23 else 2)
        last_reply = None
        while time.monotonic() < deadline:
            r = self.dev.read(64, 500)
            if r:
                last_reply = r
            # macOS can change the report/checksum header on upload ACKs.
            # The command byte is echoed by both firmware response forms.
            if len(r) >= 8 and r[3] == cid:
                return r[4:8]
        detail = f", last reply {bytes(last_reply).hex()}" if last_reply else ""
        raise TimeoutError(f"no response to command {cid} at pos {pos}{detail}")

    def load_config(self):
        self.cmd(1)
        for i in range(9):
            self.cmd(3, [0] * 4, i * 4)
        self.cmd(3, [0], 36)
        self.cmd(2)
        cfg = []
        for i in range(12):
            cfg.extend(self.cmd(5, [0] * 4, i * 4))
        return cfg

    def write_config(self, cfg):
        if len(cfg) != 48:
            raise ValueError(f"unexpected config length {len(cfg)}, refusing to write")
        self.cmd(1)
        self.cmd(6, cfg)
        self.cmd(2)


def set_clock(cfg, now=None):
    now = now or datetime.datetime.now()
    cfg[DATE_OFFSET:DATE_OFFSET + 7] = [
        bcd(now.second), bcd(now.minute), bcd(now.hour), now.isoweekday(),
        bcd(now.day), bcd(now.month), bcd(now.year - 2000)]


def show(cfg):
    s, m, h, wd, d, mo, y = cfg[DATE_OFFSET:DATE_OFFSET + 7]
    return (f"20{unbcd(y):02d}-{unbcd(mo):02d}-{unbcd(d):02d} "
            f"{unbcd(h):02d}:{unbcd(m):02d}:{unbcd(s):02d} (weekday {wd})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dump", action="store_true", help="only read and print the config")
    args = ap.parse_args()

    with Kbd() as k:
        cfg = k.load_config()
        print("config:", bytes(cfg).hex(" "))
        print("keyboard time:", show(cfg))
        if args.dump:
            return
        set_clock(cfg)
        k.write_config(cfg)
        print("set to:       ", show(cfg))


if __name__ == "__main__":
    main()
