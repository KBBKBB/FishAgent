# Conversation Goal

Use `group_goal(action=get)` for current `goal.id`, `goal.generation`, `goal.revision`.
Use `action=create` with content and `turn_limit` (1..96) when assigned overall
maintenance. Estimate actual public sends following
[the protocol](../protocol.md#conversation-goal); direct replies need no separate
receipt. `turn_limit` must stay within 1..96. Private messages do not consume it.

All mutations need stable `request_id`. Actions `update`, `complete`, `pause`,
`reopen` require exact `expected={id,generation,revision}` from the current Goal.
`complete` also needs `result_message_id` pointing to a canonical public result
visible to the requesting human. `pause` needs reason (`user_stop`, `awaiting_user`,
`turn_limit`, `no_progress`, `execution_error`, `leader_unavailable`). Preserve
human authorization when reopening; do not increase budget merely to evade limits.

`CONVERSATION_GOAL_STALE`: reread and reconsider; retry at most once with a valid
fresh version. A paused `turn_limit` Goal stops automatic recovery, not member sends
or handoffs. Choose `wake_participant_ids` and `private_to` from task routing and privacy,
not from the budget. `CONVERSATION_GOAL_PAUSED` on a send means an explicit user stop;
do not resume without a fresh human request. Never claim an unsuccessful change applied.

SDK delivery can use `group_message_send(complete_goal=expected, end_turn=true)`:
publication happens before Goal completion. If completion fails, recover using the
returned published Message ID and finish with `group_turn_finish`; do not resend.
Compatibility executors publish with `end_turn=false`, update the Goal using
`group_goal`, then finish their Inbox contract; they do not expose `group_turn_finish`.
