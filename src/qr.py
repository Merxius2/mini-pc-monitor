"""Small QR code PNG generation for dashboard connect hints."""

from __future__ import annotations

import io

import segno


def qr_png_bytes(data: str, *, scale: int = 6, border: int = 2) -> bytes:
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=border, dark="#0f172a", light="#f8fafc")
    return buf.getvalue()
