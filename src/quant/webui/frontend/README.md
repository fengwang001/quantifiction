# Quantifiction 控制台（前端）

React + Vite + TanStack Query + Recharts。经 Tailscale 访问，不暴露公网。

```bash
npm install
npm run dev        # http://127.0.0.1:5173
```

## 页面进度
- [x] Dashboard + 刹车（最小控制页，实盘前必需）
- [ ] Symbols / Strategies / Trades（含 LLM reasoning 展开）
- [ ] Cognitive / Health / Config（Monaco 编辑）

控制指令经后端写 Redis 中转，前端不接触交易所（CT-WEB-3）。
