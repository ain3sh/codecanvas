"""Impact View - Blast radius (callers/callees)."""

import math
import os
from typing import Dict, Tuple

from ..core.models import Graph, NodeKind
from . import COLORS, Style, SVGCanvas


class ImpactView:
    def __init__(self, graph: Graph):
        self.graph = graph

    def render(
        self,
        target_id: str,
        *,
        caller_counts: Dict[str, int],
        callee_counts: Dict[str, int],
        max_side: int = 8,
        output_path: str | None = None,
    ) -> str:
        """Render the impact view."""

        target_node = self.graph.get_node(target_id)
        if not target_node:
            return ""

        def short_path(p: str) -> str:
            p = (p or "").replace("\\", "/")
            return os.path.basename(p) or p

        def first_nonempty_line(s: str) -> str:
            for line in (s or "").splitlines():
                if line.strip():
                    return line.strip()
            return ""

        max_side = max(0, int(max_side))
        callers_all = [self.graph.get_node(nid) for nid in caller_counts]
        callees_all = [self.graph.get_node(nid) for nid in callee_counts]
        callers_all = [n for n in callers_all if n is not None]
        callees_all = [n for n in callees_all if n is not None]

        callers_all.sort(key=lambda n: caller_counts.get(n.id, 0), reverse=True)
        callees_all.sort(key=lambda n: callee_counts.get(n.id, 0), reverse=True)

        callers = callers_all[:max_side]
        callees = callees_all[:max_side]
        callers_more = max(0, len(callers_all) - len(callers))
        callees_more = max(0, len(callees_all) - len(callees))

        # 2. Layout
        base_width, base_height = 1000, 800
        if callers and not callees:
            cx = base_width * 0.62
        elif callees and not callers:
            cx = base_width * 0.38
        else:
            cx = base_width / 2
        cy = base_height / 2

        positions: Dict[str, Tuple[float, float]] = {}
        positions[target_id] = (cx, cy)

        # Layout Arcs
        radius_x = 350
        radius_y = 250

        def layout_nodes(nodes, start_ang, end_ang):
            if not nodes:
                return
            step = (end_ang - start_ang) / (len(nodes) + 1)
            for i, node in enumerate(nodes):
                angle = math.radians(start_ang + step * (i + 1))
                x = cx + radius_x * math.cos(angle)
                y = cy + radius_y * math.sin(angle)
                positions[node.id] = (x, y)

        layout_nodes(callers, 150, 210)  # Left
        layout_nodes(callees, -30, 30)  # Right

        card_w, card_h = 300, 150
        node_w, node_h = 180, 40
        min_w, min_h = 560, 360
        max_w, max_h = base_width, base_height
        pad_x, pad_y = 80, 80

        def _node_bounds(px: float, py: float, w: float, h: float) -> Tuple[float, float, float, float]:
            return (px - w / 2, py - h / 2, px + w / 2, py + h / 2)

        bounds = [_node_bounds(cx, cy, card_w, card_h)]
        for node in callers + callees:
            px, py = positions.get(node.id, (cx, cy))
            bounds.append(_node_bounds(px, py, node_w, node_h))

        min_x = min(b[0] for b in bounds)
        min_y = min(b[1] for b in bounds)
        max_x = max(b[2] for b in bounds)
        max_y = max(b[3] for b in bounds)
        bbox_w = max_x - min_x
        bbox_h = max_y - min_y

        width = min(max(bbox_w + 2 * pad_x, min_w), max_w)
        height = min(max(bbox_h + 2 * pad_y, min_h), max_h)

        extra_x = max(0.0, (width - (bbox_w + 2 * pad_x)) / 2)
        extra_y = max(0.0, (height - (bbox_h + 2 * pad_y)) / 2)
        shift_x = pad_x - min_x + extra_x
        shift_y = pad_y - min_y + extra_y

        def _shift(p: Tuple[float, float]) -> Tuple[float, float]:
            return (p[0] + shift_x, p[1] + shift_y)

        # 3. Render
        canvas = SVGCanvas(width=int(width), height=int(height))

        # Draw Aggregated Edges
        for neighbor in callers:
            if neighbor.id not in positions:
                continue
            count = caller_counts[neighbor.id]
            p1 = _shift(positions[neighbor.id])
            p2 = _shift(positions[target_id])

            # Thick red line
            canvas.add_line(
                p1[0], p1[1], p2[0], p2[1], style=Style(stroke=COLORS["danger"], stroke_width=2 + math.log(count))
            )

            # Label
            mid_x = (p1[0] + p2[0]) / 2
            mid_y = (p1[1] + p2[1]) / 2
            canvas.add_rect(
                mid_x - 10, mid_y - 10, 20, 20, rx=4, style=Style(fill=COLORS["bg"], stroke=COLORS["danger"])
            )
            canvas.add_text(
                mid_x,
                mid_y + 4,
                str(count),
                style=Style(fill=COLORS["danger"], text_anchor="middle", font_size=10, font_weight="bold"),
            )

        for neighbor in callees:
            if neighbor.id not in positions:
                continue
            count = callee_counts[neighbor.id]
            p1 = _shift(positions[target_id])
            p2 = _shift(positions[neighbor.id])

            # Thick blue line
            canvas.add_line(
                p1[0], p1[1], p2[0], p2[1], style=Style(stroke=COLORS["tool"], stroke_width=2 + math.log(count))
            )

        # Draw Target Card (Center)
        # Box
        cx, cy = _shift(positions[target_id])
        canvas.add_rect(
            cx - card_w / 2,
            cy - card_h / 2,
            card_w,
            card_h,
            rx=8,
            style=Style(fill=COLORS["card"], stroke=COLORS["focus"], stroke_width=2, filter="drop-shadow"),
        )

        # Title
        canvas.add_text(
            cx,
            cy - card_h / 2 + 25,
            target_node.label,
            style=Style(fill=COLORS["text"], font_size=18, font_weight="bold", text_anchor="middle"),
        )

        # Docstring / Snippet
        lines: list[str] = []
        if target_node.kind == NodeKind.MODULE:
            children = self.graph.get_children(target_node.id)
            n_cls = sum(1 for c in children if c.kind == NodeKind.CLASS)
            n_fn = sum(1 for c in children if c.kind == NodeKind.FUNC)
            lines.append(f"file: {target_node.label}")
            lines.append(f"contains: {n_cls} classes, {n_fn} funcs")
            # Show a couple of contained symbols for interpretability.
            shown = 0
            for c in sorted(children, key=lambda n: (n.kind.value, n.label)):
                if c.kind not in (NodeKind.CLASS, NodeKind.FUNC):
                    continue
                lines.append(f"- {c.kind.value}: {c.label}")
                shown += 1
                if shown >= 2:
                    break
        else:
            sig = first_nonempty_line(target_node.snippet or "")
            if sig:
                lines.append(sig)
            loc = short_path(target_node.fsPath)
            if target_node.start_line is not None:
                loc = f"{loc}:{int(target_node.start_line) + 1}"
            lines.append(loc)

        if not lines:
            lines = ["No source available"]

        lines = lines[:4]
        y_text = cy - card_h / 2 + 50
        for line in lines:
            canvas.add_text(
                cx - card_w / 2 + 10,
                y_text,
                line[:40],
                style=Style(fill=COLORS["muted"], font_family="monospace", font_size=10),
            )
            y_text += 14

        # Draw Neighbors (Simple Boxes)
        for node in callers + callees:
            if node.id not in positions:
                continue
            px, py = _shift(positions[node.id])

            color = COLORS["danger"] if node in callers else COLORS["tool"]

            canvas.add_rect(
                px - node_w / 2,
                py - node_h / 2,
                node_w,
                node_h,
                rx=4,
                style=Style(fill=COLORS["module_bg"], stroke=color, stroke_width=1),
            )

            label = _mid_ellipsis(node.label, max_len=25)
            canvas.add_text(px, py + 5, label, style=Style(fill=COLORS["text"], text_anchor="middle", font_size=12))

        if callers_more:
            canvas.add_text(
                60,
                60,
                f"+{callers_more} more callers",
                style=Style(fill=COLORS["muted"], font_size=12, font_weight="bold"),
            )
        if callees_more:
            canvas.add_text(
                width - 60,
                60,
                f"+{callees_more} more callees",
                style=Style(fill=COLORS["muted"], font_size=12, font_weight="bold", text_anchor="end"),
            )

        if output_path:
            canvas.save(output_path)

        return canvas.render()


def _mid_ellipsis(s: str, *, max_len: int, head: int = 12, tail: int = 10) -> str:
    txt = (s or "").strip()
    if len(txt) <= max_len:
        return txt
    head = min(head, max_len - 2)
    tail = min(tail, max_len - head - 1)
    return txt[:head] + "…" + txt[-tail:]
