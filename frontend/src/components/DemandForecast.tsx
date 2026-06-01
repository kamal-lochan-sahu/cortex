'use client';
import React, { useEffect, useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';

interface ForecastPoint {
  ds:          string;
  yhat:        number;
  yhat_lower:  number;
  yhat_upper:  number;
  hour:        number;
}

interface ForecastData {
  forecast:     ForecastPoint[];
  generated_at: string;
  agent:        string;
}

const ORACLE_PURPLE = '#7C3AED';

function formatHour(ds: string): string {
  try {
    const d = new Date(ds);
    return d.getUTCHours().toString().padStart(2, '0') + ':00';
  } catch { return ''; }
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="bg-slate-900 border border-purple-800/40 rounded-lg px-3 py-2 text-xs font-mono shadow-xl">
      <p className="text-purple-400 mb-1">{formatHour(d.ds)}</p>
      <p className="text-white">forecast: <span className="text-purple-300">{d.yhat} u/hr</span></p>
      <p className="text-slate-400">low: {d.yhat_lower} — high: {d.yhat_upper}</p>
    </div>
  );
};

export default function DemandForecast() {
  const [data, setData]       = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');

  useEffect(() => {
    fetch('http://localhost:8000/api/oracle/demand-forecast')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setError('Fetch failed'); setLoading(false); });
  }, []);

  // Find current hour index for reference line
  const currentHour = new Date().getUTCHours();

  if (loading) return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 flex items-center justify-center h-64">
      <span className="text-slate-500 font-mono text-sm animate-pulse">ORACLE loading forecast...</span>
    </div>
  );
  if (error || !data) return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 flex items-center justify-center h-64">
      <span className="text-red-400 font-mono text-sm">forecast unavailable</span>
    </div>
  );

  const chartData = data.forecast.map(p => ({
    ...p,
    label:    formatHour(p.ds),
    band:     [p.yhat_lower, p.yhat_upper] as [number, number],
  }));

  // Current hour reference index
  const refHour = chartData.findIndex(p => {
    const h = new Date(p.ds).getUTCHours();
    return h === currentHour;
  });

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-purple-500 animate-pulse" />
          <span className="text-xs font-mono text-slate-400 uppercase tracking-widest">
            ORACLE · Demand Forecast
          </span>
        </div>
        <span className="text-xs font-mono text-slate-600">next 24h</span>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
          <defs>
            {/* Confidence band gradient */}
            <linearGradient id="bandGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={ORACLE_PURPLE} stopOpacity={0.15} />
              <stop offset="95%" stopColor={ORACLE_PURPLE} stopOpacity={0.02} />
            </linearGradient>
            {/* Main forecast gradient */}
            <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={ORACLE_PURPLE} stopOpacity={0.4} />
              <stop offset="95%" stopColor={ORACLE_PURPLE} stopOpacity={0.0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />

          <XAxis
            dataKey="label"
            tick={{ fill: '#475569', fontSize: 10, fontFamily: 'monospace' }}
            tickLine={false}
            axisLine={false}
            interval={3}
          />
          <YAxis
            tick={{ fill: '#475569', fontSize: 10, fontFamily: 'monospace' }}
            tickLine={false}
            axisLine={false}
          />

          <Tooltip content={<CustomTooltip />} />

          {/* Current time reference line */}
          {refHour >= 0 && (
            <ReferenceLine
              x={chartData[refHour]?.label}
              stroke="#7C3AED"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              label={{ value: 'NOW', fill: '#7C3AED', fontSize: 9, fontFamily: 'monospace' }}
            />
          )}

          {/* Upper confidence band */}
          <Area
            type="monotone"
            dataKey="yhat_upper"
            stroke="none"
            fill="url(#bandGrad)"
            fillOpacity={1}
          />
          {/* Lower confidence band — fills below, creating band effect */}
          <Area
            type="monotone"
            dataKey="yhat_lower"
            stroke="none"
            fill="#0f172a"
            fillOpacity={1}
          />
          {/* Main forecast line */}
          <Area
            type="monotone"
            dataKey="yhat"
            stroke={ORACLE_PURPLE}
            strokeWidth={2}
            fill="url(#forecastGrad)"
            dot={false}
            activeDot={{ r: 4, fill: ORACLE_PURPLE, stroke: '#fff', strokeWidth: 1 }}
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3">
        <div className="flex items-center gap-1.5">
          <div className="w-4 h-0.5 bg-purple-500" />
          <span className="text-xs font-mono text-slate-500">forecast</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-4 h-3 rounded-sm" style={{ background: 'rgba(124,58,237,0.15)' }} />
          <span className="text-xs font-mono text-slate-500">confidence band</span>
        </div>
        <div className="ml-auto text-xs font-mono text-slate-600">
          {data.agent} · fallback
        </div>
      </div>
    </div>
  );
}
