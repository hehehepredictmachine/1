"""Strict GIF block walker: validates the container and reports size, frames, loop duration and transparency."""
from __future__ import annotations


def gif_info(data: bytes) -> dict | None:
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w, h = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    flags = data[10]
    pos = 13
    if flags & 0x80:
        pos += 3 * (2 ** ((flags & 0x07) + 1))
    frames, dur_cs, transparent, loop = 0, 0, False, None

    def skip_sub(p: int) -> int:
        while p < len(data):
            n = data[p]
            p += 1
            if n == 0:
                return p
            p += n
        raise ValueError("TRUNCATED")
    try:
        while pos < len(data):
            b = data[pos]
            if b == 0x3B:                                   # trailer
                break
            if b == 0x21:                                   # extension
                label = data[pos + 1]
                if label == 0xF9 and data[pos + 2] == 4:    # graphic control
                    packed = data[pos + 3]
                    dur_cs += int.from_bytes(data[pos + 4:pos + 6], "little")
                    transparent = transparent or bool(packed & 0x01)
                if label == 0xFF and data[pos + 3:pos + 14] == b"NETSCAPE2.0":
                    loop = int.from_bytes(data[pos + 16:pos + 18], "little")
                pos = skip_sub(pos + 2)
                continue
            if b == 0x2C:                                   # image descriptor
                frames += 1
                lflags = data[pos + 9]
                pos += 10
                if lflags & 0x80:
                    pos += 3 * (2 ** ((lflags & 0x07) + 1))
                pos = skip_sub(pos + 1)                     # LZW min code size + data
                continue
            return None
    except (IndexError, ValueError):
        return None
    if frames == 0:
        return None
    return {"width": w, "height": h, "frames": frames, "loop_duration_ms": dur_cs * 10, "transparency": transparent,
            "loop_count": loop, "bytes": len(data)}
