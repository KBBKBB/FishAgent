---
name: qoderwake-collab-group-passive
description: "Use for Group Conversation message, file, Goal, runtime, and SOP work in an SDK Run; use loaded essentials and MCP schemas before reading missing details."
---

# Group Collab SDK reference index

The Run system prompt contains the [Group Collab protocol](protocol.md).
If the Run reports that injection failed, read that file as its fallback.

Links resolve from this Skill's directory. Read the relevant file directly;
no directory search or preload of all references is needed.

| Needed detail | Read |
| --- | --- |
| Structured reply/progress/handoff, end of turn, and result plus Goal completion | [Operations](references/operations.md) |
| MCP sends, optional context lookup, response fields, recipients, retries, Run controls | [Messaging](references/messaging.md) |
| Directory layout, attachment transfer, shared repositories | [Files](references/files.md) |
| Persisting group procedures or capabilities; publishing and binding SOPs | [SOP and Skills](references/sop-and-skills.md) |
| IDs, Skill invocation names and paths, environment variables, binding pins | [Runtime fields](references/runtime-awareness.md) |
| Goal creation, versioned updates, completion, pause, reopen, and turn budget tools | [Conversation Goal](references/goal.md) |
| Concrete tools for confirmations, private or parallel handoffs | [Routing examples](references/examples.md) |

Use the available Group MCP tools. Identity and targets are host-bound.
Angle-bracket values are placeholders; read only missing details in references.

When creating, publishing or binding an SOP, use `group_sop`; consult
**SOP and Skills** only for missing authoring details. Do not treat a
chat response containing procedure text as a created SOP.
