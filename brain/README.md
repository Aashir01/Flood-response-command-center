# Brain (`stitch_brain`)

The orchestrator of Stitch. It is not an MCP server: it is an MCP client plus a FastAPI app. The
architecture write-up is `docs/brain-design.md`; the spec is `.kiro/specs/brain/`.

## MCP SDK notes (task 8)

- Client: `mcp.Client` (SDK 2.x) over stdio (`StdioServerParameters`) or streamable HTTP (a URL).
  The Brain keeps one long-lived session per organ, owned by a supervisor task, because the
  SDK's cancel scopes must be entered and exited in the same task.
- Cancellation: SDK 2.x sends `notifications/cancelled` when a request times out or the awaiting
  task is cancelled. A server may still finish the work; the Brain discards the result of a
  cancelled call and never stores it as evidence.
- Windows: stdio servers use pipes, which the `no_network` test guard allows. The real Ledger
  integration test (`tests/integration/test_real_ledger_stdio.py`, marker `integration`) runs
  with sockets blocked.
