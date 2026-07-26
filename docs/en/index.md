---
layout: home

hero:
  name: VoidSwitch
  text: LLM API Gateway
  tagline: One endpoint for every model — resilient key and proxy failover, OpenAI ⇄ Anthropic conversion, and a self-service dashboard.
  actions:
    - theme: brand
      text: Quick Start
      link: /en/guide/introduction
    - theme: alt
      text: Using the API
      link: /en/guide/using-the-api
    - theme: alt
      text: Administration
      link: /en/admin/overview

features:
  - title: One endpoint, many providers
    details: Point the OpenAI SDK, the Anthropic SDK, or Claude Code at a single URL. VoidSwitch picks the provider, rotates keys, and fails over proxies for you.
  - title: Self-service keys
    details: Create your own long-lived vs-… tokens, set a per-token model allowlist and rate limits, and rotate or revoke them at any time.
  - title: OpenAI ⇄ Anthropic
    details: Send OpenAI /v1/chat/completions, OpenAI /v1/responses, or Anthropic /v1/messages — requests, responses, and streaming are converted on the fly.
  - title: OpenCode ready
    details: A one-line install command adds VoidSwitch as a first-class provider for OpenCode, with full Claude Code request support.
---

## What is this?

VoidSwitch is a **multi-provider LLM API reverse proxy**. It accepts OpenAI Chat
Completions, OpenAI Responses, and Anthropic-format traffic on a single endpoint,
converts between them, and forwards requests to any upstream provider that can
serve the model — while handling key rotation, proxy failover, and per-user quotas.

This documentation is **public** and anyone can read it; it is available in both 中文 and English, switchable with the language menu in the top-right corner of the page.

- New here? Start with the [Introduction](/en/guide/introduction).
- Want to send requests? See [Your API Keys](/en/guide/api-keys) and [Using the API](/en/guide/using-the-api).
- Running the platform? Head to [Administration](/en/admin/overview).
