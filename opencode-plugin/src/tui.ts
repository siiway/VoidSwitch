/**
 * VoidSwitch TUI part — palette commands (Ctrl+P) that drive the server part
 * over RPC. They never submit a session message, unlike the slash-command
 * pipeline, whose invocations are durable user prompts by design.
 */
import { Plugin } from "@opencode/plugin/tui";
import { GatewayInfo, SyncResult, VoidSwitchRpc } from "./rpc";

type ToastVariant = "info" | "success" | "warning" | "error";

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
      ],
    }));
  },
});
