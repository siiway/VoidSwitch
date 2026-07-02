# Chat playground

The **Chat** page is a built-in playground for trying models straight from the
dashboard — no external client or token setup required.

## Using it

1. Open **Chat** from the sidebar (Account section).
2. Pick a model you're allowed to call.
3. Type a message and send.

Responses stream back in real time. It's handy for:

- checking a model is reachable and behaving;
- comparing outputs across models;
- quick one-off prompts without wiring up an SDK.

::: tip
The playground calls the same gateway your API clients use, so what you see here
reflects real routing, failover, and model availability. For automated or
high-volume use, mint a [Void-Token](/guide/api-keys) and call the
[API](/guide/using-the-api) directly.
:::
