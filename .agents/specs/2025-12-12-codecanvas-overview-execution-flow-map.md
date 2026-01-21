## Core Insight

The value isn't showing boxes - it's showing **how execution flows through the codebase**.

A developer asks:
- "Where do I start?" → Entry points
- "What's central?" → Hub modules (high in-degree)
- "What's the path?" → Call/import chains

## Visual Design: Circuit Flow Diagram

```
╔══════════════════════════════════════════════════════════════╗
║                     CODE FLOW MAP                            ║
║                                                              ║
║  ENTRY ─────────────────────────────────────────────────     ║
║                                                              ║
║     ┌─────────────┐              ┌─────────────┐            ║
║     │◉ canvas.py  │              │◉ mcp_server │            ║
║     │  main API   │              │  MCP tool   │            ║
║     └──────┬──────┘              └──────┬──────┘            ║
║            │                            │                    ║
║            └────────────┬───────────────┘                    ║
║                         ▼                                    ║
║  HUB ───────────────────────────────────────────────────     ║
║                                                              ║
║            ┌─────────────────────┐                          ║
║            │★ parser             │  ← imported by 4         ║
║            │  tree-sitter + regex│                          ║
║            └──────────┬──────────┘                          ║
║                       │                                      ║
║         ┌─────────────┼─────────────┐                       ║
║         ▼             ▼             ▼                       ║
║    ┌─────────┐  ┌──────────┐  ┌─────────┐                  ║
║    │ models  │  │ analysis │  │ renderer│                  ║
║    │ Graph   │  │ Slice    │  │ D3/PNG  │                  ║
║    └─────────┘  └──────────┘  └─────────┘                  ║
║                                                              ║
║  FOUNDATION ────────────────────────────────────────────     ║
║                                                              ║
║            ┌─────────────────────┐                          ║
║            │★ models             │  ← imported by 6         ║
║            │  Graph, Node, Edge  │                          ║
║            └─────────────────────┘                          ║
║                                                              ║
║  ───────────────────────────────────────────────────────    ║
║  ◉ Entry (0 callers)  ★ Hub (3+ dependents)  → imports     ║
╚══════════════════════════════════════════════════════════════╝
```

## What This Shows (That Grid Doesn't)

| Feature | Grid View | Flow Map |
|---------|-----------|----------|
| Entry points | No | Yes (◉ marker, top layer) |
| Central modules | No | Yes (★ marker, "imported by N") |
| Dependency direction | No | Yes (arrows flow down) |
| Architecture layers | No | Yes (ENTRY → HUB → FOUNDATION) |
| Where to start | No | Yes (top = entry points) |

## Backend: Compute Flow Metrics

```python
# In analysis.py
def compute_flow_metrics(self) -> Dict:
    """Compute centrality and layering for flow visualization."""
    modules = [n for n in self.graph.nodes if n.kind == NodeKind.MODULE]
    module_ids = {m.id for m in modules}
    
    # Compute in-degree (how many project modules import this)
    in_degree = defaultdict(int)
    out_degree = defaultdict(int)
    for e in self.graph.edges:
        if e.type == EdgeType.IMPORT:
            if e.from_id in module_ids and e.to_id in module_ids:
                in_degree[e.to_id] += 1
                out_degree[e.from_id] += 1
    
    # Classify modules
    entry_points = []  # in_degree = 0
    hubs = []          # in_degree >= 3
    foundation = []    # in_degree > 0, out_degree = 0
    core = []          # everything else
    
    for m in modules:
        ind = in_degree[m.id]
        outd = out_degree[m.id]
        
        if ind == 0:
            entry_points.append(m)
        elif ind >= 3:
            hubs.append((m, ind))
        elif outd == 0:
            foundation.append(m)
        else:
            core.append(m)
    
    # Compute layers via topological sort
    layers = self._compute_layers(modules, in_degree)
    
    return {
        'entry_points': entry_points,
        'hubs': hubs,
        'foundation': foundation,
        'core': core,
        'layers': layers,
        'in_degree': dict(in_degree),
    }
```

## Frontend: Flow Layout

```javascript
function renderOverview(data) {
    const { nodes, edges, flowMetrics } = data;
    const { entry_points, hubs, layers, in_degree } = flowMetrics;
    
    // Group modules by layer
    const layerGroups = groupByLayer(nodes, layers);
    
    // Canvas sizing
    const layerHeight = 100;
    const moduleWidth = 150;
    const height = 80 + Object.keys(layerGroups).length * layerHeight;
    
    // Layout each layer
    const positions = {};
    let y = 60;
    
    for (const [layer, mods] of Object.entries(layerGroups)) {
        // Center modules horizontally
        const totalWidth = mods.length * moduleWidth + (mods.length - 1) * 30;
        let x = (width - totalWidth) / 2;
        
        mods.forEach(m => {
            positions[m.id] = { x, y };
            x += moduleWidth + 30;
        });
        
        y += layerHeight;
    }
    
    // Draw layer labels (ENTRY, HUB, FOUNDATION)
    drawLayerLabels(svg, layerGroups);
    
    // Draw edges with arrows (import relationships)
    drawFlowEdges(svg, edges, positions);
    
    // Draw modules with role badges
    drawModules(svg, nodes, positions, {
        entryPoints: new Set(entry_points.map(e => e.id)),
        hubs: new Set(hubs.map(h => h[0].id)),
        inDegree: in_degree
    });
}
```

## Visual Style

**Typography:**
- Module names: Bold, 13px
- Descriptions: Muted, 10px
- Layer labels: Caps, muted, small

**Colors:**
- Entry points (◉): Cyan border (#00ffff)
- Hubs (★): Amber glow (#fbbf24)
- Foundation: Solid border
- Edges: Blue-ish (#a8b1ff) with arrows

**Layout:**
- Vertical flow (top = entry, bottom = foundation)
- Centered modules per layer
- Minimize edge crossings

## Implementation Order

1. **analysis.py**: Add `compute_flow_metrics()`
2. **canvas.py**: Include flow_metrics in overview render data
3. **render.js**: Rewrite `renderOverview()` with:
   - Layer grouping
   - Flow edges with arrows
   - Role badges (◉ entry, ★ hub)
   - Layer labels
4. **Test**: Verify flow is visible and informative