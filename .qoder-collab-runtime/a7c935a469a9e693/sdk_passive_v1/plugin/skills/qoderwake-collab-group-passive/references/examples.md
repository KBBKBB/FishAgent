# Routing examples

These are `group_message_send` arguments. Replace placeholders with current roster IDs.

## Public handoff

```json
{"text":"<result; next owner please continue>","wake_participant_ids":["<owner-id>"],"end_turn":true,"request_id":"handoff-1"}
```

## Private handoff

```json
{"text":"<protected input and request>","wake_participant_ids":["<owner-id>"],"private_to":["<owner-id>","<authorized-reader-id>"],"end_turn":true,"request_id":"private-1"}
```

## Non-waking progress

```json
{"text":"<verified progress>","wake_participant_ids":[],"intent":"notify","end_turn":false,"request_id":"progress-1"}
```

These calls preserve the protocol's ownership, privacy and evidence requirements.
