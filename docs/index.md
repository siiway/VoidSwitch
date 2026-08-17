---
layout: home

hero:
  name: VoidSwitch
  text: LLM API 网关
  tagline: 一个端点访问所有模型 — 弹性密钥与节点故障转移，OpenAI ⇄ Anthropic 转换，以及自助服务控制台。
  actions:
    - theme: brand
      text: 快速入门
      link: /guide/introduction
    - theme: alt
      text: 使用 API
      link: /guide/using-the-api
    - theme: alt
      text: 管理
      link: /admin/overview

features:
  - title: 一个端点，多个供应商
    details: 将 OpenAI SDK、Anthropic SDK 或 Claude Code 指向一个 URL。VoidSwitch 替你选择供应商、轮换密钥并在节点间故障转移。
  - title: 自助密钥
    details: 创建你自己的长期 vs-… 令牌，设置每个令牌的模型白名单和速率限制，并可随时轮换或撤销。
  - title: OpenAI ⇄ Anthropic
    details: 发送 OpenAI /v1/chat/completions、OpenAI /v1/responses 或 Anthropic /v1/messages — 请求、响应和流式传输在运行中自动转换。
  - title: OpenCode 就绪
    details: 一行安装命令即可将 VoidSwitch 添加为 OpenCode 的一级供应商，支持完整的 Claude Code 请求功能。
---

## 这是什么？

VoidSwitch 是一个**多供应商 LLM API 反向代理**。它在一个端点上接受 OpenAI Chat
Completions、OpenAI Responses 和 Anthropic 格式的流量，在它们之间进行转换，并将请求转发到
 能够服务该模型的任何上游供应商 — 同时处理密钥轮换、节点故障转移和每用户配额。

本文档是**公开的**，任何人都可以阅读；提供中文与 English 两种语言，用页面右上角的语言菜单切换。

- 刚来？从[简介](/guide/introduction)开始。
- 想发送请求？参阅[你的 API 密钥](/guide/api-keys)和[调用 API](/guide/using-the-api)。
- 运行平台？前往[管理](/admin/overview)。