import { defineConfig } from "vitepress";

// The docs are served — auth-gated — under /docs/ by the VoidSwitch backend
// (see backend/voidswitch/api/docs_site.py). The base path must match that
// mount, and clean URLs are resolved by the docs server's static handler.
export default defineConfig({
  base: "/docs/",
  lang: "zh-CN",
  title: "VoidSwitch 文档",
  description: "VoidSwitch 使用指南 — 多供应商 LLM API 网关。",
  // Favicon: same lightning mark as the main site, but with the bolt/background
  // colours swapped (amber field, blue bolt) so the docs tab is easy to tell
  // apart from the dashboard.
  head: [
    [
      "link",
      {
        rel: "icon",
        type: "image/svg+xml",
        href:
          "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23f59e0b'/%3E%3Cpath d='M18 3 L8 18 L14 18 L13 29 L24 12 L17 12 Z' fill='%232563eb'/%3E%3C/svg%3E",
      },
    ],
  ],
  cleanUrls: true,
  // Off: "last updated" shells out to git, which isn't present in the Docker
  // build stage (and .git isn't in the build context anyway).
  lastUpdated: false,
  ignoreDeadLinks: true,
  themeConfig: {
    nav: [
      { text: "指南", link: "/guide/introduction" },
      { text: "管理", link: "/admin/overview" },
      { text: "控制台", link: "https://voidswitch.siiway.org/" },
    ],
    sidebar: {
      "/guide/": [
        {
          text: "快速入门",
          items: [
            { text: "简介", link: "/guide/introduction" },
            { text: "登录", link: "/guide/sign-in" },
            { text: "控制台概览", link: "/guide/dashboard" },
            { text: "公告", link: "/guide/announcements" },
          ],
        },
        {
          text: "使用网关",
          items: [
            { text: "API 密钥", link: "/guide/api-keys" },
            { text: "调用 API", link: "/guide/using-the-api" },
            { text: "Claude Code", link: "/guide/claude-code" },
            { text: "OpenCode 插件", link: "/guide/opencode" },
            { text: "模型目录", link: "/guide/models" },
            { text: "聊天测试", link: "/guide/chat" },
            { text: "日志与用量", link: "/guide/logs-usage" },
          ],
        },
      ],
      "/admin/": [
        {
          text: "管理",
          items: [
            { text: "概览与角色", link: "/admin/overview" },
            { text: "供应商", link: "/admin/providers" },
            { text: "上游密钥", link: "/admin/keys" },
            { text: "代理", link: "/admin/proxies" },
            { text: "模型", link: "/admin/models" },
            { text: "身份组", link: "/admin/role-groups" },
            { text: "用户", link: "/admin/users" },
            { text: "Void-Token", link: "/admin/tokens" },
            { text: "设置", link: "/admin/settings" },
            { text: "审计与机密", link: "/admin/audit" },
          ],
        },
      ],
    },
    outline: { level: [2, 3] },
    docFooter: { prev: "上一页", next: "下一页" },
    search: { provider: "local" },
  },
});
