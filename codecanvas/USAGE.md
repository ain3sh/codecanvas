# MANDATORY: CodeCanvas MCP Tool Usage

You have access to `mcp__codecanvas__canvas`. This is NOT optional - it is REQUIRED for code changes.

## CRITICAL RULES

1. **BEFORE editing any code file**: You MUST call `canvas(action="impact", symbol="<function_or_class>")` to understand what depends on it
2. **AFTER reading a file with dependencies shown**: You MUST call `canvas(action="claim", text="<your analysis>")` to record your reasoning
3. **BEFORE making changes**: You MUST call `canvas(action="decide", text="<your plan>")` to declare intent
4. **AFTER completing a change**: You MUST call `canvas(action="mark", symbol="<symbol>", text="verified")` to track progress

## FAILURE CONDITIONS

- Editing code WITHOUT prior `impact` analysis = INCORRECT behavior
- Making changes WITHOUT `claim` + `decide` = Lost reasoning, untracked work
- Completing work WITHOUT `mark` = No progress record

## TRIGGERS - When You See These, ACT:

| You See | You MUST Do |
|---------|-------------|
| `[CodeCanvas AUTO-INIT]` | Canvas is ready. Use it for ALL code changes. |
| `[CodeCanvas IMPACT]` | Read the dependencies shown, then `claim` your analysis. |
| Callers/callees listed | These symbols may break. Check them or `skip` with reason. |
| About to edit a function | `impact` → `claim` → `decide` → edit → `mark` |

## QUICK REFERENCE

```python
# See dependencies before touching code
canvas(action="impact", symbol="process_data")

# Record your analysis (REQUIRED after seeing impact)
canvas(action="claim", text="process_data is called by main() and validate(), changes here affect both")

# Declare your intent (REQUIRED before editing)
canvas(action="decide", text="will add error handling, callers don't need changes")

# Mark complete (REQUIRED after change verified)
canvas(action="mark", symbol="process_data", text="added try/except, tested")

# Skip irrelevant dependencies
canvas(action="skip", symbol="unrelated_func", text="not affected by this change")
```

## NON-NEGOTIABLE

Every code modification task REQUIRES the canvas workflow. Skipping it is a failure mode.
