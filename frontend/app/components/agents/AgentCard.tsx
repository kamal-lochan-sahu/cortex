"use client";
import { Agent } from "@/types/cortex.types";

interface AgentCardProps {
  agent: Agent;
  isActive?: boolean;
  lastStatus?: string;
}

const STATUS_COLORS: Record<string, string> = {
  active:  "bg-green-500",
  idle:    "bg-yellow-500",
  error:   "bg-red-500",
  phase3:  "bg-gray-500",
  phase4:  "bg-gray-500",
};

const STATUS_LABELS: Record<string, string> = {
  active:  "ACTIVE",
  idle:    "IDLE",
  error:   "ERROR",
  phase3:  "PHASE 3",
  phase4:  "PHASE 4",
};

export default function AgentCard({ agent, isActive, lastStatus }: AgentCardProps) {
  const dotColor = STATUS_COLORS[agent.status] ?? "bg-gray-500";
  const label    = STATUS_LABELS[agent.status] ?? agent.status.toUpperCase();

  return (
    <div className={`
      rounded-lg border p-4 transition-all duration-300
      ${isActive ? "border-blue-500 bg-gray-900" : "border-gray-700 bg-gray-950"}
    `}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-white font-bold text-sm tracking-wider">{agent.id}</span>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${dotColor} ${agent.status === "active" ? "animate-pulse" : ""}`} />
          <span className="text-xs text-gray-400">{label}</span>
        </div>
      </div>
      <p className="text-gray-400 text-xs">{agent.role}</p>
      {lastStatus && (
        <p className={`text-xs mt-2 font-mono ${
          lastStatus === "ANOMALY_DETECTED" ? "text-red-400" : "text-green-400"
        }`}>
          {lastStatus === "ANOMALY_DETECTED" ? "⚠ ANOMALY" : "✓ NORMAL"}
        </p>
      )}
    </div>
  );
}
