"""Architecture View - The Territory Map (District Overview).

This view is intentionally low-density. It summarizes the module graph into
"district" cards (clusters of modules), then draws only the strongest
district-to-district dependency highways.

Hard budget:
- <= 24 district cards (8 per band)
- <= 20 highways
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..core.models import EdgeType, Graph, GraphNode, NodeKind
from . import COLORS, Style, SVGCanvas

Point = Tuple[float, float]


# =============================================================================
# Geometry Primitives
# =============================================================================


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def _ports(r: Rect) -> Dict[str, Point]:
    return {"N": (r.cx, r.top), "S": (r.cx, r.bottom), "W": (r.left, r.cy), "E": (r.right, r.cy)}


def _segment_intersects_rect(p1: Point, p2: Point, r: Rect) -> bool:
    """Axis-aligned segment intersection with a rectangle."""
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if x1 < r.left or x1 > r.right:
            return False
        lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)
        return not (hi < r.top or lo > r.bottom)
    if y1 == y2:
        if y1 < r.top or y1 > r.bottom:
            return False
        lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
        return not (hi < r.left or lo > r.right)
    return False


def _polyline_intersects_any_rect(
    pts: List[Point],
    rects: Iterable[Rect],
    *,
    ignore: Optional[Iterable[Rect]] = None,
) -> bool:
    ignore_set = set(ignore or [])
    rs = [r for r in rects if r not in ignore_set]
    for i in range(len(pts) - 1):
        for r in rs:
            if _segment_intersects_rect(pts[i], pts[i + 1], r):
                return True
    return False


def route_via_outer_lane(src: Rect, dst: Rect, *, side: str, lane_x: float) -> List[Point]:
    """Route an orthogonal polyline via an external vertical lane."""
    ps, pd = _ports(src), _ports(dst)
    src_p = ps["W"] if side == "left" else ps["E"]
    dst_p = pd["W"] if side == "left" else pd["E"]
    return [src_p, (lane_x, src_p[1]), (lane_x, dst_p[1]), dst_p]


def rounded_path_d(pts: List[Point], radius: float = 10.0) -> str:
    """Create an SVG path string from an orthogonal polyline with rounded corners."""
    if not pts:
        return ""
    if len(pts) == 1:
        return f"M {pts[0][0]} {pts[0][1]}"

    def clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    d: List[str] = [f"M {pts[0][0]} {pts[0][1]}"]
    for i in range(1, len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        xp, yp = pts[i - 1]
        in_dx = 0 if x1 == xp else (1 if x1 > xp else -1)
        in_dy = 0 if y1 == yp else (1 if y1 > yp else -1)
        out_dx = 0 if x2 == x1 else (1 if x2 > x1 else -1)
        out_dy = 0 if y2 == y1 else (1 if y2 > y1 else -1)
        if (in_dx, in_dy) == (out_dx, out_dy):
            d.append(f"L {x1} {y1}")
            continue
        cut_in_x, cut_in_y = x1 - in_dx * radius, y1 - in_dy * radius
        cut_out_x, cut_out_y = x1 + out_dx * radius, y1 + out_dy * radius
        if in_dx != 0:
            cut_in_x = clamp(cut_in_x, min(xp, x1), max(xp, x1))
            cut_in_y = y1
        if in_dy != 0:
            cut_in_y = clamp(cut_in_y, min(yp, y1), max(yp, y1))
            cut_in_x = x1
        if out_dx != 0:
            cut_out_x = clamp(cut_out_x, min(x1, x2), max(x1, x2))
            cut_out_y = y1
        if out_dy != 0:
            cut_out_y = clamp(cut_out_y, min(y1, y2), max(y1, y2))
            cut_out_x = x1
        d.append(f"L {cut_in_x} {cut_in_y}")
        d.append(f"Q {x1} {y1} {cut_out_x} {cut_out_y}")
    d.append(f"L {pts[-1][0]} {pts[-1][1]}")
    return " ".join(d)


@dataclass
class _Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class _District:
    district_id: str
    band: int  # 0 entry, 1 core, 2 foundation
    name: str
    module_ids: List[str]
    total_mass: float
    top_modules: List[str]


class ArchitectureView:
    def __init__(self, graph: Graph):
        self.graph = graph

    def render(self, output_path: str | None = None) -> str:
        """Render architecture overview as SVG (PNG conversion happens upstream)."""
        modules, import_edges = _module_graph(self.graph)
        if not modules:
            return SVGCanvas(width=1200, height=800).render()

        module_in_deg = _module_in_degrees(modules, import_edges)
        module_mass = _normalize_mass(module_in_deg)

        comps, mod_to_comp = _scc_kosaraju([m.id for m in modules], import_edges)
        comp_edges = _condense_edges(mod_to_comp, import_edges)
        comp_layers = _compute_layers(comps, comp_edges)
        comp_band = _bandify_components(comps, comp_edges, comp_layers)
        comp_band = _ensure_core_band(comp_band, comp_layers)

        comp_cluster = _label_propagation_clusters(comps, comp_edges)
        comp_cluster = _merge_tiny_clusters(comps, comp_edges, comp_cluster, min_modules=3)

        districts = _build_districts(
            graph=self.graph,
            modules=modules,
            mod_to_comp=mod_to_comp,
            comp_band=comp_band,
            comp_cluster=comp_cluster,
            module_mass=module_mass,
        )

        visible_ids = _select_visible_districts(districts, per_band=8)
        districts = _add_other_districts(self.graph, districts, visible_ids, module_mass)
        _normalize_district_masses(districts)
        district_remap = _remap_to_visible(districts, visible_ids)
        highways = _district_highways(import_edges, district_remap)

        dist_in, dist_out = _district_in_out(import_edges, district_remap)

        # Layout
        width, height = 1400, 900
        canvas = SVGCanvas(width=width, height=height)

        margin = 40
        band_h = (height - 2 * margin) / 3
        band_names = {0: "ENTRY", 1: "CORE", 2: "FOUNDATION"}
        default_bg = COLORS["module_bg"]
        band_bg = {
            0: COLORS.get("layer_0", default_bg),
            1: COLORS.get("layer_1", default_bg),
            2: COLORS.get("layer_2", default_bg),
        }

        # Assign boxes (dynamic grid per band)
        boxes: Dict[str, _Box] = {}
        band_order = _order_districts(districts, visible_ids, highways)
        for band in (0, 1, 2):
            band_y = margin + band * band_h
            canvas.add_rect(
                margin,
                band_y,
                width - 2 * margin,
                band_h - 12,
                rx=10,
                style=Style(fill=band_bg[band], opacity=0.25),
            )
            canvas.add_text(
                margin + 10,
                band_y + 28,
                band_names[band],
                style=Style(fill=COLORS["muted"], font_size=18, font_weight="bold", opacity=0.7),
            )

            band_districts = [d for d in districts if d.district_id in visible_ids and d.band == band]
            band_districts = band_order.get(band, band_districts)

            cols, rows = _pick_grid(len(band_districts))
            cell_w = (width - 2 * margin - (cols - 1) * 16) / max(1, cols)
            cell_h = (band_h - 60 - (rows - 1) * 16) / max(1, rows)

            for idx, d in enumerate(band_districts[: cols * rows]):
                r = idx // cols
                c = idx % cols
                x = margin + c * (cell_w + 16)
                y = band_y + 44 + r * (cell_h + 16)
                boxes[d.district_id] = _Box(x, y, cell_w, cell_h)

        # Draw highways (behind cards) routed via outer lanes so they never disappear under cards.
        highways = _filter_highways(highways)
        left_i = 0
        right_i = 0
        for (a, b), wgt in highways[:20]:
            if a not in boxes or b not in boxes:
                continue

            r1 = Rect(boxes[a].x, boxes[a].y, boxes[a].w, boxes[a].h)
            r2 = Rect(boxes[b].x, boxes[b].y, boxes[b].w, boxes[b].h)

            avg_x = (r1.cx + r2.cx) / 2
            if avg_x < width / 2:
                lane_x = max(12.0, margin - 30.0 - left_i * 10.0)
                left_i += 1
                side = "left"
            else:
                lane_x = min(width - 12.0, width - margin + 30.0 + right_i * 10.0)
                right_i += 1
                side = "right"

            pts = route_via_outer_lane(r1, r2, side=side, lane_x=lane_x)
            path_d = rounded_path_d(pts, radius=10.0)
            thickness = min(8.0, 1.5 + math.log(max(1, wgt), 2))
            canvas.add_path(
                path_d,
                style=Style(stroke=COLORS["import"], stroke_width=thickness, opacity=0.28),
            )

            if wgt >= 2:
                mx = lane_x
                my = (pts[0][1] + pts[-1][1]) / 2
                canvas.add_circle(mx, my, 10, style=Style(fill=COLORS["bg"], stroke=COLORS["outline"], opacity=0.85))
                canvas.add_text(
                    mx,
                    my + 4,
                    str(wgt),
                    style=Style(fill=COLORS["text"], font_size=10, text_anchor="middle", font_weight="bold"),
                )

        # Draw district cards
        for d in districts:
            if d.district_id not in visible_ids:
                continue
            box = boxes.get(d.district_id)
            if not box:
                continue

            canvas.add_rect(
                box.x,
                box.y,
                box.w,
                box.h,
                rx=10,
                style=Style(fill=COLORS["card"], stroke=COLORS["outline"], stroke_width=1.0, filter="drop-shadow"),
            )
            canvas.add_text(
                box.x + 12,
                box.y + 26,
                _short_title(d.name),
                style=Style(fill=COLORS["text"], font_size=14, font_weight="bold"),
            )
            in_cnt = dist_in.get(d.district_id, 0)
            out_cnt = dist_out.get(d.district_id, 0)
            canvas.add_text(
                box.x + 12,
                box.y + 44,
                f"{len(d.module_ids)} modules    in/out: {in_cnt}/{out_cnt}",
                style=Style(fill=COLORS["muted"], font_size=11),
            )

            # Hubness glyph (size-encoded): larger dot = more depended-on.
            hub_r = 4.0 + 10.0 * min(1.0, max(0.0, d.total_mass))
            canvas.add_circle(
                box.x + box.w - 18,
                box.y + 22,
                hub_r,
                style=Style(fill=COLORS["import"], stroke="none", opacity=0.9),
            )

            y = box.y + 66
            for tm in d.top_modules[:3]:
                canvas.add_text(
                    box.x + 12,
                    y,
                    f"• {_short_path(tm)}",
                    style=Style(fill=COLORS["text"], font_size=11),
                )
                y += 16

        # Legend
        lx = margin
        ly = height - 22
        canvas.add_circle(lx + 8, ly - 6, 7, style=Style(fill=COLORS["import"], stroke="none", opacity=0.9))
        canvas.add_text(
            lx + 22,
            ly,
            "dot size = hubness (imported-by-others)",
            style=Style(fill=COLORS["muted"], font_size=11),
        )

        return canvas.render()


def _short_title(s: str, max_len: int = 34) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    # Prefer keeping the left side for district titles.
    return s[: max_len - 1] + "…"


def _short_path(label: str, max_len: int = 42) -> str:
    """Render a path in a scan-friendly way: keep first segment and basename."""
    s = (label or "").replace("\\\\", "/")
    parts = [p for p in s.split("/") if p]
    if len(parts) <= 2:
        out = s
    else:
        out = f"{parts[0]}/…/{parts[-1]}"
    if len(out) <= max_len:
        return out
    # If still too long, shrink basename.
    base = parts[-1] if parts else out
    if len(base) > 18:
        base = base[:8] + "…" + base[-8:]
    if parts:
        out = f"{parts[0]}/…/{base}"
    return out[: max_len - 1] + "…" if len(out) > max_len else out


def _district_in_out(
    import_edges: List[Tuple[str, str]],
    module_to_district: Dict[str, str],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    inc: Dict[str, int] = {}
    out: Dict[str, int] = {}
    for a, b in import_edges:
        da = module_to_district.get(a)
        db = module_to_district.get(b)
        if not da or not db or da == db:
            continue
        out[da] = out.get(da, 0) + 1
        inc[db] = inc.get(db, 0) + 1
    return inc, out


def _filter_highways(highways: List[Tuple[Tuple[str, str], int]]) -> List[Tuple[Tuple[str, str], int]]:
    """Suppress low-signal edges involving the 'other' buckets unless heavy."""
    out: List[Tuple[Tuple[str, str], int]] = []
    for (a, b), w in highways:
        if (a.endswith("_other") or b.endswith("_other")) and w < 3:
            continue
        out.append(((a, b), w))
    return out


def _ensure_core_band(comp_band: Dict[int, int], comp_layers: Dict[int, int]) -> Dict[int, int]:
    if any(b == 1 for b in comp_band.values()):
        return comp_band
    if len(comp_band) <= 2:
        return comp_band

    layers = sorted(comp_layers.values())
    if not layers:
        return comp_band
    if layers[0] == layers[-1]:
        # all same layer; force all to core
        return {k: 1 for k in comp_band}

    lo = layers[int(0.2 * (len(layers) - 1))]
    hi = layers[int(0.8 * (len(layers) - 1))]
    out = dict(comp_band)
    for cid, lyr in comp_layers.items():
        if lo < lyr < hi:
            out[cid] = 1
    return out


def _module_graph(graph: Graph) -> Tuple[List[GraphNode], List[Tuple[str, str]]]:
    modules = [n for n in graph.nodes if n.kind == NodeKind.MODULE]
    module_ids = {m.id for m in modules}
    edges: List[Tuple[str, str]] = []
    for e in graph.edges:
        if e.type == EdgeType.IMPORT and e.from_id in module_ids and e.to_id in module_ids:
            if e.from_id != e.to_id:
                edges.append((e.from_id, e.to_id))
    return modules, edges


def _module_in_degrees(modules: List[GraphNode], import_edges: List[Tuple[str, str]]) -> Dict[str, int]:
    indeg = {m.id: 0 for m in modules}
    for _, to_id in import_edges:
        if to_id in indeg:
            indeg[to_id] += 1
    return indeg


def _normalize_mass(indeg: Dict[str, int]) -> Dict[str, float]:
    max_in = max(indeg.values()) if indeg else 1
    if max_in <= 0:
        max_in = 1
    return {k: (v / max_in) for k, v in indeg.items()}


def _scc_kosaraju(nodes: List[str], edges: List[Tuple[str, str]]) -> Tuple[List[List[str]], Dict[str, int]]:
    """Return SCCs and a node->component index map.

    Uses iterative DFS to avoid stack overflow on large graphs.
    """
    graph: Dict[str, List[str]] = {n: [] for n in nodes}
    rev: Dict[str, List[str]] = {n: [] for n in nodes}
    for a, b in edges:
        if a in graph and b in graph:
            graph[a].append(b)
            rev[b].append(a)

    visited: Set[str] = set()
    order: List[str] = []

    # Iterative DFS for post-order traversal
    for start in nodes:
        if start in visited:
            continue
        stack: List[Tuple[str, int]] = [(start, 0)]  # (node, child_index)
        while stack:
            node, idx = stack.pop()
            if idx == 0:
                if node in visited:
                    continue
                visited.add(node)
            children = graph.get(node, [])
            if idx < len(children):
                stack.append((node, idx + 1))
                child = children[idx]
                if child not in visited:
                    stack.append((child, 0))
            else:
                order.append(node)

    visited.clear()
    comps: List[List[str]] = []

    # Iterative DFS for component collection
    for start in reversed(order):
        if start in visited:
            continue
        acc: List[str] = []
        stack_nodes: List[str] = [start]
        while stack_nodes:
            node = stack_nodes.pop()
            if node in visited:
                continue
            visited.add(node)
            acc.append(node)
            for nxt in rev.get(node, []):
                if nxt not in visited:
                    stack_nodes.append(nxt)
        comps.append(acc)

    node_to_comp: Dict[str, int] = {}
    for i, comp in enumerate(comps):
        for n in comp:
            node_to_comp[n] = i
    return comps, node_to_comp


def _condense_edges(node_to_comp: Dict[str, int], edges: List[Tuple[str, str]]) -> Dict[Tuple[int, int], int]:
    weights: Dict[Tuple[int, int], int] = {}
    for a, b in edges:
        ca = node_to_comp[a]
        cb = node_to_comp[b]
        if ca == cb:
            continue
        weights[(ca, cb)] = weights.get((ca, cb), 0) + 1
    return weights


def _compute_layers(comps: List[List[str]], comp_edges: Dict[Tuple[int, int], int]) -> Dict[int, int]:
    n = len(comps)
    out_map: Dict[int, List[int]] = {i: [] for i in range(n)}
    in_deg: Dict[int, int] = {i: 0 for i in range(n)}
    for (a, b), _w in comp_edges.items():
        out_map[a].append(b)
        in_deg[b] += 1

    # Kahn-style layering
    from collections import deque

    q = deque([i for i in range(n) if in_deg[i] == 0])
    layer: Dict[int, int] = {i: 0 for i in q}

    while q:
        cur = q.popleft()
        cur_layer = layer.get(cur, 0)
        for nxt in out_map.get(cur, []):
            in_deg[nxt] -= 1
            layer[nxt] = max(layer.get(nxt, 0), cur_layer + 1)
            if in_deg[nxt] == 0:
                q.append(nxt)

    # Any remaining (cycles in condensed graph shouldn't happen, but keep safe)
    for i in range(n):
        layer.setdefault(i, 0)
    return layer


def _bandify_components(
    comps: List[List[str]],
    comp_edges: Dict[Tuple[int, int], int],
    comp_layers: Dict[int, int],
) -> Dict[int, int]:
    """Assign bands (entry/core/foundation).

    Primary rule: use indegree/outdegree on the condensed graph so CORE exists
    for small repos.

    Fallback: if everything is classified as CORE (rare), fall back to quantiles
    on topological layers.
    """
    n = len(comps)
    indeg = {i: 0 for i in range(n)}
    outdeg = {i: 0 for i in range(n)}
    for (a, b), _w in comp_edges.items():
        outdeg[a] += 1
        indeg[b] += 1

    band: Dict[int, int] = {}
    for i in range(n):
        if indeg[i] == 0 and outdeg[i] > 0:
            band[i] = 0
        elif outdeg[i] == 0 and indeg[i] > 0:
            band[i] = 2
        elif indeg[i] == 0 and outdeg[i] == 0:
            band[i] = 1
        else:
            band[i] = 1

    if all(v == 1 for v in band.values()):
        # fallback to layer quantiles
        layers = sorted(comp_layers.values())
        if not layers:
            return band
        if layers[0] == layers[-1]:
            return band
        lo = layers[int(0.2 * (len(layers) - 1))]
        hi = layers[int(0.8 * (len(layers) - 1))]
        for cid, lyr in comp_layers.items():
            if lyr <= lo:
                band[cid] = 0
            elif lyr >= hi:
                band[cid] = 2
            else:
                band[cid] = 1

    return band


def _label_propagation_clusters(
    comps: List[List[str]],
    comp_edges: Dict[Tuple[int, int], int],
    iters: int = 12,
) -> Dict[int, int]:
    # Build undirected weighted adjacency on components.
    n = len(comps)
    adj: Dict[int, Dict[int, int]] = {i: {} for i in range(n)}
    for (a, b), w in comp_edges.items():
        adj[a][b] = adj[a].get(b, 0) + w
        adj[b][a] = adj[b].get(a, 0) + w

    labels: Dict[int, int] = {i: i for i in range(n)}
    for _ in range(iters):
        changed = 0
        for i in range(n):
            if not adj[i]:
                continue
            score: Dict[int, int] = {}
            for nbr, w in adj[i].items():
                lab = labels[nbr]
                score[lab] = score.get(lab, 0) + w
            best = max(score.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if labels[i] != best:
                labels[i] = best
                changed += 1
        if changed == 0:
            break
    return labels


def _merge_tiny_clusters(
    comps: List[List[str]],
    comp_edges: Dict[Tuple[int, int], int],
    comp_cluster: Dict[int, int],
    min_modules: int = 3,
) -> Dict[int, int]:
    # Count modules per cluster
    cluster_mods: Dict[int, int] = {}
    for cid, nodes in enumerate(comps):
        lab = comp_cluster[cid]
        cluster_mods[lab] = cluster_mods.get(lab, 0) + len(nodes)

    n = len(comps)
    adj: Dict[int, Dict[int, int]] = {i: {} for i in range(n)}
    for (a, b), w in comp_edges.items():
        adj[a][b] = adj[a].get(b, 0) + w
        adj[b][a] = adj[b].get(a, 0) + w

    # Merge tiny clusters into their strongest neighbor cluster.
    remap = dict(comp_cluster)
    for cid in range(n):
        lab = remap[cid]
        if cluster_mods.get(lab, 0) >= min_modules:
            continue
        best_lab = lab
        best_w = 0
        for nbr, w in adj[cid].items():
            nbr_lab = remap[nbr]
            if nbr_lab == lab:
                continue
            if w > best_w:
                best_w = w
                best_lab = nbr_lab
        if best_lab != lab:
            remap[cid] = best_lab

    return remap


def _build_districts(
    *,
    graph: Graph,
    modules: List[GraphNode],
    mod_to_comp: Dict[str, int],
    comp_band: Dict[int, int],
    comp_cluster: Dict[int, int],
    module_mass: Dict[str, float],
) -> List[_District]:
    # district key = (band, cluster)
    tmp: Dict[Tuple[int, int], List[str]] = {}
    for m in modules:
        cid = mod_to_comp[m.id]
        band = comp_band.get(cid, 1)
        cl = comp_cluster.get(cid, cid)
        tmp.setdefault((band, cl), []).append(m.id)

    districts: List[_District] = []
    for (band, cl), mids in tmp.items():
        total_mass = sum(module_mass.get(mid, 0.0) for mid in mids)
        # Name by common path prefix if possible (fallback to top module when prefix is too generic).
        labels: List[str] = []
        for mid in mids:
            if (node := graph.get_node(mid)) is not None:
                labels.append(node.label)
        top = sorted(mids, key=lambda mid: module_mass.get(mid, 0.0), reverse=True)
        top_labels: List[str] = []
        for mid in top[:3]:
            if (node := graph.get_node(mid)) is not None:
                top_labels.append(node.label)
        name = _cluster_name(labels, top_labels[0] if top_labels else None)
        districts.append(
            _District(
                district_id=f"d_{band}_{cl}",
                band=band,
                name=name,
                module_ids=mids,
                total_mass=total_mass,
                top_modules=top_labels,
            )
        )

    return districts


def _cluster_name(labels: List[str], top_label: Optional[str]) -> str:
    if not labels:
        return "<unknown>"
    # Prefer common directory prefix.
    parts = [lbl.replace("\\", "/").split("/")[:-1] for lbl in labels]
    if not parts:
        return labels[0]
    prefix: List[str] = []
    for segs in zip(*parts):
        if len(set(segs)) == 1:
            prefix.append(segs[0])
        else:
            break
    if prefix:
        # If prefix is just a broad repo package (e.g. "codecanvas"), use the top module
        # filename to disambiguate.
        if len(prefix) == 1 and top_label:
            leaf = top_label.replace("\\", "/").split("/")[-1]
            return f"{prefix[0]}/{leaf}"
        return "/".join(prefix) or "<root>"
    # Fallback: top-level folder or the file itself.
    first = labels[0].replace("\\", "/")
    return first.split("/")[0] if "/" in first else first


def _select_visible_districts(districts: List[_District], per_band: int = 8) -> Set[str]:
    visible: Set[str] = set()
    for band in (0, 1, 2):
        ds = [d for d in districts if d.band == band]
        ds.sort(key=lambda d: d.total_mass, reverse=True)
        for d in ds[:per_band]:
            visible.add(d.district_id)
    return visible


def _add_other_districts(
    graph: Graph,
    districts: List[_District],
    visible_ids: Set[str],
    module_mass: Dict[str, float],
) -> List[_District]:
    out = list(districts)
    for band in (0, 1, 2):
        hidden = [d for d in districts if d.band == band and d.district_id not in visible_ids]
        if not hidden:
            continue
        mids: List[str] = []
        for d in hidden:
            mids.extend(d.module_ids)

        if not mids:
            continue

        other_id = f"d_{band}_other"
        if other_id in visible_ids:
            continue

        total_mass = sum(module_mass.get(mid, 0.0) for mid in mids)
        top = sorted(mids, key=lambda mid: module_mass.get(mid, 0.0), reverse=True)
        top_labels: List[str] = []
        for mid in top[:3]:
            if (node := graph.get_node(mid)) is not None:
                top_labels.append(node.label)
        out.append(
            _District(
                district_id=other_id,
                band=band,
                name="Other",
                module_ids=mids,
                total_mass=total_mass,
                top_modules=top_labels,
            )
        )
        visible_ids.add(other_id)

    return out


def _normalize_district_masses(districts: List[_District]) -> None:
    max_mass = max((d.total_mass for d in districts), default=1.0)
    if max_mass <= 0:
        max_mass = 1.0
    for d in districts:
        d.total_mass = min(1.0, max(0.0, d.total_mass / max_mass))


def _remap_to_visible(districts: List[_District], visible_ids: Set[str]) -> Dict[str, str]:
    # Map module_id -> visible district id (or band-specific "Other").
    module_to_visible: Dict[str, str] = {}
    for d in districts:
        if d.district_id in visible_ids:
            for mid in d.module_ids:
                module_to_visible[mid] = d.district_id

    for d in districts:
        if d.district_id in visible_ids:
            continue
        other_id = f"d_{d.band}_other"
        for mid in d.module_ids:
            module_to_visible[mid] = other_id

    return module_to_visible


def _district_highways(
    import_edges: List[Tuple[str, str]],
    module_to_district: Dict[str, str],
) -> List[Tuple[Tuple[str, str], int]]:
    weights: Dict[Tuple[str, str], int] = {}
    for a, b in import_edges:
        da = module_to_district.get(a)
        db = module_to_district.get(b)
        if not da or not db or da == db:
            continue
        key = (da, db)
        weights[key] = weights.get(key, 0) + 1
    return sorted(weights.items(), key=lambda kv: kv[1], reverse=True)


def _pick_grid(n: int) -> Tuple[int, int]:
    """Pick a (cols, rows) grid that keeps cards large.

    Heuristic targets:
    - 1..4  -> Nx1
    - 5..8  -> 3x2 / 4x2
    """
    if n <= 0:
        return 1, 1
    n = min(8, n)

    cols = min(4, n)
    rows = (n + cols - 1) // cols

    # Keep rows <= 3 to avoid tiny cards.
    while rows > 3 and cols > 1:
        cols -= 1
        rows = (n + cols - 1) // cols

    return cols, rows


def _order_districts(
    districts: List[_District],
    visible_ids: Set[str],
    highways: List[Tuple[Tuple[str, str], int]],
) -> Dict[int, List[_District]]:
    """Cheap crossing-reduction ordering: barycenter over adjacent-band neighbors."""
    by_band: Dict[int, List[_District]] = {0: [], 1: [], 2: []}
    for d in districts:
        if d.district_id in visible_ids:
            by_band[d.band].append(d)
    for b in by_band:
        by_band[b].sort(key=lambda d: d.total_mass, reverse=True)

    # base ranks within each band
    rank: Dict[str, int] = {}
    for b in (0, 1, 2):
        for i, d in enumerate(by_band[b]):
            rank[d.district_id] = i

    neigh: Dict[str, List[Tuple[str, int]]] = {}
    for (a, b), w in highways:
        if a not in visible_ids or b not in visible_ids:
            continue
        neigh.setdefault(a, []).append((b, w))
        neigh.setdefault(b, []).append((a, w))

    def score(d: _District) -> float:
        ns = neigh.get(d.district_id, [])
        if not ns:
            return float(rank.get(d.district_id, 0))
        tot_w = sum(w for _, w in ns) or 1
        return sum(rank.get(nid, 0) * w for nid, w in ns) / tot_w

    ordered: Dict[int, List[_District]] = {}
    for b in (0, 1, 2):
        ds = list(by_band[b])
        ds.sort(key=lambda d: (score(d), -d.total_mass))
        ordered[b] = ds
    return ordered
