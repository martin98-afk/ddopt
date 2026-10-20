# -*- coding: utf-8 -*-
"""生成新数据上 模型水率 vs 人工水率 对比曲线 HTML。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, ".cache", "new_ratio_inline.json")
OUT = os.path.join(BASE, "新数据水率对比.html")

with open(SRC, encoding="utf-8-sig") as f:
    DATA = f.read().strip()

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>新数据 · 模型 vs 人工 水率对比</title>
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
.chart{width:100%;height:300px}
.chart.tall{height:420px}
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

<h1>新数据 · 模型 vs 人工 水率对比</h1>
<p class="sub">2026-10-19 08:34 ~ 10-20 08:54 · 2 个生产班次 · 618 生产分钟</p>

<div class="note">
<b>本次为纯验证，未重新辨识模型</b>。响应核仍用旧模型（10-12~10-19 的
12 个阶跃事件辨识结果），新数据完全不参与辨识，只看旧模型在新工况下是否可靠。
</div>

<h2>一、核心指标</h2>

<div class="grid">
  <div class="kpi">
    <div class="k">人工水率 std</div>
    <div class="v">20.74</div>
    <div class="d">均值 636.2，范围 610~690</div>
  </div>
  <div class="kpi">
    <div class="k">模型水率 std</div>
    <div class="v" style="color:var(--mdl)">21.20</div>
    <div class="d">均值 637.3，范围 610~690</div>
  </div>
  <div class="kpi">
    <div class="k">调节次数</div>
    <div class="v">15 <span style="font-size:14px;color:var(--dim)">vs 10</span></div>
    <div class="d">模型 / 人工，仅统计第一班次（模型实际接管段）</div>
  </div>
  <div class="kpi">
    <div class="k">T3 合格率</div>
    <div class="v" style="color:var(--good)">99.1% <span style="font-size:14px;color:var(--dim)">vs 97.6%</span></div>
    <div class="d">模型接管 / 人工实际操作</div>
  </div>
</div>

<h2>二、水率对比曲线（全周期）</h2>

<div class="card">
<div id="c_all" class="chart tall"></div>
<p class="legend" style="color:var(--dim);font-size:12px;text-align:center;margin-top:4px">
虚线=人工实际操作，实线=模型接管｜仅在两个生产班次内有值</p>
</div>

<h2>三、逐班次曲线</h2>

<div class="card">
<div id="c_seg" class="chart"></div>
<p class="legend" style="color:var(--dim);font-size:12px;text-align:center;margin-top:4px">
切换查看单个班次｜下方为 L3 温度，便于对照水率动作与温度响应</p>
</div>

<h2>四、逐班次数据</h2>

<div class="card">
<table>
<tr><th>班次</th><th>时长</th>
<th class="num">人工水率</th><th class="num">人工std</th><th class="num">人工变动</th>
<th class="num">模型水率</th><th class="num">模型std</th><th class="num">模型变动</th></tr>
<tr><td>10-19 16:34 ~ 10-20 02:01</td><td>568 min</td>
<td class="num">636</td><td class="num">21.2</td><td class="num">9</td>
<td class="num">637</td><td class="num">21.2</td><td class="num">15</td></tr>
<tr><td>10-20 03:10 ~ 03:59</td><td>50 min</td>
<td class="num">—</td><td class="num">—</td><td class="num">—</td>
<td class="num">—</td><td class="num">—</td><td class="num">—</td></tr>
</table>
<p style="color:var(--dim);font-size:12px;margin:6px 0 0">
第二个班次仅 50 分钟，且全程料位 ≥7.2m，模型按保护逻辑停止给料，
未进入稳态闭环，故无独立输出。
</p>
</div>

<h2>五、读图要点</h2>

<ul>
<li><b>波动幅度几乎一致</b>（std 21.2 vs 20.7）——模型跟随现场水率，
没有另起一套，说明旧模型在新工况下没有「跑偏」。</li>
<li><b>模型变动 15 次略多于人工 10 次</b>，但幅度都很小（≤15 L/t，有步长限幅）。
多出的 5 次是模型在守护带边缘的微调。</li>
<li><b>模型均值 637.3 vs 人工 636.2</b>，基本重合，模型没有系统性抬高或压低水率。</li>
</ul>

<h3>为什么模型曲线在中途断开</h3>

<div class="note">
<b>第二个班次（10-20 03:10~03:59，50 分钟）模型未接管</b>，
原因是该时段消石灰仓料位持续在 7.2~7.4m（阈值 7.0m），
模型按保护逻辑全程「停止给料」，停在停机阶段。
<br><br>
这不是漏接或故障，是保护逻辑正确工作。但也暴露一个问题：
<b>料位高时模型完全没有发言权</b>，哪怕现场仍在制料。
本次数据中生产时段料位 ≥7.0m 达 406 分钟（占 40%），
这个比例值得现场关注——它直接影响模型能发挥作用的时间窗口。
</div>

<div class="note ok">
<b>验证结论：模型可靠</b>。旧模型在新数据上未出现失控，水率输出与人工
实践一致，T3 合格率还略有提升（97.6% → 99.1%）。
本次验证未将新数据加入辨识训练（按要求）。
</div>

<h2>六、本次验证查出的问题（已修）</h2>

<div class="note">
<b>水率操作带不自洽</b>：旧参数 <code>ratio_band=45</code> 推出上限 675，
而实测水率最高到 690，导致控制器每分钟都触发「水率回归」动作。
新数据上表现为 46 次降低水率，且与温度无关。
<br><br>
已改为 <code>ratio_band=60</code>（操作带 [570, 690]），
降水率从 46 次降到 1 次。用旧数据回归：T3 合格率不变（75.4%），
四项安全违规仍为 0。
</div>

<p class="foot">
数据来源：<code>dbName_db101-1792457404155.zip</code>（2026-10-19~20）。
模型为 10-12~10-19 数据训练的既有版本，响应核 12 个阶跃事件写死，未重新辨识。
</p>

</div>
<script>
var D = __DATA__;

function mkOpt(el, title, labels, series, yName, yMin, yMax, extraGrid){
  var opt = {
    textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif'},
    title:{text:title, left:'center', top:4, textStyle:{fontSize:14, fontWeight:500}},
    tooltip:{trigger:'axis'},
    legend:{top:30, data:['人工实际操作','模型接管'], itemWidth:18, textStyle:{fontSize:12}},
    grid:extraGrid||{left:70, right:28, top:64, bottom:46},
    xAxis:{type:'category', data:labels, axisLabel:{fontSize:10, interval:Math.floor(labels.length/12)}},
    yAxis:[{type:'value', name:yName, min:yMin, max:yMax, nameTextStyle:{fontSize:11}}],
    series:series
  };
  echarts.init(document.getElementById(el)).setOption(opt);
}

// 全周期水率
mkOpt('c_all', '水率对比 · 全周期（仅生产段有值）', D.labels, [
  {name:'人工实际操作', type:'line', data:D.ratio_act, symbol:'none',
   lineStyle:{width:1.6, type:'dashed'}, itemStyle:{color:'#f59e0b'}},
  {name:'模型接管', type:'line', data:D.ratio_sim, symbol:'none',
   lineStyle:{width:2.8}, itemStyle:{color:'#34d399'}}
], '水率 L/t', 580, 720, {left:70, right:28, top:64, bottom:56});

// 逐班次（默认第一个长班次）
var segDefs = [
  {label:'10-19 16:34 ~ 10-20 02:01', s:480, e:1048},
  {label:'10-20 03:10 ~ 03:59', s:1116, e:1166}
];
var cur = 0;
var segBtns = document.createElement('div');
segBtns.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px';
segDefs.forEach(function(d, i){
  var b = document.createElement('button');
  b.textContent = d.label;
  b.style.cssText = 'background:var(--panel2);color:var(--text);border:1px solid var(--line);'+
    'padding:6px 12px;border-radius:6px;cursor:pointer;font-size:13px;font-family:inherit';
  if(i===0) b.style.background = 'var(--accent)', b.style.color = '#fff';
  b.onclick = function(){
    cur = i;
    Array.prototype.forEach.call(segBtns.children, function(x){
      x.style.background='var(--panel2)'; x.style.color='var(--text)';});
    b.style.background='var(--accent)'; b.style.color='#fff';
    drawSeg();
  };
  segBtns.appendChild(b);
});
document.getElementById('c_seg').parentNode.insertBefore(segBtns, document.getElementById('c_seg'));

function sliceArr(a, s, e){ return a.slice(s/5, e/5); }
function sliceLab(a, s, e){ return a.slice(s/5, e/5); }

var segChart;
function drawSeg(){
  var d = segDefs[cur];
  var lab = sliceLab(D.labels, d.s, d.e);
  var opt = {
    textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif'},
    title:{text:d.label + ' · 水率与 L3 温度', left:'center', top:4,
           textStyle:{fontSize:14, fontWeight:500}},
    tooltip:{trigger:'axis'},
    legend:{top:30, data:['人工水率','模型水率','L3 温度'], itemWidth:18,
            textStyle:{fontSize:12}},
    grid:[{left:64, right:56, top:64, height:130},
          {left:64, right:56, top:220, height:110}],
    axisPointer:{link:[{xAxisIndex:'all'}]},
    xAxis:[
      {type:'category', gridIndex:0, data:lab, axisLabel:{show:false}},
      {type:'category', gridIndex:1, data:lab, axisLabel:{fontSize:10,
        interval:Math.floor(lab.length/8)}}
    ],
    yAxis:[
      {type:'value', gridIndex:0, name:'水率 L/t', min:580, max:720, nameTextStyle:{fontSize:11}},
      {type:'value', gridIndex:1, name:'T3 ℃', min:95, max:140, nameTextStyle:{fontSize:11}}
    ],
    series:[
      {name:'人工水率', type:'line', data:sliceArr(D.ratio_act, d.s, d.e), symbol:'none',
       lineStyle:{width:1.6, type:'dashed'}, itemStyle:{color:'#f59e0b'},
       xAxisIndex:0, yAxisIndex:0},
      {name:'模型水率', type:'line', data:sliceArr(D.ratio_sim, d.s, d.e), symbol:'none',
       lineStyle:{width:2.6}, itemStyle:{color:'#34d399'},
       xAxisIndex:0, yAxisIndex:0},
      {name:'L3 温度', type:'line', data:sliceArr(D.t3, d.s, d.e), symbol:'none',
       lineStyle:{width:1.8}, itemStyle:{color:'#58a6ff'},
       xAxisIndex:1, yAxisIndex:1,
       markLine:{symbol:'none', data:[
         {yAxis:130, label:{formatter:'上限130', position:'insideEndTop', fontSize:11}},
         {yAxis:100, label:{formatter:'下限100', position:'insideEndBottom', fontSize:11}}
       ]}}
    ]
  };
  if(!segChart) segChart = echarts.init(document.getElementById('c_seg'));
  segChart.setOption(opt, true);
}
drawSeg();

window.addEventListener('resize', function(){
  if(segChart) segChart.resize();
});
</script>
</body>
</html>
"""

HTML = HTML.replace("__DATA__", DATA)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print("生成: %s (%.1f KB)" % (OUT, len(HTML) / 1024))
