
'use client';
import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts';

interface Cycle {
  timestamp:        string;
  if_score:         number;
  lstm_score:       number;
  combined_score:   number;
  detection_method: string;
}
interface Props { data: Cycle[]; maxBars?: number; }

export default function ModelConfidence({ data, maxBars = 10 }: Props) {
  const recent = data.slice(-maxBars);
  const chartData = recent.map((d, i) => ({
    cycle: `C${data.length - maxBars + i + 1}`,
    'IF':       parseFloat(Math.abs(d.if_score).toFixed(4)),
    'LSTM':     parseFloat(Math.min(d.lstm_score, 3).toFixed(4)),
    method:     d.detection_method,
  }));

  if (!chartData.length)
    return <div className="flex items-center justify-center h-32 text-slate-500 text-sm">Waiting for cycles...</div>;

  const tip = ({ active, payload, label }: any) => {
    if (!active || !payload) return null;
    const item = recent[chartData.findIndex(d => d.cycle === label)];
    return (
      <div className="bg-slate-900 border border-slate-700 rounded p-3 text-xs">
        <p className="font-bold text-slate-200 mb-1">{label}</p>
        <p className="text-cyan-400">IF: {payload[0]?.value?.toFixed(4)}</p>
        <p className="text-purple-400">LSTM: {payload[1]?.value?.toFixed(4)}</p>
        <p className="text-slate-400 mt-1">Method: {item?.detection_method || '-'}</p>
      </div>
    );
  };

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="cycle" tick={{ fontSize: 10, fill: '#475569' }} />
          <YAxis tick={{ fontSize: 10, fill: '#475569' }} width={40} />
          <Tooltip content={tip} />
          <Legend wrapperStyle={{ fontSize: '11px', color: '#94a3b8' }} />
          <Bar dataKey="IF" fill="#06b6d4" radius={[2,2,0,0]} maxBarSize={20}>
            {chartData.map((e, i) => (
              <Cell key={i}
                fill={e.method==='both'||e.method==='isolation_forest' ? '#ef4444' : '#06b6d4'} />
            ))}
          </Bar>
          <Bar dataKey="LSTM" fill="#8b5cf6" radius={[2,2,0,0]} maxBarSize={20}>
            {chartData.map((e, i) => (
              <Cell key={i}
                fill={e.method==='both'||e.method==='lstm' ? '#ef4444' : '#8b5cf6'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-4 mt-1 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <span className="w-3 h-2 inline-block rounded" style={{background:'#06b6d4'}}/>IF (abs)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-2 inline-block rounded" style={{background:'#8b5cf6'}}/>LSTM (cap 3×)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-2 inline-block rounded" style={{background:'#ef4444'}}/>Flagged
        </span>
      </div>
    </div>
  );
}
