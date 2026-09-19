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

export interface CallReservation {
  review_id: string;
  reviewer_id: string;
  reviewer_name: string;
  status: 'assigned' | 'in_progress' | 'revision_required' | 'completed' | 'disputed';
  reserved_at: string;
  is_mine: boolean;
}

export interface ScorecardCriterion {
  key: string;
  label: string;
  max_score: number;
}

export interface ScorecardCategory {
  key: string;
  label: string;
  max_score: number;
  criteria: ScorecardCriterion[];
}

export interface QAScorecard {
  version: string;
  max_score: number;
  benchmark: number;
  minimum_scored_coverage: number;
  evaluation_types: Array<{ value: QAEvaluationType; label: string }>;
  applicability_states: Array<{ value: QACategoryApplicability; label: string }>;
  applicability_reasons: Array<{ value: string; label: string }>;
  categories: ScorecardCategory[];
  critical_errors: Array<{ value: string; label: string }>;
}

export type QAEvaluationType = 'full' | 'partial' | 'not_evaluable' | 'agent_premature';
export type QACategoryApplicability = 'applicable' | 'not_reached' | 'missed_opportunity';

export interface QAEvidencePatch {
  id: string;
  start_ms: number;
  end_ms: number;
  comment: string;
}

export interface QACriterionEvidence {
  comment: string;
  patches: QAEvidencePatch[];
}

export type TeamLeaderReportStatus =
  | 'pending'
  | 'acknowledged'
  | 'coaching_planned'
  | 'coaching_completed'
  | 'escalated'
  | 'returned_to_qa'
  | 'closed';

export interface ReviewWorkflowEvent {
  id: string;
  event_type: 'status_changed' | 'note_added';
  event_type_label: string;
  actor: string;
  actor_name: string;
  from_status: TeamLeaderReportStatus;
  from_status_label: string;
  to_status: TeamLeaderReportStatus;
  to_status_label: string;
  note: string;
  coaching_due_at: string | null;
  email_status: 'disabled' | 'pending' | 'sent' | 'failed';
  email_sent_at: string | null;
  created_at: string;
}

export interface QAReview {
  id: string;
  status: 'assigned' | 'in_progress' | 'revision_required' | 'completed' | 'disputed';
  status_label: string;
  score: string | null;
  evaluation_type: QAEvaluationType;
  evaluation_reason: string;
  category_applicability: Record<string, QACategoryApplicability>;
  category_applicability_reasons: Record<string, string>;
  earned_points: string | null;
  applicable_points: string | null;
  coverage: string | null;
  coverage_tier: 'insufficient' | 'limited' | 'partial' | 'full' | '';
  scorecard_version: string;
  scorecard_snapshot: QAScorecard | Record<string, never>;
  scores: Record<string, number>;
  criterion_evidence: Record<string, QACriterionEvidence>;
  critical_errors: string[];
  critical_error_evidence: Record<string, QACriterionEvidence>;
  rating: string;
  rating_label: string;
  outcome: string;
  outcome_label: string;
  feedback_summary: string;
  strengths: string;
  improvement_areas: string;
  expected_behavior: string;
  coaching_plan: string;
  reviewer: string;
  reviewer_name: string;
  team_leader: string | null;
  team_leader_name: string | null;
  assigned_at: string;
  completed_at: string | null;
  email_status: 'disabled' | 'pending' | 'sent' | 'failed';
  email_sent_at: string | null;
  leader_status: TeamLeaderReportStatus;
  leader_status_label: string;
  coaching_due_at: string | null;
  leader_reviewed_at: string | null;
  leader_closed_at: string | null;
  leader_updated_at: string | null;
  revision_requested_at: string | null;
  revision_reason: string;
  revision_count: number;
}

export interface QAAnalysisResponse {
  call: CallEvent;
  review: QAReview | null;
  scorecard: QAScorecard;
}

export interface QAReport extends QAReview {
  call_id: string;
  phone_number: string;
  agent_name: string;
  agent_user: string;
  team_name: string;
  project_name: string | null;
  call_date: string | null;
}

export interface QAReportDetail extends QAReport {
  call: CallEvent;
  workflow_events: ReviewWorkflowEvent[];
}

export interface QAReportSummary {
  total: number;
  average_score: number | null;
  pending: number;
  critical_open: number;
  coaching_open: number;
  overdue: number;
  below_benchmark_open: number;
  closed: number;
  trend: Array<{ date: string; count: number; average_score: number | null }>;
  filters: {
    projects: string[];
    teams: string[];
    agents: string[];
    dispositions: string[];
    directions: string[];
    scorecard: QAScorecard;
    reviewers: Array<{
      reviewer_id: string;
      reviewer__first_name: string;
      reviewer__last_name: string;
    }>;
  };
  generated_at: string;
}

export interface CallEvent {
  id: string;
  received_at: string;
  call_date: string | null;
  call_id: string;
  closecallid: string;
  xfercallid: string;
  lead_id: string;
  agent_user: string;
  agent_name: string;
  team: string | null;
  team_name: string;
  team_avatar: string;
  campaign: string;
  project_name: string | null;
  group: string;
  did_id: string;
  did_pattern: string;
  call_direction: 'INBOUND' | 'TRANSFER' | 'CLOSER' | 'OUTBOUND';
  dial_method: 'AUTO' | 'MANUAL' | 'UNKNOWN' | 'N/A';
  phone_number: string;
  disposition: string;
  talk_time: number;
  termination_reason: string;
  dialer: string;
  recording_lookup_status: string;
  recording_download_status: string;
  recording_available: boolean;
  reservation: CallReservation | null;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface CallFilterOptions {
  agents: string[];
  teams: string[];
  projects: string[];
  dispositions: string[];
  termination_reasons: string[];
  dialers: string[];
  event_types: Array<{ value: string; label: string }>;
  dial_methods: Array<{ value: string; label: string }>;
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
  teams: number;
  active_teams: number;
  users: number;
  active_users: number;
  dialers: number;
  active_dialers: number;
  calls: number;
  recent_security_events: SecurityEvent[];
}

export interface TeamRecord {
  id: string;
  branch: string;
  branch_name: string;
  company_name: string;
  name: string;
  avatar: string;
  team_leader: string;
  team_leader_name: string;
  team_leader_email: string;
  is_active: boolean;
  calls_count: number;
  created_at: string;
  updated_at: string;
}

export interface SystemNotification {
  id: string;
  category: string;
  severity: 'info' | 'warning' | 'error';
  title: string;
  message: string;
  branch_id: string | null;
  branch_name: string;
  call_id: string | null;
  metadata: Record<string, string>;
  occurrences: number;
  is_read: boolean;
  created_at: string;
  updated_at: string;
}

export interface NotificationResponse {
  unread_count: number;
  results: SystemNotification[];
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
  campaigns: Array<{
    id: string;
    campaign: string;
    project_name: string;
  }>;
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
  assigned_projects: Array<{
    id: string;
    dialer_id: string;
    dialer_name: string;
    campaign: string;
    project_name: string;
  }>;
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
