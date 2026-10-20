# -*- coding: utf-8 -*-
"""生成「最严重超限班次」反事实 A/B 对比 HTML。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, ".cache", "worst_inline.json")
OUT = os.path.join(BASE, "超限班次AB对比.html")

with open(SRC, encoding="utf-8-sig") as f:
    DATA = f.read().strip()

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>超限班次反事实 A/B 对比</title>
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

<h1>超限班次反事实 A/B 对比</h1>
<p class="sub">10-18 00:05 ~ 06:18 · 稳态段 374 分钟 · T3 &gt;130℃ 占 48.4%（历史最严重）</p>

<div class="note ok">
<b>这次模型是真的有贡献</b>。与前两次不同，本次做了恒定水率空白对照，
恒定值最高只能到 52.0%，模型动态调控拿到 56.7%，高出 4.7 个百分点。
详见「四、空白对照」。
</div>

<h2>一、核心指标</h2>

<div class="grid">
  <div class="kpi">
    <div class="k">T3 合格率</div>
    <div class="v" style="color:var(--good)">56.7% <span style="font-size:14px;color:var(--dim)">vs 51.6%</span></div>
    <div class="d">模型接管 / 人工实际操作</div>
  </div>
  <div class="kpi">
    <div class="k">&gt;130℃ 占比</div>
    <div class="v" style="color:var(--good)">43.3% <span style="font-size:14px;color:var(--dim)">vs 48.4%</span></div>
    <div class="d">超限时间减少 5.1 个百分点</div>
  </div>
  <div class="kpi">
    <div class="k">T3 峰值</div>
    <div class="v">141.2 <span style="font-size:14px;color:var(--dim)">vs 146.0</span></div>
    <div class="d">℃，削掉 4.8℃</div>
  </div>
  <div class="kpi">
    <div class="k">模型动作</div>
    <div class="v">8</div>
    <div class="d">加水 5 次 + 降料 3 次</div>
  </div>
</div>

<h2>二、水率控制曲线</h2>

<div class="card">
<div id="c_ratio" class="chart"></div>
<p class="legend" style="color:var(--dim);font-size:12px;text-align:center;margin-top:4px">
虚线=人工实际操作，实线=模型接管｜初值同为 625，之后模型自主调控</p>
</div>

<h2>三、T3 温度曲线</h2>

<div class="card">
<div id="c_t3" class="chart"></div>
<p class="legend" style="color:var(--dim);font-size:12px;text-align:center;margin-top:4px">
虚线=人工实际操作，实线=模型接管｜灰带为合格区间 100~130℃</p>
</div>

<h2>四、空白对照：为什么说模型有贡献</h2>

<div class="card">
<table>
<tr><th>方案</th><th class="num">T3 均值</th><th class="num">合格率</th>
<th class="num">&gt;130</th><th class="num">T3 峰值</th></tr>
<tr><td>恒定水率 600</td><td class="num">130.1</td><td class="num">47.5%</td>
<td class="num">52.5%</td><td class="num">141.2</td></tr>
<tr><td>恒定水率 620</td><td class="num">129.7</td><td class="num">52.0%</td>
<td class="num">48.0%</td><td class="num">141.2</td></tr>
<tr><td>恒定水率 640</td><td class="num">129.4</td><td class="num">52.0%</td>
<td class="num">48.0%</td><td class="num">141.2</td></tr>
<tr><td>恒定水率 660</td><td class="num">129.1</td><td class="num">49.1%</td>
<td class="num">50.9%</td><td class="num">141.2</td></tr>
<tr><td>恒定水率 680</td><td class="num">128.8</td><td class="num">48.5%</td>
<td class="num">51.5%</td><td class="num">147.6</td></tr>
<tr><td>恒定水率 690</td><td class="num">128.6</td><td class="num">48.5%</td>
<td class="num">51.5%</td><td class="num">152.3</td></tr>
<tr><td>人工实际操作</td><td class="num">129.5</td><td class="num">51.6%</td>
<td class="num">48.4%</td><td class="num">146.0</td></tr>
<tr><td><b>模型自主调控</b></td><td class="num"><b>128.6</b></td>
<td class="num"><b style="color:var(--good)">56.7%</b></td>
<td class="num"><b>43.3%</b></td><td class="num"><b>141.2</b></td></tr>
</table>
</div>

<div class="note">
<b>反直觉发现：水率加得越多，T3 反而越糟。</b>
恒定 680/690 的 T3 峰值（147.6/152.3）比恒定 620/640（141.2）还高，
加到 720 时峰值达 166.3℃。<br><br>
这是<b>非最小相位</b>的直接体现：加水后前 10 分钟 T3 会先升约 6℃，
稳态降温效应要到 30 分钟后才显现。恒定加水没有「等待」概念，
短期升温不断累积，反而更糟。<br><br>
模型靠「动作后强制等待 35 分钟」的节拍避开这个陷阱——
这是动态调控唯一能战胜恒定值的原因。
</div>

<h2>五、模型的 8 次动作</h2>

<div class="card">
<table>
<tr><th>时刻</th><th>动作</th><th class="num">水率</th><th class="num">给料量</th><th>触发原因</th></tr>
<tr><td>t=60</td><td>提高水率</td><td class="num">625→638</td><td class="num">4.24</td>
<td>T3=125.3 超守护带上限 122</td></tr>
<tr><td>t=110</td><td>提高水率</td><td class="num">638→652</td><td class="num">4.24</td>
<td>T3=125.4 超上限</td></tr>
<tr><td>t=150</td><td>提高水率</td><td class="num">652→667</td><td class="num">4.24</td>
<td>T3=128.3 超上限</td></tr>
<tr><td>t=190</td><td>提高水率</td><td class="num">667→676</td><td class="num">4.24</td>
<td>T3=124.2 超上限</td></tr>
<tr><td>t=230</td><td>提高水率</td><td class="num">676→690</td><td class="num">4.24</td>
<td>T3=126.5 超上限，水率触顶</td></tr>
<tr><td>t=270</td><td>减少给料</td><td class="num">690</td><td class="num">4.24→4.04</td>
<td>水率已到操作上限，改用给料量</td></tr>
<tr><td>t=310</td><td>减少给料</td><td class="num">690</td><td class="num">4.04→3.84</td>
<td>T3=136.7，水率无空间</td></tr>
<tr><td>t=350</td><td>减少给料</td><td class="num">690</td><td class="num">3.84→3.64</td>
<td>T3=134.0，水率无空间</td></tr>
</table>
<p style="color:var(--dim);font-size:12px;margin:6px 0 0">
动作方向全部正确：先加水（水率优先），水率触顶后才降料。
</p>
</div>

<h2>六、诚实的局限</h2>

<ul>
<li><b>仍是模型内自证</b>。T3 由响应核 + 共同扰动推演，
若响应核有偏，结论就有偏。响应核仅 12 个阶跃样本支撑。</li>
<li><b>只验证了 1 个班次</b>。历史上有 3 个班次 T3&gt;130 占 30% 以上，
本次只跑了最严重的那个。</li>
<li><b>扰动独立性有瑕</b>。共同扰动 <code>d[t]</code> 由人工水率算出，
操作员「看温度调水」的行为混在其中，无法定量拆分。</li>
<li><b>给料量的效果未建模</b>。仿真中降料不影响 T3，
所以后 3 次降料动作的降温效果是未知的。</li>
</ul>

<p class="foot">
数据来源：<code>dbName_db101-*.zip</code>（10-12~10-19 历史数据）的 10-18 00:05 稳态段。
模型为既有版本，响应核 12 个阶跃事件，未重新辨识。
反事实方法：共同扰动法，双方面对同一原料/环境扰动，仅替换水率与给料量操作序列。
</p>

</div>
<script>
var D = __DATA__;

function mkOpt(el, title, nameA, nameB, series, yName, yMin, yMax, markArea){
  echarts.init(document.getElementById(el)).setOption({
    textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif'},
    title:{text:title, left:'center', top:4, textStyle:{fontSize:14, fontWeight:500}},
    tooltip:{trigger:'axis'},
    legend:{top:30, data:[nameA, nameB], itemWidth:18, textStyle:{fontSize:12}},
    grid:{left:64, right:28, top:64, bottom:52},
    xAxis:{type:'category', data:D.t, name:'稳态段分钟', nameTextStyle:{fontSize:11}},
    yAxis:{type:'value', name:yName, min:yMin, max:yMax, nameTextStyle:{fontSize:11}},
    series:series
  });
}

mkOpt('c_ratio', '水率控制曲线', '人工实际操作', '模型接管', [
  {name:'人工实际操作', type:'line', data:D.ratio_act, symbol:'none',
   lineStyle:{width:1.6, type:'dashed'}, itemStyle:{color:'#f59e0b'}},
  {name:'模型接管', type:'line', data:D.ratio_sim, symbol:'none',
   lineStyle:{width:2.8}, itemStyle:{color:'#34d399'}}
], '水率 L/t', 600, 710);

mkOpt('c_t3', 'L3 温度曲线', '人工实际操作', '模型接管', [
  {name:'人工实际操作', type:'line', data:D.t3_act, symbol:'none',
   lineStyle:{width:1.6, type:'dashed'}, itemStyle:{color:'#f59e0b'}},
  {name:'模型接管', type:'line', data:D.t3_sim, symbol:'none',
   lineStyle:{width:2.8}, itemStyle:{color:'#34d399'},
   markArea:{silent:true, itemStyle:{opacity:.08},
     data:[[{yAxis:100, name:'合格区间'}, {yAxis:130}]]},
   markLine:{symbol:'none', data:[
     {yAxis:130, label:{formatter:'上限130', position:'insideEndTop', fontSize:11}},
     {yAxis:100, label:{formatter:'下限100', position:'insideEndBottom', fontSize:11}}
   ]}}
], 'T3 (℃)', 100, 150);

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
