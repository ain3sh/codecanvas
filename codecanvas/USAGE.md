# CodeCanvas

**Auto-init and auto-impact happen via hooks. You'll see `[CodeCanvas]` messages - READ THEM.**

## You MUST Do These

```python
# After analyzing something:
canvas(action="claim", text="bug is in X because Y")

# Before changing code:
canvas(action="decide", text="will fix by doing Z")

# After verifying change:
canvas(action="mark", symbol="function_name", text="done")
```

Without claim/decide/mark, your reasoning vanishes and progress isn't tracked.

## Optional

```python
# Manual impact (auto runs on Read, use this for other symbols):
canvas(action="impact", symbol="other_func", depth=2)

# Skip irrelevant symbols from impact results:
canvas(action="skip", symbol="unrelated", text="not affected")
```

## Pattern

Read file → see auto-impact → `claim` → `decide` → edit → `mark`
