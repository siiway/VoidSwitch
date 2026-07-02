# Your API key (Void-Tokens)

To call the gateway you need a **Void-Token** — a personal client credential that
starts with `vs-`. Manage yours on the **My API Key** page.

## Create a token

1. Open **My API Key** from the sidebar (Account section).
2. Click to create a new token and give it a **name** (e.g. `laptop`, `ci`).
3. Optionally set:
   - **Allowed models** — restrict this token to specific model ids. Empty = all
     models you're permitted to call.
   - **RPM limit** — max requests per minute (0 = unlimited).
   - **Daily quota** — max requests per day (0 = unlimited).
   - **Expiry** — a date after which the token stops working.
4. Copy the token **immediately** — the secret is shown **once**. If you lose it,
   rotate the token to get a new one.

## Manage tokens

- **Rotate** — generate a new secret for a token (the old one stops working).
  Useful if a token may have leaked.
- **Edit** — change the name, model allow-list, limits, or expiry.
- **Delete** — permanently remove a token.

::: warning Keep it secret
A Void-Token grants access to the gateway as you. Treat it like a password:
never commit it to source control or paste it into shared chats. Rotate
immediately if exposed.
:::

## Use a token

Send the token as the API key / bearer for your client. See
[Calling the API](/guide/using-the-api) for full examples. In short:

```bash
# OpenAI-style
export OPENAI_BASE_URL=https://your-voidswitch-host/v1
export OPENAI_API_KEY=vs-your-token

# Anthropic-style / Claude Code
export ANTHROPIC_BASE_URL=https://your-voidswitch-host
export ANTHROPIC_AUTH_TOKEN=vs-your-token
```

## Quotas and limits

If you exceed a token's RPM limit or daily quota, requests are rejected until the
window resets. Model allow-lists reject calls to models not on the list. Your
own usage is visible on the [Logs & usage](/guide/logs-usage) page.
