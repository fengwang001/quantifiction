"""每日收益日历页面 HTML（迭代110：日历格式展示每日收益，可点击看详情）。"""

CALENDAR_HTML = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>每日收益 · Quantifiction</title>
<style>
:root{--bg:#0f141b;--bg2:#0b0f15;--card:#171e27;--card2:#1e2732;--bd:#28323f;--bd2:#323e4d;
--fg:#e9edf2;--mut:#8b96a5;--faint:#5b6675;--brass:#d4a54a;--up:#3fb98a;--dn:#e0695a;
--up-bg:rgba(63,185,138,.13);--dn-bg:rgba(224,105,90,.13);
--mono:"SF Mono","JetBrains Mono",ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box;margin:0}body{background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
.mono{font-variant-numeric:tabular-nums;font-family:var(--mono)}
.appbar{position:sticky;top:0;z-index:10;background:rgba(11,15,21,.85);backdrop-filter:blur(10px);
border-bottom:1px solid var(--bd);padding:12px 22px;display:flex;align-items:center;gap:14px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px}
.logo{width:26px;height:26px;border-radius:7px;display:grid;place-items:center;
background:linear-gradient(135deg,var(--brass),#9a7c3a);color:#12161d;font-weight:800}
a.back{margin-left:auto;color:var(--mut);text-decoration:none;font-size:13px;border:1px solid var(--bd2);
border-radius:8px;padding:7px 14px}a.back:hover{border-color:var(--brass);color:var(--brass)}
.wrap{max-width:1080px;margin:0 auto;padding:24px 22px 60px}
.calhead{display:flex;align-items:center;gap:16px;margin-bottom:20px}
.calhead h1{font-size:22px}
.navbtn{background:var(--card2);border:1px solid var(--bd2);color:var(--fg);border-radius:8px;
width:34px;height:34px;cursor:pointer;font-size:16px}.navbtn:hover{border-color:var(--brass);color:var(--brass)}
.mtitle{font-size:18px;font-weight:600;min-width:150px;text-align:center;font-family:var(--mono)}
.sumbar{margin-left:auto;display:flex;gap:20px;font-size:13px;color:var(--mut)}
.sumbar b{font-family:var(--mono)}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:8px}
.dow{text-align:center;color:var(--faint);font-size:12px;font-weight:600;padding:4px 0}
.cell{aspect-ratio:1/.82;background:var(--card);border:1px solid var(--bd);border-radius:10px;
padding:8px 9px;display:flex;flex-direction:column;position:relative;transition:.12s}
.cell.empty{background:transparent;border:none}
.cell.has{cursor:pointer}.cell.has:hover{border-color:var(--brass);transform:translateY(-1px)}
.cell .d{font-size:12px;color:var(--mut);font-family:var(--mono)}
.cell.today .d{color:var(--brass);font-weight:700}
.cell .pnl{margin-top:auto;font-size:16px;font-weight:700;font-family:var(--mono);letter-spacing:-.02em}
.cell .sub{font-size:10px;color:var(--faint);font-family:var(--mono)}
.cell.pos{background:linear-gradient(180deg,var(--up-bg),transparent)}
.cell.neg{background:linear-gradient(180deg,var(--dn-bg),transparent)}
.up{color:var(--up)}.dn{color:var(--dn)}.mut{color:var(--mut)}
#modal{display:none;position:fixed;inset:0;background:rgba(5,8,12,.72);z-index:50;align-items:center;justify-content:center}
#modal.on{display:flex}
#mbox{background:var(--card);border:1px solid var(--bd2);border-radius:14px;width:min(880px,94vw);
max-height:88vh;display:flex;flex-direction:column;padding:20px}
#mhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
#mhead b{font-size:17px}#mclose{background:none;border:none;color:var(--mut);font-size:24px;cursor:pointer}
.chips{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.chip{background:var(--card2);border:1px solid var(--bd);border-radius:8px;padding:8px 12px;font-size:12px}
.chip .v{font-size:16px;font-weight:700;font-family:var(--mono)}
table{width:100%;border-collapse:collapse}
th,td{padding:7px 9px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--bd);font-family:var(--mono)}
th{color:var(--mut);background:var(--bg2);font-size:11px;position:sticky;top:0}
td:first-child,th:first-child{text-align:left;font-family:inherit}
#mtrades{overflow:auto;border:1px solid var(--bd);border-radius:10px}
.tag{padding:1px 6px;border-radius:5px;font-size:11px}.tag.l{background:var(--up-bg);color:var(--up)}.tag.s{background:var(--dn-bg);color:var(--dn)}
</style></head><body>
<div class=appbar>
  <div class=brand><span class=logo>Q</span>每日收益日历</div>
  <a href=/ class=back>&larr; 返回主看板</a>
</div>
<div class=wrap>
  <div class=calhead>
    <button class=navbtn onclick=nav(-1)>&lsaquo;</button>
    <div class=mtitle id=mtitle>&mdash;</div>
    <button class=navbtn onclick=nav(1)>&rsaquo;</button>
    <div class=sumbar id=sumbar></div>
  </div>
  <div class=grid id=dow></div>
  <div class=grid id=cal style=margin-top:8px></div>
</div>
<div id=modal onclick="if(event.target.id=='modal')close_()">
  <div id=mbox>
    <div id=mhead><b id=mtitle2>&mdash;</b><button id=mclose onclick=close_()>&times;</button></div>
    <div class=chips id=mchips></div>
    <div style=font-size:12px;color:var(--mut);margin-bottom:6px>当日全部成交</div>
    <div id=mtrades></div>
  </div>
</div>
<script>
const $=s=>document.getElementById(s);
let DAYS={},cur=new Date();cur.setDate(1);
function f(n,d=2){return (n>=0?'+':'')+Number(n).toFixed(d)}
function hm(ms){const t=new Date(ms);const p=x=>String(x).padStart(2,'0');return p(t.getHours())+':'+p(t.getMinutes())}
async function load(){const r=await(await fetch('/api/daily')).json();DAYS=r.days||{};render();}
function render(){
  const y=cur.getFullYear(),m=cur.getMonth();
  $('mtitle').textContent=y+' 年 '+(m+1)+' 月';
  $('dow').innerHTML=['日','一','二','三','四','五','六'].map(d=>'<div class=dow>'+d+'</div>').join('');
  const first=new Date(y,m,1).getDay(),ndays=new Date(y,m+1,0).getDate();
  const today=new Date();const tstr=today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');
  let html='',msum=0,mtr=0;
  for(let i=0;i<first;i++)html+='<div class="cell empty"></div>';
  for(let d=1;d<=ndays;d++){
    const ds=y+'-'+String(m+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');
    const e=DAYS[ds];
    if(e){msum+=e.net;mtr+=e.trades;
      const cls=e.net>=0?'pos':'neg',c=e.net>=0?'up':'dn';
      html+='<div class="cell has '+cls+' '+(ds===tstr?'today':'')+'" onclick="detail(\\''+ds+'\\')">'+
        '<div class=d>'+d+'</div><div class=pnl><span class='+c+'>'+f(e.net)+'</span></div>'+
        '<div class=sub>'+e.trades+'笔 · '+e.win_rate+'%胜</div></div>';
    }else{
      html+='<div class="cell '+(ds===tstr?'today':'')+'"><div class=d>'+d+'</div>'+
        '<div class=pnl style="color:var(--faint);font-size:12px">&mdash;</div></div>';
    }
  }
  $('cal').innerHTML=html;
  const sc=msum>=0?'up':'dn';
  $('sumbar').innerHTML='本月 <b class='+sc+'>'+f(msum)+' USDT</b> · <b>'+mtr+'</b>笔';
}
function nav(dir){cur.setMonth(cur.getMonth()+dir);render();}
async function detail(ds){
  $('modal').classList.add('on');$('mtitle2').textContent=ds+' 收益详情';
  $('mchips').innerHTML='<span class=chip>加载中…</span>';$('mtrades').innerHTML='';
  const d=await(await fetch('/api/daily/detail?date='+ds)).json();
  const nc=d.net>=0?'up':'dn';
  let chips='<div class=chip>当日净利<div class="v '+nc+'">'+f(d.net)+'</div></div><div class=chip>成交<div class=v>'+d.count+'笔</div></div>';
  for(const k in (d.by_inst||{})){const v=d.by_inst[k];const c=v.net>=0?'up':'dn';
    chips+='<div class=chip>'+k+'<div class="v '+c+'">'+f(v.net)+'</div><span class=mut style="font-size:10px">'+v.trades+'笔'+v.wins+'胜</span></div>';}
  $('mchips').innerHTML=chips;
  const rows=(d.trades||[]).map(function(t){return '<tr><td class=mut>'+t.inst+'</td><td>'+t.strategy+'</td>'+
    '<td><span class="tag '+(t.dir=='多'?'l':'s')+'">'+t.dir+'</span></td><td>'+hm(t.buy_ms||t.open_ms)+'</td>'+
    '<td>'+hm(t.sell_ms||t.ts)+'</td><td class="'+(t.net_usd>=0?'up':'dn')+'" style="font-weight:700">'+f(t.net_usd,3)+'</td>'+
    '<td class=mut>'+(t.reason=='tp'?'止盈':t.reason=='sl'?'止损':t.reason=='trail'?'追踪':'超时')+'</td></tr>';}).join('');
  $('mtrades').innerHTML='<table><thead><tr><th>标的</th><th>策略</th><th>方向</th><th>开仓</th><th>平仓</th><th>净USDT</th><th>出场</th></tr></thead><tbody>'+(rows||'<tr><td colspan=7 class=mut style="text-align:center;padding:16px">无成交</td></tr>')+'</tbody></table>';
}
function close_(){$('modal').classList.remove('on');}
load();setInterval(load,15000);
</script></body></html>"""
