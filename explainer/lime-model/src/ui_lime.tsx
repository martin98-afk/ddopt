import React from 'react';
import {FONT_ORB} from './common/lib';
import {clamp01} from './common';
import {PURPLE, PURPLE_PALE, ORANGE, RED_DEEP, GREEN, GREY, WHITE, BLOOM_SOFT, CText} from './ui';

/**
 * 本片专属语义图元（消石灰制备控制）。风格与 ui.tsx 一致：黑填充 + 白描边 2–2.5px、accent 紫、BLOOM_SOFT。
 * 组件均为纯函数式、绝对定位（画布 1280×720）；动画由调用方按帧 N 计算后传入。
 */

const svgBase = (opacity: number) => ({position: 'absolute', inset: 0, pointerEvents: 'none', opacity} as React.CSSProperties);

/** 反应釜剖面：立式罐体 + 进料口 + 液面 + 搅拌桨 + 加热焰。h 为整体高，level 0–1 液面，spin 搅拌角，heating 0–1 焰强。 */
export const ReactorIcon: React.FC<{cx: number; cy: number; h?: number; level?: number; spin?: number; heating?: number; label?: string; opacity?: number; accent?: string}> = ({cx, cy, h = 260, level = 0.55, spin = 0, heating = 0, label, opacity = 1, accent = PURPLE}) => {
  const w = h * 0.62, top = cy - h / 2, bot = cy + h / 2, bodyH = h * 0.72, bodyTop = top + h * 0.16;
  const liq = bodyTop + bodyH * (1 - clamp01(level));
  const flame = (dx: number) => heating > 0.01 ? (
    <path key={dx} d={`M${cx + dx},${bot + 26} q7,-16 0,-26 q-7,10 0,26`} fill="none" stroke={ORANGE} strokeWidth={3} opacity={clamp01(heating)} style={{filter: `drop-shadow(0 0 6px ${ORANGE})`}} />
  ) : null;
  return (
    <div style={svgBase(opacity)}>
      <svg width={1280} height={720} viewBox="0 0 1280 720" style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', filter: BLOOM_SOFT}}>
        <line x1={cx - w * 0.32} y1={bot + 14} x2={cx - w * 0.42} y2={bot + 44} stroke={WHITE} strokeWidth={2.5} />
        <line x1={cx + w * 0.32} y1={bot + 14} x2={cx + w * 0.42} y2={bot + 44} stroke={WHITE} strokeWidth={2.5} />
        <rect x={cx - w / 2} y={bodyTop} width={w} height={bodyH} rx={16} fill="#000" stroke={WHITE} strokeWidth={2.5} />
        <ellipse cx={cx} cy={bodyTop} rx={w / 2} ry={h * 0.07} fill="#000" stroke={WHITE} strokeWidth={2.5} />
        <rect x={cx - 7} y={top} width={14} height={h * 0.09} fill="#000" stroke={WHITE} strokeWidth={2.5} />
        <rect x={cx - w / 2 - 34} y={bodyTop + 14} width={34} height={14} fill="#000" stroke={WHITE} strokeWidth={2.5} />
        <rect x={cx + w / 2} y={bodyTop + 14} width={34} height={14} fill="#000" stroke={WHITE} strokeWidth={2.5} />
        <rect x={cx - w / 2 + 3} y={liq} width={w - 6} height={Math.max(0, bodyTop + bodyH - liq - 3)} rx={10} fill={accent} opacity={0.28} />
        <line x1={cx - w / 2 + 6} y1={liq} x2={cx + w / 2 - 6} y2={liq} stroke={accent} strokeWidth={2.5} style={{filter: 'drop-shadow(0 0 6px rgba(102,45,248,.8))'}} />
        <line x1={cx} y1={bodyTop + 8} x2={cx} y2={cy + bodyH * 0.22} stroke={WHITE} strokeWidth={2.5} />
        <g transform={`rotate(${spin} ${cx} ${cy + bodyH * 0.22})`}>
          <rect x={cx - w * 0.3} y={cy + bodyH * 0.22 - 3} width={w * 0.6} height={6} rx={3} fill="none" stroke={WHITE} strokeWidth={2.5} />
        </g>
        {flame(-w * 0.25)}{flame(0)}{flame(w * 0.25)}
      </svg>
      {label ? <CText cx={cx} cy={bot + 66} size={24} weight={600} color={GREY}>{label}</CText> : null}
    </div>
  );
};

/** 竖直温度带：min–max 刻度、lo–hi 合格绿带、上下警戒红纹、cursor 游标光点。 */
export const ThermoBand: React.FC<{x: number; y: number; w?: number; h?: number; min?: number; max?: number; lo?: number; hi?: number; cursor?: number | null; labels?: boolean; opacity?: number; accent?: string}> = ({x, y, w = 120, h = 420, min = 80, max = 150, lo = 100, hi = 130, cursor = null, labels = true, opacity = 1, accent = PURPLE}) => {
  const ty = (v: number) => y + h - ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * h;
  const tick = (v: number) => (
    <g key={v}>
      <line x1={x + w} y1={ty(v)} x2={x + w + 14} y2={ty(v)} stroke={WHITE} strokeWidth={2} />
      {labels ? <CText cx={x + w + 52} cy={ty(v)} size={26} weight={700} family={FONT_ORB}>{v}</CText> : null}
    </g>
  );
  return (
    <div style={svgBase(opacity)}>
      <svg width={1280} height={720} viewBox="0 0 1280 720" style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', filter: BLOOM_SOFT}}>
        <rect x={x} y={y} width={w} height={h} rx={10} fill="#000" stroke={WHITE} strokeWidth={2.5} />
        <rect x={x + 4} y={y + 4} width={w - 8} height={Math.max(0, ty(lo) - y - 4)} rx={8} fill={RED_DEEP} opacity={0.30} />
        <rect x={x + 4} y={ty(hi)} width={w - 8} height={Math.max(0, y + h - ty(hi) - 4)} rx={8} fill={RED_DEEP} opacity={0.30} />
        <rect x={x + 4} y={ty(hi)} width={w - 8} height={Math.max(0, ty(lo) - ty(hi))} fill={GREEN} opacity={0.16} />
        <line x1={x} y1={ty(hi)} x2={x + w} y2={ty(hi)} stroke={WHITE} strokeWidth={2} strokeDasharray="6 5" />
        <line x1={x} y1={ty(lo)} x2={x + w} y2={ty(lo)} stroke={WHITE} strokeWidth={2} strokeDasharray="6 5" />
        {tick(max)}{tick(hi)}{tick(lo)}{tick(min)}
        {cursor != null ? (
          <g style={{filter: `drop-shadow(0 0 8px ${accent})`}}>
            <circle cx={x + w / 2} cy={ty(cursor)} r={11} fill={accent} stroke={WHITE} strokeWidth={2.5} />
            <line x1={x + 8} y1={ty(cursor)} x2={x + w - 8} y2={ty(cursor)} stroke={PURPLE_PALE} strokeWidth={2} opacity={0.7} />
          </g>
        ) : null}
      </svg>
    </div>
  );
};

/** 大船侧影（比喻）：tilt 正值为右倾；底部虚线水线。 */
export const ShipIcon: React.FC<{cx: number; cy: number; w?: number; tilt?: number; opacity?: number}> = ({cx, cy, w = 460, tilt = 0, opacity = 1}) => {
  const h = w * 0.34;
  return (
    <div style={svgBase(opacity)}>
      <svg width={1280} height={720} viewBox="0 0 1280 720" style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', filter: BLOOM_SOFT}}>
        <g transform={`rotate(${tilt} ${cx} ${cy})`}>
          <path d={`M${cx - w / 2},${cy - h * 0.12} L${cx - w * 0.42},${cy - h * 0.30} L${cx + w * 0.30},${cy - h * 0.30} L${cx + w * 0.30},${cy - h * 0.05} L${cx + w / 2},${cy - h * 0.02} L${cx + w * 0.30},${cy + h * 0.28} Q${cx},${cy + h * 0.34} ${cx - w * 0.28},${cy + h * 0.28} Z`} fill="#000" stroke={WHITE} strokeWidth={2.5} strokeLinejoin="round" />
          <rect x={cx - w * 0.22} y={cy - h * 0.52} width={w * 0.14} height={h * 0.22} fill="#000" stroke={WHITE} strokeWidth={2.5} />
          <rect x={cx - w * 0.02} y={cy - h * 0.58} width={w * 0.20} height={h * 0.28} fill="#000" stroke={WHITE} strokeWidth={2.5} />
          {[0.1, 0.28].map((f, i) => <circle key={i} cx={cx + w * (f - 0.12)} cy={cy - h * 0.44} r={4} fill={PURPLE_PALE} opacity={0.8} />)}
        </g>
        <line x1={cx - w * 0.62} y1={cy + h * 0.24} x2={cx + w * 0.66} y2={cy + h * 0.24} stroke={GREY} strokeWidth={2} strokeDasharray="10 8" opacity={0.7} />
      </svg>
    </div>
  );
};

/** 舵轮：外环 + 8 辐条 + 把手球，spin 旋转角。 */
export const HelmIcon: React.FC<{cx: number; cy: number; r?: number; spin?: number; opacity?: number; accent?: string}> = ({cx, cy, r = 110, spin = 0, opacity = 1, accent = PURPLE}) => (
  <div style={svgBase(opacity)}>
    <svg width={1280} height={720} viewBox="0 0 1280 720" style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', filter: BLOOM_SOFT}}>
      <g transform={`rotate(${spin} ${cx} ${cy})`}>
        <circle cx={cx} cy={cy} r={r} fill="#000" stroke={WHITE} strokeWidth={6} />
        <circle cx={cx} cy={cy} r={r * 0.22} fill="#000" stroke={WHITE} strokeWidth={4} />
        {Array.from({length: 8}, (_, i) => {
          const a = (i * Math.PI) / 4;
          return <line key={i} x1={cx + r * 0.22 * Math.cos(a)} y1={cy + r * 0.22 * Math.sin(a)} x2={cx + r * Math.cos(a)} y2={cy + r * Math.sin(a)} stroke={WHITE} strokeWidth={4} />;
        })}
        {Array.from({length: 8}, (_, i) => {
          const a = (i * Math.PI) / 4 + Math.PI / 8;
          return <circle key={i} cx={cx + (r + 10) * Math.cos(a)} cy={cy + (r + 10) * Math.sin(a)} r={6} fill={accent} stroke={WHITE} strokeWidth={2} />;
        })}
      </g>
    </svg>
  </div>
);

/** 齿轮：teeth 齿、spin 旋转角。 */
export const GearIcon: React.FC<{cx: number; cy: number; r?: number; teeth?: number; spin?: number; color?: string; accent?: string; opacity?: number}> = ({cx, cy, r = 120, teeth = 12, spin = 0, color = WHITE, accent = PURPLE, opacity = 1}) => {
  const inner = r * 0.74;
  const pts: string[] = [];
  for (let i = 0; i < teeth * 2; i++) {
    const a0 = ((i - 0.5) * Math.PI) / teeth, a1 = ((i + 0.5) * Math.PI) / teeth;
    const rad = i % 2 === 0 ? r : inner;
    pts.push(`${i === 0 ? 'M' : 'L'}${(cx + rad * Math.cos(a0)).toFixed(1)},${(cy + rad * Math.sin(a0)).toFixed(1)}`);
    pts.push(`L${(cx + rad * Math.cos(a1)).toFixed(1)},${(cy + rad * Math.sin(a1)).toFixed(1)}`);
  }
  return (
    <div style={svgBase(opacity)}>
      <svg width={1280} height={720} viewBox="0 0 1280 720" style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', filter: BLOOM_SOFT}}>
        <g transform={`rotate(${spin} ${cx} ${cy})`}>
          <path d={pts.join(' ') + ' Z'} fill="#000" stroke={color} strokeWidth={2.5} strokeLinejoin="round" />
          <circle cx={cx} cy={cy} r={inner * 0.62} fill="none" stroke={color} strokeWidth={2.5} />
          <circle cx={cx} cy={cy} r={inner * 0.24} fill="none" stroke={accent} strokeWidth={2.5} style={{filter: `drop-shadow(0 0 6px ${accent})`}} />
        </g>
      </svg>
    </div>
  );
};
