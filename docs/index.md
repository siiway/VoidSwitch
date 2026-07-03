---
layout: home

hero:
  name: VoidSwitch
  text: LLM API gateway
  tagline: One endpoint for every model — resilient key & proxy failover, OpenAI ⇄ Anthropic translation, and a self-service dashboard.
  actions:
    - theme: brand
      text: Get started
      link: /guide/introduction
    - theme: alt
      text: Using the API
      link: /guide/using-the-api
    - theme: alt
      text: Administration
      link: /admin/overview

features:
  - title: One endpoint, many providers
    details: Point an OpenAI SDK, an Anthropic SDK, or Claude Code at a single URL. VoidSwitch picks the provider, rotates keys, and fails over proxies for you.
  - title: Self-service keys
    details: Mint your own long-lived vs-… tokens, set per-token model allow-lists and rate limits, and rotate or revoke them any time.
  - title: OpenAI ⇄ Anthropic
    details: Send OpenAI /v1/chat/completions, OpenAI /v1/responses, or Anthropic /v1/messages — requests, responses, and streaming are translated on the fly.
  - title: OpenCode ready
    details: A one-line installer adds VoidSwitch as a first-class OpenCode provider with the full Claude Code request surface.
---

## What is this?

VoidSwitch is a **multi-provider LLM API reverse proxy**. It accepts OpenAI Chat
Completions, OpenAI Responses, and Anthropic-style traffic on one endpoint,
translates between them, and forwards requests to whichever upstream provider can
serve the model — handling key rotation, proxy failover, and per-user quotas
along the way.

This documentation site is **private**: only users who can sign in to the
VoidSwitch dashboard can read it.

- New here? Start with the [Introduction](/guide/introduction).
- Want to make requests? See [Your API key](/guide/api-keys) and
  [Calling the API](/guide/using-the-api).
- Running the platform? Head to [Administration](/admin/overview).
