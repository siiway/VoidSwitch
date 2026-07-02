import { defineConfig } from "vitepress";

// The docs are served — auth-gated — under /docs/ by the VoidSwitch backend
// (see backend/voidswitch/api/docs_site.py). The base path must match that
// mount, and clean URLs are resolved by the docs server's static handler.
export default defineConfig({
  base: "/docs/",
  lang: "en-US",
  title: "VoidSwitch Docs",
  description: "How to use VoidSwitch — the multi-provider LLM API gateway.",
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: true,
  themeConfig: {
    nav: [
      { text: "Guide", link: "/guide/introduction" },
      { text: "Admin", link: "/admin/overview" },
      { text: "Dashboard", link: "/" },
    ],
    sidebar: {
      "/guide/": [
        {
          text: "Getting started",
          items: [
            { text: "Introduction", link: "/guide/introduction" },
            { text: "Signing in", link: "/guide/sign-in" },
            { text: "The dashboard", link: "/guide/dashboard" },
            { text: "Announcements", link: "/guide/announcements" },
          ],
        },
        {
          text: "Using the gateway",
          items: [
            { text: "Your API key", link: "/guide/api-keys" },
            { text: "Calling the API", link: "/guide/using-the-api" },
            { text: "Claude Code", link: "/guide/claude-code" },
            { text: "OpenCode plugin", link: "/guide/opencode" },
            { text: "Models catalog", link: "/guide/models" },
            { text: "Chat playground", link: "/guide/chat" },
            { text: "Logs & usage", link: "/guide/logs-usage" },
          ],
        },
      ],
      "/admin/": [
        {
          text: "Administration",
          items: [
            { text: "Overview & roles", link: "/admin/overview" },
            { text: "Providers", link: "/admin/providers" },
            { text: "Upstream keys", link: "/admin/keys" },
            { text: "Proxies", link: "/admin/proxies" },
            { text: "Models", link: "/admin/models" },
            { text: "Role groups", link: "/admin/role-groups" },
            { text: "Users", link: "/admin/users" },
            { text: "Void-Tokens", link: "/admin/tokens" },
            { text: "Settings", link: "/admin/settings" },
            { text: "Audit & secrets", link: "/admin/audit" },
          ],
        },
      ],
    },
    outline: { level: [2, 3] },
    docFooter: { prev: true, next: true },
    search: { provider: "local" },
  },
});
