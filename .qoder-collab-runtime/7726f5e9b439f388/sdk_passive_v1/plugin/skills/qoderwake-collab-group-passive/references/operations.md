# Structured Group submission

Use the available SDK `group_message_send` tool for replies, progress, and
handoffs. The daemon binds Conversation, sender, and Run authority; do not pass
these identities. The tool returns canonical `message` fields.

| Argument | Meaning |
| --- | --- |
| `text` | Exact body with actual newlines |
| `wake_participant_ids` | Current roster IDs of immediate actors; `[]` means no wake |
| `private_to` | Authorized private readers; omitted or `[]` means public |
| `attachment_ids` | Optional existing attachment IDs; pending Run outputs are still automatically linked |
| `intent` | Optional `chat`, `ask`, `request_action`, or `notify`; does not replace wake routing |
| `end_turn` | Required: `false` for progress/earlier sends, `true` for the last reply or handoff |
| `complete_goal` | Optional exact `{id, generation, revision}`; requires `end_turn: true` |
| `request_id` | Stable key for this exact submission; reuse unchanged arguments on retry |

Example: one public contribution handing a next step to its actual owner:

```json
{
  "text": "<your contribution and actionable next step>",
  "wake_participant_ids": ["<next owner's current participant ID>"],
  "end_turn": true,
  "request_id": "<stable submission key>"
}
```

A non-waking reply uses `wake_participant_ids: []`. A private handoff also sets
`private_to` to authorized readers including every actor. Routing and privacy
requirements remain in [the protocol](../protocol.md#routing).

For overall completion, provide `complete_goal` from the current Goal version.
Publication occurs first; Goal completion reuses existing canonical-result and
version checks. A Goal failure returns `isError` and `published_message_id`:
the message already exists, but the turn has not terminated. Retry this exact
submission or repair the Goal using its current version and that Message ID;
do not send the result again. A stale version requires reconsideration, not blind
retry. After repairing state via existing `group_goal` tools, use `group_turn_finish`
with `{"message_id":"<the published Message ID>"}` to end without another message.
It accepts only canonical messages successfully published by this active Run,
and does not itself complete the Goal.
A successful `end_turn` returns `groupFinalReceipt`, which the runtime
uses to stop generation; it is not an external task/IM delivery receipt.

If a required MCP tool is unavailable, report the capability failure.
External final results use `atwaker_result_submit`.
