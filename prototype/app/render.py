"""예시 이미지 그리기. 실제 사진 대신 OCR 줄을 패키지 모양 위에 그린 SVG를 돌려준다.
판독 신뢰도가 기준 미만인 줄은 흐리게 그려 '왜 판독불가인지' 보이게 한다."""
from __future__ import annotations

from xml.sax.saxutils import escape


def _wrap(text: str, width: int) -> list[str]:
    out, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= width:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def render_svg(fx: dict, threshold: float = 0.80) -> str:
    face = fx.get("face", "other")
    category = fx.get("category", "container")
    W = 300
    H = max(160, min(420, round(W * fx["h"] / fx["w"])))
    lowres = fx["w"] < 500
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
             '<defs><filter id="blur"><feGaussianBlur stdDeviation="1.6"/></filter>'
             '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
             '<stop offset="0" stop-color="#e9eef3"/><stop offset="1" stop-color="#d7dfe8"/></linearGradient></defs>',
             f'<rect width="{W}" height="{H}" fill="url(#bg)"/>']

    if face == "lifestyle":
        parts.append(f'<circle cx="{W*0.7}" cy="{H*0.45}" r="{H*0.32}" fill="#c9d6e3"/>')
        parts.append(f'<rect x="{W*0.18}" y="{H*0.28}" width="{W*0.3}" height="{H*0.5}" rx="14" fill="#f7f9fb" stroke="#9fb1c4"/>')
        parts.append(f'<text x="{W/2}" y="{H-16}" text-anchor="middle" font-size="13" fill="#4a5b6d" '
                     f'font-family="sans-serif">연출컷 · 표시사항 없음</text></svg>')
        return "".join(parts)

    pad = 18
    if category == "tube" and face in ("front", "back", "left", "right"):
        x0, x1 = pad + 10, W - pad - 10
        parts.append(f'<path d="M{x0} {pad+14} H{x1} L{x1-22} {H-pad-26} H{x0+22} Z" fill="#fbfcfd" stroke="#8fa3b8"/>')
        parts.append(f'<rect x="{W/2-34}" y="{H-pad-26}" width="68" height="22" rx="4" fill="#cfd8e2" stroke="#8fa3b8"/>')
        tx, ty, tw = x0 + 14, pad + 38, x1 - x0 - 28
    elif face in ("top", "bottom") and category == "container":
        r = min(W, H) / 2 - pad
        parts.append(f'<circle cx="{W/2}" cy="{H/2}" r="{r}" fill="#fbfcfd" stroke="#8fa3b8"/>')
        tx, ty, tw = W / 2 - r * 0.7, H / 2 - 8, r * 1.4
    elif face in ("top", "bottom"):
        parts.append(f'<rect x="{pad}" y="{H/2-34}" width="{W-2*pad}" height="68" rx="6" fill="#fbfcfd" stroke="#8fa3b8"/>')
        for i in range(12):
            x = pad + 8 + i * (W - 2 * pad - 16) / 11
            parts.append(f'<line x1="{x}" y1="{H/2-34}" x2="{x}" y2="{H/2-24}" stroke="#b5c3d1"/>')
        tx, ty, tw = pad + 16, H / 2 - 6, W - 2 * pad - 32
    else:
        parts.append(f'<rect x="{W/2-50}" y="{pad}" width="100" height="22" rx="5" fill="#cfd8e2" stroke="#8fa3b8"/>')
        parts.append(f'<rect x="{pad}" y="{pad+26}" width="{W-2*pad}" height="{H-2*pad-26}" rx="16" fill="#fbfcfd" stroke="#8fa3b8"/>')
        tx, ty, tw = pad + 16, pad + 52, W - 2 * pad - 32

    big = face == "front"
    fs = 15 if big else 10.5
    chars = max(8, int(tw / (fs * 0.95)))
    y = ty
    group = ' filter="url(#blur)"' if lowres else ""
    parts.append(f'<g font-family="sans-serif"{group}>')
    for line in fx.get("ocr", []):
        low = line["conf"] < threshold
        attrs = ' filter="url(#blur)" opacity="0.55"' if low else ""
        for seg in _wrap(line["text"], chars):
            if y > H - pad - 8:
                break
            anchor = f'x="{W/2}" text-anchor="middle"' if big or face in ("top", "bottom") else f'x="{tx}"'
            parts.append(f'<text {anchor} y="{y:.0f}" font-size="{fs}" fill="#1f2a36"{attrs}>{escape(seg)}</text>')
            y += fs * 1.45
        y += 2 if not big else 6
    parts.append("</g></svg>")
    return "".join(parts)
