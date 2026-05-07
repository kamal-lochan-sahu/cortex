"use client";
import { useEffect, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import AgentCard from "@/app/components/agents/AgentCard";
import { Agent, SentinelLog, MasterStats } from "@/types/cortex.types";

const WS_URL  = "ws://localhost:8000/ws";
const API_URL = "http://localhost:8000";

export default function Home() {
  const { lastEvent, connected } = useWebSocket(WS_URL);
  const [agents, setAgents]       = useState<Agent[]>([]);
  const [logs, setLogs]           = useState<SentinelLog[]>([]);
  const [masterStats, setMasterStats] = useState<MasterStats | null>(null);

  // Fetch initial data
  useEffect(() => {
    fetch(`${API_URL}/agents`)
      .then(r => r.json())
      .then(data => {
        setAgents(data.agents ?? []);
        setMasterStats(data.master ?? null);
      });
    fetch(`${API_URL}/agents/logs`)
      .then(r => r.json())
      .then(data => setLogs(data.logs ?? []));
  }, []);

  // Update on WebSocket events
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
    }
  }, [lastEvent]);

  return (
    <main className="min-h-screen bg-black text-white p-6">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-widest text-white">CORTEX</h1>
        <p className="text-gray-400 text-sm mt-1">Autonomous Multi-Agent Industrial Intelligence</p>
        <div className="flex items-center gap-2 mt-2">
          <div className={`w-2 h-2 rounded-full ${connected ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
          <span className="text-xs text-gray-400">{connected ? "WebSocket Connected" : "Reconnecting..."}</span>
        </div>
      </div>

      {/* Master Stats */}
      {masterStats && (
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[
            { label: "CYCLES",    value: masterStats.cycles_completed },
            { label: "ANOMALIES", value: masterStats.anomalies_found },
            { label: "RATE",      value: `${masterStats.anomaly_rate}%` },
            { label: "STATUS",    value: masterStats.master_status },
          ].map(stat => (
            <div key={stat.label} className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <p className="text-gray-400 text-xs tracking-widest">{stat.label}</p>
              <p className="text-white text-2xl font-bold mt-1">{stat.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Agent Grid */}
      <h2 className="text-gray-400 text-xs tracking-widest mb-3">AGENTS</h2>
      <div className="grid grid-cols-3 gap-3 mb-8">
        {agents.map(agent => (
          <AgentCard
            key={agent.id}
            agent={agent}
            isActive={agent.status === "active"}
            lastStatus={
              agent.id === "SENTINEL" ? lastEvent?.status : undefined
            }
          />
        ))}
      </div>

      {/* Live Log */}
      <h2 className="text-gray-400 text-xs tracking-widest mb-3">LIVE DETECTION LOG</h2>
      <div className="space-y-2">
        {logs.map((log, i) => (
          <div key={i} className={`
            flex items-center gap-4 p-3 rounded border text-xs font-mono
            ${log.status === "ANOMALY_DETECTED"
              ? "border-red-800 bg-red-950 text-red-300"
              : "border-gray-800 bg-gray-950 text-gray-400"}
          `}>
            <span className="w-24 shrink-0">
              {log.status === "ANOMALY_DETECTED" ? "⚠ ANOMALY" : "✓ NORMAL"}
            </span>
            <span className="w-16 shrink-0">s={log.anomaly_score?.toFixed(3)}</span>
            <span className="w-24 shrink-0">{log.detection_method}</span>
            <span className="truncate">{log.summary}</span>
          </div>
        ))}
      </div>
    </main>
  );
}
