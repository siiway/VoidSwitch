/**
 * VoidSwitch TUI part — palette commands (Ctrl+P) that drive the server part
 * over RPC. They never submit a session message, unlike the slash-command
 * pipeline, whose invocations are durable user prompts by design.
 */
import { Plugin } from "@opencode/plugin/tui";
import { GatewayInfo, McpStatusInfo, SyncResult, VoidSwitchRpc } from "./rpc";

type ToastVariant = "info" | "success" | "warning" | "error";

/** The four management actions offered for the MCP server. */
type McpAction = "setup" | "enable" | "disable" | "uninstall";

/** OpenCode's MCP connection states, in palette wording. */
const MCP_STATE_LABEL: Record<string, string> = {
  connected: "connected",
  pending: "connecting…",
  disabled: "disabled",
  failed: "failed",
  needs_auth: "needs sign-in",
};

const describe = (e: unknown): string =>
  e instanceof Error ? e.message : String(e);

export default Plugin.define({
  id: "voidswitch-tui",
  async setup(context) {
    const rpc = context.client.rpc(VoidSwitchRpc);

    const toast = (message: string, variant: ToastVariant) =>
      context.ui.toast.show({
        title: "VoidSwitch",
        message,
        variant,
        duration: 6000,
      });

    /**
     * Second-level menus arrived after the first 2.x builds. Without them the
     * palette exposes setup and uninstall as two standalone commands.
     */
    const hasMenu = typeof context.ui.dialog.select === "function";

    /** The live connection state OpenCode reports for our server. */
    const connectionState = async (name: string): Promise<string> => {
      try {
        await context.data.location.mcp.server.sync(context.location);
        const server = (
          context.data.location.mcp.server.list(context.location) ?? []
        ).find((s) => s.name === name);
        if (!server) return "";
        return MCP_STATE_LABEL[server.status.status] ?? server.status.status;
      } catch {
        return "";
      }
    };

    /**
     * Short successes go to a toast; failures and multi-line output (diagnostics
     * with request/status/body) need a dialog the user can actually read.
     */
    const report = async (note: string, ok: boolean): Promise<void> => {
      if (ok && !note.includes("\n")) {
        toast(note, "success");
        return;
      }
      await context.ui.dialog.alert({
        title: ok ? "VoidSwitch" : "VoidSwitch — action failed",
        message: note,
      });
    };

    /** Drive one management action and report the server part's own wording. */
    const runMcp = async (action: McpAction, key = ""): Promise<void> => {
      try {
        const request =
          action === "setup"
            ? rpc.mcpSetup({ key })
            : action === "enable"
              ? rpc.mcpEnable({})
              : action === "disable"
                ? rpc.mcpDisable({})
                : rpc.mcpUninstall({});
        const result = (await request) as SyncResult;
        await report(result.note, result.ok);
      } catch (e) {
        toast(`couldn't reach the OpenCode server: ${describe(e)}`, "error");
      }
    };

    const setupMcp = async (): Promise<void> => {
      const raw = await context.ui.dialog.prompt({
        title: "VoidSwitch platform API key",
        description:
          "Paste a vsapi-… platform API key (staff only). Leave empty to keep the stored key.",
        placeholder: "vsapi-…",
      });
      if (raw === undefined) return;
      await runMcp("setup", raw);
    };

    const uninstallMcp = async (): Promise<void> => {
      const confirmed = await context.ui.dialog.confirm({
        title: "Remove the VoidSwitch MCP server?",
        message:
          "The server is removed and the stored vsapi-… key is deleted from this machine. The key itself stays valid in the dashboard.",
        label: { confirm: "Uninstall", cancel: "Cancel" },
      });
      if (!confirmed) return;
      await runMcp("uninstall");
    };

    /** The menu: every action stays listed, the unusable ones greyed out. */
    const configureMcp = async (): Promise<void> => {
      let status: McpStatusInfo;
      try {
        status = (await rpc.mcpStatus({})) as McpStatusInfo;
      } catch (e) {
        toast(`couldn't reach the OpenCode server: ${describe(e)}`, "error");
        return;
      }
      const live = await connectionState(status.name);
      const suffix = live ? ` · ${live}` : "";
      const unsupported =
        "this OpenCode build cannot register MCP servers — upgrade to 2.3 or newer";
      const selected = await context.ui.dialog.select<McpAction>({
        title: "VoidSwitch MCP server",
        options: [
          {
            title: status.installed ? "Setup / re-configure" : "Setup",
            value: "setup",
            disabled: !status.supported,
            description: !status.supported
              ? unsupported
              : status.installed
                ? `${status.prefix}${suffix} · ${status.url}`
                : `paste a vsapi-… platform API key · ${status.url}`,
          },
          {
            title: "Enable",
            value: "enable",
            disabled: !status.supported || !status.installed || status.enabled,
            description: !status.supported
              ? unsupported
              : !status.installed
                ? "install the server first"
                : status.enabled
                  ? "already enabled"
                  : "turn the server on",
          },
          {
            title: "Disable",
            value: "disable",
            disabled: !status.supported || !status.installed || !status.enabled,
            description: !status.supported
              ? unsupported
              : !status.installed
                ? "install the server first"
                : status.enabled
                  ? "turn the server off (the key is kept)"
                  : "already disabled",
          },
          {
            title: "Uninstall",
            value: "uninstall",
            disabled: !status.installed,
            description: !status.installed
              ? "nothing installed"
              : "remove the server and delete the stored key",
          },
        ],
      });
      if (selected === undefined) return;
      if (selected === "setup") return setupMcp();
      if (selected === "uninstall") return uninstallMcp();
      await runMcp(selected);
    };

    /** Palette entries for the server: one menu, or setup / uninstall apart. */
    const mcpCommands: Array<{
      id: string;
      title: string;
      group: string;
      palette: true;
      run: () => Promise<void>;
    }> = hasMenu
      ? [
          {
            id: "voidswitch.configureMcp",
            title: "VoidSwitch: configure mcp server",
            group: "VoidSwitch",
            palette: true,
            run: async () => {
              await configureMcp();
            },
          },
        ]
      : [
          {
            id: "voidswitch.setupMcp",
            title: "VoidSwitch: setup mcp server",
            group: "VoidSwitch",
            palette: true,
            run: async () => {
              await setupMcp();
            },
          },
          {
            id: "voidswitch.uninstallMcp",
            title: "VoidSwitch: uninstall mcp server",
            group: "VoidSwitch",
            palette: true,
            run: async () => {
              await uninstallMcp();
            },
          },
        ];

    context.keymap.layer(() => ({
      mode: "global",
      priority: 10,
      commands: [
        {
          id: "voidswitch.syncModels",
          title: "VoidSwitch: sync models",
          group: "VoidSwitch",
          palette: true,
          suggested: true,
          async run() {
            try {
              const result = (await rpc.syncModels({})) as SyncResult;
              toast(result.note, result.ok ? "success" : "error");
            } catch (e) {
              toast(
                `couldn't reach the OpenCode server: ${describe(e)}`,
                "error",
              );
            }
          },
        },
        {
          id: "voidswitch.setGateway",
          title: "VoidSwitch: set gateway URL",
          group: "VoidSwitch",
          palette: true,
          async run() {
            let current = "";
            try {
              const info = (await rpc.gateway({})) as GatewayInfo;
              current = info.url;
            } catch {
              // The server part may not be configured yet; start blank.
            }
            const raw = await context.ui.dialog.prompt({
              title: "VoidSwitch gateway URL",
              description:
                "Empty resets to the default (install-baked or the public instance).",
              placeholder: current || "https://voidswitch.siiway.org",
              value: current,
            });
            if (raw === undefined) return;
            try {
              const result = (await rpc.setGateway({
                url: raw.trim(),
              })) as SyncResult;
              toast(result.note, result.ok ? "success" : "error");
            } catch (e) {
              toast(
                `couldn't reach the OpenCode server: ${describe(e)}`,
                "error",
              );
            }
          },
        },
        ...mcpCommands,
      ],
    }));
  },
});
