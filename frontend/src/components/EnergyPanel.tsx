'use client';
import React, { useEffect, useState, useRef } from 'react';

interface EnergyStatus {
  current_price_eur_mwh:    number;
  price_level:              'LOW' | 'MED' | 'HIGH';
  price_source:             string;
  current_action:           string;
  confidence:               number;
  auto_applied:             boolean;
  savings_this_cycle_eur:   number;
  savings_today_eur:        number;
  timestamp:                string;
  agent:                    string;
}

const ACTION_STYLES: Record<string, string> = {
  NORMAL:      'bg-slate-700/60 text-slate-300 border-slate-600/40',
  REDUCE_10:   'bg-blue-900/40 text-blue-400 border-blue-700/40',
  REDUCE_20:   'bg-blue-900/60 text-blue-300 border-blue-600/40',
  SHIFT_HEAVY: 'bg-emerald-900/40 text-emerald-400 border-emerald-700/40',
  PRE_COOL:    'bg-cyan-900/40 text-cyan-400 border-cyan-700/40',
};

const PRICE_COLOR: Record<string, string> = {
  LOW:  '#10b981',
  MED:  '#f59e0b',
  HIGH: '#ef4444',
};

// Count-up animation hook
function useCountUp(target: number, duration = 800) {
  const [value, setValue] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    const start    = prev.current;
    const diff     = target - start;
    const steps    = 30;
    const stepTime = duration / steps;
    let step       = 0;
    const timer = setInterval(() => {
      step++;
      setValue(start + diff * (step / steps));
      if (step >= steps) {
        clearInterval(timer);
        prev.current = target;
      }
    }, stepTime);
    return () => clearInterval(timer);
  }, [target]);
  return value;
}

export default function EnergyPanel() {
  const [data, setData]       = useState<EnergyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [prevPrice, setPrevPrice] = useState<number | null>(null);

  useEffect(() => {
    const load = () => {
      fetch('http://localhost:8000/api/optimus/energy-status')
        .then(r => r.json())
        .then(d => {
          setPrevPrice(data?.current_price_eur_mwh ?? null);
          setData(d);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    };
    load();
    const interval = setInterval(load, 15000); // refresh every 15s
    return () => clearInterval(interval);
  }, []);

  const animatedSavings = useCountUp(data?.savings_today_eur ?? 0);

  if (loading) return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5 h-full">
      <span className="text-slate-500 font-mono text-sm animate-pulse">
        OPTIMUS initializing...
      </span>
    </div>
  );

  if (!data) return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      <span className="text-red-400 font-mono text-sm">energy status unavailable</span>
    </div>
  );

  const priceColor   = PRICE_COLOR[data.price_level] ?? '#f59e0b';
  const actionStyle  = ACTION_STYLES[data.current_action] ?? ACTION_STYLES.NORMAL;
  const priceUp      = prevPrice !== null && data.current_price_eur_mwh > prevPrice;
  const priceDown    = prevPrice !== null && data.current_price_eur_mwh < prevPrice;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: '#00E676' }} />
          <span className="text-xs font-mono text-slate-400 uppercase tracking-widest">
            OPTIMUS · Energy
          </span>
        </div>
        <span className="text-xs font-mono text-slate-600">
          {data.price_source === 'entsoe_live' ? '🟢 live' : '🟡 synthetic'}
        </span>
      </div>

      {/* Live Energy Price */}
      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/40">
        <p className="text-xs font-mono text-slate-500 mb-1">EU ENERGY PRICE</p>
        <div className="flex items-end gap-2">
          <span className="text-3xl font-mono font-bold" style={{ color: priceColor }}>
            {data.current_price_eur_mwh.toFixed(1)}
          </span>
          <span className="text-sm font-mono text-slate-400 mb-1">EUR/MWh</span>
          {priceUp   && <span className="text-xs text-red-400 mb-1">↑</span>}
          {priceDown && <span className="text-xs text-emerald-400 mb-1">↓</span>}
          <span
            className="ml-auto text-xs font-mono px-2 py-0.5 rounded-full border"
            style={{
              color: priceColor,
              backgroundColor: `${priceColor}18`,
              borderColor: `${priceColor}40`,
            }}
          >
            {data.price_level}
          </span>
        </div>
      </div>

      {/* Current Action */}
      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/40">
        <p className="text-xs font-mono text-slate-500 mb-2">ACTIVE DECISION</p>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-lg text-sm font-mono font-bold border ${actionStyle}`}>
            {data.current_action}
          </span>
          {data.auto_applied && (
            <span className="text-xs font-mono text-emerald-500 border border-emerald-800/40
                             bg-emerald-900/20 px-2 py-0.5 rounded-full">
              AUTO
            </span>
          )}
          <span className="ml-auto text-xs font-mono text-slate-400">
            {Math.round(data.confidence * 100)}% conf
          </span>
        </div>
        {/* Confidence bar */}
        <div className="mt-2 h-1 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${Math.round(data.confidence * 100)}%`,
              backgroundColor: '#00E676',
            }}
          />
        </div>
      </div>

      {/* Savings Today */}
      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/40">
        <p className="text-xs font-mono text-slate-500 mb-1">SAVINGS TODAY</p>
        <div className="flex items-end gap-1">
          <span className="text-2xl font-mono font-bold text-emerald-400">
            €{animatedSavings.toFixed(2)}
          </span>
          <span className="text-xs font-mono text-slate-500 mb-1">saved</span>
        </div>
        <p className="text-xs font-mono text-slate-600 mt-1">
          this cycle: €{data.savings_this_cycle_eur.toFixed(4)}
        </p>
      </div>
    </div>
  );
}
