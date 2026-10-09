import {
  ArrowRightOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  HistoryOutlined,
  MenuOutlined,
  PlusOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { Alert, App as AntApp, Button, Drawer, Skeleton, Spin, Tag, Tooltip, Typography } from 'antd';
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { ApiError } from '../lib/api';
import { aiApi, aiSuggestedQuestions, type AIConversation, type AIEvidence, type AIMessage, type AIMetadata } from '../lib/ai';
import { appDate } from '../lib/datetime';
import { SafeAIText } from '../components/SafeAIText';

const { Text, Title } = Typography;

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return 'Your account does not have access to AI Insights. Contact an administrator if you need access.';
    if (error.status === 404) return 'This conversation is no longer available within your current permissions.';
    if (error.status === 409) return 'This conversation is already processing another request. Try again shortly.';
    if (error.status === 429) return error.message.includes('Expected available in') ? error.message : 'You have reached the AI request limit. Please try again later.';
    if (error.status === 503) return 'The AI service is temporarily unavailable. Please try again later.';
    return error.message;
  }
  return 'The request could not be completed. Check your connection and try again.';
}

function EvidenceList({ evidence }: { evidence: AIEvidence[] }) {
  const unique = Array.from(new Map(evidence.filter((item) => item.review_id).map((item) => [item.review_id, item])).values());
  if (!unique.length) return null;
  return (
    <div className="ai-evidence" aria-label="Supporting QA reports">
      <span className="ai-evidence__label"><FileSearchOutlined /> Supporting evaluations</span>
      <div className="ai-evidence__links">
        {unique.slice(0, 12).map((item, index) => (
          <Link key={item.review_id} to={`/queue?review=${encodeURIComponent(item.review_id)}`} className="ai-evidence__link" title={`Open QA report ${item.review_id}`}>
            Report {index + 1} <ArrowRightOutlined />
          </Link>
        ))}
      </div>
    </div>
  );
}

function Transcript({ messages, waiting }: { messages: AIMessage[]; waiting: boolean }) {
  const bottom = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, waiting]);
  return (
    <div className="ai-transcript" role="log" aria-live="polite" aria-relevant="additions text">
      {messages.map((item) => (
        <div key={item.id} className={`ai-message ai-message--${item.role}`}>
          <div className="ai-message__avatar" aria-hidden="true">{item.role === 'assistant' ? <RobotOutlined /> : 'You'}</div>
          <div className="ai-message__body">
            <div className="ai-message__meta"><strong>{item.role === 'assistant' ? 'QA Assistant' : 'You'}</strong><span>{appDate(item.created_at).format('DD MMM, h:mm A')}</span></div>
            <div className="ai-message__content">{item.role === 'assistant' ? <SafeAIText content={item.content} /> : item.content}</div>
            {item.role === 'assistant' && item.interpretation?.intent && (
              <div className="ai-interpretation" aria-label="Reporting interpretation">
                <Tag color="default">{item.interpretation.intent.replaceAll('_', ' ')}</Tag>
                {item.interpretation.label && <Text type="secondary">{item.interpretation.label}</Text>}
                {item.interpretation.date_from && item.interpretation.date_to &&
                  <Text type="secondary">{item.interpretation.date_from} to {item.interpretation.date_to}</Text>}
                {item.interpretation.backlog_mode === 'current_backlog' &&
                  <Text type="secondary"> · Current outstanding, including older pending reviews</Text>}
                {item.interpretation.project && <Tag>{item.interpretation.project}</Tag>}
              </div>
            )}
            {item.role === 'assistant' && item.warnings?.map((warning, index) => (
              <div key={index} className="ai-warning"><Text type="warning">{warning}</Text></div>
            ))}
            {item.role === 'assistant' && item.evidence && <EvidenceList evidence={item.evidence} />}
          </div>
        </div>
      ))}
      {waiting && <div className="ai-message ai-message--assistant ai-message--waiting"><div className="ai-message__avatar"><RobotOutlined /></div><div className="ai-message__body"><div className="ai-message__meta"><strong>QA Assistant</strong></div><div className="ai-message__thinking"><Spin size="small" /> Reviewing permitted QA records…</div></div></div>}
      <div ref={bottom} />
    </div>
  );
}

export function AIInsightsPage() {
  const { user } = useAuth();
  const { message: toast, modal } = AntApp.useApp();
  const [metadata, setMetadata] = useState<AIMetadata | null>(null);
  const [conversations, setConversations] = useState<AIConversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AIMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const requestGuard = useRef(false);
  const conversationIdRef = useRef<string | null>(null);
  const viewVersion = useRef(0);
  const detailsAbort = useRef<AbortController | null>(null);
  const starterQuestions = aiSuggestedQuestions(user?.role ?? 'team_leader');
  const ready = Boolean(metadata?.enabled && metadata?.provider_configured);

  const reloadConversations = useCallback(async () => {
    try {
      const result = await aiApi.conversations();
      setConversations(result.conversations);
      setHistoryError('');
    } catch (reason) {
      setHistoryError(errorText(reason));
    }
  }, []);

  const reloadWorkspace = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await aiApi.metadata();
      setMetadata(result);
      if (result.enabled) await reloadConversations();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }, [reloadConversations]);

  useEffect(() => {
    void reloadWorkspace();
    return () => { viewVersion.current += 1; detailsAbort.current?.abort(); };
  }, [reloadWorkspace]);

  const newConversation = useCallback(() => {
    if (requestGuard.current) return;
    viewVersion.current += 1;
    detailsAbort.current?.abort();
    conversationIdRef.current = null;
    setConversationId(null);
    setMessages([]);
    setDraft('');
    setError('');
    setMobileHistoryOpen(false);
    composerRef.current?.focus();
  }, []);

  const openConversation = useCallback(async (id: string) => {
    if (requestGuard.current || conversationIdRef.current === id) return;
    const version = ++viewVersion.current;
    detailsAbort.current?.abort();
    const controller = new AbortController();
    detailsAbort.current = controller;
    conversationIdRef.current = id;
    setConversationId(id);
    setMessages([]);
    setError('');
    setLoadingHistory(true);
    setMobileHistoryOpen(false);
    try {
      const result = await aiApi.conversation(id, controller.signal);
      if (version !== viewVersion.current) return;
      setMessages(result.messages);
    } catch (reason) {
      if (controller.signal.aborted || version !== viewVersion.current) return;
      conversationIdRef.current = null;
      setConversationId(null);
      setError(errorText(reason));
      await reloadConversations();
    } finally {
      if (version === viewVersion.current) setLoadingHistory(false);
    }
  }, [reloadConversations]);

  const deleteConversation = useCallback((item: AIConversation) => {
    if (requestGuard.current) return;
    modal.confirm({
      title: 'Delete this conversation?',
      content: 'The chat history will be permanently deleted. Your QA reports are not affected.',
      okText: 'Delete conversation',
      okType: 'danger',
      onOk: async () => {
        try {
          await aiApi.deleteConversation(item.id);
          if (conversationIdRef.current === item.id) newConversation();
          setConversations((all) => all.filter((entry) => entry.id !== item.id));
          void toast.success('Conversation deleted');
        } catch (reason) { void toast.error(errorText(reason)); }
      },
    });
  }, [newConversation, toast, modal]);

  const sendMessage = useCallback(async (value: string) => {
    const question = value.trim();
    if (!ready || requestGuard.current || !question || question.length > 2000 || loadingHistory) return;
    const version = viewVersion.current;
    const idAtSend = conversationIdRef.current;
    requestGuard.current = true;
    setSending(true);
    setError('');
    setDraft('');
    setMessages((current) => [...current, { id: `local-user-${Date.now()}`, role: 'user', content: question, created_at: new Date().toISOString() }]);
    try {
      const reply = await aiApi.chat(question, idAtSend ?? undefined);
      if (version !== viewVersion.current) return;
      conversationIdRef.current = reply.conversation_id;
      setConversationId(reply.conversation_id);
      setMessages((current) => [...current, {
        id: `local-ai-${Date.now()}`,
        role: 'assistant',
        content: reply.answer,
        evidence: reply.evidence,
        tools_used: reply.tools_used,
        interpretation: reply.interpretation,
        warnings: reply.warnings,
        created_at: new Date().toISOString(),
      }]);
      void reloadConversations();
    } catch (reason) {
      if (version === viewVersion.current) {
        setError(errorText(reason));
        setDraft(question);
        setMessages((current) => current.filter((item) => item.role !== 'user' || item.content !== question || !item.id.startsWith('local-user-')));
      }
    } finally {
      requestGuard.current = false;
      setSending(false);
    }
  }, [ready, loadingHistory, reloadConversations]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void sendMessage(draft);
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void sendMessage(draft);
    }
  };

  const historyPanel = (
    <div className="ai-history">
      <div className="ai-history__top"><span><HistoryOutlined /> Conversations</span><Tooltip title="New conversation"><Button aria-label="New conversation" type="text" icon={<PlusOutlined />} onClick={newConversation} disabled={sending} /></Tooltip></div>
      <div className="ai-history__items">
        {historyError && <Alert type="warning" showIcon title="History unavailable" description={historyError} action={<Button size="small" onClick={() => void reloadConversations()}>Retry</Button>} />}
        {!conversations.length && !historyError && <div className="ai-history__empty">Your recent conversations will appear here.</div>}
        {conversations.map((item) => <div key={item.id} className={`ai-history__entry${conversationId === item.id ? ' is-active' : ''}`}>
          <button type="button" className="ai-history__open" aria-current={conversationId === item.id ? 'page' : undefined} onClick={() => void openConversation(item.id)} disabled={sending}>
            <span>{item.title}</span><small>{appDate(item.updated_at).format('DD MMM YYYY')}</small>
          </button>
          <Tooltip title="Delete conversation"><Button size="small" type="text" danger className="ai-history__delete" aria-label={`Delete ${item.title}`} icon={<DeleteOutlined />} disabled={sending} onClick={() => deleteConversation(item)} /></Tooltip>
        </div>)}
      </div>
      <div className="ai-history__footer"><SafetyCertificateOutlined /> Answers are limited to your authorized QA data.</div>
    </div>
  );

  return (
    <div className="ai-page">
      <div className="ai-page__heading">
        <div className="ai-page__heading-copy"><span className="ai-page__eyebrow"><RobotOutlined /> MANAGEMENT INTELLIGENCE</span><Title level={2} className="page-title">AI Insights</Title><Text type="secondary">Ask questions about report reviews, quality trends, coaching and repeated mistakes.</Text></div>
        <div className="ai-page__heading-actions"><Tag icon={<SafetyCertificateOutlined />} color="processing">Read-only analytics</Tag><Button icon={<PlusOutlined />} onClick={newConversation} disabled={sending}>New chat</Button></div>
      </div>
      <Alert
        className="ai-prototype-banner"
        type="warning"
        showIcon
        title="AI Insights is an experimental prototype"
        description="This feature is currently undergoing rigorous testing and validation. Responses may contain incorrect conclusions, incomplete analysis, or misinterpreted data. Do not rely on AI judgements for coaching, compliance, performance decisions, or disciplinary action without independently verifying the underlying QA reports."
        role="status"
      />
      <div className="ai-workspace">
        <aside className="ai-workspace__sidebar" aria-label="AI conversation history">{historyPanel}</aside>
        <main className="ai-workspace__main">
          <div className="ai-workspace__toolbar"><Button className="ai-workspace__mobile-history" icon={<MenuOutlined />} onClick={() => setMobileHistoryOpen(true)}>History</Button><div className="ai-workspace__identity"><span className="ai-workspace__status"><span className={ready ? 'ai-status-dot' : 'ai-status-dot ai-status-dot--offline'} />{loading ? 'Checking service' : ready ? 'Assistant available' : 'Assistant unavailable'}</span><small>{user?.company?.name ?? 'All companies'} · {user?.branch?.name ?? 'All branches'}</small></div></div>
          {loading ? <div className="ai-workspace__loading"><Skeleton active paragraph={{ rows: 5 }} /></div> : error && !metadata ? <div className="ai-state"><Alert type="error" showIcon title="Unable to load AI Insights" description={error} /><Button onClick={() => void reloadWorkspace()}>Try again</Button></div> : !ready ? <div className="ai-state"><RobotOutlined className="ai-state__icon" /><Title level={4}>{metadata?.enabled ? 'Inference connection not configured' : 'AI Insights is currently disabled'}</Title><Text type="secondary">{metadata?.enabled ? 'An administrator must configure the AI provider before this workspace can answer questions.' : 'An administrator must enable the AI assistant before it can be used.'}</Text><Button onClick={() => void reloadWorkspace()}>Check again</Button></div> : <>
            {error && <Alert className="ai-chat-error" type="error" showIcon closable onClose={() => setError('')} title="Unable to complete your request" description={error} />}
            <div className="ai-workspace__conversation">
              {loadingHistory ? <div className="ai-workspace__loading"><Spin /> Loading conversation…</div> : messages.length || sending ? <Transcript messages={messages} waiting={sending} /> : <div className="ai-welcome"><div className="ai-welcome__icon"><BulbOutlined /></div><span className="ai-page__eyebrow">START WITH A QUESTION</span><Title level={3}>What would you like to understand?</Title><Text type="secondary">Ask about your QA reports. The assistant uses controlled, permission-checked tools to retrieve evidence rather than guessing from memory.</Text><div className="ai-prompts">{starterQuestions.map((question) => <button key={question} type="button" className="ai-prompt" onClick={() => void sendMessage(question)}><span>{question}</span><ArrowRightOutlined /></button>)}</div></div>}
            </div>
            <div className="ai-compose"><form onSubmit={handleSubmit} className="ai-compose__form"><label htmlFor="ai-question" className="sr-only">Ask AI Insights a question</label><textarea ref={composerRef} id="ai-question" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleKeyDown} placeholder="Ask about pending reports, repeated QA errors, team performance…" maxLength={2000} rows={2} disabled={sending || loadingHistory} /><Button type="primary" htmlType="submit" icon={sending ? <Spin size="small" /> : <SendOutlined />} disabled={!draft.trim() || sending || loadingHistory} aria-label="Send question">Send</Button></form><div className="ai-compose__foot"><span><CheckCircleOutlined /> Scope enforced by QA Portal permissions</span><span>{draft.length}/2000 · Enter to send, Shift+Enter for a new line</span></div></div>
          </>}
        </main>
      </div>
      <Drawer title="Recent conversations" placement="left" size={320} open={mobileHistoryOpen} onClose={() => setMobileHistoryOpen(false)} className="ai-history-drawer">{historyPanel}</Drawer>
    </div>
  );
}
