"use client";
import { useEffect, useRef, useState, useCallback } from "react";

export interface CortexEvent {
  event: string;
  cycle_id?: number;
  priority?: string;
  status?: string;
  score?: number;
  method?: string;
  flagged?: Array<{ sensor_id: string; value: number; normal_max: number }>;
  summary?: string;
  timestamp?: string;
  master_stats?: {
    master_status: string;
    cycles_completed: number;
    anomalies_found: number;
    anomaly_rate: number;
  };
  message?: string;
}

export function useWebSocket(url: string) {
  const [lastEvent, setLastEvent] = useState<CortexEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setConnected(true);
      console.log("[WS] Connected to CORTEX");
    };

    ws.onmessage = (e) => {
      try {
        const data: CortexEvent = JSON.parse(e.data);
        setLastEvent(data);
      } catch {}
    };

    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect after 3 seconds
      setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
    wsRef.current = ws;
  }, [url]);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return { lastEvent, connected };
}
