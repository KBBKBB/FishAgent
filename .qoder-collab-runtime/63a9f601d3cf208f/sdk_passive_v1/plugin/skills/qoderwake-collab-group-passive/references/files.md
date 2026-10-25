# File locations and transfer

For visibility and delivery requirements, see the Group Collab protocol's
**Privacy** and **Delivery** sections.

## Runtime layout

```text
<conversation-workdir>/
  workers/<waker-id>/   default private cwd
  shared/              shared writable output directory
<managed-default-conversation-dir>/attachments/<waker-id>/
                       private materialized attachment input cache
```

A member workspace override can replace the default cwd. `QODER_WORKSPACE`
identifies that private workspace; it does not relocate the shared directories.
The attachment cache stays under the managed default Conversation directory,
even when a Conversation or member workspace is overridden. The executor receives
the shared directory and only its own attachment cache as additional directories;
only the shared directory is an artifact output root. Use the absolute paths
provided by this Run, not an inferred attachment parent or another member's cache.
A path under another member's private cwd is not an exchanged file location.

For shared code, use one repository clone under `shared/` and a separate git
worktree under each participating Waker's private workspace. Worktree paths
remain private; exchange committed changes through the shared repository.
Moving an existing file changes paths held by others, so coordinate relocation
with its owner before moving it.

## Attachment MCP

Use existing local paths first. For another delivered Message attachment, call
`group_attachment_download(message_id=..., attachment_id=...)`; the host validates
canonical visibility, file size and hash and returns this Waker's local cache path.
Use `conversation_attachment.upload` to upload permitted output files, then pass
returned attachment IDs to `group_message_send`. Upload alone is not publication.
For external final delivery use `atwaker_result_submit(files=[<absolute path>], ...)`.
Private files must not be made public through attachments.

The actual cwd, shared output directory and attachment cache remain unchanged.
Do not infer another member's input directory; attachment IDs are not local paths.
