## The “ideology clash” is real — and it’s mostly a host/transport constraint
Today, CodeCanvas *hooks* can only inject **text** via `hookSpecificOutput.additionalContext` (see `.factory/specs/...hooks...md` + what shows up in `claude-code.txt` as `hook_response`). The only first-class “images inline to the model” path in this repo is the **MCP tool** (`canvas`), which returns `ImageContent` (base64 PNG) from the long-lived MCP process.

So if your goal is literally: **“after Edit/Write, the model sees an impact PNG without explicitly calling the tool”**, then:
- **Option C alone won’t achieve that**, because the hook channel can’t deliver `ImageContent`.
- And importantly: **the current hook implementation also doesn’t deliver images inline**; it only writes PNGs to disk + injects text.

That said, Option C can still preserve the *spirit* of hooks (automatic impact awareness) if we define “injection” as:
- Auto-run impact analysis at the right times,
- Write artifacts (PNGs + state) deterministically,
- Inject a short, high-signal summary into context.

---

## Option C (fleshed out) that aligns with hook goals: “Persistent compute, hook-triggered UX”
Instead of trying to have hooks *be* the transport for images, Option C should make the **expensive/fragile part (call graph build)** happen in a **long-lived process**, while hooks continue to:
- decide *when* to run impact,
- and inject *what* the model needs (text summary + stable pointers to the freshly generated artifacts).

### C1′ (recommended): Persistent **call-graph builder** + local artifacts, not a persistent “rendering UI”
**Key idea:** move *call-graph generation* out of short-lived hook processes, but keep *impact rendering* + artifact writing where it already is.

1) A long-lived process (MCP server or a separate daemon) builds call edges and persists them to disk:
- Output file: `${CANVAS_ARTIFACT_DIR}/call_edges.json` (or similar)
- Includes: generation id, root, timestamp, and a list of edges in a stable representation.

2) Hook processes do `impact` like they do today, but **preload/merge** the persisted edges into the in-memory graph before computing callers/callees.
- This keeps the hook UX intact: the impact PNG is still produced at the time of edit/write.
- It avoids relying on a daemon thread that dies when the hook process exits.

3) The hook’s additionalContext remains the “automation channel”:
- It can say “impact image updated at …/impact_*.png; call_graph status=completed edges_total=N”
- If the host/UI supports showing those images automatically, great; if not, the model still gets the numeric blast-radius summary.

### Why this resolves the clash
- Hooks still run “at crucial points” without the agent explicitly calling the tool.
- The call graph actually completes (because it’s computed in a persistent place and persisted durably).
- We don’t need hooks to transport image bytes.

---

## If you truly want *inline PNGs without tool calls* (strong form)
That requires a host-side feature beyond CodeCanvas itself:

### C2′: TerminalBench/host transcript injection (if you control the host)
- Hooks/daemon produce PNGs on disk.
- The **host** (TerminalBench harness or Claude Code host) watches for new `impact_*.png` and injects them into the model context as an image attachment.
- In MCP terms, that’s like the host fabricating a tool-result message containing `ImageContent`.

This is doable in TerminalBench (since it already captures trajectories), but it’s not something CodeCanvas can do purely from within the hook script.

---

## Decision points
1) Which definition of “injection” do you want?
- **A (practical, in-repo):** hooks inject high-signal text + write PNG artifacts deterministically (no inline images).
- **B (strong):** inline images appear in the model context automatically (requires host integration).

2) Where should the persistent process live?
- **C1:** inside the MCP server (add a second IPC transport so hooks can request “build call graph now” and/or read status)
- **C2:** standalone daemon spawned by SessionStart hook

---

## Proposed next step (if you approve)
I’ll draft an implementation plan for **C1′** (persistent call-graph cache + hook-side merge), because it directly targets the call-graph=0 issue while keeping the hook UX story consistent.
