-- Migration 001: Initial Schema
-- Creates all core tables for the Mentions application

-- Enable required extensions (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Core Multi-Tenant Structure

-- Companies
CREATE TABLE companies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_companies_created_at ON companies(created_at);

-- User Profiles
CREATE TABLE user_profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  role text CHECK (role IN ('owner','admin','member')) DEFAULT 'member',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_user_profiles_company_id ON user_profiles(company_id);
CREATE UNIQUE INDEX idx_user_profiles_id_company ON user_profiles(id, company_id);

-- 2. Keywords & Prompts

-- Keywords
CREATE TABLE keywords (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  keyword text NOT NULL,
  is_active boolean DEFAULT true,
  priority text CHECK (priority IN ('low', 'normal', 'high')) DEFAULT 'normal',
  discovery_frequency_minutes int DEFAULT 120,
  last_discovered_at timestamptz,
  next_discovery_at timestamptz,
  total_discoveries int DEFAULT 0,
  total_artifacts int DEFAULT 0,
  max_artifacts_per_day int DEFAULT 10,
  created_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX idx_keywords_company_keyword ON keywords(company_id, keyword);
CREATE INDEX idx_keywords_next_discovery ON keywords(next_discovery_at) WHERE is_active = true;
CREATE INDEX idx_keywords_company_active ON keywords(company_id, is_active) WHERE is_active = true;
CREATE INDEX idx_keywords_priority ON keywords(priority, next_discovery_at) WHERE is_active = true;

-- Prompts
CREATE TABLE prompts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name text NOT NULL,
  body text NOT NULL,
  model text DEFAULT 'gpt-5-mini',
  fine_tuned_model_id text,
  temperature numeric DEFAULT 0.6,
  is_default boolean DEFAULT false,
  version int DEFAULT 1,
  created_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_prompts_company_id ON prompts(company_id);
CREATE INDEX idx_prompts_company_default ON prompts(company_id, is_default) WHERE is_default = true;
CREATE INDEX idx_prompts_fine_tuned ON prompts(company_id, fine_tuned_model_id) WHERE fine_tuned_model_id IS NOT NULL;

-- 3. Reddit Integration

-- Company Reddit Apps
CREATE TABLE company_reddit_apps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  client_id text NOT NULL,
  client_secret_ciphertext text NOT NULL,
  redirect_uri text NOT NULL,
  scopes text[] NOT NULL DEFAULT '{identity,read,submit,vote}',
  created_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX idx_company_reddit_apps_company ON company_reddit_apps(company_id);

-- Reddit Connections (User OAuth)
CREATE TABLE reddit_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  company_reddit_app_id uuid NOT NULL REFERENCES company_reddit_apps(id) ON DELETE CASCADE,
  reddit_username text,
  refresh_token_ciphertext text NOT NULL,
  expires_at timestamptz,
  scopes text[],
  karma_total int DEFAULT 0,
  karma_comment int DEFAULT 0,
  account_created_at timestamptz,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_reddit_connections_company ON reddit_connections(company_id);
CREATE INDEX idx_reddit_connections_user ON reddit_connections(user_id);
CREATE INDEX idx_reddit_connections_active ON reddit_connections(company_id, is_active) WHERE is_active = true;

-- 4. Posting Eligibility & Volume Controls

CREATE TABLE posting_eligibility (
  company_id uuid PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
  min_account_age_days int DEFAULT 30,
  min_total_karma int DEFAULT 300,
  min_comment_karma int DEFAULT 100,
  max_daily_per_sub int DEFAULT 3,
  max_daily_per_account int DEFAULT 10,
  max_weekly_per_account int DEFAULT 70,
  cooldown_seconds int DEFAULT 180,
  strict_mode boolean DEFAULT false,
  updated_at timestamptz DEFAULT now()
);

-- 5. RAG: Company Documents & Embeddings

-- Company Docs
CREATE TABLE company_docs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  title text,
  source text,
  url text,
  raw_text text NOT NULL,
  uploaded_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_company_docs_company ON company_docs(company_id);
CREATE INDEX idx_company_docs_source ON company_docs(company_id, source);

-- Company Doc Chunks (with Embeddings)
CREATE TABLE company_doc_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  doc_id uuid NOT NULL REFERENCES company_docs(id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  chunk_text text NOT NULL,
  embedding vector(1536),
  metadata jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_company_doc_chunks_doc ON company_doc_chunks(doc_id);
CREATE INDEX idx_company_doc_chunks_company ON company_doc_chunks(company_id);

-- Vector index for similarity search (created after some data exists)
-- CREATE INDEX idx_company_doc_chunks_embedding ON company_doc_chunks 
--   USING ivfflat (embedding vector_cosine_ops)
--   WITH (lists = 100);

-- 6. Subreddit Discovery & History

CREATE TABLE subreddit_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  keyword text NOT NULL,
  subreddit text NOT NULL,
  llm_label text CHECK (llm_label IN ('good','bad')),
  llm_score numeric,
  llm_reasoning text,
  times_selected int DEFAULT 0,
  times_posted int DEFAULT 0,
  last_selected_at timestamptz,
  last_posted_at timestamptz,
  last_judged_at timestamptz DEFAULT now(),
  created_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX idx_subreddit_history_unique ON subreddit_history(company_id, keyword, subreddit);
CREATE INDEX idx_subreddit_history_keyword ON subreddit_history(company_id, keyword, llm_label);
CREATE INDEX idx_subreddit_history_posted ON subreddit_history(company_id, subreddit, last_posted_at);

-- 7. Threads & Artifacts

-- Threads
CREATE TABLE threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  subreddit text NOT NULL,
  reddit_id text NOT NULL,
  title text,
  body text,
  url text,
  author text,
  created_utc timestamptz,
  score int,
  num_comments int,
  discovered_at timestamptz DEFAULT now(),
  rank_score numeric,
  metadata jsonb
);

CREATE UNIQUE INDEX idx_threads_unique ON threads(company_id, reddit_id);
CREATE INDEX idx_threads_subreddit ON threads(company_id, subreddit, discovered_at DESC);

-- Artifacts
CREATE TABLE artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  reddit_account_id uuid REFERENCES reddit_connections(id) ON DELETE SET NULL,
  thread_id uuid NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  subreddit text NOT NULL,
  keyword text NOT NULL,
  company_goal text,
  thread_reddit_id text NOT NULL,
  thread_title text,
  thread_body text,
  thread_url text,
  rules_summary jsonb,
  draft_primary text NOT NULL,
  draft_variants text[],
  rag_context jsonb,
  judge_subreddit jsonb,
  judge_draft jsonb,
  prompt_id uuid REFERENCES prompts(id),
  status text CHECK (status IN ('new','edited','approved','posted','failed')) DEFAULT 'new',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX idx_artifacts_unique ON artifacts(company_id, thread_reddit_id);
CREATE INDEX idx_artifacts_company_status ON artifacts(company_id, status, created_at DESC);
CREATE INDEX idx_artifacts_subreddit ON artifacts(company_id, subreddit, status);
CREATE INDEX idx_artifacts_keyword ON artifacts(company_id, keyword, status);
CREATE INDEX idx_artifacts_thread ON artifacts(thread_id);
CREATE INDEX idx_artifacts_reddit_account ON artifacts(reddit_account_id) WHERE reddit_account_id IS NOT NULL;

-- 8. Drafts, Approvals, Posts

-- Drafts
CREATE TABLE drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  kind text CHECK (kind IN ('generated','edited')) DEFAULT 'generated',
  text text NOT NULL,
  source_draft_id uuid REFERENCES drafts(id),
  risk text CHECK (risk IN ('low', 'medium', 'high')),
  edit_meta jsonb,
  created_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_drafts_artifact ON drafts(artifact_id, created_at DESC);
CREATE INDEX idx_drafts_kind ON drafts(artifact_id, kind);

-- Approvals
CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  chosen_draft_id uuid NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  approved_by uuid NOT NULL REFERENCES auth.users(id),
  approved_at timestamptz DEFAULT now(),
  status text CHECK (status IN ('approved','posted','failed')) DEFAULT 'approved'
);

CREATE INDEX idx_approvals_artifact ON approvals(artifact_id);
CREATE INDEX idx_approvals_user ON approvals(approved_by, approved_at DESC);
CREATE INDEX idx_approvals_draft ON approvals(chosen_draft_id);

-- Posts
CREATE TABLE posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  reddit_account_id uuid NOT NULL REFERENCES reddit_connections(id) ON DELETE CASCADE,
  artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  subreddit text NOT NULL,
  thread_reddit_id text NOT NULL,
  comment_reddit_id text,
  permalink text,
  posted_at timestamptz NOT NULL,
  verified boolean DEFAULT false,
  verified_at timestamptz,
  idempotency_key text UNIQUE NOT NULL,
  retry_count int DEFAULT 0,
  error_message text
);

CREATE INDEX idx_posts_company ON posts(company_id, posted_at DESC);
CREATE INDEX idx_posts_subreddit ON posts(company_id, subreddit, posted_at DESC);
CREATE INDEX idx_posts_account ON posts(reddit_account_id, posted_at DESC);
CREATE INDEX idx_posts_artifact ON posts(artifact_id) WHERE artifact_id IS NOT NULL;
CREATE INDEX idx_posts_verification ON posts(verified, posted_at) WHERE verified = false;
CREATE UNIQUE INDEX idx_posts_idempotency ON posts(idempotency_key);

-- 9. Moderation & Feedback

-- Moderation Events
CREATE TABLE moderation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  post_id uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  event text CHECK (event IN ('removed','shadow','automod','approved')),
  detail jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_moderation_events_post ON moderation_events(post_id);
CREATE INDEX idx_moderation_events_company ON moderation_events(company_id, created_at DESC);

-- Subreddit Feedback
CREATE TABLE subreddit_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  subreddit text NOT NULL,
  label text CHECK (label IN ('good','bad')) NOT NULL,
  reason text,
  user_id uuid NOT NULL REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_subreddit_feedback_company_sub ON subreddit_feedback(company_id, subreddit);

-- 10. Subreddit Accounts & Canary

CREATE TABLE subreddit_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reddit_account_id uuid NOT NULL REFERENCES reddit_connections(id) ON DELETE CASCADE,
  subreddit text NOT NULL,
  canary_passed_at timestamptz,
  canary_failed_at timestamptz,
  last_posted_at timestamptz,
  last_removed_at timestamptz,
  post_count int DEFAULT 0,
  removal_count int DEFAULT 0
);

CREATE UNIQUE INDEX idx_subreddit_accounts_unique ON subreddit_accounts(reddit_account_id, subreddit);
CREATE INDEX idx_subreddit_accounts_canary ON subreddit_accounts(reddit_account_id, canary_passed_at);

-- 11. Training & Learning

-- Training Events
CREATE TABLE training_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  draft_id uuid REFERENCES drafts(id) ON DELETE SET NULL,
  reddit_account_id uuid REFERENCES reddit_connections(id) ON DELETE SET NULL,
  subreddit text,
  thread_reddit_id text,
  event_type text CHECK (
    event_type IN (
      'generated_draft',
      'edited_draft',
      'rejected_draft',
      'approved_draft',
      'posted',
      'removed',
      'engagement_snapshot'
    )
  ) NOT NULL,
  llm_judge jsonb,
  human_label text,
  human_reason text,
  engagement jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_training_events_company ON training_events(company_id, created_at DESC);
CREATE INDEX idx_training_events_artifact ON training_events(artifact_id, event_type) WHERE artifact_id IS NOT NULL;
CREATE INDEX idx_training_events_draft ON training_events(draft_id) WHERE draft_id IS NOT NULL;
CREATE INDEX idx_training_events_type ON training_events(event_type, created_at DESC);

-- Fine-Tuning Jobs
CREATE TABLE fine_tuning_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  openai_job_id text,
  base_model text NOT NULL,
  fine_tuned_model_id text,
  status text CHECK (
    status IN (
      'preparing',
      'submitted',
      'running',
      'succeeded',
      'failed',
      'cancelled'
    )
  ) DEFAULT 'preparing',
  training_file_id text,
  validation_file_id text,
  num_training_examples int,
  num_validation_examples int,
  training_data_start_date timestamptz,
  training_data_end_date timestamptz,
  hyperparameters jsonb,
  results jsonb,
  error_message text,
  created_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now(),
  completed_at timestamptz,
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_fine_tuning_jobs_company ON fine_tuning_jobs(company_id, created_at DESC);
CREATE INDEX idx_fine_tuning_jobs_status ON fine_tuning_jobs(status, created_at DESC);
CREATE INDEX idx_fine_tuning_jobs_openai ON fine_tuning_jobs(openai_job_id) WHERE openai_job_id IS NOT NULL;

-- Fine-Tuning Exports
CREATE TABLE fine_tuning_exports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  export_type text CHECK (export_type IN ('training', 'validation', 'full')) NOT NULL,
  file_path text NOT NULL,
  openai_file_id text,
  num_examples int NOT NULL,
  start_date timestamptz NOT NULL,
  end_date timestamptz NOT NULL,
  filters jsonb,
  created_by uuid REFERENCES auth.users(id),
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_fine_tuning_exports_company ON fine_tuning_exports(company_id, created_at DESC);
CREATE INDEX idx_fine_tuning_exports_type ON fine_tuning_exports(company_id, export_type);

-- 12. Subscriptions & Billing

-- Subscriptions
CREATE TABLE subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  stripe_subscription_id text UNIQUE NOT NULL,
  stripe_customer_id text NOT NULL,
  stripe_price_id text NOT NULL,
  plan_name text NOT NULL CHECK (plan_name IN ('starter', 'growth', 'enterprise')),
  status text NOT NULL CHECK (
    status IN (
      'active',
      'trialing',
      'past_due',
      'canceled',
      'unpaid',
      'incomplete',
      'incomplete_expired'
    )
  ),
  current_period_start timestamptz NOT NULL,
  current_period_end timestamptz NOT NULL,
  cancel_at_period_end boolean DEFAULT false,
  canceled_at timestamptz,
  trial_start timestamptz,
  trial_end timestamptz,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX idx_subscriptions_company ON subscriptions(company_id);
CREATE INDEX idx_subscriptions_stripe_customer ON subscriptions(stripe_customer_id);
CREATE INDEX idx_subscriptions_status ON subscriptions(status);

-- Plan Limits
CREATE TABLE plan_limits (
  plan_name text PRIMARY KEY CHECK (plan_name IN ('starter', 'growth', 'enterprise')),
  max_team_members int NOT NULL,
  max_posts_per_month int NOT NULL,
  max_reddit_accounts int NOT NULL,
  max_keywords int NOT NULL,
  fine_tuning_enabled boolean DEFAULT false,
  priority_support boolean DEFAULT false,
  updated_at timestamptz DEFAULT now()
);

-- Insert default limits
INSERT INTO plan_limits (
  plan_name, 
  max_team_members, 
  max_posts_per_month, 
  max_reddit_accounts, 
  max_keywords,
  fine_tuning_enabled,
  priority_support
) VALUES
  ('starter', 2, 50, 3, 2, false, false),
  ('growth', 10, 200, 10, 10, true, true),
  ('enterprise', -1, -1, -1, -1, true, true);

-- Invoices
CREATE TABLE invoices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  stripe_invoice_id text UNIQUE NOT NULL,
  stripe_subscription_id text NOT NULL,
  amount_due int NOT NULL,
  amount_paid int NOT NULL,
  currency text DEFAULT 'usd',
  status text NOT NULL CHECK (
    status IN ('draft', 'open', 'paid', 'uncollectible', 'void')
  ),
  invoice_pdf text,
  hosted_invoice_url text,
  period_start timestamptz NOT NULL,
  period_end timestamptz NOT NULL,
  due_date timestamptz,
  paid_at timestamptz,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_invoices_company ON invoices(company_id);
CREATE INDEX idx_invoices_stripe_subscription ON invoices(stripe_subscription_id);

-- 13. LangGraph State Persistence

-- LangGraph checkpoint storage
CREATE TABLE langgraph_checkpoints (
  thread_id text NOT NULL,
  checkpoint_ns text NOT NULL DEFAULT '',
  checkpoint_id text NOT NULL,
  parent_checkpoint_id text,
  type text,
  checkpoint jsonb NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE INDEX idx_langgraph_checkpoints_parent 
  ON langgraph_checkpoints(thread_id, checkpoint_ns, parent_checkpoint_id);

-- LangGraph checkpoint writes
CREATE TABLE langgraph_checkpoint_writes (
  thread_id text NOT NULL,
  checkpoint_ns text NOT NULL DEFAULT '',
  checkpoint_id text NOT NULL,
  task_id text NOT NULL,
  idx integer NOT NULL,
  channel text NOT NULL,
  type text,
  value jsonb,
  PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX idx_langgraph_writes_checkpoint 
  ON langgraph_checkpoint_writes(thread_id, checkpoint_ns, checkpoint_id);

