'use client';
import React, { useEffect, useState } from 'react';

interface Window_ {
  machine:        string;
  window_start:   string;
  window_end:     string;
  score:          number;
  failure_prob:   number;
  demand_level:   number;
  impact:         'safe' | 'minor' | 'significant';
  impact_label:   string;
  risk_level:     string;
  confidence_pct: number;
}

interface MaintenanceData {
  windows:      Window_[];
  generated_at: string;
  agent:        string;
}

const IMPACT_STYLES = {
  safe:        { dot: '#10b981', badge: 'bg-emerald-900/40 text-emerald-400 border-emerald-700/40' },
  minor:       { dot: '#f59e0b', badge: 'bg-amber-900/40 text-amber-400 border-amber-700/40'     },
  significant: { dot: '#ef4444', badge: 'bg-red-900/40 text-red-400 border-red-700/40'           },
};

function formatWindowTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toUTCString().slice(0, 16) + ' ' +
      d.getUTCHours().toString().padStart(2,'0') + ':00 UTC';
  } catch { return iso; }
}

function formatShort(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { month:'short', day:'numeric' }) +
      ' ' + d.getUTCHours().toString().padStart(2,'0') + ':00';
  } catch { return iso; }
}

export default function MaintenanceList() {
  const [data, setData]       = useState<MaintenanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://localhost:8000/api/oracle/maintenance-windows')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      <span className="text-slate-500 font-mono text-sm animate-pulse">
        ORACLE computing windows...
      </span>
    </div>
  );

  if (!data?.windows?.length) return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      <span className="text-slate-500 font-mono text-sm">no windows available</span>
    </div>
  );

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-purple-500 animate-pulse" />
          <span className="text-xs font-mono text-slate-400 uppercase tracking-widest">
            ORACLE · Maintenance Windows
          </span>
        </div>
        <span className="text-xs font-mono text-slate-600">top 3</span>
      </div>

      {/* Window list */}
      <div className="space-y-3">
        {data.windows.map((w, i) => {
          const styles = IMPACT_STYLES[w.impact] ?? IMPACT_STYLES.safe;
          return (
            <div
              key={i}
              className="flex items-start gap-3 p-3 rounded-lg bg-slate-800/60 border border-slate-700/40
                         hover:border-slate-600/60 transition-colors duration-200"
            >
              {/* Rank */}
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-slate-700 flex items-center
                              justify-center text-xs font-mono text-slate-400 mt-0.5">
                {i + 1}
              </div>

              {/* Main content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-mono font-bold text-white">
                    Machine {w.machine}
                  </span>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-mono border ${styles.badge}`}>
                    {w.impact}
                  </span>
                  <span className="ml-auto text-xs font-mono text-slate-400">
                    {w.confidence_pct}% conf
                  </span>
                </div>

                <p className="text-xs font-mono text-slate-400 mb-2">
                  {formatShort(w.window_start)} → {formatShort(w.window_end)}
                </p>

                {/* Progress bars */}
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-600 w-16 font-mono">failure</span>
                    <div className="flex-1 h-1 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.round(w.failure_prob * 100)}%`,
                          backgroundColor: w.failure_prob > 0.7 ? '#ef4444' :
                                           w.failure_prob > 0.35 ? '#f59e0b' : '#10b981',
                        }}
                      />
                    </div>
                    <span className="text-xs font-mono text-slate-400 w-8 text-right">
                      {Math.round(w.failure_prob * 100)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-600 w-16 font-mono">demand</span>
                    <div className="flex-1 h-1 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full"
                        style={{ width: `${Math.round(w.demand_level * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-slate-400 w-8 text-right">
                      {Math.round(w.demand_level * 100)}%
                    </span>
                  </div>
                </div>

                <p className="text-xs text-slate-500 mt-2">{w.impact_label}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
