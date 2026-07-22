// 控制台 API 客户端。所有控制指令经后端写 Redis 中转，前端不接触交易所。
const BASE = import.meta.env.VITE_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export interface Status {
  equity: number;
  today_pnl: number;
  state: "RUNNING" | "PAUSED" | "HALTED";
  positions: unknown[];
}

export const api = {
  status: () => get<Status>("/status"),
  symbols: () => get("/symbols"),
  strategies: () => get("/strategies"),
  trades: (limit = 100) => get(`/trades?limit=${limit}`),
  tradeDetail: (id: string) => get(`/trades/${id}`),
  cognitive: () => get("/cognitive"),
  health: () => get("/health"),
  // 控制（二次确认在 UI 层）
  pause: () => post("/control/pause"),
  resume: () => post("/control/resume"),
  flat: () => post("/control/flat"),
};
