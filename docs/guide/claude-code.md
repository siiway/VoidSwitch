# Using with Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) speaks the
Anthropic API, so it points at VoidSwitch directly.

## Configure

Set the base URL and your [Void-Token](/guide/api-keys) as the auth token:

```bash
export ANTHROPIC_BASE_URL=https://your-voidswitch-host
export ANTHROPIC_AUTH_TOKEN=vs-your-token
```

Then run Claude Code as usual. Requests flow through VoidSwitch, which routes
them to a provider that serves the requested Claude model and handles key/proxy
failover.

## Choosing a model

Use a model id that VoidSwitch advertises (see [Models](/guide/models) or call
`/v1/models`). If your platform maps Claude models onto other upstreams, the
mapping is transparent — just use the advertised id.

## Notes

- Streaming, tool use, and token usage reporting are supported end-to-end.
- If you'd rather use **OpenCode**, install the dedicated plugin instead — it adds
  the full Claude Code request surface (effort levels, fast mode, thinking) at the
  wire level. See [OpenCode plugin](/guide/opencode).
