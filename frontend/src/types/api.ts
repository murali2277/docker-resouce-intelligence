/**
 * TypeScript definitions matching Pydantic models in src/dri/api/models.py
 */

export interface MetricsResponse {
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
  anomaly_type: string | null;
}

export interface ContainerMetricsListResponse {
  timestamp: string;
  containers: MetricsResponse[];
  total_count: number;
}

export interface AlertResponse {
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

export interface AlertsResponse {
  timestamp: string;
  alerts: AlertResponse[];
  total_count: number;
}

export interface ActionHistoryResponse {
  action_id: string;
  container_id: string;
  container_name: string;
  timestamp: string;
  action_type: string;
  reason: string;
  success: boolean;
  error_message: string | null;
}

export interface ActionHistoryListResponse {
  timestamp: string;
  actions: ActionHistoryResponse[];
  total_count: number;
}

export interface PolicyRule {
  metric: string;
  operator: string;
  value: number;
  duration_seconds: number;
  action: string;
  [key: string]: unknown;
}

export interface PolicyResponse {
  name: string;
  enabled: boolean;
  selector: Record<string, string>;
  rules: PolicyRule[];
}

export interface PoliciesResponse {
  timestamp: string;
  policies: PolicyResponse[];
  total_count: number;
}
