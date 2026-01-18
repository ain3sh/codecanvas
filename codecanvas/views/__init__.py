"""CodeCanvas visualization views.

Provides high-contrast, multimodal-optimized SVG generation for code architecture,
impact analysis, and task visualization.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

import cairosvg

from codecanvas.core.paths import update_manifest

# =============================================================================
# Color Palette (High Contrast / Neon on Black)
# =============================================================================

COLORS = {
    "bg": "#0e1116",
    "card": "#1b2130",
    "module_bg": "#141922",
    "outline": "#8a919a",
    "text": "#e6edf3",
    "muted": "#7d8590",
    # State Colors
    "pending": "#ef4444",
    "in_progress": "#fbbf24",
    "verified": "#22c55e",
    "skipped": "#9ca3af",
    # Edge Colors
    "import": "#a8b1ff",
    "call": "#86efac",
    "inherit": "#f472b6",
    # Highlights
    "danger": "#ef4444",
    "tool": "#0ea5e9",
    "focus": "#facc15",
    # Layer Bands
    "layer_0": "rgba(20, 25, 34, 0.5)",
    "layer_1": "rgba(27, 33, 48, 0.5)",
    "layer_2": "rgba(35, 43, 62, 0.5)",
}


# =============================================================================
# Style
# =============================================================================


@dataclass
class Style:
    fill: str = "none"
    stroke: str = "none"
    stroke_width: float = 1.0
    stroke_dasharray: Optional[str] = None
    opacity: float = 1.0
    font_size: int = 12
    font_family: str = "system-ui, -apple-system, sans-serif"
    font_weight: str = "normal"
    text_anchor: str = "start"
    filter: Optional[str] = None


# =============================================================================
# SVG Canvas
# =============================================================================


class SVGCanvas:
    """Lightweight SVG generator."""

    def __init__(self, width: int = 800, height: int = 600, dark_mode: bool = True):
        self.width = width
        self.height = height
        self.elements: List[str] = []
        self.defs: List[str] = []
        self.bg_color = COLORS["bg"] if dark_mode else "#ffffff"
        self._add_markers()
        self._add_filters()

    def _add_markers(self):
        self.defs.append(f'''
        <marker id="arrow-call" viewBox="0 -5 10 10" refX="8" refY="0" 
                markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,-5L10,0L0,5" fill="{COLORS["call"]}" />
        </marker>''')
        self.defs.append(f'''
        <marker id="arrow-import" viewBox="0 -5 10 10" refX="8" refY="0" 
                markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,-5L10,0L0,5" fill="{COLORS["import"]}" />
        </marker>''')

    def _add_filters(self):
        self.defs.append("""
        <filter id="drop-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2"/>
            <feOffset dx="2" dy="2" result="offsetblur"/>
            <feComponentTransfer><feFuncA type="linear" slope="0.3"/></feComponentTransfer>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>""")

    def add_rect(self, x: float, y: float, w: float, h: float, rx: float = 0, style: Style | None = None):
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" {attrs} />')

    def add_circle(self, cx: float, cy: float, r: float, style: Style | None = None):
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {attrs} />')

    def add_text(self, x: float, y: float, text: str, style: Style | None = None):
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<text x="{x}" y="{y}" {attrs}>{html.escape(str(text))}</text>')

    def add_text_lines(
        self,
        x: float,
        y: float,
        lines: List[str],
        style: Style | None = None,
        line_height: Optional[float] = None,
    ):
        if not lines:
            return
        s = style or Style()
        attrs = self._style_to_attrs(s)
        lh = line_height if line_height is not None else (s.font_size * 1.25)
        tspans = "".join(
            f'<tspan x="{x}" dy="{0 if i == 0 else lh}">{html.escape(str(line))}</tspan>'
            for i, line in enumerate(lines)
        )
        self.elements.append(f'<text x="{x}" y="{y}" {attrs}>{tspans}</text>')

    def add_image(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        href: str,
        opacity: float = 1.0,
        preserve_aspect_ratio: str = "xMidYMid meet",
    ):
        escaped_href = html.escape(str(href), quote=True)
        self.elements.append(
            f'<image x="{x}" y="{y}" width="{w}" height="{h}" href="{escaped_href}" '
            f'opacity="{opacity}" preserveAspectRatio="{preserve_aspect_ratio}" />'
        )

    def add_path(self, d: str, style: Style | None = None, marker_end: str | None = None):
        attrs = self._style_to_attrs(style or Style())
        marker = f'marker-end="url(#{marker_end})"' if marker_end else ""
        self.elements.append(f'<path d="{d}" {attrs} {marker} />')

    def add_line(self, x1: float, y1: float, x2: float, y2: float, style: Style | None = None):
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {attrs} />')

    def _style_to_attrs(self, style: Style) -> str:
        attrs = [
            f'fill="{style.fill}"',
            f'stroke="{style.stroke}"',
            f'stroke-width="{style.stroke_width}"',
            f'opacity="{style.opacity}"',
            f'font-family="{style.font_family}"',
            f'font-size="{style.font_size}px"',
            f'font-weight="{style.font_weight}"',
            f'text-anchor="{style.text_anchor}"',
        ]
        if style.stroke_dasharray:
            attrs.append(f'stroke-dasharray="{style.stroke_dasharray}"')
        if style.filter:
            attrs.append(f'filter="url(#{style.filter})"')
        return " ".join(attrs)

    def render(self) -> str:
        defs_block = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}"
     xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <rect width="100%" height="100%" fill="{self.bg_color}" />
    {defs_block}
    {chr(10).join(self.elements)}
</svg>'''

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.render())


# =============================================================================
# PNG Rasterization
# =============================================================================


def svg_string_to_png_bytes(svg: str) -> bytes:
    """Convert an SVG string to PNG bytes."""
    out = cairosvg.svg2png(bytestring=svg.encode("utf-8"))
    if out is None:
        raise ValueError("cairosvg.svg2png returned None")
    return out


def save_png(svg: str, png_path: str | Path) -> bytes:
    """Save SVG-rendered content to PNG and return the bytes."""
    out_path = Path(png_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = svg_string_to_png_bytes(svg)
    out_path.write_bytes(png_bytes)
    update_manifest(out_path.parent, [out_path.name])
    return png_bytes


# =============================================================================
# View Exports
# =============================================================================

if TYPE_CHECKING:
    from .architecture import ArchitectureView
    from .impact import ImpactView
    from .task import TaskView


def __getattr__(name: str) -> Any:
    if name == "ArchitectureView":
        from .architecture import ArchitectureView as _ArchitectureView

        return _ArchitectureView
    if name == "ImpactView":
        from .impact import ImpactView as _ImpactView

        return _ImpactView
    if name == "TaskView":
        from .task import TaskView as _TaskView

        return _TaskView
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ArchitectureView",
    "ImpactView",
    "TaskView",
    "COLORS",
    "Style",
    "SVGCanvas",
    "save_png",
    "svg_string_to_png_bytes",
]
