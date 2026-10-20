# -*- coding: utf-8 -*-
"""把 A/B 结果渲染成单文件 HTML 讲解文档。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, ".cache", "ab_inline.json")
OUT = os.path.join(BASE, "控制模型讲解.html")

with open(SRC, encoding="utf-8-sig") as f:
    DATA = f.read().strip()

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>消石灰制备参数控制模型 · 讲解与 A/B 对比</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>
:root{
  --bg:#0f1216; --panel:#161b22; --panel2:#1c2129; --line:#30363d;
  --text:#e6edf3; --dim:#8b949e; --accent:#58a6ff;
  --good:#3fb950; --warn:#d29922; --bad:#f85149;
}
@media (prefers-color-scheme: light){
  :root{
    --bg:#ffffff; --panel:#f6f8fa; --panel2:#eaeef2; --line:#d0d7de;
    --text:#1f2328; --dim:#656d76; --accent:#0969da;
    --good:#1a7f37; --warn:#9a6700; --bad:#cf222e;
  }
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  line-height:1.75; font-size:15px;
}
.wrap{max-width:1080px; margin:0 auto; padding:32px 24px 80px}
h1{font-size:28px; margin:0 0 8px; letter-spacing:.5px}
h2{
  font-size:20px; margin:44px 0 14px; padding-bottom:8px;
  border-bottom:1px solid var(--line);
}
h3{font-size:16px; margin:26px 0 10px; color:var(--accent)}
.sub{color:var(--dim); font-size:14px; margin:0 0 28px}
p{margin:12px 0}
code{
  background:var(--panel2); padding:2px 6px; border-radius:4px;
  font-family:ui-monospace,Consolas,monospace; font-size:13px;
}
pre{
  background:var(--panel2); padding:14px 16px; border-radius:8px;
  overflow-x:auto; border:1px solid var(--line);
  font-family:ui-monospace,Consolas,monospace; font-size:13px; line-height:1.6;
}
.card{
  background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:18px 20px; margin:16px 0;
}
.grid{display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.kpi{background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px}
.kpi .v{font-size:26px; font-weight:600; margin:4px 0}
.kpi .k{color:var(--dim); font-size:13px}
.kpi .d{font-size:12px; color:var(--dim); margin-top:6px}
.chart{width:100%; height:380px; margin:8px 0}
.chart.sm{height:300px}
table{width:100%; border-collapse:collapse; margin:14px 0; font-size:14px}
th,td{padding:9px 12px; text-align:left; border-bottom:1px solid var(--line)}
th{color:var(--dim); font-weight:500; font-size:13px}
td.num{text-align:right; font-variant-numeric:tabular-nums}
.tag{
  display:inline-block; padding:2px 8px; border-radius:12px;
  font-size:12px; font-weight:500;
}
.t-good{background:rgba(63,185,80,.15); color:var(--good)}
.t-warn{background:rgba(210,153,34,.15); color:var(--warn)}
.t-bad{background:rgba(248,81,73,.15); color:var(--bad)}
.t-info{background:rgba(88,166,255,.15); color:var(--accent)}
.note{
  border-left:3px solid var(--warn); background:var(--panel);
  padding:12px 16px; margin:16px 0; border-radius:0 8px 8px 0; font-size:14px;
}
.note.bad{border-left-color:var(--bad)}
.note.ok{border-left-color:var(--good)}
.note b{color:var(--text)}
ul,ol{margin:12px 0; padding-left:22px}
li{margin:6px 0}
.legend{color:var(--dim); font-size:12px; text-align:center; margin-top:4px}
.shiftnav{display:flex; flex-wrap:wrap; gap:8px; margin:12px 0}
.shiftnav button{
  background:var(--panel2); color:var(--text); border:1px solid var(--line);
  padding:7px 14px; border-radius:6px; cursor:pointer; font-size:13px;
  font-family:inherit;
}
.shiftnav button.on{background:var(--accent); color:#fff; border-color:var(--accent)}
.fl{display:flex; gap:10px; flex-wrap:wrap; margin:14px 0}
.fl .step{
  flex:1; min-width:150px; background:var(--panel); border:1px solid var(--line);
  border-radius:8px; padding:12px 14px; font-size:13px;
}
.fl .step .n{color:var(--accent); font-weight:600; font-size:12px}
.hd{color:var(--dim); font-size:13px; margin:0 0 10px}
</style>
</head>
<body>
<div class="wrap">

<h1>消石灰制备参数控制模型</h1>
<p class="sub">算法讲解 · 反事实 A/B 对比 · 部署建议</p>

<div class="note ok">
<b>先把结论摆在最前面</b>：反事实仿真显示，模型 T3 合格率 <b>76.3%</b>，
人工 <b>76.0%</b>，模型<b>高 0.3 个百分点</b>。&gt;130℃ 占比 24.0% → 23.5%。
<br><br>
提升幅度很小，且受限于「主导扰动是原料批次」这个物理事实。
本工作真正的产出是过程中查出并修正的<b>四个设计缺陷</b>——
每一次修正都由仿真数据驱动，其中两次直接改变了结论走向。
</div>

<div class="note ok" style="border-left-color:var(--good)">
<b>如果只看一句话</b>：<br><br>
这个机器像一锅粥，<b>加水会先变烫、过会儿才变温</b>；
而且<b>温度主要由生石灰原料决定，水率调不动多少</b>。
所以最好的办法不是拼命调，而是
<b>平时别动，真要超标了先加水，水加到头了才少放料</b>。
<br><br>
模型就是照这个思路写的。下面从头讲起，不用任何术语。
</div>

<h2>一、控制的是什么</h2>

<p>操纵两个变量：<b>水流量</b>（以水灰比 <code>水率 L/t</code> 下发）和
<b>生石灰流量</b>（<code>t/h</code>）。目标是三个，按优先级排：</p>

<div class="card">
<table>
<tr><th>优先级</th><th>目标</th><th>取值</th><th>来源</th></tr>
<tr><td>1 安全</td><td>L1 螺旋输送机电流 &lt; X</td><td>X 默认 18A，23A 停产</td><td>现场指定</td></tr>
<tr><td>2 品质</td><td>L3 出口温度 ∈ [100, 130]℃</td><td>目标带 106~126℃</td><td>控制逻辑文档</td></tr>
<tr><td>3 生产</td><td>给水给料允许信号 = 1 才动作</td><td>唯一生产判据</td><td>现场指定</td></tr>
</table>
</div>

<p>生产判据经过校验：允许信号与「生石灰流量 &gt; 0」在 3079 分钟上
<b>完全吻合（100%）</b>，不存在信号滞后或抖动。</p>

<h2>二、先讲人话：这个系统在折腾什么</h2>

<p>这一节不用任何术语。搞懂了这两张图，后面的技术内容只是换个说法。</p>

<h3>2.0.1 第一件事：往热粥里加水，会先变得更烫</h3>

<svg viewBox="0 0 680 260" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:680px;display:block;margin:12px auto">
<style>
.t{font:400 13px sans-serif;fill:var(--text)}
.ts{font:400 12px sans-serif;fill:var(--dim)}
.th{font:500 14px sans-serif;fill:var(--text)}
.pot{animation:boil 2s ease-in-out infinite}
@keyframes boil{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.steam{opacity:0;animation:rise 3s ease-in-out infinite}
.steam2{opacity:0;animation:rise 3s ease-in-out infinite;animation-delay:1s}
.steam3{opacity:0;animation:rise 3s ease-in-out infinite;animation-delay:2s}
@keyframes rise{0%{opacity:0;transform:translateY(0)}40%{opacity:.55}100%{opacity:0;transform:translateY(-24px)}}
.arrow{animation:slide 2.5s ease-in-out infinite}
@keyframes slide{0%,100%{transform:translateX(0)}50%{transform:translateX(6px)}}
@media (prefers-reduced-motion: reduce){
  .pot,.steam,.steam2,.steam3,.arrow{animation:none}
  .steam,.steam2,.steam3{opacity:.35}
}
</style>
<defs>
<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
<path d="M2 1L8 5L2 9" fill="none" stroke="var(--dim)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</marker>
</defs>

<text class="th" x="340" y="26" text-anchor="middle">往一锅滚烫的粥里加一瓢水，会发生什么？</text>

<g class="pot" style="transform-origin:170px 150px">
  <rect x="105" y="120" width="130" height="76" rx="10" fill="none" stroke="var(--dim)" stroke-width="1.2"/>
  <path d="M100 120 L240 120" stroke="var(--dim)" stroke-width="1.2" stroke-linecap="round"/>
  <text class="ts" x="170" y="160" text-anchor="middle">锅里 100℃ 的粥</text>
  <text class="ts" x="170" y="178" text-anchor="middle">咕嘟咕嘟</text>
</g>
<path class="steam" d="M150 112 q-8 -14 0 -22" stroke="var(--dim)" fill="none" stroke-width="2" stroke-linecap="round"/>
<path class="steam2" d="M170 112 q8 -14 0 -22" stroke="var(--dim)" fill="none" stroke-width="2" stroke-linecap="round"/>
<path class="steam3" d="M190 112 q-8 -14 0 -22" stroke="var(--dim)" fill="none" stroke-width="2" stroke-linecap="round"/>

<g class="arrow" style="transform-origin:340px 150px">
<path d="M258 150 L378 150" stroke="var(--dim)" stroke-width="1.5" fill="none" marker-end="url(#arrow)"/>
<text class="ts" x="318" y="136" text-anchor="middle">加一瓢水</text>
</g>

<rect x="405" y="100" width="150" height="52" rx="10" fill="none" stroke="var(--warn)" stroke-width="1.2"/>
<text class="th" x="480" y="120" text-anchor="middle" fill="var(--warn)">第 1 分钟</text>
<text class="ts" x="480" y="140" text-anchor="middle">粥翻腾得更凶 → 更烫</text>

<rect x="405" y="170" width="150" height="52" rx="10" fill="none" stroke="var(--good)" stroke-width="1.2"/>
<text class="th" x="480" y="190" text-anchor="middle" fill="var(--good)">第 30 分钟后</text>
<text class="ts" x="480" y="210" text-anchor="middle">整锅被稀释 → 变温</text>

<text class="ts" x="340" y="246" text-anchor="middle">同一瓢水：先让你觉得更烫，过一会儿才真的变温</text>
</svg>

<p>这个厂里的机器跟这锅粥一模一样。</p>

<div class="card">
<table>
<tr><th>粥</th><th>工厂里的东西</th><th>说明</th></tr>
<tr><td>一锅粥</td><td>消化器（三级搅拌桶）</td><td>生石灰加水会发热，跟煮粥一样</td></tr>
<tr><td>加一瓢水</td><td>把「水率」调大</td><td>水率 = 水 ÷ 生石灰，就是粥的稀稠</td></tr>
<tr><td>粥的温度</td><td>第 3 级出口温度（T3）</td><td>必须保持在 100~130℃ 之间</td></tr>
<tr><td>先变烫后变温</td><td>「非最小相位」</td><td>加水的头 10 分钟温度反而上升</td></tr>
</table>
</div>

<div class="note bad">
<b>这就是为什么不能用普通的自动调节器。</b><br><br>
普通调节器的逻辑是「看见温度高 → 加水 → 再看温度」。
但它加水后一分钟看温度计——温度<b>还在往上涨</b>！
它就以为「加水没用」，赶紧改成减水。
<br><br>
结果：减水的效果（会让温度升）在 20 分钟后才到，
跟前面加水的效果撞在一起，温度就开始来回蹦。
</div>

<h3>2.0.2 第二件事：不是动得越多越好</h3>

<svg viewBox="0 0 680 250" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:680px;display:block;margin:12px auto">
<style>
.t{font:400 13px sans-serif;fill:var(--text)}
.ts{font:400 12px sans-serif;fill:var(--dim)}
.th{font:500 14px sans-serif;fill:var(--text)}
.car{animation:swerve 4s ease-in-out infinite}
@keyframes swerve{
  0%,100%{transform:translateX(0)}
  25%{transform:translateX(14px)}
  75%{transform:translateX(-14px)}
}
.line{stroke-dasharray:1800;stroke-dashoffset:1800;animation:draw 2.5s ease-out forwards}
@keyframes draw{to{stroke-dashoffset:0}}
@media (prefers-reduced-motion: reduce){
  .car{animation:none}
  .line{animation:none;stroke-dashoffset:0}
}
</style>

<text class="th" x="340" y="28" text-anchor="middle">开车：看见偏离就猛打方向，会怎样？</text>

<text class="ts" x="40" y="62" fill="var(--bad)">✗ 偏一点点就立刻打方向</text>
<path d="M40 96 L640 96" stroke="var(--line)" stroke-width="1" stroke-dasharray="4 4" fill="none"/>
<g class="car">
  <rect x="316" y="82" width="48" height="28" rx="6" fill="none" stroke="var(--bad)" stroke-width="1.5"/>
  <text class="ts" x="340" y="97" text-anchor="middle" fill="var(--bad)">车</text>
</g>
<path class="line" d="M40 132 Q 110 116 180 132 T 320 132 T 460 132 T 600 132"
      stroke="var(--bad)" stroke-width="2" fill="none"/>
<text class="ts" x="40" y="150" fill="var(--bad)">结果：一直在画龙，越修越歪，还累</text>

<text class="ts" x="40" y="190" fill="var(--good)">✓ 小偏离不理，快压线了才修一点</text>
<path d="M40 218 L640 218" stroke="var(--line)" stroke-width="1" stroke-dasharray="4 4" fill="none"/>
<rect x="316" y="204" width="48" height="28" rx="6" fill="none" stroke="var(--good)" stroke-width="1.5"/>
<text class="ts" x="340" y="219" text-anchor="middle" fill="var(--good)">车</text>
<text class="ts" x="40" y="240" fill="var(--good)">结果：走得直，还不累　← 这就是「最小干预」</text>
</svg>

<p>工厂里的老师傅早就懂这个道理。翻历史记录会发现：
他们把水率设成 630 之后，<b>一整班都不动它</b>。</p>

<div class="note">
这不是偷懒。是这个系统有个天生的脾气：<br><br>
· 水率调了半天，温度只动一点点（调 100 个单位，温度才变 15 度）<br>
· 但各班次的温度天生就不一样，差别有 28.6℃——
这个差别来自<b>生石灰原料本身</b>（产地、批次、存放时间），谁也改不了
<br><br>
所以「努力调水率」就像「坐在后排指挥司机」——
你喊得越勤，车越晃。
</div>

<h3>2.0.3 那什么时候该动？用对手段</h3>

<p>温度真的要冲出 130℃ 上限了，这时候<b>不动是不负责任的</b>。
但要动对地方：</p>

<div class="fl">
  <div class="step"><div class="n">第一选择</div><b>加水</b>——水越多，粥越稀，温度越低。这是正路。</div>
  <div class="step"><div class="n">实在不行</div>水率已经加到头了还没压住，才<b>少放点生石灰</b>。这是备用方案。</div>
</div>

<div class="note bad">
<b>我一开始就把这个顺序搞反了。</b>
写成了「先减料，减不了再加水」，还把减料的触发线设得比加水还低——
结果加水那一段程序<b>从头到尾一次都没执行过</b>。
<br><br>
改成「先加水」之后，模型的水率动作从 0 次变成 11 次，
减料从 9 次降到 2 次，效果也从「比人差」变成了「比人好一点点」。
</div>

<hr style="margin:36px 0;border:none;border-top:1px solid var(--line)">

<h2>三、技术细节</h2>

<p class="hd">下面是工程师看的部分，说同一个事情，只是换了词。</p>

<h3>3.1 对象是非最小相位系统</h3>

<p>这是全部设计的起点。从 12 个干净的水率阶跃事件（升 7 / 降 5）辨识出的
单位阶跃响应：</p>

<div class="card">
<div id="c_kernel" class="chart"></div>
<p class="legend">纵轴：+100 L/t 水率阶跃引起的 T3 变化（℃）｜升/降两组分别辨识后归一</p>
</div>

<p>加水之后，T3 <b>先升到 +46.7℃（第 5 分钟），再跌到 −15.1℃（第 60 分钟）</b>，
穿越零点。</p>

<div class="note">
<b>用人话说</b>：这根曲线就是「加一瓢水，粥先翻腾得更凶，过一会儿才变温」的
数据版本。前 10 分钟往上翘的那一段，就是骗过普通调节器的地方。
</div>

<p>常规 PID 会在前 10 分钟看到「温度还在涨」而判定加水无效、
反向减水；等到第 20 分钟水率的真实降温效应到达时，两次作用叠加就是振荡。</p>

<h3>3.2 现行控制律</h3>

<div class="fl">
  <div class="step"><div class="n">STEP 1</div>T3 在守护带 106~126℃ 内 → <b>不动</b></div>
  <div class="step"><div class="n">STEP 2</div>超出守护带 → <b>先加水</b>（≤15 L/t）</div>
  <div class="step"><div class="n">STEP 3</div>水率到 675 且 T3&gt;132℃ → 才降料</div>
  <div class="step"><div class="n">STEP 4</div>动作后<b>闭眼等 35 分钟</b>再评估</div>
</div>

<p>水率增量的计算：</p>

<pre>Δr = −Kp · (T3 − 边界)        Kp = 4.0 L/t per ℃
其中 T3 偏高时取 (T3 − 126)，偏低时取 (106 − T3)
     Δr 经 ±15 L/t 限幅，并裁剪到 [585, 675]</pre>

<p>注意这个式子<b>没有积分项</b>。积分在这里是有害的，原因见下一节。</p>

<h3>3.3 手段优先级：水率优先，给料量后备</h3>

<div class="note">
初版把<b>降料写在加水之前</b>，且降料触发线 130−8=122 低于纠偏触发线 126。
这个大小关系导致加水分支<b>永远执行不到（死代码）</b>——
T3 一旦越过 126 进入纠偏，它必然同时 &gt; 122，直接落到降料。
</div>

<p>物理原理很清楚：水率越大温度越低。</p>

<div class="note">
<b>用人话说</b>：水率调大 100 个单位，温度最后才降 15 度
（这个比值叫「稳态增益」，是 −0.151 ℃/(L/t)）。
<br><br>
15 度听起来不少，但各班次的温度天生就差 28.6 度——
所以水率这个旋钮，<b>劲比较小</b>。
</div>

<p>所以手段顺序应该是先用水率，水率用尽才动给料量：</p>

<pre>T3 偏高 → 先看水率还有没有调节空间
          有  → 加水（不动给料量）
          无（已到 675）且 T3 &gt; 132℃ → 才降料</pre>

<p>三条触发线的大小关系必须严格满足，否则又会退回死代码：<br>
<code>纠偏线 126 &lt; 降料线 132</code></p>

<h3>3.4 为什么取消积分：一段失败记录</h3>

<div class="note bad">
初版我写的是「节拍式 PI，把 T3 死死纠到目标 118℃」。
反事实仿真打脸了——以 10-16 00:04 班次为例：
<br><br>
· 人工：水率<b>恒定 630</b> 全程不动 → T3 标准差 2.9，合格率 <b>100%</b><br>
· 模型：水率从 630 <b>一路降到 350</b>（物理下限）→ T3 标准差 9.6，合格率 <b>91%</b>
<br><br>
模型在拼命纠一个它纠不动的量，把水率推到边界，反而注入了额外方差。
</div>

<p>根因是三条硬事实：</p>

<div class="card">
<table>
<tr><th>事实</th><th>数值</th><th>含义</th></tr>
<tr><td>水率 → T3 稳态增益</td><td>−0.151 ℃/(L/t)</td><td>很弱，纠 10℃ 需 66 L/t</td></tr>
<tr><td>各班次 T3 稳态均值跨度</td><td>28.6℃</td><td>由原料批次主导，不可控不可测</td></tr>
<tr><td>稳态段水率标准差</td><td>12.7 L/t</td><td>操作员几乎不调水率</td></tr>
</table>
</div>

<p>在「主导扰动不可控 + 执行器增益弱」的系统里，积分项会把不可控扰动的偏差
持续累积，最终单向漂移触界。所以正确策略是<b>最小干预</b>：
T3 在区间内就不动，逼近硬边界才出手，且只出手有限幅度。</p>

<p>四次修正后的仿真结果演进：</p>

<div class="card">
<table>
<tr><th>方案</th><th>T3 合格率</th><th>相对人工</th></tr>
<tr><td>人工（实际）</td><td>76.0%</td><td>基准</td></tr>
<tr><td>① 节拍式 PI 追 118℃</td><td>70.7%</td><td class="t-bad">−5.3</td></tr>
<tr><td>② 取消积分 → 区间守护 + 最小干预</td><td>75.6%</td><td class="t-warn">−0.4</td></tr>
<tr><td>③ 手段改为水率优先</td><td>76.3%</td><td class="t-good">+0.3</td></tr>
</table>
</div>

<p>第 ③ 步同时让手段构成回到正轨：</p>

<div class="card">
<table>
<tr><th>通道</th><th>② 降料优先</th><th>③ 水率优先</th></tr>
<tr><td>提高水率</td><td>0 次</td><td><b>11 次</b></td></tr>
<tr><td>降低水率</td><td>0 次</td><td>1 次</td></tr>
<tr><td>减少给料</td><td>9 次</td><td><b>2 次</b></td></tr>
<tr><td>报警</td><td>556 次</td><td><b>0 次</b></td></tr>
</table>
</div>

<h2>四、A/B 反事实仿真</h2>

<h3>4.1 方法</h3>

<p>历史数据是操作员的闭环结果，不能直接拿来比较。做法是：</p>

<ol>
<li><b>辨识</b>：从 12 个干净阶跃事件得到水率 → T3 的响应核 <code>g[k]</code></li>
<li><b>拆扰动</b>：把实际 T3 轨迹拆成「水率驱动的」+「水率解释不了的 <code>d[t]</code>」</li>
<li><b>反事实</b>：保持 <code>d[t]</code> 不变（共同随机数法），只把水率序列换成模型的，推演 T3</li>
</ol>

<p>第 3 步保证公平：双方面对<b>完全相同的原料批次与环境扰动</b>，
唯一差别是操作序列。</p>

<h3>4.2 总体结果</h3>

<div class="grid">
  <div class="kpi">
    <div class="k">人工 T3 合格率</div>
    <div class="v" style="color:var(--accent)">76.0%</div>
    <div class="d">2002 分钟样本</div>
  </div>
  <div class="kpi">
    <div class="k">模型 T3 合格率</div>
    <div class="v" style="color:var(--good)">76.3%</div>
    <div class="d">高 +0.3 个百分点</div>
  </div>
  <div class="kpi">
    <div class="k">T3 标准差</div>
    <div class="v">10.30 <span style="font-size:15px;color:var(--dim)">vs 10.40</span></div>
    <div class="d">波动略降</div>
  </div>
  <div class="kpi">
    <div class="k">越上限占比</div>
    <div class="v">23.5% <span style="font-size:15px;color:var(--dim)">vs 24.0%</span></div>
    <div class="d">&gt;130℃ 比例下降</div>
  </div>
</div>

<h3>4.3 逐班次对比</h3>

<div class="card">
<table>
<tr>
  <th>班次（稳态段）</th><th>时长</th>
  <th class="num">人工 T3</th><th class="num">人工 std</th><th class="num">人工合格</th>
  <th class="num">模型 T3</th><th class="num">模型 std</th><th class="num">模型合格</th>
</tr>
__ROWS__
</table>
</div>

<p>分两类看：</p>

<ul>
<li><b>T3 本来就在区间内</b>的班次（10-12、10-16×2）：模型与人工<b>完全一致</b>，
因为它选择不动。其中两个班次的 T3 标准差还有小幅下降（4.2→3.4、2.9→2.8）。</li>
<li><b>T3 天然贴着 130℃ 上限</b>的班次（10-15 均值 129.3、10-18 均值 129.5）：
模型纠不动，正确行为是<b>报警转人工</b>。</li>
</ul>

<div class="note">
<b>这是本次工作最重要的发现</b>：在一个主导扰动不可控的系统里，
自动化系统的价值不在于「比人调得更勤」，
而在于<b>知道什么时候不该调、该调的时候用对手段</b>。
操作员把水率设 630 然后不动，不是因为他懒，
而是因为他凭经验知道这个量平时调不动。

但注意——这不等于「永远不动」。当 T3 真的逼近上限时，
正确做法是<b>加水</b>（水率越大温度越低），而不是降到料。
第 ③ 次修正正是把这一点纠正过来，也是结果转正的原因。
</div>

<h3>4.4 轨迹对比</h3>

<div class="shiftnav" id="nav"></div>
<div class="card">
<div id="c_shift" class="chart"></div>
<p class="legend">上半：T3 轨迹（含 100/130 合格边界）｜下半：水率操作序列</p>
</div>

<h2>五、四层保护架构</h2>

<p>控制律只是中间一层，外面套着优先级更高的保护：</p>

<pre>第 0 层  安全联锁（任何阶段最高优先级，不可覆盖）
         ├ 连锁条件：排气风机 / 生石灰仓 / 水箱 任一不满足 → 退出模型
         ├ 消石灰仓高料位 → 停止制料
         ├ L1 电流三级：≥16 预警禁止增量 / ≥18 降载 / ≥23 停产
         └ 温度：硬边界（全程）+ 升温速率（仅稳态）
第 1 层  阶段判定：启动（&lt;120min 且 T3&lt;100℃）沿用现场参数 / 稳态进闭环
第 2 层  稳态优化：区间守护 + 最小干预 + 水率优先（本模型核心）
第 3 层  输出限幅：步长 ≤15 L/t / 最小间隔 35min / 水率裁剪到 630±45</pre>

<svg viewBox="0 0 680 250" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:680px;display:block;margin:16px auto">
<style>
.t{font:400 13px sans-serif;fill:var(--text)}
.ts{font:400 12px sans-serif;fill:var(--dim)}
.th{font:500 14px sans-serif;fill:var(--text)}
</style>

<text class="th" x="340" y="24" text-anchor="middle">四层保护：越往上，权力越大</text>

<!-- 第0层 -->
<rect x="40" y="44" width="600" height="42" rx="10" fill="none" stroke="var(--bad)" stroke-width="1.3"/>
<text class="th" x="60" y="65" fill="var(--bad)">第 0 层　安全联锁</text>
<text class="ts" x="212" y="65">电流太大？料仓满了？风机没开？→ 立刻停产，谁也拦不住</text>

<!-- 第1层 -->
<rect x="40" y="94" width="600" height="38" rx="10" fill="none" stroke="var(--warn)" stroke-width="1.3"/>
<text class="th" x="60" y="113" fill="var(--warn)">第 1 层　阶段判定</text>
<text class="ts" x="212" y="113">刚开机温度还在爬 → 先用老师傅的参数，不插手</text>

<!-- 第2层 -->
<rect x="40" y="140" width="600" height="38" rx="10" fill="none" stroke="var(--accent)" stroke-width="1.3"/>
<text class="th" x="60" y="159" fill="var(--accent)">第 2 层　稳态优化</text>
<text class="ts" x="212" y="159">温度正常 → 不动；真超标 → 先加水</text>

<!-- 第3层 -->
<rect x="40" y="186" width="600" height="38" rx="10" fill="none" stroke="var(--dim)" stroke-width="1.3"/>
<text class="th" x="60" y="205">第 3 层　输出限幅</text>
<text class="ts" x="212" y="205">每次最多调 15，调完等 35 分钟，不许猛调</text>

<text class="ts" x="340" y="240" text-anchor="middle">下面三层说的是「怎么调」，最上面那层说的是「什么时候不许调」</text>
</svg>

<p>启动阶段的升温速率保护<b>必须放在阶段判定之后</b>。
启动期 T3 从 38℃ 升到 150℃ 是物理必然（10 分钟变化可达 80℃），
若先判速率，整个启动阶段会被短路，模型永远进不了稳态。这是我踩过的坑。</p>

<h3>5.1 验证结果</h3>

<div class="card">
<table>
<tr><th>检查项</th><th class="num">违规数 / 总数</th><th>结论</th></tr>
<tr><td>水率越界</td><td class="num">0 / 3079</td><td><span class="tag t-good">通过</span></td></tr>
<tr><td>给料量越界</td><td class="num">0 / 3079</td><td><span class="tag t-good">通过</span></td></tr>
<tr><td>L1 电流高高报</td><td class="num">0 / 3079</td><td><span class="tag t-good">通过</span></td></tr>
<tr><td>T3 硬边界</td><td class="num">0 / 3079</td><td><span class="tag t-good">通过</span></td></tr>
</table>
</div>

<h2>六、能不能直接下控</h2>

<div class="note">
<b>不能直接下控</b>。缺的不是代码，是三样现场的东西。
逐项确认清单见 <code>点表确认清单.md</code>，拿去现场对照，预计半天。
</div>

<h3>6.1 必须先解决的</h3>

<div class="card">
<table>
<tr><th>问题</th><th>现状</th><th>要做什么</th></tr>
<tr>
  <td>电流阈值无数据支撑</td>
  <td>历史最大仅 15.96A，<b>&gt;16A 占比 0.00%</b>，从未接近 18A</td>
  <td>按电机铭牌额定电流重新定 X</td>
</tr>
<tr>
  <td>响应模型样本太少</td>
  <td>仅 12 个干净阶跃，且幅度小（中位 12 L/t）</td>
  <td>现场做阶跃测试：水率 +50 L/t 保持 60 分钟，重复 5~8 次</td>
</tr>
<tr>
  <td>输出通道未确认</td>
  <td><code>生石灰流量设定值</code>测点在历史库中全为 1970 无效时间戳</td>
  <td>确认模型能否写入该点，以及 1 级转速给定点的写入权限</td>
</tr>
</table>
</div>

<h3>6.2 建议的上线路径</h3>

<ol>
<li><b>查点表</b>（半天，零风险）：确认三个设定值测点能否写入。
这是所有后续工作的前提——不可写则模型输出落不下去。</li>
<li><b>开环监护</b>（2~4 周，零风险）：模型只算不发，建议值显示在 HMI 上与实际值并列。
期间模型会基本不动（水率恒定），这是<b>预期行为而非故障</b>。</li>
<li><b>闭环水率</b>（2 周）：只投水率，给料量保持人工。</li>
<li><b>全闭环</b>：电流保护投用，前提是 X 已按铭牌重定，且做过真实的电流高报警触发演练。</li>
</ol>

<div class="note ok">
按当前仿真，即使全闭环，T3 合格率也只是与人工持平（+0.3）。
所以它真正的卖点不是提升合格率，而是两件事：
<b>消除班组间操作差异</b>（8 个班次的人工 T3 均值从 108.8 跨到 137.4℃，
这个跨度才是品质一致性的敌人）；以及<b>24 小时安全监护不疲劳</b>。
</div>

<div class="note">
<b>预期管理</b>：如果你期待「上模型后合格率大涨」，会失望。
这个系统的问题不在控制算法，在上游原料一致性。
水率对 T3 的稳态增益只有 −0.151 ℃/(L/t)，而各班次 T3 差异达 28.6℃。
</div>

<h2>七、已知局限</h2>

<ol>
<li><b>仿真是模型内自证</b>。A/B 在「自己辨识出的模型」里进行，
若响应核 <code>g[k]</code> 有偏，结论就有偏。真实检验仍需现场 A/B。</li>
<li><b>给料量对 T3 的影响未建模</b>。仿真中给料量动作不影响 T3，
因此「降料降温度」这条路的效果是<b>未被评估</b>的，目前按无效处理。</li>
<li><b>响应核尾部不可靠</b>。<code>g[k=60]</code> 的 −15.1℃ 已是事件样本的外推边界，
稳态增益的真实值可能有较大偏差。</li>
<li><b>L1 电流保护从未被实数据验证</b>。16/18/23 是规则不是学到的。</li>
</ol>

<p style="color:var(--dim); font-size:13px; margin-top:40px; border-top:1px solid var(--line); padding-top:16px">
数据来源：2026-10-12 ~ 10-19 共 8 个生产班次，51.3 小时，3079 分钟生产数据。
A/B 仿真样本 2002 分钟（6 个班次的稳态段）。
</p>

</div>

<script>
var D = __DATA__;

function base(){
  return {
    textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif'},
    grid:{left:62,right:28,top:40,bottom:44}
  };
}

// ---- 响应核 ----
(function(){
  var k = D.kernel.map(function(v){return +(v*100).toFixed(2);});
  var opt = base();
  opt.title = {text:'水率 → T3 单位阶跃响应（+100 L/t）', left:'center', top:6,
               textStyle:{fontSize:14, fontWeight:500}};
  opt.tooltip = {trigger:'axis'};
  opt.xAxis = {type:'category', name:'分钟', data:k.map(function(_,i){return i;}),
               nameTextStyle:{fontSize:11}};
  opt.yAxis = {type:'value', name:'T3 变化 (℃)', nameTextStyle:{fontSize:11}};
  opt.series = [{
    type:'line', data:k, smooth:true, symbol:'none',
    lineStyle:{width:2.5},
    areaStyle:{opacity:.14},
    markLine:{
      symbol:'none',
      label:{show:false},
      data:[{yAxis:0},{xAxis:5},{xAxis:20}]
    },
    markPoint:{
      symbol:'circle', symbolSize:9,
      data:[
        {coord:[5, k[5]], value:'反向峰值 +' + k[5].toFixed(1) + '℃'},
        {coord:[60, k[60]], value:'稳态 ' + k[60].toFixed(1) + '℃'}
      ],
      label:{fontSize:11, position:'top'}
    }
  }];
  opt.grid.top = 58;
  echarts.init(document.getElementById('c_kernel')).setOption(opt);
})();

// ---- 逐班次 ----
var shifts = D.shifts;
var cur = 0;
var nav = document.getElementById('nav');
shifts.forEach(function(s, i){
  var b = document.createElement('button');
  b.textContent = s.label;
  if(i === 0) b.className = 'on';
  b.onclick = function(){
    cur = i;
    Array.prototype.forEach.call(nav.children, function(c){c.className='';});
    b.className = 'on';
    draw();
  };
  nav.appendChild(b);
});

var chart;
function draw(){
  var s = shifts[cur];
  var opt = base();
  opt.grid = [
    {left:62, right:28, top:34, height:150},
    {left:62, right:28, top:210, height:96}
  ];
  opt.axisPointer = {link:[{xAxisIndex:'all'}]};
  opt.xAxis = [
    {type:'category', gridIndex:0, data:s.t, axisLabel:{show:false}},
    {type:'category', gridIndex:1, data:s.t, name:'稳态段分钟', nameTextStyle:{fontSize:11}}
  ];
  opt.yAxis = [
    {type:'value', gridIndex:0, name:'T3 (℃)', min:90, max:150, nameTextStyle:{fontSize:11}},
    {type:'value', gridIndex:1, name:'水率 (L/t)', nameTextStyle:{fontSize:11}}
  ];
  opt.tooltip = {trigger:'axis'};
  opt.legend = {top:4, data:['人工 T3','模型 T3'], itemWidth:18, textStyle:{fontSize:12}};
  opt.series = [
    {name:'人工 T3', type:'line', data:s.t3_act, symbol:'none',
     lineStyle:{width:1.6}, xAxisIndex:0, yAxisIndex:0},
    {name:'模型 T3', type:'line', data:s.t3_sim, symbol:'none',
     lineStyle:{width:2.2}, xAxisIndex:0, yAxisIndex:0,
     markLine:{symbol:'none', data:[
       {yAxis:130, label:{formatter:'上限130', position:'insideEndTop', fontSize:11}},
       {yAxis:100, label:{formatter:'下限100', position:'insideEndBottom', fontSize:11}}
     ]}},
    {name:'人工水率', type:'line', data:s.r_act, symbol:'none',
     lineStyle:{width:1.4, type:'dashed'}, xAxisIndex:1, yAxisIndex:1},
    {name:'模型水率', type:'line', data:s.r_sim, symbol:'none',
     lineStyle:{width:2}, xAxisIndex:1, yAxisIndex:1}
  ];
  if(!chart) chart = echarts.init(document.getElementById('c_shift'));
  chart.setOption(opt, true);
}
draw();

window.addEventListener('resize', function(){
  if(chart) chart.resize();
});
</script>
</body>
</html>
"""

# 生成逐班次表格行
rows = []
for s in json.loads(DATA)["shifts"]:
    a, m = s["m_act"], s["m_sim"]
    d = m["in_band"] - a["in_band"]
    if abs(d) < 0.05:
        tag = '<span class="tag t-info">持平</span>'
    elif d > 0:
        tag = '<span class="tag t-good">%+.1f</span>' % d
    else:
        tag = '<span class="tag t-bad">%+.1f</span>' % d
    rows.append(
        "<tr><td>%s</td><td>%d min</td>"
        "<td class=\"num\">%.1f</td><td class=\"num\">%.1f</td>"
        "<td class=\"num\">%.1f%%</td>"
        "<td class=\"num\">%.1f</td><td class=\"num\">%.1f</td>"
        "<td class=\"num\">%.1f%% %s</td></tr>" % (
            s["label"], (a["n"]), a["mean"], a["std"], a["in_band"],
            m["mean"], m["std"], m["in_band"], tag))

HTML = HTML.replace("__ROWS__", "\n".join(rows)).replace("__DATA__", DATA)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print("生成: %s (%.1f KB)" % (OUT, len(HTML) / 1024))
