# Group MCP messaging

Routing requirements are in [the protocol](../protocol.md#routing).
Use `group_message_send` with exact `text`, current participant IDs in
`wake_participant_ids`, optional authorized `private_to`, optional `attachment_ids`,
`intent`, explicit `end_turn` and a stable `request_id`. Empty actors means no wake;
omitted readers means public, even with a single actor. Visible @Name is not routing.
For compatibility executors, `end_turn` does not replace Inbox completion.

### Multiline text

Use actual newline characters in the decoded text field. JSON serializes newlines
as escapes; distinguish the decoded text from its JSON representation. If requested
content intentionally contains literal `\n`, preserve it; do not send double escapes
as formatting line breaks.

## Response fields

The result contains canonical `message.content.text`, `message.audience`,
`message.private_to`, sender, ID and sequence. Verify returned body and routing.
Retry the same request unchanged after uncertain submission; changed parameters
need a new key after resolving the previous outcome. Never invent a success receipt.
`group_runs(action=list/cancel)` is scoped to this task. Cancellation is not delivery.
`group_task(title=..., request_id=...)` changes the task title, never the Group name.

## Optional context lookup

Normally use host-delivered messages. Only when extra context is needed, call
`group_message_list` with optional `limit` (default 30, maximum 100). It returns
recent messages for this task only, with necessary sender/body/routing/time and
attachment references. Private visibility is enforced for your participant.
Use returned `next_cursor` as `cursor` only to request older context. An empty page
with a cursor can follow hidden messages. Querying is optional, does not acknowledge
Inbox delivery, and is not a precondition for replying or sending; do not poll.
