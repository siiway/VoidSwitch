# Dashboard overview

After signing in you land on the **Dashboard** — your home page. What it shows depends on your tier.

## Visible to everyone

- **Announcements** — the latest platform announcements. See [Announcements](/en/guide/announcements).
- The **Docs** tab in the sidebar (Account section) opens this documentation in a new tab.

## Visible to members

The dashboard summarizes **your own** activity:

- **My Requests** — the number of requests you've made through the gateway.
- **My Token Usage** — the total number of tokens your requests consumed.
- **My API Keys** — the number of Void-Tokens you currently hold.

Members don't see platform-wide statistics or provider pages.

## Activity heatmap

At the **bottom** of the page is an **activity heatmap** similar to the "contribution graph" on code-hosting sites, showing your token usage by day (the darker the color, the more you used that day; hover over a cell to see the **exact** token count for that day, with no "K / M" abbreviation). Above the heatmap are a few summary figures:

- **Cumulative tokens** — total usage within the retention window.
- **Peak tokens** — the highest single-day usage.
- **Longest task duration** — the longest span, computed by session ID, of a single session (task) from its first to its last request.
- **Current streak / Longest streak** — consecutive days with usage.

A staff member's dashboard shows **both** heatmaps: **Site activity** (platform-wide aggregate) and **My activity** (your own data).

## Visible to staff

Staff see a platform-wide overview:

- Counts of **Providers**, **Active keys**, and **Void-Tokens**.
- **24-hour activity**: requests, successes, failures, success rate, token usage, average time-to-first-token (TTFT), and average tokens per request.
- **Background jobs**: the status of the balance-probe, proxy-revival, and log-cleanup scheduled tasks.
- The **Site** and **Personal** activity heatmaps at the bottom of the page (see "Activity heatmap" above).

## Sidebar navigation

The sidebar groups pages into **Overview**, **Routing**, **Operations**, and **Account**. You only see pages your tier can access; theme switch, language switch, and sign out are in the footer.

| Page | Who sees it |
| ---- | ---- |
| Dashboard | Everyone |
| Models, Statistics, Logs | Everyone |
| Chat, My Tokens, Docs | Everyone |
| Providers, Proxies, Users, Role Groups, Settings | Staff |
| Tokens | Owners |

Next: [Announcements](/en/guide/announcements).
