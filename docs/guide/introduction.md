# Introduction

VoidSwitch is a **multi-provider LLM API gateway**. Instead of wiring each app to
a specific provider's API and juggling its keys, you point your client at one
VoidSwitch endpoint and let it:

- **route** each request to a provider that serves the requested model;
- **rotate keys** when one is rate-limited, out of balance, or invalid;
- **fail over proxies** when a network path breaks;
- **translate** between OpenAI-style and Anthropic-style APIs on the fly;
- **enforce quotas** per user and per token.

```
       OpenAI client ─┐                          ┌─ OpenAI-style upstreams
                      ├─►  VoidSwitch gateway  ──┤   (OpenAI, DeepSeek, Groq, …)
  Claude Code / SDK ──┘   translate · failover   └─ Anthropic-style upstreams
                            key + proxy rotation        (Anthropic / Claude)
```

## Key concepts

| Term | Meaning |
| ---- | ------- |
| **Void-Token** (`vs-…`) | Your personal client credential. Send it as the API key when calling the gateway. Create and manage these on the **My Tokens** page. |
| **Provider** | An upstream LLM platform (OpenAI, Anthropic, DeepSeek, …) configured by staff, with its own API keys and model list. |
| **Model** | A model id served by one or more providers. Browse them on the **Models** page. |
| **Role group** | A named group that grants access to specific models. Membership is assigned automatically from your team roles at sign-in. |
| **Proxy** | An optional HTTP/SOCKS egress route the gateway can use to reach a provider. |

## Who can do what

VoidSwitch has three permission tiers. Most of this guide's **Using the gateway**
section applies to everyone; the **Administration** section is for staff.

| Tier | Who | Can |
| ---- | --- | --- |
| **Member** | Any signed-in user | Mint their own Void-Tokens, call the API for models they're allowed, browse models, use chat, read their own logs/usage, read announcements. |
| **Staff** | owner + co-owner + admin | Everything a member can, plus manage providers, keys, proxies, models, role groups, users, settings, and publish announcements. |
| **Owner** | owner + co-owner | Everything staff can, plus sensitive actions: disabling users, deleting providers, revealing secrets, editing settings. |

See [Overview & roles](/admin/overview) for the full breakdown.

## Endpoints at a glance

| Path | Purpose |
| ---- | ------- |
| `/v1/chat/completions` | OpenAI-style chat completions |
| `/v1/messages` | Anthropic-style messages |
| `/v1/models` | List models you can call |
| `/docs/` | This documentation site (private) |
| `/swagger` | Interactive API reference (Swagger UI) |

Next: [Signing in](/guide/sign-in).
