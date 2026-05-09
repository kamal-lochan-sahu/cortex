
'use client';
import React, { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceDot,
} from 'recharts';

interface Reading {
  timestamp: string;
  value: number;
  is_anomaly: boolean;
  anomaly_score: number;
}
interface Props {
  sensorId: string;
  data: Reading[];
  color?: string;
  unit?: string;
  height?: number;
}

const COLORS: Record<string, string> = {
  temp_01: '#f97316', vib_01: '#8b5cf6', pres_01: '#3b82f6',
  curr_01: '#10b981', cool_01: '#06b6d4', pow_01:  '#f59e0b',
  torque_01: '#ec4899',
};

export default function SensorChart({ sensorId, data, color, unit = '', height = 200 }: Props) {
  const c = color || COLORS[sensorId] || '#64748b';

  const chartData = useMemo(() =>
    data.slice(-50).map((d, i) => ({
      ...d,
      i,
      time: new Date(d.timestamp).toLocaleTimeString('en-US',
        { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    })), [data]
  );

  const anomalies = chartData.filter(d => d.is_anomaly);
  const latest    = data.length > 0 ? data[data.length - 1]?.value : null;

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-slate-400">{sensorId}</span>
        {latest !== null && (
          <span className="text-xs font-mono" style={{ color: c }}>
            {latest.toFixed(3)} {unit}
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="time" tick={{ fontSize: 9, fill: '#475569' }}
                 interval="preserveStartEnd" tickLine={false} />
          <YAxis tick={{ fontSize: 9, fill: '#475569' }} tickLine={false}
                 axisLine={false} width={45} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #1e293b',
                           borderRadius: '6px', fontSize: '11px', color: '#e2e8f0' }}
            formatter={(val: number) => [`\${val?.toFixed(4)} \${unit}`, sensorId]}
            labelFormatter={(l) => `Time: \${l}`}
          />
          <Line type="monotone" dataKey="value" stroke={c} strokeWidth={1.5}
                dot={false} isAnimationActive={false} />
          {anomalies.map((p, i) => (
            <ReferenceDot key={i} x={p.time} y={p.value}
                          r={4} fill="#ef4444" stroke="#fca5a5" strokeWidth={1} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
