# Your API Keys (Void-Token)

To call the gateway you need a **Void-Token** — a personal client credential that starts with `vs-`. Manage your tokens on the **My Tokens** page.

## Creating a token

1. Open **My Tokens** from the sidebar (Account section).
2. Click to create a new token and give it a name (for example `laptop`, `ci`).
3. Optional settings:
   - **Allowed models** — restrict this token to specific model IDs. Leave empty = all models you're authorized to call.
   - **RPM limit** — the maximum number of requests per minute (0 = unlimited).
   - **Daily quota** — the maximum number of requests per day (0 = unlimited).
   - **Expiration** — the token stops working after this date.
4. Copy the token **immediately** — the key is shown only **once**. If you lose it, rotate the token to get a new key.

## Managing tokens

- **Rotate** — generate a new key for the token (the old key stops working). Use this if a token may have leaked.
- **Rename** — change the token's name to make its source easy to identify in logs.
- **Enable / Disable** — temporarily cut off or restore a token without administrator involvement.
- **Delete** — the token is invalidated immediately; its name, ID, and creator are still shown in the logs.

::: warning Keep it secret
A Void-Token grants gateway access as you. Treat it like a password: never commit it to source control or paste it into a shared chat. If it is exposed, rotate it immediately.
:::

## Using a token

Send the token as the API key / bearer to your client. See [Using the API](/en/guide/using-the-api) for complete examples. In short:

```bash
# OpenAI-style
export OPENAI_BASE_URL=https://voidswitch.siiway.org/v1
export OPENAI_API_KEY=vs-your-token

# Anthropic-style / Claude Code
export ANTHROPIC_BASE_URL=https://voidswitch.siiway.org
export ANTHROPIC_AUTH_TOKEN=vs-your-token
```

## Quotas and limits

If you exceed the token's RPM limit or daily quota, requests are rejected until the window resets. The model allowlist rejects calls to models not on the list.
A platform-wide **per-user call rate limit** may also apply (set by the owner), stacking on top of your token's own limits.
You can view your own usage on the [Logs & Usage](/en/guide/logs-usage) page.
