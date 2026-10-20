# -*- coding: utf-8 -*-
"""生成「水流量 / 生石灰流量 控制曲线对比」HTML。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, ".cache", "flow_lime_cmp.json")
OUT = os.path.join(BASE, "流量控制曲线对比.html")

with open(SRC, encoding="utf-8-sig") as f:
    DATA = f.read().strip()

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>水流量 / 生石灰流量 控制曲线对比</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>
:root{
  --bg:#0f1216;--panel:#161b22;--panel2:#1c2129;--line:#30363d;
  --text:#e6edf3;--dim:#8b949e;--accent:#58a6ff;
  --good:#3fb950;--warn:#d29922;--bad:#f85149;--mdl:#34d399;
}
@media (prefers-color-scheme: light){
  :root{
    --bg:#fff;--panel:#f6f8fa;--panel2:#eaeef2;--line:#d0d7de;
    --text:#1f2328;--dim:#656d76;--accent:#0969da;
    --good:#1a7f37;--warn:#9a6700;--bad:#cf222e;--mdl:#0f7b52;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  line-height:1.75;font-size:15px}
.wrap{max-width:1120px;margin:0 auto;padding:32px 24px 80px}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:19px;margin:38px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.sub{color:var(--dim);font-size:14px;margin:0 0 26px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:16px 0}
.chart{width:100%;height:400px}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500;font-size:13px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.note{border-left:3px solid var(--warn);background:var(--panel);padding:12px 16px;
  margin:16px 0;border-radius:0 8px 8px 0;font-size:14px}
.note.ok{border-left-color:var(--good)}
.note.bad{border-left-color:var(--bad)}
.note b{color:var(--text)}
.shiftnav{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.shiftnav button{background:var(--panel2);color:var(--text);border:1px solid var(--line);
  padding:7px 14px;border-radius:6px;cursor:pointer;font-size:13px;font-family:inherit}
.shiftnav button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.legend{color:var(--dim);font-size:12px;text-align:center;margin-top:4px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi .v{font-size:23px;font-weight:600;margin:4px 0}
.kpi .k{color:var(--dim);font-size:13px}
.kpi .d{font-size:12px;color:var(--dim);margin-top:6px}
ul{margin:12px 0;padding-left:22px}
li{margin:6px 0}
code{background:var(--panel2);padding:2px 6px;border-radius:4px;
  font-family:ui-monospace,Consolas,monospace;font-size:13px}
.foot{color:var(--dim);font-size:13px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}
</style>
</head>
<body>
<div class="wrap">

<h1>水流量 / 生石灰流量 控制曲线对比</h1>
<p class="sub">模型输出 vs 人工操作 · 6 个班次的稳态段</p>

<div class="note">
<b>两条曲线的性质完全不同</b>，需要分开看：<br><br>
· <b>生石灰流量</b>：模型直接设定，是主动控制的结果（平坦是设计意图）<br>
· <b>水流量</b>：模型<b>不直接控制</b>，而是由 <code>水率 × 给料量</code> 推算出来的
</div>

<h2>一、生石灰流量（模型直接控制）</h2>

<div class="grid">
  <div class="kpi">
    <div class="k">给料量 std</div>
    <div class="v">0.02 <span style="font-size:14px;color:var(--dim)">vs 0.31</span></div>
    <div class="d">模型几乎不调</div>
  </div>
  <div class="kpi">
    <div class="k">降料动作</div>
    <div class="v">2 <span style="font-size:14px;color:var(--dim)">次 / 33.4h</span></div>
    <div class="d">5/6 班次完全不降</div>
  </div>
  <div class="kpi">
    <div class="k">均值</div>
    <div class="v">3.92 <span style="font-size:14px;color:var(--dim)">vs 3.84</span></div>
    <div class="d">t/h，与人工持平</div>
  </div>
  <div class="kpi">
    <div class="k">最低点</div>
    <div class="v">3.12</div>
    <div class="d">下限 3.0 未触及</div>
  </div>
</div>

<h2>二、水流量（推算值，非直接控制）</h2>

<div class="note bad">
<b>水流量这条曲线不要当真</b>。实测「水流量」与「水率 × 给料量」的
相关系数只有 <b>+0.672</b>；给料量变化 28% 时，实测水流量仅变化 0.1%。
现场存在<b>独立的水流量控制回路</b>，水流量不由这两个量决定。
<br><br>
所以图上模型水流量的形状，是 <code>水率 × 给料量</code> 推算的结果，
<b>不是现场会实际发生的值</b>。
</div>

<div class="grid">
  <div class="kpi">
    <div class="k">水流量 std</div>
    <div class="v">28 <span style="font-size:14px;color:var(--dim)">vs 27</span></div>
    <div class="d">单班次内，双方持平</div>
  </div>
  <div class="kpi">
    <div class="k">均值</div>
    <div class="v">2528 <span style="font-size:14px;color:var(--dim)">vs 2401</span></div>
    <div class="d">模型高 5%，因水率优先抬高</div>
  </div>
</div>

<h2>三、逐班次曲线</h2>

<div class="shiftnav" id="nav"></div>
<div class="card">
<div id="c_lime" class="chart"></div>
<p class="legend">生石灰流量 t/h｜实线=模型，虚线=人工</p>
</div>
<div class="card">
<div id="c_water" class="chart"></div>
<p class="legend">水流量 L/h｜实线=模型（推算），虚线=人工（实测）</p>
</div>

<h2>四、逐班次数据</h2>

<div class="card">
<table>
<tr><th>班次</th><th>时长</th>
<th class="num">给料std(人)</th><th class="num">给料std(模)</th>
<th class="num">水std(人)</th><th class="num">水std(模)</th>
<th class="num">水均值(人)</th><th class="num">水均值(模)</th></tr>
__ROWS__
</table>
</div>

<h2>五、关于 std 的口径（重要）</h2>

<div class="note">
水流量 std 有两个口径，差别很大，别混用：<br><br>
· <b>单班次内</b>：13 ~ 63 L/h（本表用的就是这个）<br>
· <b>跨班次合并</b>：184.3 L/h<br><br>
后者大，是因为各班次均值本身就不同（2540 / 2135 / 2524 / 2521 / 2514 / 2176），
差异来自原料批次，不是单班次内波动大。两个口径都对。
</div>

<h2>六、结论</h2>

<ul>
<li><b>生石灰流量</b>：模型稳定，几乎不动。这是"水率优先"的直接结果——
手段换成加水后，给料量从 9 次降载降到 2 次。</li>
<li><b>水流量</b>：模型均值比人工高 5%（2528 vs 2401），因为水率优先策略
把水率从 630 抬到了 646。但这条曲线是推算的，实际效果取决于
现场水流量能否被水率带动。</li>
<li><b>待确认</b>：水流量设定值测点（<code>5#_XSH_SLLSDZ</code>）能否直接写入。
若能，应绕开"水率"直接输出水流量，那才是响应最快的通道。</li>
</ul>

<p class="foot">
数据来源：2026-10-12 ~ 10-19，6 个班次的稳态段，33.4 小时。
人工为历史实测值，模型为反事实仿真输出（共同扰动法）。
</p>

</div>
<script>
var D = __DATA__;
var charts = D.charts, cur = 0;
var nav = document.getElementById('nav');
charts.forEach(function(c, i){
  var b = document.createElement('button');
  b.textContent = c.label;
  if(i === 0) b.className = 'on';
  b.onclick = function(){
    cur = i;
    Array.prototype.forEach.call(nav.children, function(x){x.className='';});
    b.className = 'on'; draw();
  };
  nav.appendChild(b);
});

function base(title, unit, ymin, ymax){
  return {
    textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif'},
    title:{text:title, left:'center', top:4, textStyle:{fontSize:14, fontWeight:500}},
    tooltip:{trigger:'axis'},
    legend:{top:30, data:['人工','模型'], itemWidth:18, textStyle:{fontSize:12}},
    grid:{left:70, right:28, top:64, bottom:46},
    xAxis:{type:'category', data:[], name:'稳态段分钟', nameTextStyle:{fontSize:11}},
    yAxis:{type:'value', name:unit, min:ymin, max:ymax, nameTextStyle:{fontSize:11}},
    series:[]
  };
}

var cL, cW;
function draw(){
  var c = charts[cur];
  var oL = base('生石灰流量 · ' + c.label, 't/h', 2.5, 5.5);
  oL.xAxis.data = c.t;
  oL.series = [
    {name:'人工', type:'line', data:c.l_act, symbol:'none', lineStyle:{width:1.6, type:'dashed'}},
    {name:'模型', type:'line', data:c.l_sim, symbol:'none', lineStyle:{width:2.6, color:'#34d399'}}
  ];
  var oW = base('水流量 · ' + c.label, 'L/h', 1800, 3000);
  oW.xAxis.data = c.t;
  oW.series = [
    {name:'人工', type:'line', data:c.w_act, symbol:'none', lineStyle:{width:1.6, type:'dashed'}},
    {name:'模型', type:'line', data:c.w_sim, symbol:'none', lineStyle:{width:2.6, color:'#34d399'}}
  ];
  if(!cL) cL = echarts.init(document.getElementById('c_lime'));
  if(!cW) cW = echarts.init(document.getElementById('c_water'));
  cL.setOption(oL, true);
  cW.setOption(oW, true);
}
draw();
window.addEventListener('resize', function(){
  if(cL) cL.resize();
  if(cW) cW.resize();
});
</script>
</body>
</html>
"""

rows = []
for r in json.loads(DATA)["rows"]:
    rows.append(
        "<tr><td>%s</td><td>%d min</td>"
        "<td class=\"num\">%.2f</td><td class=\"num\">%.2f</td>"
        "<td class=\"num\">%.0f</td><td class=\"num\">%.0f</td>"
        "<td class=\"num\">%.0f</td><td class=\"num\">%.0f</td></tr>" % (
            r["label"], r["dur"],
            r["l_act"]["std"], r["l_sim"]["std"],
            r["w_act"]["std"], r["w_sim"]["std"],
            r["w_act"]["mean"], r["w_sim"]["mean"]))

HTML = HTML.replace("__ROWS__", "\n".join(rows)).replace("__DATA__", DATA)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print("生成: %s (%.1f KB)" % (OUT, len(HTML) / 1024))
