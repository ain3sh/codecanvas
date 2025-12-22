"""
CodeCanvas Visualizer - Python-native SVG engine.

Provides high-contrast, multimodal-optimized SVG generation primitives.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cairosvg

# Color Palette (High Contrast / Neon on Black)
COLORS = {
    "bg": "#0e1116",
    "card": "#1b2130",
    "module_bg": "#141922",
    "outline": "#8a919a",
    "text": "#e6edf3",
    "muted": "#7d8590",
    # State Colors
    "pending": "#ef4444",  # Red
    "in_progress": "#fbbf24",  # Yellow/Amber
    "verified": "#22c55e",  # Green
    "skipped": "#9ca3af",  # Gray
    # Edge Colors
    "import": "#a8b1ff",  # Soft Blue
    "call": "#86efac",  # Soft Green
    "inherit": "#f472b6",  # Pink
    # Highlights
    "danger": "#ef4444",  # Red (Inward rays)
    "tool": "#0ea5e9",  # Blue (Outward rays)
    "focus": "#facc15",  # Yellow
    # Layer Bands
    "layer_0": "rgba(20, 25, 34, 0.5)",  # Deepest
    "layer_1": "rgba(27, 33, 48, 0.5)",
    "layer_2": "rgba(35, 43, 62, 0.5)",
}


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

    # New filters for shadows etc
    filter: Optional[str] = None


class SVGCanvas:
    """
    Lightweight SVG generator.
    """

    def __init__(self, width: int = 800, height: int = 600, dark_mode: bool = True):
        self.width = width
        self.height = height
        self.elements: List[str] = []
        self.defs: List[str] = []
        self.bg_color = COLORS["bg"] if dark_mode else "#ffffff"

        # Add default markers and filters
        self._add_markers()
        self._add_filters()

    def _add_markers(self):
        """Add standard arrow markers."""
        self.defs.append(
            """
        <marker id="arrow-call" viewBox="0 -5 10 10" refX="8" refY="0" 
                markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,-5L10,0L0,5" fill="{}" />
        </marker>
        """.format(COLORS["call"])
        )

        self.defs.append(
            """
        <marker id="arrow-import" viewBox="0 -5 10 10" refX="8" refY="0" 
                markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,-5L10,0L0,5" fill="{}" />
        </marker>
        """.format(COLORS["import"])
        )

    def _add_filters(self):
        """Add drop shadow filter."""
        self.defs.append("""
        <filter id="drop-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2"/>
            <feOffset dx="2" dy="2" result="offsetblur"/>
            <feComponentTransfer>
                <feFuncA type="linear" slope="0.3"/>
            </feComponentTransfer>
            <feMerge>
                <feMergeNode/>
                <feMergeNode in="SourceGraphic"/>
            </feMerge>
        </filter>
        """)

    def add_rect(self, x: float, y: float, w: float, h: float, rx: float = 0, style: Style | None = None):
        """Draw a rectangle."""
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" {attrs} />')

    def add_circle(self, cx: float, cy: float, r: float, style: Style | None = None):
        """Draw a circle."""
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {attrs} />')

    def add_text(self, x: float, y: float, text: str, style: Style | None = None):
        """Draw text."""
        s = style or Style()
        attrs = self._style_to_attrs(s)
        escaped_text = html.escape(str(text))
        self.elements.append(f'<text x="{x}" y="{y}" {attrs}>{escaped_text}</text>')

    def add_text_lines(
        self,
        x: float,
        y: float,
        lines: List[str],
        style: Style | None = None,
        line_height: Optional[float] = None,
    ):
        """Draw multiline text using tspans (SVG does not render \n in <text>)."""
        if not lines:
            return
        s = style or Style()
        attrs = self._style_to_attrs(s)
        lh = line_height if line_height is not None else (s.font_size * 1.25)
        tspans = []
        for i, line in enumerate(lines):
            dy = 0 if i == 0 else lh
            tspans.append(f'<tspan x="{x}" dy="{dy}">{html.escape(str(line))}</tspan>')
        inner = "".join(tspans)
        self.elements.append(f'<text x="{x}" y="{y}" {attrs}>{inner}</text>')

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
        safe_href = html.escape(str(href), quote=True)
        self.elements.append(
            f'<image x="{x}" y="{y}" width="{w}" height="{h}" href="{safe_href}" '
            f'opacity="{opacity}" preserveAspectRatio="{preserve_aspect_ratio}" />'
        )

    def add_path(self, d: str, style: Style | None = None, marker_end: str | None = None):
        """Draw a path."""
        attrs = self._style_to_attrs(style or Style())
        marker_attr = f'marker-end="url(#{marker_end})"' if marker_end else ""
        self.elements.append(f'<path d="{d}" {attrs} {marker_attr} />')

    def add_line(self, x1: float, y1: float, x2: float, y2: float, style: Style | None = None):
        """Draw a line."""
        attrs = self._style_to_attrs(style or Style())
        self.elements.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {attrs} />')

    def _style_to_attrs(self, style: Style) -> str:
        """Convert Style object to SVG attributes string."""
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
        """Generate full SVG string."""
        defs_block = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        content = "\n".join(self.elements)

        return f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}"
     xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <rect width="100%" height="100%" fill="{self.bg_color}" />
    {defs_block}
    {content}
</svg>"""

    def save(self, path: str):
        """Save SVG to file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.render())


# --- Rasterization helpers ---


def svg_string_to_png_bytes(svg: str) -> bytes:
    """Convert an SVG string to PNG bytes."""
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"))


def _get_extraction_dir() -> Path:
    """Get the extraction directory for Harbor.
    
    Uses CLAUDE_CONFIG_DIR if set (Harbor container), otherwise ~/.claude/.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "codecanvas"
    return Path.home() / ".claude" / "codecanvas"


def _save_for_harbor_extraction(png_bytes: bytes, filename: str) -> None:
    """Save a copy to CLAUDE_CONFIG_DIR/codecanvas/ for Harbor extraction.
    
    In Harbor containers, the project's .codecanvas/ directory is not extracted.
    But CLAUDE_CONFIG_DIR (which becomes agent/sessions/) IS extracted. Saving here
    ensures images are available for post-hoc analysis.
    
    Best-effort: silently fails if write doesn't work.
    """
    extraction_dir = _get_extraction_dir()
    try:
        extraction_dir.mkdir(parents=True, exist_ok=True)
        (extraction_dir / filename).write_bytes(png_bytes)
    except (OSError, PermissionError):
        pass


def save_png(svg: str, png_path: str | Path) -> bytes:
    """Save SVG-rendered content to a PNG on disk and return the bytes.
    
    Saves to two locations:
    1. Primary: The requested path (typically .codecanvas/ in project)
    2. Extraction: CLAUDE_CONFIG_DIR/codecanvas/ (for Harbor artifact extraction)
    """
    out_path = Path(png_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = svg_string_to_png_bytes(svg)
    out_path.write_bytes(png_bytes)
    
    _save_for_harbor_extraction(png_bytes, out_path.name)
    
    return png_bytes
