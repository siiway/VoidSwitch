# Chat test

The **Chat** page is a built-in playground for trying models directly from the dashboard — no external client or token setup required.

## How to use it

1. Open **Chat** from the sidebar (account section).
2. Select a model you are allowed to call.
3. Type a message and send it.

Responses stream back in real time. It's useful for:

- Checking whether a model is reachable and working;
- Comparing outputs from different models;
- Quick one-off prompts without configuring an SDK.

::: tip
The playground uses the same gateway as your API clients, so what you see here reflects real routing, failover, and model availability.
For automation or heavy usage, create a [Void-Token](/en/guide/api-keys) and call the [API](/en/guide/using-the-api) directly.
:::
