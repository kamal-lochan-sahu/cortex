'use client';
import React from 'react';

// ── Types ──────────────────────────────────────────────────
interface Supplier {
  supplier_id:            string;
  supplier_name:          string;
  otd_rate:               number;
  quality_rate:           number;
  reliability_score:      number;
  status:                 'PREFERRED' | 'ACTIVE' | 'AT_RISK' | 'SWITCHED';
  active_components_live: number;
  last_delay_at:          string | null;
  last_updated:           string;
}

interface Props {
  suppliers: Supplier[];
}

// ── Constants ──────────────────────────────────────────────
const HERMES_ORANGE = '#FF9100';

const STATUS_CONFIG = {
  PREFERRED: { color: '#10b981', bg: '#10b98115', border: '#10b98140', icon: '★' },
  ACTIVE:    { color: '#3b82f6', bg: '#3b82f615', border: '#3b82f640', icon: '●' },
  AT_RISK:   { color: '#ef4444', bg: '#ef444415', border: '#ef444440', icon: '⚠' },
  SWITCHED:  { color: '#8b5cf6', bg: '#8b5cf615', border: '#8b5cf640', icon: '⟳' },
};

// ── Score Bar ──────────────────────────────────────────────
function ScoreBar({
  value,
  max = 100,
  color,
}: {
  value: number;
  max?: number;
  color: string;
}) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-mono w-10 text-right" style={{ color }}>
        {value.toFixed(1)}%
      </span>
    </div>
  );
}

// ── Single Supplier Row ────────────────────────────────────
function SupplierRow({ s }: { s: Supplier }) {
  const cfg        = STATUS_CONFIG[s.status];
  const hasDelay   = s.last_delay_at !== null;

  // Score color: green >88, orange 78-88, red <78
  const scoreColor =
    s.reliability_score >= 88 ? '#10b981' :
    s.reliability_score >= 78 ? '#f59e0b' :
    '#ef4444';

  return (
    <div
      className="p-3 rounded-xl border transition-all duration-300"
      style={{
        backgroundColor: cfg.bg,
        borderColor:     cfg.border,
        boxShadow:       s.status === 'PREFERRED'
                         ? `0 0 10px ${cfg.color}20`
                         : 'none',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {/* Supplier ID badge */}
          <span
            className="text-xs font-mono font-bold px-2 py-0.5 rounded"
            style={{
              backgroundColor: '#0f172a',
              color:            HERMES_ORANGE,
              border:           `1px solid ${HERMES_ORANGE}40`,
            }}
          >
            {s.supplier_id}
          </span>
          <span className="text-sm font-medium text-slate-200 truncate max-w-32"
                title={s.supplier_name}>
            {s.supplier_name}
          </span>
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-1">
          {hasDelay && (
            <span
              className="text-xs px-1.5 py-0.5 rounded font-mono animate-pulse"
              style={{
                backgroundColor: '#ef444420',
                color:            '#ef4444',
                border:           '1px solid #ef444440',
              }}
            >
              DELAY
            </span>
          )}
          <span
            className="text-xs font-bold px-2 py-0.5 rounded-full"
            style={{
              backgroundColor: cfg.bg,
              color:            cfg.color,
              border:           `1px solid ${cfg.border}`,
            }}
          >
            {cfg.icon} {s.status}
          </span>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {/* Reliability Score */}
        <div className="col-span-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-slate-500">Reliability Score</span>
            <span
              className="text-sm font-bold font-mono"
              style={{ color: scoreColor }}
            >
              {s.reliability_score.toFixed(1)}
            </span>
          </div>
          <ScoreBar value={s.reliability_score} color={scoreColor} />
        </div>

        {/* OTD Rate */}
        <div>
          <span className="text-xs text-slate-500 block mb-1">OTD Rate</span>
          <ScoreBar
            value={s.otd_rate}
            color={s.otd_rate >= 90 ? '#10b981' : s.otd_rate >= 80 ? '#f59e0b' : '#ef4444'}
          />
        </div>

        {/* Quality Rate */}
        <div>
          <span className="text-xs text-slate-500 block mb-1">Quality</span>
          <ScoreBar
            value={s.quality_rate}
            color={s.quality_rate >= 90 ? '#10b981' : '#f59e0b'}
          />
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-3 pt-2 border-t border-slate-800">
        <span className="text-xs text-slate-500 font-mono">
          {s.active_components_live} active component
          {s.active_components_live !== 1 ? 's' : ''}
        </span>
        {hasDelay && s.last_delay_at && (
          <span className="text-xs text-red-400 font-mono">
            Last delay: {new Date(s.last_delay_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main Export ────────────────────────────────────────────
export default function SupplierMatrix({ suppliers }: Props) {
  if (!suppliers || suppliers.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
        HERMES loading suppliers...
      </div>
    );
  }

  const preferred = suppliers.find(s => s.status === 'PREFERRED');
  const atRisk    = suppliers.filter(s => s.status === 'AT_RISK');

  return (
    <div className="w-full">
      {/* Section header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full animate-pulse"
            style={{ backgroundColor: HERMES_ORANGE }}
          />
          <span
            className="text-xs font-mono font-bold uppercase tracking-wider"
            style={{ color: HERMES_ORANGE }}
          >
            Supplier Intelligence
          </span>
        </div>
        <div className="flex items-center gap-2">
          {atRisk.length > 0 && (
            <span className="text-xs font-mono text-red-400 animate-pulse">
              ⚠ {atRisk.length} AT_RISK
            </span>
          )}
          {preferred && (
            <span className="text-xs font-mono text-emerald-400">
              ★ {preferred.supplier_id}
            </span>
          )}
        </div>
      </div>

      {/* 2x2 grid — 4 suppliers */}
      <div className="grid grid-cols-2 gap-2">
        {suppliers.map(s => (
          <SupplierRow key={s.supplier_id} s={s} />
        ))}
      </div>

      {/* Score formula note */}
      <div className="mt-3 pt-3 border-t border-slate-800">
        <span className="text-xs text-slate-600 font-mono">
          Score = OTD×0.6 + Quality×0.3 + Price×0.1
        </span>
      </div>
    </div>
  );
}
