
'use client';
import React, { useState } from 'react';

interface AnomalyEvent {
  timestamp:        string;
  detection_method: 'isolation_forest' | 'lstm' | 'both' | 'none';
  combined_score:   number;
  if_score:         number;
  lstm_score:       number;
  flagged_sensors:  { sensor_id: string }[];
}
interface Props { events: AnomalyEvent[]; maxShow?: number; }

const STYLES = {
  isolation_forest: { bg: '#0e7490', border: '#06b6d4', label: 'IF'   },
  lstm:             { bg: '#6d28d9', border: '#8b5cf6', label: 'LSTM' },
  both:             { bg: '#991b1b', border: '#ef4444', label: 'BOTH' },
  none:             { bg: '#1e293b', border: '#475569', label: 'OK'   },
};

export default function AnomalyTimeline({ events, maxShow = 20 }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const anomalies = events.filter(e => e.detection_method !== 'none').slice(-maxShow).reverse();

  if (!anomalies.length)
    return <div className="flex items-center justify-center h-16 text-slate-500 text-sm">No anomalies yet</div>;

  return (
    <div className="w-full">
      <div className="flex items-end gap-3 overflow-x-auto pb-3 px-2 min-w-max">
        {anomalies.map((ev, idx) => {
          const s    = STYLES[ev.detection_method] || STYLES.none;
          const time = new Date(ev.timestamp).toLocaleTimeString('en-US',
            { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          return (
            <div key={idx} className="relative flex flex-col items-center gap-1"
                 onMouseEnter={() => setHovered(idx)}
                 onMouseLeave={() => setHovered(null)}>
              {hovered === idx && (
                <div className="absolute bottom-full mb-2 z-20 w-52 bg-slate-900
                                border border-slate-700 rounded-lg p-3 text-xs shadow-xl">
                  <p className="font-bold mb-1" style={{ color: s.border }}>
                    {ev.detection_method.toUpperCase()}
                  </p>
                  <p className="text-slate-400">{time}</p>
                  <p className="text-slate-400 mt-1">IF: {ev.if_score?.toFixed(4)}</p>
                  <p className="text-slate-400">LSTM: {ev.lstm_score?.toFixed(4)}</p>
                  <p className="text-slate-400">Combined: {ev.combined_score?.toFixed(4)}</p>
                  <p className="text-slate-500 mt-1 truncate text-xs">
                    {ev.flagged_sensors?.map(s => s.sensor_id).join(', ')}
                  </p>
                </div>
              )}
              <div className="w-4 h-4 rounded-full cursor-pointer border-2 transition-transform"
                   style={{ backgroundColor: s.bg, borderColor: s.border,
                            transform: hovered === idx ? 'scale(1.5)' : 'scale(1)' }} />
              <span className="font-mono" style={{ color: s.border, fontSize: '8px' }}>
                {s.label}
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 mt-2">
        {(Object.entries(STYLES) as any[]).filter(([k]: any) => k !== 'none').map(([method, s]: any) => (
          <div key={method} className="flex items-center gap-1 text-xs">
            <div className="w-3 h-3 rounded-full border-2"
                 style={{ backgroundColor: s.bg, borderColor: s.border }} />
            <span className="text-slate-400">{method.replace('_',' ')}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
