
'use client';
import React from 'react';
import { RadialBarChart, RadialBar, ResponsiveContainer } from 'recharts';

interface Prediction {
  machine_id:               string;
  failure_probability_6h:   number;
  failure_probability_12h:  number;
  failure_probability_24h:  number;
  risk_level:               'LOW' | 'MEDIUM' | 'HIGH';
  timestamp:                string;
}
interface Props { predictions: Record<string, Prediction>; }

const RISK_COLOR = { LOW: '#10b981', MEDIUM: '#f59e0b', HIGH: '#ef4444' };

function GaugeCard({ p }: { p: Prediction }) {
  const pct   = Math.round(p.failure_probability_6h * 100);
  const color = RISK_COLOR[p.risk_level];
  const data  = [{ value: pct, fill: color }, { value: 100 - pct, fill: '#1e293b' }];

  return (
    <div className="flex flex-col items-center p-4 bg-slate-900 rounded-xl border border-slate-800">
      <span className="text-xs font-mono text-slate-400 mb-2">Machine {p.machine_id}</span>
      <div className="relative w-32 h-20">
        <ResponsiveContainer width="100%" height={80}>
          <RadialBarChart cx="50%" cy="100%" innerRadius="60%" outerRadius="100%"
                          startAngle={180} endAngle={0} data={data}>
            <RadialBar dataKey="value" cornerRadius={4} background={false} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex items-end justify-center pb-0">
          <span className="text-2xl font-bold font-mono" style={{ color }}>{pct}%</span>
        </div>
      </div>
      <span className="mt-2 px-3 py-0.5 rounded-full text-xs font-bold"
            style={{ backgroundColor: `\${color}20`, color, border: `1px solid \${color}40` }}>
        {p.risk_level}
      </span>
      <div className="mt-3 w-full space-y-1">
        {([['6h', p.failure_probability_6h], ['12h', p.failure_probability_12h],
           ['24h', p.failure_probability_24h]] as [string, number][]).map(([label, val]) => (
          <div key={label} className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-6">{label}</span>
            <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-500"
                   style={{
                     width: `\${Math.round(val * 100)}%`,
                     backgroundColor: val>0.7 ? '#ef4444' : val>0.35 ? '#f59e0b' : '#10b981'
                   }} />
            </div>
            <span className="text-xs font-mono text-slate-400 w-8">{Math.round(val*100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function FailureGauge({ predictions }: Props) {
  const list = Object.values(predictions);
  if (!list.length)
    return <div className="flex items-center justify-center h-32 text-slate-500 text-sm">ORACLE initializing...</div>;
  return (
    <div className="grid grid-cols-3 gap-4 w-full">
      {list.map(p => <GaugeCard key={p.machine_id} p={p} />)}
    </div>
  );
}
