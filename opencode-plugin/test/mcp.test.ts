/**
 * Palette-side MCP server management, exercised against a fake gateway: the
 * palette part itself is TUI-only, so every behaviour worth regressing lives
 * behind the RPC surface tested here.
 */
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import plugin from "../src/index";

const GOOD_KEY = "vsapi-test-0123456789abcdef";
const BAD_KEY = "vsapi-test-rejected";

let gateway: ReturnType<typeof Bun.serve>;
let configHome = "";

beforeAll(() => {
  gateway = Bun.serve({
    port: 0,
    fetch(req) {
      const url = new URL(req.url);
      if (url.pathname === "/v1/models")
        return Response.json({ data: [{ id: "claude-opus-4-8" }] });
      if (url.pathname === "/v1/models/sync")
        return Response.json({ total: 1 });
      if (url.pathname === "/api/v1/whoami") {
        if (req.headers.get("authorization") !== `Bearer ${GOOD_KEY}`)
          return Response.json({ detail: "Invalid API key." }, { status: 401 });
        return Response.json({
          user: "admin",
          role: "owner",
          key: "smoke",
          prefix: "vsapi-test-0…cdef",
          scopes: ["read"],
          tools: ["model.get", "stats.get"],
        });
      }
      return new Response("not found", { status: 404 });
    },
  });
});

afterAll(() => {
  gateway.stop();
});

interface Harness {
  rpc: Record<string, (input?: any) => Promise<any>>;
  servers: Record<string, any>;
  reloads: () => number;
  statePath: string;
  cleanup: () => Promise<void>;
  unavailability: string[];
}

/** Build a plugin context: a fake gateway, a recording MCP registry, RPC capture. */
async function createHarness(
  options: {
    withMcp?: boolean;
    configServers?: Record<string, any>;
    sidecar?: string;
  } = {},
): Promise<Harness> {
  const withMcp = options.withMcp !== false;
  const configServers = options.configServers ?? {};
  const previousConfigHome = process.env.XDG_CONFIG_HOME;
  configHome = mkdtempSync(join(tmpdir(), "vs-mcp-test-"));
  process.env.XDG_CONFIG_HOME = configHome;
  delete process.env.VOIDSWITCH_URL;
  delete process.env.VOIDSWITCH_TOKEN;
  delete process.env.OPENCODE_CONFIG;

  const statePath = join(configHome, "opencode", "voidswitch-mcp.json");
  if (options.sidecar !== undefined) {
    mkdirSync(join(configHome, "opencode"), { recursive: true });
    writeFileSync(statePath, options.sidecar);
  }

  const servers: Record<string, any> = {};
  const rpc: Record<string, (input?: any) => Promise<any>> = {};
  const unavailability: string[] = [];
  let transform: ((editor: any) => void) | undefined;
  let reloads = 0;

  const replay = () => {
    for (const name of Object.keys(servers)) delete servers[name];
    // A fresh config-derived registry: hand-written `mcp.servers` entries live
    // here, exactly like OpenCode rebuilds the value on every transform replay.
    for (const [name, config] of Object.entries(configServers))
      servers[name] = { ...config };
    transform?.({
      list: () => Object.entries(servers),
      get: (name: string) => servers[name],
      set: (name: string, config: any) => {
        servers[name] = config;
      },
      update: (name: string, apply: (config: any) => void) => {
        if (servers[name]) apply(servers[name]);
      },
      remove: (name: string) => {
        delete servers[name];
      },
    });
  };

  const ctx: any = {
    options: { url: `http://127.0.0.1:${gateway.port}` },
    location: {},
    integration: {
      connection: {
        active: async () => undefined,
        resolve: async () => undefined,
      },
      transform: async (apply: any) => {
        apply({ list: () => [], method: { update() {}, remove() {} } });
        return { dispose: async () => {} };
      },
    },
    provider: {
      transform: async (apply: any) => {
        const blocks: Record<string, any> = {};
        apply({
          get: (id: string) => blocks[id],
          add: (input: any) => {
            blocks[input.info.id] = input;
          },
          update: (id: string, fn: (draft: any) => void) => {
            if (blocks[id]) fn(blocks[id]);
          },
          models: {
            set: (id: string, models: any[]) => {
              blocks[id] = { ...(blocks[id] ?? {}), models };
            },
          },
        });
        return { dispose: async () => {} };
      },
    },
    command: {
      transform: async (apply: any) => {
        apply({ add() {} });
        return { dispose: async () => {} };
      },
    },
    rpc: {
      register: async (_contract: any, impl: Record<string, any>) => {
        Object.assign(rpc, impl);
      },
    },
    event: {
      subscribe: async function* () {},
    },
    session: {
      hook: async () => ({ dispose: async () => {} }),
      prompt: async () => {},
    },
    mcp: withMcp
      ? {
          transform: async (apply: (editor: any) => void) => {
            transform = apply;
            replay();
            return { dispose: async () => {} };
          },
          reload: async () => {
            reloads += 1;
            replay();
          },
          list: async () => ({ servers: [] }),
        }
      : undefined,
  };

  const restoreEnv = () => {
    if (previousConfigHome === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previousConfigHome;
  };

  if (!withMcp) {
    const originalError = console.error;
    console.error = (...args: any[]) => {
      unavailability.push(args.join(" "));
    };
    const cleanup = await plugin.setup(ctx);
    console.error = originalError;
    return {
      rpc,
      servers,
      reloads: () => reloads,
      statePath,
      cleanup: async () => {
        await cleanup?.();
        restoreEnv();
      },
      unavailability,
    };
  }

  const cleanup = await plugin.setup(ctx);
  return {
    rpc,
    servers,
    reloads: () => reloads,
    statePath,
    cleanup: async () => {
      await cleanup?.();
      restoreEnv();
    },
    unavailability,
  };
}

let harness: Harness;

beforeEach(async () => {
  harness = await createHarness();
});

afterEach(async () => {
  await harness.cleanup();
});

describe("management MCP server", () => {
  it("installs nothing until a key is accepted", async () => {
    expect(Object.keys(harness.servers)).toHaveLength(0);
    expect((await harness.rpc.mcpStatus({})).installed).toBe(false);
  });

  it("refuses a key the gateway rejects and writes nothing", async () => {
    const result = await harness.rpc.mcpSetup({ key: BAD_KEY });
    expect(result.ok).toBe(false);
    expect(result.note).toContain("rejected");
    expect(existsSync(harness.statePath)).toBe(false);
    expect(harness.servers.voidswitch).toBeUndefined();
  });

  it("refuses a gateway token instead of a platform API key", async () => {
    const result = await harness.rpc.mcpSetup({ key: "vs-not-a-platform-key" });
    expect(result.ok).toBe(false);
    expect(result.note).toContain("vsapi-");
    expect(existsSync(harness.statePath)).toBe(false);
  });

  it("registers a remote server with the key in a bearer header", async () => {
    const result = await harness.rpc.mcpSetup({ key: GOOD_KEY });
    expect(result.ok).toBe(true);

    const server = harness.servers.voidswitch;
    expect(server.type).toBe("remote");
    expect(server.url).toBe(`http://127.0.0.1:${gateway.port}/api/v1/mcp`);
    expect(server.headers.Authorization).toBe(`Bearer ${GOOD_KEY}`);
    expect(server.oauth).toBe(false);
    expect(server.disabled).toBe(false);
  });

  it("keeps the key out of opencode.json, in a 0600 sidecar", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });
    const stored = JSON.parse(readFileSync(harness.statePath, "utf8"));
    expect(stored).toEqual({
      key: GOOD_KEY,
      enabled: true,
      prefix: "vsapi-test-0…cdef",
    });
    expect(statSync(harness.statePath).mode & 0o777).toBe(0o600);
  });

  it("reports status without leaking the key", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });
    const status = await harness.rpc.mcpStatus({});
    expect(status.installed).toBe(true);
    expect(status.enabled).toBe(true);
    expect(status.prefix).toContain("…");
    expect(status.prefix).not.toContain(GOOD_KEY);
  });

  it("disables and enables without forgetting the key", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });

    expect((await harness.rpc.mcpDisable({})).ok).toBe(true);
    expect(harness.servers.voidswitch.disabled).toBe(true);
    expect(JSON.parse(readFileSync(harness.statePath, "utf8")).key).toBe(
      GOOD_KEY,
    );

    expect((await harness.rpc.mcpEnable({})).ok).toBe(true);
    expect(harness.servers.voidswitch.disabled).toBe(false);
  });

  it("keeps the stored key when setup is given an empty one", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });
    const result = await harness.rpc.mcpSetup({ key: "" });
    expect(result.ok).toBe(true);
    expect(harness.servers.voidswitch.headers.Authorization).toBe(
      `Bearer ${GOOD_KEY}`,
    );
  });

  it("re-points the server at the current gateway after a switch", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });
    const result = await harness.rpc.setGateway({
      url: `http://127.0.0.1:${gateway.port}`,
    });
    expect(result.note).toContain("MCP server re-pointed");
    expect(harness.servers.voidswitch.url).toBe(
      `http://127.0.0.1:${gateway.port}/api/v1/mcp`,
    );
  });

  it("uninstalls the server and deletes the sidecar", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });
    expect((await harness.rpc.mcpUninstall({})).ok).toBe(true);
    expect(harness.servers.voidswitch).toBeUndefined();
    expect(existsSync(harness.statePath)).toBe(false);
  });

  it("warns when opencode.json declares its own voidswitch server", async () => {
    const dir = join(configHome, "opencode");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "opencode.json"),
      JSON.stringify({
        mcp: {
          servers: {
            voidswitch: {
              type: "remote",
              url: "https://old.example.com/api/v1/mcp",
            },
          },
        },
      }),
    );

    const result = await harness.rpc.mcpSetup({ key: GOOD_KEY });
    expect(result.ok).toBe(true);
    expect(result.note).toContain("also declares");
  });

  it("keeps a disabled server disabled when re-keying", async () => {
    await harness.rpc.mcpSetup({ key: GOOD_KEY });
    await harness.rpc.mcpDisable({});

    const result = await harness.rpc.mcpSetup({ key: "" });
    expect(result.ok).toBe(true);
    expect(result.note).toContain("currently disabled");
    expect(JSON.parse(readFileSync(harness.statePath, "utf8")).enabled).toBe(
      false,
    );
    expect(harness.servers.voidswitch.disabled).toBe(true);
  });

  it("treats a sidecar without a platform key as not installed", async () => {
    const stale = await createHarness({
      sidecar: JSON.stringify({ key: "junk", enabled: true }),
    });

    expect(Object.keys(stale.servers)).toHaveLength(0);
    expect((await stale.rpc.mcpStatus({})).installed).toBe(false);

    await stale.cleanup();
  });

  it("never writes the key into the plugin's error log", async () => {
    await harness.rpc.mcpSetup({ key: BAD_KEY });
    const logPath = join(configHome, "opencode", "voidswitch-error.log");
    const log = existsSync(logPath) ? readFileSync(logPath, "utf8") : "";
    expect(log).not.toContain(BAD_KEY);
    expect(log).not.toContain(GOOD_KEY);
  });

  it("leaves a hand-written opencode.json server untouched at startup", async () => {
    const manual = await createHarness({
      configServers: {
        voidswitch: {
          type: "remote",
          url: "https://old.example.com/api/v1/mcp",
        },
      },
    });

    expect(manual.servers.voidswitch?.url).toBe(
      "https://old.example.com/api/v1/mcp",
    );
    expect((await manual.rpc.mcpStatus({})).installed).toBe(false);

    await manual.cleanup();
  });

  it("answers uninstall cleanly when nothing is installed", async () => {
    const result = await harness.rpc.mcpUninstall({});
    expect(result.ok).toBe(false);
    expect(result.note).toContain("no MCP server");
  });
});

describe("management MCP server on a build without the domain", () => {
  it("degrades to a clear message instead of throwing", async () => {
    const legacy = await createHarness({ withMcp: false });

    const setup = await legacy.rpc.mcpSetup({ key: GOOD_KEY });
    expect(setup.ok).toBe(false);
    expect(setup.note).toContain("2.3");
    expect(existsSync(legacy.statePath)).toBe(false);
    expect((await legacy.rpc.mcpStatus({})).installed).toBe(false);
    expect(legacy.unavailability.join(" ")).toContain("ctx.mcp.transform");

    await legacy.cleanup();
  });
});
