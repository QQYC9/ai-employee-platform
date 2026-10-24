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

export interface PlatformIntegrationItem {
  id: string;
  tenant_id: string | null;
  name: string;
  provider: 'groq' | 'openai' | 'gemini' | string;
  status: 'active' | 'inactive' | 'disabled' | 'deleted' | string;
  model: string;
  base_url?: string | null;
  temperature: number;
  max_tokens?: number | null;
  is_default: boolean;
  masked_api_key: string;
  last_test_status: 'success' | 'failed' | 'untested' | string;
  last_test_result?: Record<string, any>;
  last_tested_at?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PlatformIntegrationCreatePayload {
  name: string;
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
  temperature?: number;
  max_tokens?: number;
  is_default?: boolean;
}

export interface PlatformIntegrationUpdatePayload {
  name?: string;
  model?: string;
  api_key?: string;
  base_url?: string;
  temperature?: number;
  max_tokens?: number;
  is_default?: boolean;
  status?: string;
}

export interface PlatformIntegrationTestResult {
  success: boolean;
  provider: string;
  model: string;
  latency_ms?: number;
  error_type?: string | null;
  error_message?: string | null;
}

export type TenantIntegrationItem = PlatformIntegrationItem;

export interface TenantChannelItem {
  id: string;
  tenant_id: string;
  name: string;
  channel_type: string;
  provider?: string | null;
  status: string;
  config: Record<string, any>;
  last_test_status?: string;
  last_test_result?: Record<string, any>;
  last_tested_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateTenantChannelPayload {
  name: string;
  channel_type: string;
  provider?: string | null;
  config?: Record<string, any>;
}

export interface UpdateTenantChannelPayload {
  name?: string;
  status?: string;
  provider?: string | null;
  config?: Record<string, any>;
}

export interface TenantChannelTestResult {
  connected?: boolean;
  success?: boolean;
  status?: string;
  latency_ms: number;
  error?: string | null;
  error_message?: string | null;
  error_type?: string | null;
  channel_id?: string;
  channel_type?: string;
  details?: Record<string, any>;
}

export interface CreateTenantIntegrationPayload {
  name: string;
  provider: 'groq' | 'openai' | 'gemini' | string;
  model: string;
  api_key?: string;
  base_url?: string;
  temperature?: number;
  max_tokens?: number;
  is_default?: boolean;
  extra_params?: Record<string, any>;
}

export type TenantIntegrationTestResult = PlatformIntegrationTestResult;

export interface TenantTasksResponse {
  total: number;
  limit: number;
  offset: number;
  tasks: TaskItem[];
}

export interface ExecutionTraceItem {
  id: string;
  trace_id: string;
  tenant_id: string;
  trigger_type: string;
  status: string;
  task_id?: string | null;
  agent_id?: string | null;
  conversation_id?: string | null;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  error_summary?: Record<string, any> | null;
  metadata_json?: Record<string, any>;
  step_count?: number;
}

export interface ExecutionTracesResponse {
  tenant_id: string;
  items: ExecutionTraceItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ExecutionStepItem {
  id: string;
  trace_id: string;
  step_order: number;
  step_type: string;
  step_name: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  attempt_count?: number;
  input_summary?: Record<string, any>;
  output_summary?: Record<string, any>;
  error_info?: Record<string, any> | null;
  children?: ExecutionStepItem[];
}

export interface CapabilityItem {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  config?: Record<string, any>;
  is_active: boolean;
  scope: 'tenant_custom' | 'global_shared';
  created_at?: string | null;
}

export interface CapabilityVersionItem {
  id: string;
  capability_id?: string | null;
  request_id?: string | null;
  version_number: number;
  slug: string;
  name: string;
  description?: string | null;
  risk_level: string;
  status: string;
  approval_id?: string | null;
  activated_at?: string | null;
  rolled_back_at?: string | null;
  rollback_reason?: string | null;
  created_at?: string | null;
}

export interface TenantCapabilitiesResponse {
  tenant_id: string;
  tenant_capabilities: CapabilityItem[];
  shared_capabilities: CapabilityItem[];
  self_development_versions: CapabilityVersionItem[];
}

export interface TenantErrorsResponse {
  tenant_id: string;
  total_errors: number;
  tasks_errors: Array<{
    id: string;
    task_title: string;
    status: string;
    error_message?: string | null;
    agent_id?: string | null;
    occurred_at?: string | null;
  }>;
  traces_errors: Array<{
    id: string;
    trace_id: string;
    trigger_type: string;
    task_id?: string | null;
    agent_id?: string | null;
    error_summary?: Record<string, any> | null;
    occurred_at?: string | null;
  }>;
  ai_errors: Array<{
    id: string;
    provider: string;
    model: string;
    error_category?: string | null;
    error_message?: string | null;
    task_id?: string | null;
    occurred_at?: string | null;
  }>;
  outbox_errors: Array<{
    id: string;
    event_type: string;
    status: string;
    retry_count: number;
    error_message?: string | null;
    occurred_at?: string | null;
  }>;
}

export interface TenantDashboardData {
  tenant: {
    id: string;
    name: string;
    slug: string;
    status: string;
  };
  tasks: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
    in_progress: number;
    success_rate_pct: number;
    failure_rate_pct: number;
    avg_execution_latency_sec: number;
  };
  agents: {
    total: number;
    items: Array<{
      id: string;
      name: string;
      agent_type: string;
      status: string;
      created_at?: string | null;
    }>;
  };
  channels: {
    total: number;
    items: Array<{
      id: string;
      name: string;
      channel_type: string;
      provider?: string | null;
      status: string;
      config: Record<string, any>;
      created_at?: string | null;
    }>;
  };
  outbox: {
    total: number;
    by_status: Record<string, number>;
    dead_letter: number;
  };
  budget: TenantBudget;
  recent_audit_events: Array<{
    id: string;
    event_type: string;
    action?: string | null;
    description?: string | null;
    user_id?: string | null;
    agent_id?: string | null;
    created_at?: string | null;
  }>;
  generated_at: string;
}

