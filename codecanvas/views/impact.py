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
        width, height = 1000, 800
        cx, cy = width / 2, height / 2

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

        # 3. Render
        canvas = SVGCanvas(width=width, height=height)

        # Draw Aggregated Edges
        for neighbor in callers:
            if neighbor.id not in positions:
                continue
            count = caller_counts[neighbor.id]
            p1 = positions[neighbor.id]
            p2 = positions[target_id]

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
            p1 = positions[target_id]
            p2 = positions[neighbor.id]

            # Thick blue line
            canvas.add_line(
                p1[0], p1[1], p2[0], p2[1], style=Style(stroke=COLORS["tool"], stroke_width=2 + math.log(count))
            )

        # Draw Target Card (Center)
        # Box
        card_w, card_h = 300, 150
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
        node_w, node_h = 180, 40
        for node in callers + callees:
            if node.id not in positions:
                continue
            px, py = positions[node.id]

            color = COLORS["danger"] if node in callers else COLORS["tool"]

            canvas.add_rect(
                px - node_w / 2,
                py - node_h / 2,
                node_w,
                node_h,
                rx=4,
                style=Style(fill=COLORS["module_bg"], stroke=color, stroke_width=1),
            )

            label = node.label
            if len(label) > 25:
                label = "..." + label[-22:]
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
