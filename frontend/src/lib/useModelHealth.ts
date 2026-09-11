import { useEffect, useState } from "react";
import { API_BASE, getToken } from "../api/client";
import type { ModelHealth } from "../api/types";

function healthRows(value: unknown): ModelHealth[] {
  if (Array.isArray(value)) return value as ModelHealth[];
  if (!value || typeof value !== "object") return [];
  const body = value as Record<string, unknown>;
  for (const key of ["models", "snapshot", "health"]) {
    if (Array.isArray(body[key])) return body[key] as ModelHealth[];
  }
  return typeof body.model_id === "string" ? [body as unknown as ModelHealth] : [];
}

export function useModelHealth(modelId?: string): Record<string, ModelHealth> {
  const [health, setHealth] = useState<Record<string, ModelHealth>>({});

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    let active = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const apply = (payload: unknown) => {
      const rows = healthRows(payload);
      if (!rows.length || !active) return;
      setHealth((current) => {
        const next = { ...current };
        for (const row of rows) {
          if (row.model_id && (!modelId || row.model_id === modelId)) {
            next[row.model_id] = row;
          }
        }
        return next;
      });
    };

    const connect = async () => {
      controller = new AbortController();
      try {
        const response = await fetch(`${API_BASE}/api/models/health/stream`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (active) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const data = frame
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (data) {
              try { apply(JSON.parse(data)); } catch { /* ignore malformed events */ }
            }
          }
        }
      } catch {
        // A brief reconnect keeps the page live across deploys and network changes.
      } finally {
        if (active) retry = setTimeout(connect, 2000);
      }
    };

    void connect();
    return () => {
      active = false;
      controller?.abort();
      if (retry) clearTimeout(retry);
    };
  }, [modelId]);

  return health;
}
