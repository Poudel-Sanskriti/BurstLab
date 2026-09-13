export type Lane = "direct" | "queued";
export type Status =
  | "planned"
  | "waiting"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "rejected"
  | "dead_letter"
  | "cancelled"
  | "unresolved";
export interface Config {
  name: string;
  count: number;
  rate: number;
  concurrency: number;
  delay_ms: number;
  failure_percent: number;
  max_attempts: number;
  pattern: "steady" | "burst";
  payload: string;
  seed: number;
  first_lane: Lane;
}
export interface Job {
  id: string;
  lane: Lane;
  payload: string;
  status: Status;
  attempts: number;
  submitted_at: number;
  started_at: number;
  finished_at: number;
  duration_ms?: number;
  result_url?: string;
  error?: string;
  fail_first: boolean;
  checksum?: string;
  size_bytes?: number;
  attempt_log: {
    attempt: number;
    outcome: string;
    duration_ms: number;
    started_at?: number;
    ended_at: number;
  }[];
}
export interface RunEvent {
  seq: number;
  at: number;
  kind: string;
  lane?: Lane;
  job?: Job;
  job_id?: string;
  status?: string;
}
export interface Metric {
  counts: Record<string, number>;
  total: number;
  completed: number;
  unsuccessful: number;
  dispatched: number;
  attempts: number;
  retries: number;
  p50_ms: number | null;
  p95_ms: number | null;
  wait_p95_ms: number | null;
  elapsed_ms: number;
  throughput: number;
  latency_samples: number;
}
export interface Run {
  id: string;
  name: string;
  mode: "local" | "aws";
  status: string;
  phase: Lane;
  created_at: number;
  finished_at: number | null;
  config: Config;
  manifest_hash: string;
  jobs: Job[];
  events: RunEvent[];
  notes: string[];
  error?: string;
  phases: Partial<Record<Lane, { started_at: number; ended_at?: number }>>;
  metrics: Record<Lane, Metric>;
}
export interface Session {
  token: string;
  mode: "aws" | "local";
  region: string | null;
  configured: boolean;
  setup_message: string | null;
  active_run_id: string | null;
}
export type HistoryItem = Pick<
  Run,
  "id" | "name" | "mode" | "status" | "created_at" | "config" | "metrics"
>;
