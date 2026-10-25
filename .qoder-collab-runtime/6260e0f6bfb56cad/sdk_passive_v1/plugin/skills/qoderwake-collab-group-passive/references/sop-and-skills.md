# Persisting procedures and capabilities

## Choose the owner

| Requested scope | MCP operation |
| --- | --- |
| This Group's roles, handoffs, approvals, order or completion process | `group_sop` |
| Reusable knowledge, tools or methods shared by this Group | `group_skill(scope=group)` |
| One Waker's durable capability across Groups | `group_skill(scope=waker)` |
| This assignment only | Temporary runtime support is required; persistent tools have no expiry |

Classify the content, not just the term "skill". Coordination semantics belong
in SOP. Current Run binding supplies identity; resolving a Group does not grant
permission to modify it. External tasks may deny configuration management.

## SOP authoring and binding

Use `group_sop(action=catalog)` for compact release metadata. To read one template,
provide `skill_id`, `version` and `include_template=true`. Author a template:

```json
{"format":"qoder-sop-template/v1","description":"<purpose>","body":"<procedure>","parameters":[],"scripts":[]}
```

Parameter keys, types (`text`, `number`, `time`, `waker`), required/default values
and `${{key}}` placeholders follow the existing SOP template contract. Script paths
are relative safe paths. Use `action=validate` with `skill_id`, `template` and
`parameter_values` to check rendering. `action=publish` also requires immutable
`version` and a stable `request_id`; publication returns catalog profile/release IDs.
Retry identical parameters with the same `request_id`; changed parameters require
a new `request_id`. A published `skill_id`/`version` is immutable: changed content
is published under a fresh version of the same SOP by default on a confirmed
version conflict. Use the returned `publication.version` and `publishedReleaseId`
for binding. `version_conflict=error` requires the exact requested version. Never
rename the SOP just to avoid a collision; a new key cannot overwrite a release.
Read `action=bindings`, then `action=bind` with `expected_revision` from the current
Group and the complete ordered `bindings` array (`profileId`, `releaseId`, `priority`,
optional `parameterValues`), plus a stable `request_id`. Preserve unchanged entries,
versions, ordering and parameter values. On conflict, reread and reconsider.
Verify final bindings. Publication alone is inactive; a draft or unbound release
must not be described as active. Honor the human's draft/create/bind authorization.

## Skill management

`group_skill` supports `create`, `patch`, `edit`, `write_file`, `remove_file`.
Choose `scope`, then use `skill_name`/`skill_id`, content or relative resource path,
change summary and stable `request_id`. `dry_run=true` previews. Preserve
`base_version_id`/`expected_base_hash` when editing existing versions. Only
`status=applied` means changed; rejected/conflicting results need resolution.
Safety scanning and post-apply synchronization remain active.

## Already loaded knowledge

The system prompt provides pinned source/version/path and selected execution rules.
Do not reload rules already present. Read original SKILL.md/scripts/references only
for missing details. To define key rules, authors may provide `prompt.md` or a
`## Runtime essentials` section; arbitrary resources are not recursively injected.
