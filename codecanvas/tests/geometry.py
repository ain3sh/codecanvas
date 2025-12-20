from __future__ import annotations

from codecanvas.views.geometry import Rect, polyline_intersects_any_rect, route_via_outer_lane


def test_route_via_outer_lane_avoids_other_rects():
    src = Rect(100, 100, 200, 120)
    dst = Rect(500, 420, 200, 120)
    obstacle = Rect(250, 250, 200, 140)

    pts = route_via_outer_lane(src, dst, side="left", lane_x=40)
    assert not polyline_intersects_any_rect(pts, [obstacle], ignore=[src, dst])


def test_route_via_outer_lane_has_expected_shape():
    src = Rect(100, 100, 200, 120)
    dst = Rect(500, 420, 200, 120)
    pts = route_via_outer_lane(src, dst, side="right", lane_x=900)
    assert len(pts) == 4
    assert pts[1][0] == 900 and pts[2][0] == 900
