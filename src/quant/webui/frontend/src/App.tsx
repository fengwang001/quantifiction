import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip,
} from "recharts";
import { api, Status } from "./api";

// 最小控制页（Dashboard + 刹车）——宪法要求实盘前不可砍。
// 其余页面（Symbols/Strategies/Trades/Cognitive/Config）为后续增量。
function Dashboard() {
  const { data, isError } = useQuery<Status>({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 3000,
  });
  const [busy, setBusy] = useState(false);

  async function confirmFlat() {
    if (!window.confirm("确认立即全平所有仓位？")) return;
    setBusy(true);
    try { await api.flat(); } finally { setBusy(false); }
  }

  if (isError) return <div style={{ padding: 24 }}>无法连接后端（检查 Tailscale）</div>;

  return (
    <div style={{ padding: 24, fontFamily: "system-ui" }}>
      <h1>Quantifiction 控制台</h1>
      <section style={{ display: "flex", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 28, fontWeight: 700 }}>
            权益 ${data?.equity ?? "—"}
          </div>
          <div>今日 PnL: {data?.today_pnl ?? "—"} · 状态: {data?.state ?? "—"}</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 12 }}>
          <button onClick={() => api.pause()} disabled={busy}>⏸ 暂停</button>
          <button onClick={() => api.resume()} disabled={busy}>▶ 恢复</button>
          <button onClick={confirmFlat} disabled={busy}
                  style={{ background: "#c0392b", color: "#fff", fontWeight: 700 }}>
            🔴 全平
          </button>
        </div>
      </section>

      <EquityChart />
      <p style={{ color: "#888", marginTop: 32 }}>
        风控参数（地板/杠杆/单笔风险）不可在此修改，仅可改配置文件 + 重启（宪法 III）。
      </p>
    </div>
  );
}

// 权益曲线，含 $900/$850 地板参考线
function EquityChart() {
  const { data } = useQuery({
    queryKey: ["equityCurve"],
    queryFn: () => api.status().then((s) => [{ t: Date.now(), equity: s.equity }]),
    refetchInterval: 5000,
  });
  return (
    <div style={{ height: 260, marginTop: 24 }}>
      <ResponsiveContainer>
        <LineChart data={data ?? []}>
          <XAxis dataKey="t" hide />
          <YAxis domain={[800, "auto"]} />
          <Tooltip />
          <ReferenceLine y={900} stroke="#e67e22" label="软地板" />
          <ReferenceLine y={850} stroke="#c0392b" label="硬地板" />
          <Line type="monotone" dataKey="equity" stroke="#2980b9" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function App() {
  return <Dashboard />;
}
