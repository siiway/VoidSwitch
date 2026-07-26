# Using with Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) uses the Anthropic API,
so it can point directly at VoidSwitch.

## Configuration

Set the Base URL and your [Void-Token](/en/guide/api-keys) as the auth token:

```bash
export ANTHROPIC_BASE_URL=https://voidswitch.siiway.org
export ANTHROPIC_AUTH_TOKEN=vs-your-token
```

Then run Claude Code as usual. Requests flow through VoidSwitch, which routes them to a provider
that serves the requested Claude model and handles key/proxy failover.

## Choosing a model

Use the model IDs that VoidSwitch publishes (see [Models](/en/guide/models) or call `/v1/models`).
If your platform maps Claude models to other upstreams, the mapping is transparent — just use the published ID.

## Notes

- Streaming, tool calls, and token usage reporting are all supported end to end.
- If you prefer **OpenCode**, install the dedicated plugin — it adds the full Claude Code
  request capabilities at the wire level (effort levels, fast mode, thinking). See [OpenCode plugin](/en/guide/opencode).
