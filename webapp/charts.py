"""Grafik SVG sederhana (tanpa library eksternal, jalan offline)."""
from markupsafe import Markup, escape

NAVY, TEAL, ORANGE, GREY, YEL = '#1F3864', '#2E75B6', '#ED7D31', '#BFBFBF', '#FFF2CC'


def _fmt_short(v):
    a = abs(v)
    if a >= 1e9:
        return f'{v / 1e9:.1f} M'.replace('.', ',')
    if a >= 1e6:
        return f'{v / 1e6:.1f} jt'.replace('.', ',')
    if a >= 1e3:
        return f'{v / 1e3:.0f} rb'
    return f'{v:.0f}'


def hbar(items, fmt=_fmt_short, width=640, color=TEAL):
    items = [(l, v) for l, v in items if v is not None]
    if not items:
        return Markup('<p class="muted">Belum ada data.</p>')
    bh, gap, left = 20, 8, 230
    h = len(items) * (bh + gap) + 10
    mx = max(abs(v) for _, v in items) or 1
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    for i, (l, v) in enumerate(items):
        y = 5 + i * (bh + gap)
        w = max(1, (width - left - 90) * abs(v) / mx)
        out.append(f'<text x="{left - 8}" y="{y + 14}" text-anchor="end" font-size="12" fill="#333">{escape(str(l)[:34])}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bh}" fill="{color}" rx="2"/>')
        out.append(f'<text x="{left + w + 6:.1f}" y="{y + 14}" font-size="12" fill="#333">{escape(fmt(v))}</text>')
    out.append('</svg>')
    return Markup(''.join(out))


def daily(days, qp, qn, total, flag, width=860, height=300):
    n = len(days)
    if not n:
        return Markup('')
    L, R, T, B = 60, 70, 20, 40
    pw, ph = width - L - R, height - T - B
    bw = pw / n
    mxq = max((a + b) for a, b in zip(qp, qn)) or 1
    mxt = max(total) or 1
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">']
    for i, f in enumerate(flag):
        if f:
            out.append(f'<rect x="{L + i * bw:.1f}" y="{T}" width="{bw:.1f}" height="{ph}" fill="{YEL}"/>')
    for i in range(n):
        x = L + i * bw + 1
        hn_ = ph * qn[i] / mxq
        hp_ = ph * qp[i] / mxq
        out.append(f'<rect x="{x:.1f}" y="{T + ph - hn_:.1f}" width="{bw - 2:.1f}" height="{hn_:.1f}" fill="{TEAL}"/>')
        out.append(f'<rect x="{x:.1f}" y="{T + ph - hn_ - hp_:.1f}" width="{bw - 2:.1f}" height="{hp_:.1f}" fill="{ORANGE}"/>')
        if i % 2 == 0 or n < 20:
            out.append(f'<text x="{x + bw / 2 - 1:.1f}" y="{T + ph + 14}" font-size="10" text-anchor="middle" fill="#555">{days[i]}</text>')
    pts = ' '.join(f'{L + i * bw + bw / 2:.1f},{T + ph - ph * total[i] / mxt:.1f}' for i in range(n))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{NAVY}" stroke-width="2"/>')
    out.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#999"/>')
    out.append(f'<text x="{L - 6}" y="{T + 10}" font-size="10" text-anchor="end" fill="#555">{mxq:.0f}</text><text x="{L - 6}" y="{T + ph}" font-size="10" text-anchor="end" fill="#555">0</text>')
    out.append(f'<text x="{L + pw + 6}" y="{T + 10}" font-size="10" fill="{NAVY}">{escape(_fmt_short(mxt))}</text>')
    ly = height - 8
    out.append(f'<rect x="{L}" y="{ly - 9}" width="10" height="10" fill="{ORANGE}"/><text x="{L + 14}" y="{ly}" font-size="11">Qty button promo</text>')
    out.append(f'<rect x="{L + 130}" y="{ly - 9}" width="10" height="10" fill="{TEAL}"/><text x="{L + 144}" y="{ly}" font-size="11">Qty button normal</text>')
    out.append(f'<line x1="{L + 270}" y1="{ly - 4}" x2="{L + 290}" y2="{ly - 4}" stroke="{NAVY}" stroke-width="2"/><text x="{L + 294}" y="{ly}" font-size="11">Total sales dine-in (kanan)</text>')
    out.append(f'<rect x="{L + 470}" y="{ly - 9}" width="10" height="10" fill="{YEL}" stroke="#ccc"/><text x="{L + 484}" y="{ly}" font-size="11">Periode promo</text>')
    out.append('</svg>')
    return Markup(''.join(out))


def monthly(labels, bars, line, width=860, height=280):
    n = len(labels)
    L, R, T, B = 70, 60, 20, 44
    pw, ph = width - L - R, height - T - B
    bw = pw / n
    bv = [b or 0 for b in bars]
    lv = [x for x in line]
    mxb = max(bv) or 1
    mxl = max([x for x in lv if x is not None] or [1]) or 1
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">']
    for i in range(n):
        x = L + i * bw + 6
        h = ph * bv[i] / mxb
        out.append(f'<rect x="{x:.1f}" y="{T + ph - h:.1f}" width="{bw - 12:.1f}" height="{h:.1f}" fill="{TEAL}"/>')
        if bv[i]:
            out.append(f'<text x="{x + (bw - 12) / 2:.1f}" y="{T + ph - h - 4:.1f}" font-size="10" text-anchor="middle" fill="#333">{escape(_fmt_short(bv[i]))}</text>')
        out.append(f'<text x="{x + (bw - 12) / 2:.1f}" y="{T + ph + 14}" font-size="11" text-anchor="middle" fill="#555">{escape(labels[i])}</text>')
    pts = [(L + i * bw + bw / 2, T + ph - ph * v / mxl) for i, v in enumerate(lv) if v is not None]
    if len(pts) > 1:
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{ORANGE}" stroke-width="2.5"/>')
    for (x, y), v in zip(pts, [v for v in lv if v is not None]):
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{ORANGE}"/><text x="{x:.1f}" y="{y - 8:.1f}" font-size="10" text-anchor="middle" fill="{ORANGE}">{v * 100:.1f}%</text>'.replace('.', ',', 0))
    out.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#999"/>')
    ly = height - 6
    out.append(f'<rect x="{L}" y="{ly - 9}" width="10" height="10" fill="{TEAL}"/><text x="{L + 14}" y="{ly}" font-size="11">Sales per hari promo (Rp)</text>')
    out.append(f'<line x1="{L + 190}" y1="{ly - 4}" x2="{L + 210}" y2="{ly - 4}" stroke="{ORANGE}" stroke-width="2.5"/><text x="{L + 214}" y="{ly}" font-size="11">Kontribusi ke sales outlet (%)</text>')
    out.append('</svg>')
    return Markup(''.join(out))
