// API client — typed wrappers for all DRI backend endpoints

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(`${BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface HealthData {
  status: string;
  version: string;
  timestamp: string;
  uptime_seconds: number;
  metrics_processed: number;
  alerts_generated: number;
  actions_executed: number;
}

export interface ContainerMetrics {
  container_id: string;
  container_name: string;
  timestamp: string;
  cpu_percent: number;
  cpu_percent_5m: number;
  cpu_percent_15m: number;
  cpu_percent_60m: number;
  memory_percent: number;
  memory_percent_5m: number;
  memory_percent_15m: number;
  memory_percent_60m: number;
  memory_growth_rate_1m: number;
  memory_growth_rate_5m: number;
  is_anomaly: boolean;
  anomaly_type?: string;
}

export interface MetricsList {
  timestamp: string;
  containers: ContainerMetrics[];
  total_count: number;
}

export interface Alert {
  alert_id: string;
  container_id: string;
  container_name: string;
  timestamp: string;
  alert_type: string;
  metric: string;
  current_value: number;
  threshold: number;
  message: string;
  acknowledged: boolean;
}

export interface AlertsData {
  timestamp: string;
  alerts: Alert[];
  total_count: number;
}

export interface ActionRecord {
  action_id: string;
  container_id: string;
  container_name: string;
  timestamp: string;
  action_type: string;
  reason: string;
  success: boolean;
  error_message?: string;
}

export interface ActionsData {
  timestamp: string;
  actions: ActionRecord[];
  total_count: number;
}

export interface Recommendation {
  container_id: string;
  container_name: string;
  recommended_cpu_pct: number;
  recommended_memory_bytes: number;
  p95_cpu: number;
  p95_memory_bytes: number;
  p95_memory_pct: number;
  sample_count: number;
  lookback_days: number;
  lookback_actual_days: number;
  safety_margin: number;
  data_completeness?: string;
  confidence_tier: string;   // "low" | "medium" | "high"
  is_memory_leak: boolean;
  memory_leak_slope_pct_per_hour: number;
  is_idle: boolean;
  idle_recommendation?: string;
  computed_at?: string;
}

export interface RecommendationsData {
  timestamp: string;
  recommendations: Recommendation[];
  total_count: number;
}

export interface ForecastData {
  container_id: string;
  metric: string;
  horizon_hours: number;
  current_value: number;
  predicted_value: number;
  confidence_low: number;
  confidence_high: number;
  predicted_at: string;
  method_used: string;
  sample_count: number;
  computed_at?: string;
}

// ── API Functions ──────────────────────────────────────────────────────────

export const api = {
  health: () => get<HealthData>('/api/v1/health'),
  metrics: (container_id?: string) =>
    get<MetricsList>('/api/v1/metrics', container_id ? { container_id } : undefined),
  alerts: (limit = 100, offset = 0) =>
    get<AlertsData>('/api/v1/alerts', { limit, offset }),
  actions: (limit = 100, offset = 0) =>
    get<ActionsData>('/api/v1/actions/history', { limit, offset }),
  recommendations: (lookback_days = 7, safety_margin = 0.2) =>
    get<RecommendationsData>('/api/v1/recommendations', { lookback_days, safety_margin }),
  forecast: (container_id: string, horizon_hours = 24, metric = 'memory_percent') =>
    get<ForecastData>(`/api/v1/forecast/${container_id}`, { horizon_hours, metric }),
};
