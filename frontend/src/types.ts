export type UserRole = 'qa' | 'team_leader' | 'project_manager' | 'supervisor' | 'administrator';

export interface TenantReference {
  id: string;
  name: string;
  code?: string;
}

export interface CurrentUser {
  id: string;
  email: string;
  name: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  role_label: string;
  company: TenantReference | null;
  branch: TenantReference | null;
  must_change_password: boolean;
  is_superuser: boolean;
}

export interface CallEvent {
  id: string;
  received_at: string;
  call_date: string | null;
  call_id: string;
  lead_id: string;
  agent_user: string;
  campaign: string;
  phone_number: string;
  disposition: string;
  talk_time: number;
  dialer: string;
  recording_lookup_status: string;
  recording_download_status: string;
  recording_available: boolean;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface CallFilterOptions {
  agents: string[];
  campaigns: string[];
  dispositions: string[];
  dialers: string[];
  event_types: Array<{ value: string; label: string }>;
  recording_statuses: Array<{ value: string; label: string }>;
}

export interface DashboardSummary {
  metrics: {
    total_calls: number;
    recordings_ready: number;
    recordings_pending: number;
    avg_talk_time: number | null;
    reviewed: number;
    review_completion: number;
  };
  recent_calls: CallEvent[];
  generated_at: string;
}

export interface AdminSummary {
  companies: number;
  branches: number;
  users: number;
  active_users: number;
  dialers: number;
  active_dialers: number;
  calls: number;
  recent_security_events: SecurityEvent[];
}

export interface CompanyRecord {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  branches_count: number;
  users_count: number;
  created_at: string;
  updated_at: string;
}

export interface BranchRecord {
  id: string;
  company: string;
  company_name: string;
  name: string;
  code: string;
  timezone: string;
  is_active: boolean;
  users_count: number;
  dialers_count: number;
  created_at: string;
  updated_at: string;
}

export interface DialerRecord {
  id: string;
  branch: string;
  branch_name: string;
  company_name: string;
  name: string;
  api_url: string;
  api_username: string;
  api_source: string;
  webhook_path: string;
  allowed_recording_hosts: string;
  request_timeout_seconds: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AdminUserRecord {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  name: string;
  role: Exclude<UserRole, 'administrator'>;
  role_label: string;
  company: string;
  company_name: string;
  branch: string;
  branch_name: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login: string | null;
  created_at: string;
  updated_at: string;
}

export interface SecurityEvent {
  id: string;
  user_name: string;
  email: string;
  event: string;
  event_label: string;
  ip_address: string | null;
  user_agent: string;
  created_at: string;
}
