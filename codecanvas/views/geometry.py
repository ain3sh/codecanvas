from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

Point = Tuple[float, float]


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


def ports(r: Rect) -> Dict[str, Point]:
    return {
        "N": (r.cx, r.top),
        "S": (r.cx, r.bottom),
        "W": (r.left, r.cy),
        "E": (r.right, r.cy),
    }


def segment_intersects_rect(p1: Point, p2: Point, r: Rect) -> bool:
    """Axis-aligned segment intersection with a rectangle (inclusive borders).

    This is intentionally simple: CodeCanvas routes only orthogonal polylines.
    """
    x1, y1 = p1
    x2, y2 = p2

    if x1 == x2:
        x = x1
        if x < r.left or x > r.right:
            return False
        lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)
        return not (hi < r.top or lo > r.bottom)

    if y1 == y2:
        y = y1
        if y < r.top or y > r.bottom:
            return False
        lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
        return not (hi < r.left or lo > r.right)

    # Non-orthogonal segments are not expected.
    return False


def polyline_intersects_any_rect(
    pts: List[Point],
    rects: Iterable[Rect],
    *,
    ignore: Optional[Iterable[Rect]] = None,
) -> bool:
    ignore_set = set(ignore or [])
    rs = [r for r in rects if r not in ignore_set]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        for r in rs:
            if segment_intersects_rect(a, b, r):
                return True
    return False


def route_via_outer_lane(
    src: Rect,
    dst: Rect,
    *,
    side: str,
    lane_x: float,
) -> List[Point]:
    """Route an orthogonal polyline via an external vertical lane.

    side: 'left' or 'right'
    """
    ps = ports(src)
    pd = ports(dst)
    src_p = ps["W"] if side == "left" else ps["E"]
    dst_p = pd["W"] if side == "left" else pd["E"]

    return [
        src_p,
        (lane_x, src_p[1]),
        (lane_x, dst_p[1]),
        dst_p,
    ]


def rounded_path_d(pts: List[Point], radius: float = 10.0) -> str:
    """Create an SVG path string from an orthogonal polyline with rounded corners."""
    if not pts:
        return ""
    if len(pts) == 1:
        x, y = pts[0]
        return f"M {x} {y}"

    def clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    d: List[str] = []
    x0, y0 = pts[0]
    d.append(f"M {x0} {y0}")

    for i in range(1, len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        xp, yp = pts[i - 1]

        # Incoming dir
        in_dx = 0 if x1 == xp else (1 if x1 > xp else -1)
        in_dy = 0 if y1 == yp else (1 if y1 > yp else -1)
        out_dx = 0 if x2 == x1 else (1 if x2 > x1 else -1)
        out_dy = 0 if y2 == y1 else (1 if y2 > y1 else -1)

        # If it's a straight segment, just line-to.
        if (in_dx, in_dy) == (out_dx, out_dy):
            d.append(f"L {x1} {y1}")
            continue

        # Shorten the corner by radius in both directions.
        cut_in_x = x1 - in_dx * radius
        cut_in_y = y1 - in_dy * radius
        cut_out_x = x1 + out_dx * radius
        cut_out_y = y1 + out_dy * radius

        # Clamp cut points so we don't overshoot segment length.
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

    xN, yN = pts[-1]
    d.append(f"L {xN} {yN}")
    return " ".join(d)
