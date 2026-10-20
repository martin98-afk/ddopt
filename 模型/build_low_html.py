# -*- coding: utf-8 -*-
"""生成偏低班次 AB 对比 HTML（验证减水方向）。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, ".cache", "low_inline.json")
OUT = os.path.join(BASE, "偏低班次AB对比.html")

with open(SRC, encoding="utf-8-sig") as f:
    DATA = f.read().strip()

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>偏低班次反事实 A/B 对比（减水方向）</title>
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
.chart{width:100%;height:320px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi .v{font-size:24px;font-weight:600;margin:4px 0}
.kpi .k{color:var(--dim);font-size:13px}
.kpi .d{font-size:12px;color:var(--dim);margin-top:6px}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500;font-size:13px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.note{border-left:3px solid var(--warn);background:var(--panel);padding:12px 16px;
  margin:16px 0;border-radius:0 8px 8px 0;font-size:14px}
.note.ok{border-left-color:var(--good)}
.note.bad{border-left-color:var(--bad)}
.note b{color:var(--text)}
ul{margin:12px 0;padding-left:22px}
li{margin:6px 0}
code{background:var(--panel2);padding:2px 6px;border-radius:4px;
  font-family:ui-monospace,Consolas,monospace;font-size:13px}
.foot{color:var(--dim);font-size:13px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}
</style>
</head>
<body>
<div class="wrap">

<h1>偏低班次反事实 A/B 对比</h1>
<p class="sub">10-16 00:04 ~ 07:04 · 稳态段 420 分钟 · T3 &lt;110℃ 占 64.3%（验证减水方向）</p>

<div class="note ok">
<b>减水方向验证通过</b>：6 次动作全是<b>降低水率</b>，无一次误加水，方向判断正确。
这是对「T3 超限 → 加水」方向的必要补充——此前只验证了半个模型。
</div>

<h2>一、核心指标</h2>

<div class="grid">
  <div class="kpi">
    <div class="k">减水动作</div>
    <div class="v" style="color:var(--good)">6 <span style="font-size:14px;color:var(--dim)">/ 加水 0</span></div>
    <div class="d">方向全部正确</div>
  </div>
  <div class="kpi">
    <div class="k">T3 合格率</div>
    <div class="v" style="color:var(--bad)">97.9% <span style="font-size:14px;color:var(--dim)">vs 100.0%</span></div>
    <div class="d">模型接管 / 人工实际操作</div>
  </div>
  <div class="kpi">
    <div class="k">T3 &lt;100 占比</div>
    <div class="v" style="color:var(--bad)">2.1% <span style="font-size:14px;color:var(--dim)">vs 0.0%</span></div>
    <div class="d">9 分钟跌破下限</div>
  </div>
  <div class="kpi">
    <div class="k">水率范围</div>
    <div class="v">594~640</div>
    <div class="d">人工 630~640</div>
  </div>
</div>

<h2>二、水率控制曲线</h2>

<div class="card">
<div id="c_ratio" class="chart"></div>
<p class="legend" style="color:var(--dim);font-size:12px;text-align:center;margin-top:4px">
虚线=人工实际操作，实线=模型接管｜模型一路减到 594，人工始终 630~640</p>
</div>

<h2>三、T3 温度曲线</h2>

<div class="card">
<div id="c_t3" class="chart"></div>
<p class="legend" style="color:var(--dim);font-size:12px;text-align:center;margin-top:4px">
虚线=人工实际操作，实线=模型接管｜灰带为合格区间 100~130℃</p>
</div>

<h2>四、恒定水率对照：为什么模型反而更差</h2>

<div class="card">
<table>
<tr><th>方案</th><th class="num">T3 均值</th><th class="num">合格率</th>
<th class="num">&lt;100</th><th class="num">&lt;110</th></tr>
<tr><td>恒定水率 580</td><td class="num">109.5</td><td class="num">96.9%</td>
<td class="num">3.1%</td><td class="num">62.7%</td></tr>
<tr><td>恒定水率 600</td><td class="num">109.3</td><td class="num">97.1%</td>
<td class="num">2.9%</td><td class="num">62.9%</td></tr>
<tr><td>恒定水率 620</td><td class="num">109.0</td><td class="num">99.0%</td>
<td class="num">1.0%</td><td class="num">63.7%</td></tr>
<tr><td>恒定水率 630</td><td class="num">108.8</td><td class="num" style="color:var(--good)">100.0%</td>
<td class="num">0.0%</td><td class="num">64.8%</td></tr>
<tr><td>恒定水率 640</td><td class="num">108.7</td><td class="num" style="color:var(--good)">100.0%</td>
<td class="num">0.0%</td><td class="num">68.6%</td></tr>
<tr><td>人工实际操作</td><td class="num">108.8</td><td class="num" style="color:var(--good)">100.0%</td>
<td class="num">0.0%</td><td class="num">64.3%</td></tr>
<tr><td><b>模型自主调控</b></td><td class="num"><b>109.1</b></td>
<td class="num"><b style="color:var(--bad)">97.9%</b></td>
<td class="num"><b>2.1%</b></td><td class="num"><b>58.3%</b></td></tr>
</table>
</div>

<div class="note bad">
<b>根因：守护带下限 110 比这个班次的最优工作点还高。</b><br><br>
这个班次 T3 均值只有 108.8，<b>本来就应该在 110 以下运行</b>。
恒定 630/640 的合格率是 100%，而模型认为「T3&lt;110 = 偏低 = 该减水」，
一路减到 594，把 T3 推到 100℃ 以下 9 分钟。<br><br>
水率越低反而越糟：580 时合格率掉到 96.9%。
模型在纠一个<b>不该纠的偏差</b>。<br><br>
这是<b>参数与工况不匹配</b>，不是方向错误——方向判断（减水）本身是对的。
</div>

<h2>五、模型的 6 次减水</h2>

<div class="card">
<table>
<tr><th>时刻</th><th>动作</th><th class="num">水率</th><th>触发原因</th></tr>
<tr><td>t=10</td><td>降低水率</td><td class="num">640→636</td><td>T3=109.0 低于下限 110</td></tr>
<tr><td>t=220</td><td>降低水率</td><td class="num">636→634</td><td>T3=109.5 低于下限</td></tr>
<tr><td>t=260</td><td>降低水率</td><td class="num">634→619</td><td>T3=105.8 低于下限</td></tr>
<tr><td>t=330</td><td>降低水率</td><td class="num">619→606</td><td>T3=106.7 低于下限</td></tr>
<tr><td>t=370</td><td>降低水率</td><td class="num">606→603</td><td>T3=109.3 低于下限</td></tr>
<tr><td>t=410</td><td>降低水率</td><td class="num">603→594</td><td>T3=107.8 低于下限</td></tr>
</table>
<p style="color:var(--dim);font-size:12px;margin:6px 0 0">
每次都是 T3 &lt; 110 触发，方向一致，但在这个班次上属于过度干预。
</p>
</div>

<h2>六、双向验证总结</h2>

<div class="card">
<table>
<tr><th>方向</th><th>验证班次</th><th>方向判断</th><th>控制效果</th></tr>
<tr><td>T3 超限 → 加水</td><td>10-18 00:05（T3&gt;130 占 48.4%）</td>
<td><span style="color:var(--good)">正确</span></td>
<td><b style="color:var(--good)">优于人工 4.7pp</b></td></tr>
<tr><td>T3 偏低 → 减水</td><td>10-16 00:04（T3&lt;110 占 64.3%）</td>
<td><span style="color:var(--good)">正确</span></td>
<td><b style="color:var(--bad)">劣于人工 2.1pp</b>（参数失配）</td></tr>
</table>
</div>

<ul>
<li><b>控制律本身没问题</b>：两个方向的方向判断都正确。</li>
<li><b>问题在守护带一刀切</b>：各班次 T3 最优工作点从 108.8 到 129.5，
跨度 20℃，固定 110~122 必然有的班次适配、有的不适配。</li>
<li><b>改进方向</b>：下限下调至 105，或改为按班次自适应。</li>
</ul>

<p class="foot">
数据来源：历史数据 10-16 00:04 稳态段（420 分钟）。
模型为既有版本，响应核 12 个阶跃事件，未重新辨识。
反事实方法：共同扰动法，双方面对同一原料/环境扰动，仅替换水率操作序列。
</p>

</div>
<script>
var D = __DATA__;

function mkOpt(el, title, series, yName, yMin, yMax){
  echarts.init(document.getElementById(el)).setOption({
    textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif'},
    title:{text:title, left:'center', top:4, textStyle:{fontSize:14, fontWeight:500}},
    tooltip:{trigger:'axis'},
    legend:{top:30, data:['人工实际操作','模型接管'], itemWidth:18, textStyle:{fontSize:12}},
    grid:{left:64, right:28, top:64, bottom:52},
    xAxis:{type:'category', data:D.t, name:'稳态段分钟', nameTextStyle:{fontSize:11}},
    yAxis:{type:'value', name:yName, min:yMin, max:yMax, nameTextStyle:{fontSize:11}},
    series:series
  });
}

mkOpt('c_ratio', '水率控制曲线', [
  {name:'人工实际操作', type:'line', data:D.ratio_act, symbol:'none',
   lineStyle:{width:1.8, type:'dashed'}, itemStyle:{color:'#f59e0b'}},
  {name:'模型接管', type:'line', data:D.ratio_sim, symbol:'none',
   lineStyle:{width:2.8}, itemStyle:{color:'#34d399'}}
], '水率 L/t', 580, 660);

mkOpt('c_t3', 'L3 温度曲线', [
  {name:'人工实际操作', type:'line', data:D.t3_act, symbol:'none',
   lineStyle:{width:1.8, type:'dashed'}, itemStyle:{color:'#f59e0b'}},
  {name:'模型接管', type:'line', data:D.t3_sim, symbol:'none',
   lineStyle:{width:2.8}, itemStyle:{color:'#34d399'},
   markArea:{silent:true, itemStyle:{opacity:.08},
     data:[[{yAxis:100, name:'合格区间'}, {yAxis:130}]]},
   markLine:{symbol:'none', data:[
     {yAxis:130, label:{formatter:'上限130', position:'insideEndTop', fontSize:11}},
     {yAxis:100, label:{formatter:'下限100', position:'insideEndBottom', fontSize:11}}
   ]}}
], 'T3 (℃)', 96, 120);

window.addEventListener('resize', function(){
  ['c_ratio','c_t3'].forEach(function(id){
    var inst = echarts.getInstanceByDom(document.getElementById(id));
    if(inst) inst.resize();
  });
});
</script>
</body>
</html>
"""

HTML = HTML.replace("__DATA__", DATA)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print("生成: %s (%.1f KB)" % (OUT, len(HTML) / 1024))
