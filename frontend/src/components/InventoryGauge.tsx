'use client';
import React from 'react';

// ── Types ──────────────────────────────────────────────────
interface Component {
  component_id:       string;
  display_name:       string;
  current_stock:      number;
  safety_stock_level: number;
  reorder_point:      number;
  reorder_quantity:   number;
  unit_cost_eur:      number;
  daily_consumption:  number;
  days_of_stock:      number;
  risk_level:         'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  assigned_supplier:  string;
  pending_order:      boolean;
  last_reorder_at:    string | null;
}

interface Summary {
  total:    number;
  critical: number;
  high:     number;
  medium:   number;
  low:      number;
}

interface Props {
  components: Component[];
  summary:    Summary;
}

// ── Constants ──────────────────────────────────────────────
// HERMES orange theme — Phase 4 brand color
const HERMES_ORANGE = '#FF9100';

const RISK_CONFIG = {
  CRITICAL: { color: '#ef4444', bg: '#ef444420', border: '#ef444440', label: 'CRITICAL' },
  HIGH:     { color: '#f97316', bg: '#f9731620', border: '#f9731640', label: 'HIGH'     },
  MEDIUM:   { color: '#f59e0b', bg: '#f59e0b20', border: '#f59e0b40', label: 'MEDIUM'   },
  LOW:      { color: '#10b981', bg: '#10b98120', border: '#10b98140', label: 'LOW'      },
};

// ── Single Component Card ──────────────────────────────────
function ComponentCard({ c }: { c: Component }) {
  const cfg = RISK_CONFIG[c.risk_level];

  // Bar fill percentage — relative to reorder_quantity as max scale
  // 0% = empty, 100% = fully stocked (reorder_qty as reference)
  const maxScale  = c.reorder_quantity * 1.5;
  const fillPct   = Math.min(100, Math.round((c.current_stock / maxScale) * 100));

  // Bar color logic:
  // green  → above safety_stock
  // orange → between reorder_point and safety_stock
  // red    → below reorder_point
  const barColor =
    c.current_stock > c.safety_stock_level ? '#10b981' :
    c.current_stock > c.reorder_point      ? '#f97316' :
    '#ef4444';

  // Short name for display (max 14 chars)
  const shortName = c.display_name.length > 16
    ? c.display_name.slice(0, 14) + '…'
    : c.display_name;

  return (
    <div
      className="p-3 bg-slate-900 rounded-xl border transition-all duration-300"
      style={{
        borderColor: c.pending_order ? HERMES_ORANGE + '60' : '#1e293b',
        boxShadow:   c.risk_level === 'CRITICAL'
                     ? `0 0 12px ${cfg.color}30`
                     : 'none',
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-mono text-slate-300 truncate" title={c.display_name}>
          {shortName}
        </span>

        {/* Risk badge — pulses if order pending */}
        <span
          className={`text-xs font-bold px-2 py-0.5 rounded-full ${c.pending_order ? 'animate-pulse' : ''}`}
          style={{
            backgroundColor: cfg.bg,
            color:            cfg.color,
            border:           `1px solid ${cfg.border}`,
          }}
        >
          {cfg.label}
        </span>
      </div>

      {/* Stock number */}
      <div className="flex items-baseline gap-1 mb-2">
        <span className="text-2xl font-bold font-mono" style={{ color: barColor }}>
          {c.current_stock}
        </span>
        <span className="text-xs text-slate-500">units</span>
        <span className="ml-auto text-xs font-mono text-slate-500">
          {c.days_of_stock}d
        </span>
      </div>

      {/* Horizontal stock bar */}
      <div className="relative h-2 bg-slate-800 rounded-full overflow-hidden mb-2">
        {/* Fill bar */}
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${fillPct}%`, backgroundColor: barColor }}
        />
        {/* Safety stock marker line */}
        <div
          className="absolute top-0 bottom-0 w-px bg-yellow-400 opacity-70"
          style={{
            left: `${Math.min(100, Math.round((c.safety_stock_level / maxScale) * 100))}%`,
          }}
          title={`Safety stock: ${c.safety_stock_level}`}
        />
        {/* Reorder point marker line */}
        <div
          className="absolute top-0 bottom-0 w-px bg-red-500 opacity-70"
          style={{
            left: `${Math.min(100, Math.round((c.reorder_point / maxScale) * 100))}%`,
          }}
          title={`Reorder point: ${c.reorder_point}`}
        />
      </div>

      {/* Footer row */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-600 font-mono">
          {c.assigned_supplier}
        </span>
        {c.pending_order && (
          <span
            className="text-xs font-mono animate-pulse"
            style={{ color: HERMES_ORANGE }}
          >
            ⟳ ORDER
          </span>
        )}
      </div>
    </div>
  );
}

// ── Summary Bar ────────────────────────────────────────────
function SummaryBar({ summary }: { summary: Summary }) {
  const items = [
    { label: 'CRITICAL', count: summary.critical, color: '#ef4444' },
    { label: 'HIGH',     count: summary.high,     color: '#f97316' },
    { label: 'MEDIUM',   count: summary.medium,   color: '#f59e0b' },
    { label: 'LOW',      count: summary.low,      color: '#10b981' },
  ];
  return (
    <div className="flex items-center gap-3 mb-3 flex-wrap">
      {items.map(({ label, count, color }) => (
        <div key={label} className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
          <span className="text-xs font-mono text-slate-400">
            {count} <span style={{ color }}>{label}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Main Export ────────────────────────────────────────────
export default function InventoryGauge({ components, summary }: Props) {
  if (!components || components.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
        HERMES initializing...
      </div>
    );
  }

  return (
    <div className="w-full">
      {/* Section header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full animate-pulse"
               style={{ backgroundColor: HERMES_ORANGE }} />
          <span className="text-xs font-mono font-bold uppercase tracking-wider"
                style={{ color: HERMES_ORANGE }}>
            Inventory Monitor
          </span>
        </div>
        <span className="text-xs font-mono text-slate-500">
          {summary.total} components
        </span>
      </div>

      {/* Summary pills */}
      <SummaryBar summary={summary} />

      {/* 2x5 grid — 10 components */}
      <div className="grid grid-cols-2 gap-2">
        {components.map(c => (
          <ComponentCard key={c.component_id} c={c} />
        ))}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 pt-3 border-t border-slate-800">
        <span className="text-xs text-slate-600">Bar markers:</span>
        <div className="flex items-center gap-1">
          <div className="w-px h-3 bg-yellow-400" />
          <span className="text-xs text-slate-600">Safety stock</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-px h-3 bg-red-500" />
          <span className="text-xs text-slate-600">Reorder point</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full"
               style={{ backgroundColor: HERMES_ORANGE }} />
          <span className="text-xs text-slate-600">Pending order</span>
        </div>
      </div>
    </div>
  );
}
