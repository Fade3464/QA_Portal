import { api } from './api';
import type { CurrentUser } from '../types';

export interface AIMetadata {
  enabled: boolean;
  provider_configured: boolean;
  engine_version?: string;
  tools: string[];
  capabilities: string[];
  actions_enabled: boolean;
}

export interface AIEvidence {
  review_id: string;
  tool: string;
}

export interface AIInterpretation {
  intent?: string;
  period?: string;
  label?: string;
  timezone?: string;
  engine?: string;
  backlog_mode?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  all_time?: boolean;
  subject?: string;
  operation?: string;
  metric?: string | null;
  order?: 'best' | 'worst';
  result_status?: 'complete' | 'incomplete' | 'clarification';
  response_kind?: 'conversation';
  project?: string | null;
  team?: string | null;
  agent?: string | null;
}

export interface AIMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  evidence?: AIEvidence[];
  tools_used?: string[];
  interpretation?: AIInterpretation;
  warnings?: string[];
}

export interface AIConversation {
  id: string;
  title: string;
  updated_at: string;
}

export interface AIConversationDetail {
  id: string;
  messages: AIMessage[];
}

export interface AIChatResponse {
  conversation_id: string;
  answer: string;
  evidence: AIEvidence[];
  tools_used: string[];
  interpretation?: AIInterpretation;
  warnings?: string[];
}

export function canUseAI(user: CurrentUser | null): boolean {
  if (!user || user.must_change_password) return false;
  return (user.role === 'administrator' && user.is_superuser)
    || user.role === 'project_manager'
    || user.role === 'supervisor'
    || user.role === 'team_leader';
}

export const aiApi = {
  metadata: () => api<AIMetadata>('/api/v1/ai/metadata/'),
  conversations: () => api<{ conversations: AIConversation[] }>('/api/v1/ai/conversations/'),
  conversation: (id: string, signal?: AbortSignal) => api<AIConversationDetail>(`/api/v1/ai/conversations/${encodeURIComponent(id)}/`, { signal }),
  deleteConversation: (id: string) => api<void>(`/api/v1/ai/conversations/${encodeURIComponent(id)}/`, { method: 'DELETE' }),
  chat: (message: string, conversationId?: string) => api<AIChatResponse>('/api/v1/ai/chat/', {
    method: 'POST',
    body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }),
  }),
};

export function aiSuggestedQuestions(role: CurrentUser['role']): string[] {
  if (role === 'team_leader') return [
    'Which agents in my team repeated the same QA mistake this month?',
    'Which of my QA reports still need review?',
    'Which agents have an overdue coaching follow-up?',
    'What are the most common critical errors in my team this week?',
  ];
  if (role === 'project_manager' || role === 'supervisor') return [
    'Which team leaders have pending QA reports this week?',
    'Compare quality trends across the teams I oversee.',
    'Which agents repeatedly failed the same QA criterion?',
    'What are the biggest QA risks across my projects this month?',
  ];
  return [
    'Which branches have the largest pending-review backlog?',
    'Show repeat critical errors across the organization this month.',
    'Compare project performance over the last 30 days.',
    'Which team leaders have overdue report reviews?',
  ];
}
