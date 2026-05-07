export type AgentStatus = "active" | "idle" | "error" | "phase3" | "phase4";
export type Priority = "HIGH" | "MEDIUM" | "LOW";
export type DetectionStatus = "ANOMALY_DETECTED" | "ALL_NORMAL" | "UNKNOWN";

export interface Agent {
  id: string;
  status: AgentStatus;
  role: string;
}

export interface SentinelLog {
  id: number;
  status: DetectionStatus;
  anomaly_score: number;
  detection_method: string;
  flagged_sensors: Array<{ sensor_id: string; value: number; normal_max: number }>;
  summary: string;
  timestamp: string;
}

export interface MasterStats {
  master_status: string;
  started_at: string;
  cycles_completed: number;
  anomalies_found: number;
  anomaly_rate: number;
}
