"use client";
import { useEffect, useState, useCallback } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import AgentCard from "@/app/components/agents/AgentCard";
import SensorChart from "@/src/components/SensorChart";
import AnomalyTimeline from "@/src/components/AnomalyTimeline";
import ModelConfidence from "@/src/components/ModelConfidence";
import FailureGauge from "@/src/components/FailureGauge";
import DemandForecast from "@/src/components/DemandForecast";
import MaintenanceList from "@/src/components/MaintenanceList";
import EnergyPanel from "@/src/components/EnergyPanel";
import { Agent, SentinelLog, MasterStats } from "@/types/cortex.types";

const WS_URL  = "ws://localhost:8000/ws";
const API_URL = "http://localhost:8000";

export default function Home() {
  const { lastEvent, connected } = useWebSocket(WS_URL);
  const [agents, setAgents]           = useState<Agent[]>([]);
  const [logs, setLogs]               = useState<SentinelLog[]>([]);
  const [masterStats, setMasterStats] = useState<MasterStats | null>(null);
  const [cycleHistory, setCycleHistory] = useState<any[]>([]);
  const [sensorData, setSensorData]   = useState<Record<string, any[]>>({});
  const [oraclePreds, setOraclePreds] = useState<Record<string, any>>({});
  const [activeTab, setActiveTab]     = useState<"overview"|"sensors"|"oracle"|"operations"|"guardian">("overview");

  // ── Initial fetch ─────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_URL}/agents`)
      .then(r => r.json())
      .then(d => { setAgents(d.agents ?? []); setMasterStats(d.master ?? null); });
    fetch(`${API_URL}/agents/logs`)
      .then(r => r.json())
      .then(d => setLogs(d.logs ?? []));
    fetch(`${API_URL}/api/sentinel/anomalies`)
      .then(r => r.json())
      .then(d => setCycleHistory(d.results ?? []));
    fetch(`${API_URL}/api/sensors/history`)
      .then(r => r.json())
      .then(d => setSensorData(d.sensors ?? {}));
    fetch(`${API_URL}/api/oracle/predictions`)
      .then(r => r.json())
      .then(d => setOraclePreds(d.predictions ?? {}));
  }, []);

  // ── WebSocket updates ─────────────────────────────────────────
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.master_stats) setMasterStats(lastEvent.master_stats as any);
    if (lastEvent.event === "cycle_complete") {
      const newLog: SentinelLog = {
        id:               lastEvent.cycle_id ?? 0,
        status:           (lastEvent.status as any) ?? "UNKNOWN",
        anomaly_score:    lastEvent.score ?? 0,
        detection_method: lastEvent.method ?? "none",
        flagged_sensors:  lastEvent.flagged ?? [],
        summary:          lastEvent.summary ?? "",
        timestamp:        lastEvent.timestamp ?? "",
      };
      setLogs(prev => [newLog, ...prev].slice(0, 10));
      setCycleHistory(prev => [...prev, {
        timestamp:        lastEvent.timestamp,
        detection_method: lastEvent.method,
        if_score:         lastEvent.score ?? 0,
        lstm_score:       0,
        combined_score:   lastEvent.score ?? 0,
        status:           lastEvent.status,
        flagged_sensors:  (lastEvent.flagged ?? []).map((s: any) =>
          typeof s === "string" ? { sensor_id: s } : s),
      }].slice(-50));
    }
  }, [lastEvent]);

  // ── Sensor data polling every 10s ────────────────────────────
  useEffect(() => {
    const interval = setInterval(() => {
      fetch(`${API_URL}/api/sensors/history`)
        .then(r => r.json())
        .then(d => setSensorData(d.sensors ?? {}));
      fetch(`${API_URL}/api/oracle/predictions`)
        .then(r => r.json())
        .then(d => setOraclePreds(d.predictions ?? {}));
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const KEY_SENSORS = ["temp_01","vib_01","pres_01","curr_01"];
  const SENSOR_UNITS: Record<string,string> = {
    temp_01:"C", vib_01:"mm/s", pres_01:"bar", curr_01:"A",
    cool_01:"C", pow_01:"W", torque_01:"Nm",
  };

  return (
    <main className="min-h-screen bg-[#0a0a0f] text-white">
      {/* ── Top Bar ── */}
      <div className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-widest text-white font-mono">CORTEX</h1>
          <p className="text-slate-500 text-xs mt-0.5">Autonomous Multi-Agent Industrial Intelligence · Phase 3</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
          <span className="text-xs text-slate-400 font-mono">{connected ? "LIVE" : "RECONNECTING"}</span>
        </div>
      </div>

      {/* ── Master Stats ── */}
      {masterStats && (
        <div className="grid grid-cols-4 gap-3 px-6 py-4 border-b border-slate-800">
          {[
            { label: "CYCLES",    value: masterStats.cycles_completed,           color: "text-white" },
            { label: "ANOMALIES", value: masterStats.anomalies_found,            color: "text-red-400" },
            { label: "RATE",      value: `${masterStats.anomaly_rate}%`,         color: "text-amber-400" },
            { label: "STATUS",    value: masterStats.master_status,              color: "text-emerald-400" },
          ].map(s => (
            <div key={s.label} className="bg-slate-900 border border-slate-800 rounded-lg p-4">
              <p className="text-slate-500 text-xs tracking-widest font-mono">{s.label}</p>
              <p className={`text-2xl font-bold mt-1 font-mono ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* ── Tab Nav ── */}
      <div className="flex gap-1 px-6 pt-4">
        {(["overview","sensors","oracle","operations","guardian"] as const).map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`px-4 py-1.5 rounded-md text-xs font-mono uppercase tracking-wider transition-colors
              ${activeTab===tab
                ? "bg-slate-700 text-white"
                : "text-slate-500 hover:text-slate-300"}`}>
            {tab}
          </button>
        ))}
      </div>

      <div className="px-6 pb-6 mt-4 space-y-6">

        {/* ════════════ OVERVIEW TAB ════════════ */}
        {activeTab === "overview" && (<>

          {/* Agents */}
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">AGENTS</h2>
            <div className="grid grid-cols-3 gap-3">
              {agents.map(agent => (
                <AgentCard key={agent.id} agent={agent}
                  isActive={agent.status === "active"}
                  lastStatus={agent.id==="SENTINEL" ? lastEvent?.status : undefined} />
              ))}
            </div>
          </section>

          {/* Anomaly Timeline */}
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">ANOMALY TIMELINE</h2>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <AnomalyTimeline events={cycleHistory} maxShow={20} />
            </div>
          </section>

          {/* Model Confidence */}
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">MODEL CONFIDENCE — IF vs LSTM</h2>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <ModelConfidence data={cycleHistory} maxBars={10} />
            </div>
          </section>

          {/* Live Log */}
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">LIVE DETECTION LOG</h2>
            <div className="space-y-1.5">
              {logs.map((log, i) => (
                <div key={i} className={`flex items-center gap-4 p-3 rounded-lg border text-xs font-mono
                  ${log.status==="ANOMALY_DETECTED"
                    ? "border-red-900 bg-red-950/50 text-red-300"
                    : "border-slate-800 bg-slate-900/50 text-slate-400"}`}>
                  <span className="w-24 shrink-0">{log.status==="ANOMALY_DETECTED" ? "⚠ ANOMALY" : "✓ NORMAL"}</span>
                  <span className="w-16 shrink-0">s={log.anomaly_score?.toFixed(3)}</span>
                  <span className="w-28 shrink-0">{log.detection_method}</span>
                  <span className="truncate text-slate-500">{log.summary}</span>
                </div>
              ))}
            </div>
          </section>
        </>)}

        {/* ════════════ SENSORS TAB ════════════ */}
        {activeTab === "sensors" && (<>
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">LIVE SENSOR STREAMS</h2>
            <div className="grid grid-cols-2 gap-4">
              {KEY_SENSORS.map(sid => (
                <div key={sid} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                  <SensorChart
                    sensorId={sid}
                    data={sensorData[sid] ?? []}
                    unit={SENSOR_UNITS[sid] ?? ""}
                    height={180}
                  />
                </div>
              ))}
            </div>
          </section>
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">ALL SENSOR STREAMS</h2>
            <div className="grid grid-cols-2 gap-4">
              {Object.keys(sensorData).filter(s => !KEY_SENSORS.includes(s)).map(sid => (
                <div key={sid} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                  <SensorChart
                    sensorId={sid}
                    data={sensorData[sid] ?? []}
                    unit={SENSOR_UNITS[sid] ?? ""}
                    height={140}
                  />
                </div>
              ))}
            </div>
          </section>
        </>)}

        {/* ════════════ ORACLE TAB ════════════ */}
        {activeTab === "oracle" && (<>
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">FAILURE PREDICTION — MACHINE A / B / C</h2>
            <FailureGauge predictions={oraclePreds} />
          </section>
          <section className="mt-4">
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">PREDICTION DETAILS</h2>
            <div className="space-y-2">
              {Object.values(oraclePreds).map((p: any) => (
                <div key={p.machine_id} className="bg-slate-900 border border-slate-800 rounded-xl p-4 font-mono text-xs">
                  <div className="flex justify-between items-center">
                    <span className="text-white font-bold">Machine {p.machine_id}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-bold
                      ${p.risk_level==="HIGH" ? "bg-red-900/50 text-red-400 border border-red-800"
                        : p.risk_level==="MEDIUM" ? "bg-amber-900/50 text-amber-400 border border-amber-800"
                        : "bg-emerald-900/50 text-emerald-400 border border-emerald-800"}`}>
                      {p.risk_level}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-3 mt-3">
                    {[["6h", p.failure_probability_6h], ["12h", p.failure_probability_12h],
                      ["24h", p.failure_probability_24h]].map(([h, v]: any) => (
                      <div key={h} className="text-center">
                        <p className="text-slate-500">{h} horizon</p>
                        <p className="text-xl font-bold text-white mt-1">{Math.round(v*100)}%</p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>)}


        {/* ════════════ OPERATIONS TAB ════════════ */}
        {activeTab === "operations" && (<>

          {/* Energy Panel + Demand Forecast side by side */}
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">
              OPTIMUS · ENERGY OPTIMIZATION
            </h2>
            <div className="grid grid-cols-3 gap-4">
              <div className="col-span-1">
                <EnergyPanel />
              </div>
              <div className="col-span-2">
                <DemandForecast />
              </div>
            </div>
          </section>

          {/* Maintenance Windows */}
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">
              ORACLE · MAINTENANCE WINDOWS
            </h2>
            <MaintenanceList />
          </section>

        </>)}

        {/* ════════════ GUARDIAN TAB ════════════ */}
        {activeTab === "guardian" && (<>
          <section>
            <h2 className="text-slate-500 text-xs tracking-widest font-mono mb-3">NETWORK SECURITY STATUS</h2>
            <GuardianPanel apiUrl={API_URL} />
          </section>
        </>)}

      </div>
    </main>
  );
}

// ── Guardian Panel ────────────────────────────────────────────────
function GuardianPanel({ apiUrl }: { apiUrl: string }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    const fetch_ = () =>
      fetch(`${apiUrl}/api/guardian/status`).then(r => r.json()).then(setData);
    fetch_();
    const t = setInterval(fetch_, 15000);
    return () => clearInterval(t);
  }, [apiUrl]);
  if (!data) return <div className="text-slate-500 text-sm font-mono">Loading...</div>;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <span className="font-mono text-lg font-bold text-white">GUARDIAN</span>
        <span className={`px-3 py-1 rounded-full text-xs font-mono font-bold
          ${data.status==="THREAT_DETECTED"
            ? "bg-red-900/50 text-red-400 border border-red-800"
            : "bg-emerald-900/50 text-emerald-400 border border-emerald-800"}`}>
          {data.status}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {Object.entries(data.network_features ?? {}).map(([k, v]: any) => (
          <div key={k} className="bg-slate-800 rounded-lg p-3">
            <p className="text-slate-500 text-xs font-mono">{k.replace(/_/g," ")}</p>
            <p className="text-white font-bold font-mono mt-1">{typeof v==="number" ? v.toFixed(2) : v}</p>
          </div>
        ))}
      </div>
      <p className="text-slate-400 text-xs font-mono mt-4">{data.summary}</p>
    </div>
  );
}