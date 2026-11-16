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
  },
  events: {},
});
