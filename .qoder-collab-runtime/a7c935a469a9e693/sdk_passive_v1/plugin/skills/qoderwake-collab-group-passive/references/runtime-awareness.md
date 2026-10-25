# Runtime fields

For authority between context sources, see **Conversation Run precedence** in
the Run system prompt.

## Coordinates

| ID | Object |
| --- | --- |
| `csgrp_*` | Group container and configuration owner |
| `conv_*` | Canonical message stream, including a Discussion's own stream |
| `cpart_*` | Participant in that stream |
| `crun_*` | One execution for a participant |
| `cmsg_*` | Canonical Message |

A `group_conversation` is a first-level Group stream. A `group_thread` is a
Discussion rooted at a Message; parent coordinates and root content are
reference data. An Executor Session can be resumed across Runs and is not a
Conversation or Group.

These MCP tools cannot create or enter another Group message stream. The
human-facing entry is the localized Conversation Task control; `session create`
creates an executor task, not that stream. A standalone Thread is separate from
a Group; a Section is a sidebar category with no Messages or Runs.

## Skill discovery

The collab package ID identifies the product resource, not necessarily a callable
Skill tool name. Use the exact name exposed in this execution's available Skill
catalog; it may include a namespace. A plugin manifest name or a name from an
earlier Run does not establish that invocation name.

On a Skill-not-found result, check the returned available names before retrying.
If file access is needed, `QODERWAKE_COLLAB_SKILL_PATH` points to the mounted
`SKILL.md`; resolve its links from that directory. A lookup-name mismatch alone
does not establish that the package needs installation.

## Environment

| Variable | Meaning |
| --- | --- |
| `QODERWAKE_CONVERSATION_ID` | Current canonical stream ID |
| `QODERWAKE_CONVERSATION_KIND` | `group_conversation` or `group_thread` |
| `QODERWAKE_PARTICIPANT_ID` | This Run's participant |
| `QODERWAKE_RUN_ID` | This execution's Run ID |
| `QODERWAKE_RUN_TOKEN` | Expiring Run credential; bound by the host, never include it in tool arguments |
| `QODERWAKE_COLLAB_SKILL_ID` | Mounted collab package ID; see Skill discovery above |
| `QODERWAKE_COLLAB_SKILL_PATH` | Mounted collab file entrypoint; see Skill discovery above |
| `QODERWAKE_COLLAB_RELEASE_VERSION` / `QODERWAKE_COLLAB_RELEASE_DIGEST` | Locally materialized collab release |
| `QODERWAKE_CLI` | Matching CLI executable path, available for diagnostics |
| `QODER_WORKSPACE` | Private Waker working directory |

The Run supplies its command prefix explicitly. Credential values are not
runtime context to display. Skill paths and materialization details can differ
between release versions without changing the Conversation coordinates.

## Delivered Run input

The current Run input includes Group and Conversation coordinates, this
participant's identity, member roles and descriptions, delivered Message IDs,
sender, content, intent, action audience and visibility. It also identifies
materialized attachment paths, work directories, pinned group resources and the
current Goal when applicable. New messages arrive as interjections with current
Goal snapshots. History lookup boundaries are defined in the
[protocol](../protocol.md#delivered-work).
A missing routing projection is not evidence that a Message is public.

## Scenario pins

The Run binding's `system_skills` entries identify SOP releases with `skill_id`,
`version`, `digest`, `priority`, and optional `parameter_values`. Its `user_skills`
entries identify Group Skills with `skill_id`, optional `version` / `digest`,
`enabled`, and optional `parameter_values`. The daemon materializes these into
separate system and user skill plugins. These are snapshots for the current
Run, not live subscriptions to subsequent configuration changes.

Publishing and changing bindings is described in [SOP and Skills](sop-and-skills.md).
