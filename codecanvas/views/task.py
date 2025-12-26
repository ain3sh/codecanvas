"""Task View - Evidence Board (Claims ↔ Evidence ↔ Decisions)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import List, Optional

from ..core.models import Graph
from ..core.state import CanvasState, Claim, Decision, Evidence, TaskSpec, pick_task
from . import COLORS, Style, SVGCanvas


class TaskView:
    def __init__(self, graph: Graph, state: CanvasState, *, tasks: List[TaskSpec]):
        self.graph = graph
        self.state = state
        self.tasks = tasks

    def render(self, output_path: str | None = None) -> str:
        width, height = 1400, 900
        canvas = SVGCanvas(width=width, height=height)

        margin = 40
        top = 110
        gap = 22
        col_w = (width - 2 * margin - 2 * gap) / 3
        col_h = height - top - 80

        focus = (self.state.focus or "(none)").strip()
        canvas.add_text(
            margin,
            56,
            "EVIDENCE BOARD",
            style=Style(fill=COLORS["text"], font_size=26, font_weight="bold"),
        )
        stats = (
            f"focus: {_short_line(focus, 50)}  "
            f"evidence: {len(self.state.evidence)}  "
            f"claims: {len(self.state.claims)}  "
            f"decisions: {len(self.state.decisions)}"
        )
        canvas.add_text(
            margin,
            82,
            stats,
            style=Style(fill=COLORS["muted"], font_size=13, font_weight="bold"),
        )

        claims_x = margin
        evidence_x = margin + col_w + gap
        decisions_x = margin + 2 * (col_w + gap)

        self._panel(canvas, claims_x, top, col_w, col_h, title="CLAIMS")
        self._panel(canvas, evidence_x, top, col_w, col_h, title="EVIDENCE")
        self._panel(canvas, decisions_x, top, col_w, col_h, title="DECISIONS")

        self._draw_claims(canvas, claims_x, top, col_w, col_h)
        self._draw_evidence(canvas, evidence_x, top, col_w, col_h)
        self._draw_decisions(canvas, decisions_x, top, col_w, col_h)

        t = pick_task(self.tasks, self.state.active_task_id)
        footer_y = height - 36
        if t:
            bits = [f"task: {t.id}"]
            if t.dataset:
                bits.append(f"dataset: {t.dataset}")
            if t.tb_url:
                bits.append(_short_url(t.tb_url, max_len=64))
            canvas.add_text(margin, footer_y, "    ".join(bits), style=Style(fill=COLORS["muted"], font_size=12))
        else:
            canvas.add_text(margin, footer_y, "task: (none)", style=Style(fill=COLORS["muted"], font_size=12))

        if output_path:
            canvas.save(output_path)
        return canvas.render()

    def _panel(self, canvas: SVGCanvas, x: float, y: float, w: float, h: float, *, title: str) -> None:
        canvas.add_rect(
            x,
            y,
            w,
            h,
            rx=14,
            style=Style(fill=COLORS["card"], stroke=COLORS["outline"], filter="drop-shadow"),
        )
        canvas.add_text(
            x + 18,
            y + 34,
            title,
            style=Style(fill=COLORS["text"], font_size=14, font_weight="bold"),
        )

    def _draw_claims(self, canvas: SVGCanvas, x: float, y: float, w: float, h: float) -> None:
        claims = [c for c in (self.state.claims or []) if (c.status or "active") == "active"]
        claims.sort(key=lambda c: c.created_at)
        claims = list(reversed(claims[-6:]))

        if not claims:
            canvas.add_text(x + 18, y + 62, "(empty)", style=Style(fill=COLORS["muted"], font_size=12))
            return

        box_x = x + 14
        box_w = w - 28
        box_h = 118
        y0 = y + 52
        for i, c in enumerate(claims):
            yy = y0 + i * (box_h + 12)
            if yy + box_h > y + h - 12:
                break
            self._claim_box(canvas, box_x, yy, box_w, box_h, c)

    def _claim_box(self, canvas: SVGCanvas, x: float, y: float, w: float, h: float, c: Claim) -> None:
        canvas.add_rect(
            x,
            y,
            w,
            h,
            rx=12,
            style=Style(fill=COLORS["module_bg"], stroke=COLORS["outline"], opacity=0.92),
        )
        hdr = f"{c.id}  [{(c.kind or 'claim').lower()}]"
        canvas.add_text(
            x + 14,
            y + 26,
            hdr,
            style=Style(fill=COLORS["muted"], font_size=11, font_weight="bold"),
        )
        lines = _wrap_text(c.text or "", max_chars=46, max_lines=4)
        canvas.add_text_lines(x + 14, y + 48, lines, style=Style(fill=COLORS["text"], font_size=12), line_height=16)
        if c.evidence_ids:
            canvas.add_text(
                x + 14,
                y + h - 16,
                f"evidence: {_chips(c.evidence_ids)}",
                style=Style(fill=COLORS["muted"], font_size=11),
            )

    def _draw_decisions(self, canvas: SVGCanvas, x: float, y: float, w: float, h: float) -> None:
        decs = list(self.state.decisions or [])
        decs.sort(key=lambda d: d.created_at)
        decs = list(reversed(decs[-6:]))
        if not decs:
            canvas.add_text(x + 18, y + 62, "(empty)", style=Style(fill=COLORS["muted"], font_size=12))
            return

        box_x = x + 14
        box_w = w - 28
        box_h = 118
        y0 = y + 52
        for i, d in enumerate(decs):
            yy = y0 + i * (box_h + 12)
            if yy + box_h > y + h - 12:
                break
            self._decision_box(canvas, box_x, yy, box_w, box_h, d)

    def _decision_box(self, canvas: SVGCanvas, x: float, y: float, w: float, h: float, d: Decision) -> None:
        canvas.add_rect(
            x,
            y,
            w,
            h,
            rx=12,
            style=Style(fill=COLORS["module_bg"], stroke=COLORS["outline"], opacity=0.92),
        )
        hdr = f"{d.id}  [{(d.kind or 'decision').lower()}]"
        if d.target:
            hdr += f"  {_short_line(d.target, 26)}"
        canvas.add_text(
            x + 14,
            y + 26,
            hdr,
            style=Style(fill=COLORS["muted"], font_size=11, font_weight="bold"),
        )
        lines = _wrap_text(d.text or "", max_chars=46, max_lines=4)
        canvas.add_text_lines(x + 14, y + 48, lines, style=Style(fill=COLORS["text"], font_size=12), line_height=16)
        if d.evidence_ids:
            canvas.add_text(
                x + 14,
                y + h - 16,
                f"evidence: {_chips(d.evidence_ids)}",
                style=Style(fill=COLORS["muted"], font_size=11),
            )

    def _draw_evidence(self, canvas: SVGCanvas, x: float, y: float, w: float, h: float) -> None:
        evs = list(self.state.evidence or [])
        evs.sort(key=lambda e: e.created_at)
        evs = list(reversed(evs[-6:]))
        if not evs:
            canvas.add_text(x + 18, y + 62, "(empty)", style=Style(fill=COLORS["muted"], font_size=12))
            return

        pad = 14
        inner_gap = 14
        grid_x = x + pad
        grid_y = y + 52
        grid_w = w - 2 * pad

        tile_w = (grid_w - inner_gap) / 2
        tile_h = 222
        thumb_h = 170

        for i, ev in enumerate(evs):
            r = i // 2
            c = i % 2
            xx = grid_x + c * (tile_w + inner_gap)
            yy = grid_y + r * (tile_h + inner_gap)
            if yy + tile_h > y + h - 12:
                break
            self._evidence_tile(canvas, xx, yy, tile_w, tile_h, thumb_h, ev)

    def _evidence_tile(
        self, canvas: SVGCanvas, x: float, y: float, w: float, h: float, thumb_h: float, ev: Evidence
    ) -> None:
        canvas.add_rect(
            x,
            y,
            w,
            h,
            rx=12,
            style=Style(fill=COLORS["module_bg"], stroke=COLORS["outline"], opacity=0.92),
        )
        img_x, img_y = x + 10, y + 10
        img_w, img_h = w - 20, thumb_h - 20
        href = _png_to_data_url(ev.png_path)
        if href:
            canvas.add_image(img_x, img_y, img_w, img_h, href, opacity=0.98)
        else:
            canvas.add_rect(
                img_x,
                img_y,
                img_w,
                img_h,
                rx=8,
                style=Style(fill="rgba(255,255,255,0.04)", stroke=COLORS["outline"]),
            )
            canvas.add_text(
                img_x + 10,
                img_y + 20,
                "(missing image)",
                style=Style(fill=COLORS["muted"], font_size=11),
            )

        caption_y = y + thumb_h + 18
        sym_part = f"  {_short_line(ev.symbol or '', 22)}" if ev.symbol else ""
        line1 = f"{ev.id}  {ev.kind}" + sym_part
        canvas.add_text(
            x + 12,
            caption_y,
            line1.strip(),
            style=Style(fill=COLORS["text"], font_size=11, font_weight="bold"),
        )
        line2 = _metrics_line(ev.metrics)
        if line2:
            canvas.add_text(
                x + 12,
                caption_y + 16,
                _short_line(line2, 40),
                style=Style(fill=COLORS["muted"], font_size=11),
            )


def _png_to_data_url(png_path: str) -> Optional[str]:
    if not png_path:
        return None
    p = Path(png_path)
    if not p.exists() or not p.is_file():
        return None
    try:
        raw = p.read_bytes()
    except Exception:
        return None
    if len(raw) > 2_000_000:
        return None
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _metrics_line(metrics: object) -> str:
    if not isinstance(metrics, dict):
        return ""
    out: List[str] = []
    if "depth" in metrics:
        out.append(f"d={metrics.get('depth')}")
    if "node_count" in metrics:
        out.append(f"nodes={metrics.get('node_count')}")
    if "edge_count" in metrics:
        out.append(f"edges={metrics.get('edge_count')}")
    return " ".join(out)


def _chips(ids: List[str]) -> str:
    xs = list(ids or [])
    s = " ".join(xs[:4])
    if len(xs) > 4:
        s += f" +{len(xs) - 4}"
    return s


def _wrap_text(text: str, *, max_chars: int, max_lines: int) -> List[str]:
    t = (text or "").strip()
    if not t:
        return ["(empty)"]

    words = t.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
            continue
        if len(cur) + 1 + len(w) <= max_chars:
            cur = cur + " " + w
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break

    if len(lines) < max_lines and cur:
        lines.append(cur)

    if len(lines) == max_lines and (" ".join(lines) != t):
        last = lines[-1]
        if len(last) >= max_chars:
            last = last[: max(0, max_chars - 1)]
        lines[-1] = last.rstrip() + "…"
    return lines


def _short_line(s: str, max_len: int) -> str:
    ss = (s or "").strip()
    return ss if len(ss) <= max_len else ss[: max_len - 1] + "…"


def _short_url(url: str, *, max_len: int) -> str:
    u = (url or "").strip()
    if len(u) <= max_len:
        return u
    if "://" in u:
        _, rest = u.split("://", 1)
        dom = rest.split("/", 1)[0]
        tail = u[-18:]
        cand = f"{dom}/…/{tail}"
        return cand if len(cand) <= max_len else cand[: max_len - 1] + "…"
    return u[: max_len - 1] + "…"
