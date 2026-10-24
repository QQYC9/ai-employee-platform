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

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
}

export interface Agent {
  id: string;
  name: string;
  agent_type: string;
  status: string;
}

export interface Task {
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

export interface Channel {
  id: string;
  tenant_id: string;
  name: string;
  channel_type: string;
  provider?: string | null;
  status: string;
  config?: Record<string, any>;
  last_test_status?: string;
  last_test_result?: Record<string, any>;
  last_tested_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TenantBudgetStatus {
  configured: boolean;
  daily_limit: number | null;
  monthly_limit: number | null;
  current_day_tokens: number;
  current_month_tokens: number;
  daily_remaining?: number | null;
  monthly_remaining?: number | null;
  is_hard_limit?: boolean;
  alert_level: 'none' | 'normal' | 'warning' | 'critical' | 'exceeded' | string;
}

export interface TenantDashboardData {
  tenant: Tenant;
  agents: {
    total: number;
    by_status?: Record<string, number>;
    items: Agent[];
  };
  tasks: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
    in_progress: number;
    tasks_with_errors?: number;
    success_rate_pct: number;
    failure_rate_pct: number;
  };
  channels: {
    total: number;
    by_type?: Record<string, number>;
    items: Channel[];
  };
  outbox: {
    total: number;
    by_status: Record<string, number>;
    dead_letter: number;
    stuck_processing?: number;
  };
  budget: TenantBudgetStatus;
}

export interface DailyTrend {
  date: string;
  requests: number;
  tokens: number;
  errors: number;
}

export interface TenantMetrics {
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

export interface BusinessBrain {
  identity?: Record<string, any>;
  products?: Record<string, any>;
  services?: Record<string, any>;
  pricing?: Record<string, any>;
  brand?: Record<string, any>;
  customers?: Record<string, any>;
  policies?: Record<string, any>;
  goals?: Record<string, any>;
  [key: string]: any;
}

export interface CampaignMetrics {
  total_recipients: number;
  enqueued_count: number;
  sent_count: number;
  delivered_count: number;
  failed_count: number;
  skipped_count: number;
}

export interface Campaign {
  id: string;
  tenant_id: string;
  name: string;
  goal?: string | null;
  message_template: string;
  channel_id?: string | null;
  status: 'draft' | 'scheduled' | 'running' | 'paused' | 'completed' | 'cancelled' | string;
  audience_filter: Record<string, any>;
  scheduled_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metrics: CampaignMetrics;
  requires_approval: boolean;
  approval_id?: string | null;
  rate_limit_per_minute: number;
  batch_size: number;
  metadata_json?: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CampaignRecipient {
  id: string;
  tenant_id: string;
  campaign_id: string;
  customer_id: string;
  channel_id?: string | null;
  recipient_address: string;
  status: 'pending' | 'enqueued' | 'sent' | 'delivered' | 'failed' | 'skipped' | string;
  skip_reason?: string | null;
  error_message?: string | null;
  rendered_content?: string | null;
  sent_at?: string | null;
  delivered_at?: string | null;
  created_at?: string | null;
}
