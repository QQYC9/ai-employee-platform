export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  tenant_id?: string | null;
  status: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface PlatformSummary {
  tenants: {
    total: number;
    by_status: Record<string, number>;
  };
  agents: {
    total: number;
    by_status: Record<string, number>;
  };
  tasks: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
    in_progress: number;
    tasks_with_errors: number;
    success_rate_pct: number;
    failure_rate_pct: number;
  };
  channels: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
  };
  outbox: {
    total: number;
    by_status: Record<string, number>;
    dead_letter: number;
    stuck_processing: number;
  };
  ai_usage: {
    total_requests: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    avg_duration_ms: number;
    error_requests: number;
    fallback_requests: number;
  };
  audit: {
    recent_events_24h: number;
  };
  generated_at: string;
}

export interface OperationalComponent {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  details: Record<string, any>;
}

export interface OperationalHealth {
  overall_status?: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  components?: {
    database?: OperationalComponent;
    outbox?: OperationalComponent;
    stalled_tasks?: OperationalComponent;
    ai_providers?: OperationalComponent;
    [key: string]: OperationalComponent | undefined;
  };
  database?: OperationalComponent;
  outbox?: OperationalComponent;
  stalled_tasks?: OperationalComponent;
  checked_at?: string;
  [key: string]: any;
}

export interface TenantBudget {
  configured: boolean;
  daily_limit: number | null;
  monthly_limit: number | null;
  current_day_tokens: number;
  current_month_tokens: number;
  alert_level: 'none' | 'warning' | 'critical' | 'exceeded';
}

export interface TenantItem {
  id: string;
  name: string;
  slug: string;
  status: string;
  created_at: string | null;
  agent_count: number;
  task_count: number;
  failed_task_count: number;
  budget: TenantBudget;
}

export interface TenantsResponse {
  total: number;
  limit: number;
  offset: number;
  tenants: TenantItem[];
}

export interface AgentItem {
  id: string;
  name: string;
  agent_type: string;
  status: string;
}

export interface TaskItem {
  id: string;
  tenant_id: string;
  agent_id?: string | null;
  requested_by_user_id?: string | null;
  title: string;
  objective: string;
  status: string;
  priority: string;
  plan?: Record<string, any> | null;
  result?: Record<string, any> | null;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DailyTrend {
  date: string;
  requests: number;
  tokens: number;
  errors: number;
}

export interface PlatformMetrics {
  time_window_days: number;
  summary: {
    total_requests: number;
    successful_requests: number;
    error_requests: number;
    fallback_requests: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    avg_duration_ms: number;
    unique_tasks_invoked: number;
  };
  by_provider: Record<string, { requests: number; tokens: number; errors: number; fallbacks?: number }>;
  by_model: Record<string, { provider: string; requests: number; tokens: number; errors: number }>;
  daily_trends: DailyTrend[];
}

export interface AuditEventItem {
  id: string;
  tenant_id?: string | null;
  user_id?: string | null;
  agent_id?: string | null;
  event_type: string;
  action: string;
  description: string;
  event_metadata?: Record<string, any>;
  created_at?: string;
}

export interface AuditLogsResponse {
  limit: number;
  offset: number;
  events: AuditEventItem[];
}
