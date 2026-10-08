# ADR 0010: MCP side-effect tools use the shared registry with generic HITL approval

## Status

Accepted

## Context

Until now, the MCP adapter (#320, #324, #326) only exposed tools that read
data or write Kernector-owned drafts. Issue #199 adds
`software_delivery.create_xray_tests`, which creates Jira Test issues in an
external system. Each successful call creates new issues, and the tool has no
dedupe key, so running it twice creates duplicates.

In chat, high-impact tools already pause for a human decision (#214):
`ToolApprovalPolicy` lists the tool names that need approval, and the
LangGraph agent interrupts before `Tool.run`. MCP calls skip that agent. An
MCP client calls `tools/call` directly, and `McpToolRegistry.invoke_authorized`
runs the tool as soon as authorization and argument validation pass.

Exposing a side-effect tool over MCP therefore needs an approval step that:

- cannot be skipped by adding the tool to the MCP allowlist,
- never shows raw arguments, tokens, or external ids to the approver,
- fails closed when the client cannot ask the user, and
- leaves read-only tools unchanged.

## Decision

1. **One registry, one tool class.** Side-effect tools are contributed through
   the pack's existing `build_mcp_tools` entrypoint into the shared
   `McpToolRegistry`. They are the same `Tool` classes the chat path uses.
   There is no MCP-specific wrapper or subclass.
2. **Fixed order inside `invoke_authorized`.** The registry runs:
   authorization, then argument validation, then the approval policy, then the
   approval gate, then `Tool.run`. An unauthorized caller gets
   `tool_unavailable` before any approval work happens, so the MCP allowlist
   decides which tools exist, never whether approval is needed.
3. **The same policy as chat.** The registry receives a `ToolApprovalPolicy`
   (the default policy unless one is injected). A tool needs approval on MCP
   exactly when it needs approval in chat.
4. **A presentation-owned gate.** Composition stays free of the `mcp` SDK. The
   registry accepts an optional `approve` callable that receives a
   `PendingToolApproval` built by `project_pending_approval`. A tool may offer
   optional `approval_hints(arguments)` to supply a safe title, summary,
   destination label, and item count. The MCP presentation adapter supplies
   the gate through form elicitation, and only when the client declared the
   elicitation capability.
5. **Fail closed.** The tool does not run when any of these happen:
   - No gate is supplied, for example when the client has no elicitation
     support. The caller gets `approval_required`.
   - The gate raises, or the transport cannot send the request. The caller
     gets `approval_required`.
   - The user declines or cancels. The caller gets `approval_declined`.
6. **Read-only tools are untouched.** When the policy does not require
   approval, the registry neither builds an approval projection nor calls the
   gate.
7. **Approval is not idempotency.** Approval confirms one call. It does not
   dedupe. Tools with external side effects document their duplicate
   behaviour, for example the Xray tool in
   `packs/software_delivery/README.md`.

## Rejected alternatives

- **Keep side-effect tools off MCP.** This is simpler, but MCP users then have
  no way to run #199. Each later side-effect tool would also need its own
  exception.
- **An MCP-only wrapper tool that asks for confirmation.** This duplicates the
  tool contract, can drift from the chat tool, and puts approval logic inside
  a tool instead of the registry boundary.
- **Treat the MCP allowlist as approval.** The allowlist is set by an operator
  in configuration. No person approves an individual call, so it would remove
  human-in-the-loop for every allowlisted tool.
- **A `confirm: true` argument.** The model can fill in any argument by
  itself, so the flag proves nothing about user intent.
- **Run, then ask to undo.** External creates such as Jira issues cannot be
  reliably rolled back.

## Consequences

- MCP clients without elicitation support can list a side-effect tool but
  always get `approval_required` when they call it. Nothing is created.
- The registry has two new safe wire codes, `approval_required` and
  `approval_declined`. Neither carries arguments.
- New side-effect tools get MCP approval by being in `ToolApprovalPolicy`.
  They need no MCP-specific code.
- Tests in `test/composition/mcp/` pin the order, the fail-closed paths, and
  that read-only tools never reach the approval projection or the gate.

## Related docs

- Issues #199, #214, #320, #324, #326
- [ADR 0007 (composition pack adapters)](0007-composition-pack-adapters.md)
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
- [Software Delivery pack README](../../packs/software_delivery/README.md)
