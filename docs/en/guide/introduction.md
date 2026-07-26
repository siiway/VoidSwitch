# Introduction

VoidSwitch is a **multi-provider LLM API gateway**. Instead of wiring each
application directly to a provider-specific API and managing its keys, point your
clients at a single VoidSwitch endpoint and let it:

- **route** each request to a provider that serves the requested model;
- **rotate keys** when one is rate-limited, out of balance, or invalid;
- **fail over proxies** when a network path goes down;
- **convert in real time** between the OpenAI Chat Completions, OpenAI Responses, and Anthropic APIs;
- **enforce quotas** per user and per token.

```
       OpenAI clients ─┐                          ┌─ OpenAI-style upstreams
                       ├─►  VoidSwitch Gateway  ──┤   (OpenAI, DeepSeek, Groq, …)
   Claude Code / SDK ──┘   convert · failover      └─ Anthropic-style upstreams
                             key + proxy rotation         (Anthropic / Claude)
```

## Core concepts

| Term | Meaning |
| ---- | ---- |
| **Void-Token** (`vs-…`) | Your personal client credential. Sent as the API key when calling the gateway. Created and managed on the **My Tokens** page. |
| **Provider** | An upstream LLM platform (OpenAI, Anthropic, DeepSeek, etc.), configured by staff, with its own API keys and model list. |
| **Model** | A model ID served by one or more providers. Browse it on the **Models** page. |
| **Role group** | A named group that grants access to specific models. Membership is assigned automatically at sign-in based on your team role. |
| **Proxy** | An optional HTTP/SOCKS egress route the gateway can use to reach providers. |

## Who can do what

VoidSwitch has three permission tiers. The **Using the Gateway** section of this
guide applies to everyone; the **Administration** section applies to staff.

| Tier | Who | Can |
| ---- | --- | --- |
| **Member** | Any signed-in user | Create their own Void-Tokens, call the API for allowed models, browse models, use chat, view their own logs/usage, read announcements. |
| **Staff** | owner + co-owner + admin | Everything members can do, plus managing providers, keys, proxies, models, role groups, users, settings, and publishing announcements. |
| **Owner** | owner + co-owner | Everything staff can do, plus sensitive actions: disabling users, deleting providers, revealing secrets, editing settings. |

See [Overview & Roles](/en/admin/overview) for the full breakdown.

## Endpoints at a glance

| Path | Purpose |
| ---- | ---- |
| `/v1/chat/completions` | OpenAI-style chat completions |
| `/v1/responses` | OpenAI Responses API |
| `/v1/messages` | Anthropic-style messages |
| `/v1/models` | List the models you can call |
| `/swagger` | Interactive API reference (Swagger UI) |

Next: [Sign in](/en/guide/sign-in).
