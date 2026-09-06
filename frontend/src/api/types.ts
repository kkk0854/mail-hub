export interface Mailbox {
  id: string;
  email: string;
  display_name: string;
  provider_type: string;
  status: string;
  health_status: string | null;
  health_score: number;
  pool_id: string | null;
  pool_name: string | null;
  last_check_at: string | null;
  last_sync_at: string | null;
  last_mail_at: string | null;
  failure_count: number;
  tags: string[];
  today_mail_count: number | null;
  created_at: string;
}

export interface MessageSummary {
  id: string;
  mailbox_id: string;
  mailbox: string | null;
  sender: string;
  recipient: string;
  subject: string;
  preview: string;
  received_at: string | null;
  is_read: boolean;
  is_archived: boolean;
  category: string;
  parse_status: string;
  has_results: boolean;
}

export interface ParseResultT {
  id: string;
  message_id: string;
  rule_name: string;
  type: string;
  value: string;
  confidence: number;
  created_at: string | null;
}

export interface MessageDetail extends MessageSummary {
  body_text: string;
  body_html: string;
  headers: Record<string, string>;
  raw_storage_ref: string;
  results: ParseResultT[];
}

export interface RegistrationTask {
  id: string;
  idempotency_key: string | null;
  external_ref: string;
  pool_id: string | null;
  mailbox_id: string | null;
  mailbox: string | null;
  state: string;
  match: { sender?: string; subject_contains?: string };
  timeout_seconds: number;
  expires_at: string | null;
  result: { type: string; value: string; confidence?: number } | null;
  callback_url: string | null;
  callback_state: string | null;
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
  matched_message?: { id: string; sender: string; subject: string; received_at: string };
}

export interface FetchTask {
  id: string;
  mailbox_id: string | null;
  mailbox: string | null;
  task_type: string;
  state: string;
  attempt: number;
  max_attempt: number;
  next_run_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface Pool {
  id: string;
  name: string;
  description: string;
  max_concurrent: number;
  cooldown_seconds: number;
  daily_limit: number;
  failure_threshold: number;
  auto_quarantine: boolean;
  status: string;
  stats?: Record<string, number>;
}

export interface ParserRule {
  id: string;
  name: string;
  provider_type: string | null;
  sender_pattern: string;
  subject_pattern: string;
  body_regex: string;
  output_type: string;
  priority: number;
  status: string;
}

export interface CfDomain {
  id: string;
  domain: string;
  status: string;
  mode: string;
  dns_status: string;
  mx_status: string;
  spf_status: string;
  dkim_status: string;
  has_inbound_secret: boolean;
  notes: string;
  last_mail_at: string | null;
  today_messages: number | null;
  inbound_secret?: string;
}

export interface Alias {
  id: string;
  master_mailbox_id: string;
  master: string | null;
  alias_address: string;
  alias_type: string;
  status: string;
}

export interface ImportPreview {
  id: string;
  provider_type: string;
  source_type: string;
  total_rows: number;
  valid_rows: number;
  duplicate_rows: number;
  error_rows: number;
  missing_rows: number;
  status: string;
  rows: {
    line_no: number;
    raw_line: string;
    segments: string[];
    parsed: Record<string, string>;
    status: string;
    error: string;
  }[];
}

export interface DashboardSummary {
  mailboxes: { total: number; healthy: number; warning: number; error: number; quarantine: number; by_provider: Record<string, number> };
  mail: { today_received: number; today_parsed: number };
  tasks: { running: number; completed: number; failed: number; cancelled: number; success_rate: number | null };
  workers: { count: number; embedded: boolean; queue_depth: number };
  pools: { id: string; name: string; available: number; total: number; health_rate: number | null }[];
  recent_errors: { id: string; mailbox_id: string | null; task_type: string; error_code: string | null; error_message: string | null; finished_at: string | null }[];
}

export interface MailEvent {
  event_id: string;
  type: string;
  payload: Record<string, any>;
  created_at: string;
}
