import { defineConfig } from "vitepress";
import { readFileSync } from "node:fs";

// Caddyfile TextMate grammar for syntax highlighting (not bundled in Shiki).
const caddyfileGrammar = JSON.parse(
  readFileSync(new URL("./caddyfile.tmLanguage.json", import.meta.url), "utf-8"),
);

// Public documentation site (deployed to GitHub Pages at voidswitch.siiway.page).
// Bilingual: Simplified Chinese is the root locale (served at `/`), English is
// mounted under `/en/`. The language menu (top-right) switches between them.
const DASHBOARD_URL = "https://voidswitch.siiway.org/";

// --- Simplified Chinese (root) --------------------------------------------- //
const zhNav = [
  { text: "指南", link: "/guide/introduction" },
  { text: "管理", link: "/admin/overview" },
  { text: "控制台", link: DASHBOARD_URL },
];

const zhSidebar = {
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
        { text: "供应商目录", link: "/admin/provider-catalog" },
        { text: "上游密钥", link: "/admin/keys" },
        { text: "节点与节点组", link: "/admin/proxies" },
        { text: "VS Agent", link: "/admin/agents" },
        { text: "反向代理", link: "/admin/reverse-proxy" },
        { text: "模型", link: "/admin/models" },
        { text: "身份组", link: "/admin/role-groups" },
        { text: "用户", link: "/admin/users" },
        { text: "Void-Token", link: "/admin/tokens" },
        { text: "设置", link: "/admin/settings" },
        { text: "审计与机密", link: "/admin/audit" },
      ],
    },
  ],
};

// --- English (/en/) -------------------------------------------------------- //
const enNav = [
  { text: "Guide", link: "/en/guide/introduction" },
  { text: "Admin", link: "/en/admin/overview" },
  { text: "Dashboard", link: DASHBOARD_URL },
];

const enSidebar = {
  "/en/guide/": [
    {
      text: "Getting started",
      items: [
        { text: "Introduction", link: "/en/guide/introduction" },
        { text: "Signing in", link: "/en/guide/sign-in" },
        { text: "Dashboard overview", link: "/en/guide/dashboard" },
        { text: "Announcements", link: "/en/guide/announcements" },
      ],
    },
    {
      text: "Using the gateway",
      items: [
        { text: "API keys", link: "/en/guide/api-keys" },
        { text: "Calling the API", link: "/en/guide/using-the-api" },
        { text: "Claude Code", link: "/en/guide/claude-code" },
        { text: "OpenCode plugin", link: "/en/guide/opencode" },
        { text: "Model catalog", link: "/en/guide/models" },
        { text: "Chat playground", link: "/en/guide/chat" },
        { text: "Logs & usage", link: "/en/guide/logs-usage" },
      ],
    },
  ],
  "/en/admin/": [
    {
      text: "Administration",
      items: [
        { text: "Overview & roles", link: "/en/admin/overview" },
        { text: "Providers", link: "/en/admin/providers" },
        { text: "Provider catalog", link: "/en/admin/provider-catalog" },
        { text: "Upstream keys", link: "/en/admin/keys" },
        { text: "Nodes & Node Groups", link: "/en/admin/proxies" },
        { text: "VS Agent", link: "/en/admin/agents" },
        { text: "Reverse proxy", link: "/en/admin/reverse-proxy" },
        { text: "Models", link: "/en/admin/models" },
        { text: "Role groups", link: "/en/admin/role-groups" },
        { text: "Users", link: "/en/admin/users" },
        { text: "Void-Tokens", link: "/en/admin/tokens" },
        { text: "Settings", link: "/en/admin/settings" },
        { text: "Audit & secrets", link: "/en/admin/audit" },
      ],
    },
  ],
};

export default defineConfig({
  base: "/",
  title: "VoidSwitch",
  description: "VoidSwitch — a multi-provider LLM API gateway.",
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
  lastUpdated: false,
  ignoreDeadLinks: true,
  markdown: {
    languages: [caddyfileGrammar],
  },
  locales: {
    root: {
      label: "简体中文",
      lang: "zh-CN",
      title: "VoidSwitch 文档",
      description: "VoidSwitch 使用指南 — 多供应商 LLM API 网关。",
      themeConfig: {
        nav: zhNav,
        sidebar: zhSidebar,
        outline: { level: [2, 3], label: "本页目录" },
        docFooter: { prev: "上一页", next: "下一页" },
        darkModeSwitchLabel: "外观",
        sidebarMenuLabel: "菜单",
        returnToTopLabel: "返回顶部",
        langMenuLabel: "切换语言",
      },
    },
    en: {
      label: "English",
      lang: "en",
      link: "/en/",
      title: "VoidSwitch Docs",
      description: "VoidSwitch usage guide — a multi-provider LLM API gateway.",
      themeConfig: {
        nav: enNav,
        sidebar: enSidebar,
        outline: { level: [2, 3] },
      },
    },
  },
  themeConfig: {
    search: {
      provider: "local",
      options: {
        locales: {
          root: {
            translations: {
              button: { buttonText: "搜索文档", buttonAriaLabel: "搜索文档" },
              modal: {
                noResultsText: "无法找到相关结果",
                resetButtonTitle: "清除查询条件",
                footer: {
                  selectText: "选择",
                  navigateText: "切换",
                  closeText: "关闭",
                },
              },
            },
          },
        },
      },
    },
  },
});
