/**
 * VoidSwitch plugin RPC contract — the typed surface the TUI part calls to
 * drive the server part without touching a session. Schemas are JSON Schema
 * (dependency-free); values arrive as `unknown`, so callers narrow locally.
 */
import { Rpc } from "@opencode/plugin/rpc";

/** Result of a catalog refresh: `ok` false carries the failure note verbatim. */
export interface SyncResult {
  ok: boolean;
  note: string;
}

/** The gateway the server part resolves to, plus why (`option`|`env`|`config`|`install`|`default`). */
export interface GatewayInfo {
  url: string;
  source: string;
}

/** The MCP server as the palette needs it; the raw key never crosses the RPC. */
export interface McpStatusInfo {
  /** Server name registered with OpenCode. */
  name: string;
  /** Whether this OpenCode build can register MCP servers at all. */
  supported: boolean;
  installed: boolean;
  enabled: boolean;
  url: string;
  /** The gateway's own fingerprint (`vsapi-ab12cd…wxyz`), empty when unset. */
  prefix: string;
}

export const VoidSwitchRpc = Rpc.define({
  id: "voidswitch",
  methods: {
    /** Refresh the model catalog from the gateway and persist it. */
    syncModels: {
      input: { type: "object", properties: {}, additionalProperties: false },
      output: {
        type: "object",
        properties: { ok: { type: "boolean" }, note: { type: "string" } },
        required: ["ok", "note"],
        additionalProperties: false,
      },
    },
    /** The gateway currently in use and where it came from. */
    gateway: {
      input: { type: "object", properties: {}, additionalProperties: false },
      output: {
        type: "object",
        properties: { url: { type: "string" }, source: { type: "string" } },
        required: ["url", "source"],
        additionalProperties: false,
      },
    },
    /** Point the plugin at another gateway (empty resets to the default). */
    setGateway: {
      input: {
        type: "object",
        properties: { url: { type: "string" } },
        additionalProperties: false,
      },
      output: {
        type: "object",
        properties: { ok: { type: "boolean" }, note: { type: "string" } },
        required: ["ok", "note"],
        additionalProperties: false,
      },
    },
    /** Whether the management MCP server is installed, enabled and where it points. */
    mcpStatus: {
      input: { type: "object", properties: {}, additionalProperties: false },
      output: {
        type: "object",
        properties: {
          name: { type: "string" },
          supported: { type: "boolean" },
          installed: { type: "boolean" },
          enabled: { type: "boolean" },
          url: { type: "string" },
          prefix: { type: "string" },
        },
        required: [
          "name",
          "supported",
          "installed",
          "enabled",
          "url",
          "prefix",
        ],
        additionalProperties: false,
      },
    },
    /** Install or re-key the MCP server (empty key keeps the stored one). */
    mcpSetup: {
      input: {
        type: "object",
        properties: { key: { type: "string" } },
        additionalProperties: false,
      },
      output: {
        type: "object",
        properties: { ok: { type: "boolean" }, note: { type: "string" } },
        required: ["ok", "note"],
        additionalProperties: false,
      },
    },
    /** Enable the installed MCP server. */
    mcpEnable: {
      input: { type: "object", properties: {}, additionalProperties: false },
      output: {
        type: "object",
        properties: { ok: { type: "boolean" }, note: { type: "string" } },
        required: ["ok", "note"],
        additionalProperties: false,
      },
    },
    /** Disable the installed MCP server without forgetting its key. */
    mcpDisable: {
      input: { type: "object", properties: {}, additionalProperties: false },
      output: {
        type: "object",
        properties: { ok: { type: "boolean" }, note: { type: "string" } },
        required: ["ok", "note"],
        additionalProperties: false,
      },
    },
    /** Remove the MCP server and delete the stored key. */
    mcpUninstall: {
      input: { type: "object", properties: {}, additionalProperties: false },
      output: {
        type: "object",
        properties: { ok: { type: "boolean" }, note: { type: "string" } },
        required: ["ok", "note"],
        additionalProperties: false,
      },
    },
  },
  events: {},
});
