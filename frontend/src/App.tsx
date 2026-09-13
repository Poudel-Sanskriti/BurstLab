import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Cpu,
  Database,
  FlaskConical,
  Gauge,
  GitBranch,
  Layers3,
  LoaderCircle,
  Play,
  QrCode,
  Radio,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Square,
  Terminal,
  Timer,
  Waves,
  X,
  Zap,
} from "lucide-react";
import type { Config, HistoryItem, Job, Lane, Run, Session } from "./types";
import {
  defaultConfig,
  metric,
  milliseconds,
  replayAt,
  statusName,
  terminal,
} from "./data";

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Check the experiment settings and try again.",
    );
  return body;
}

const presets = [
  {
    id: "steady",
    title: "Steady stream",
    icon: Waves,
    description: "A gentle baseline",
    values: {
      name: "Steady stream",
      pattern: "steady",
      rate: 4,
      delay_ms: 0,
      failure_percent: 0,
    },
  },
  {
    id: "burst",
    title: "Traffic burst",
    icon: Zap,
    description: "A rush of requests",
    values: {
      name: "Traffic burst",
      pattern: "burst",
      rate: 12,
      delay_ms: 350,
      failure_percent: 0,
    },
  },
  {
    id: "recovery",
    title: "Recovery test",
    icon: RotateCcw,
    description: "Fail, retry, recover",
    values: {
      name: "Recovery under pressure",
      pattern: "steady",
      rate: 12,
      delay_ms: 350,
      failure_percent: 20,
    },
  },
] as const;

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [config, setConfig] = useState<Config>(defaultConfig);
  const [preset, setPreset] = useState("recovery");
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [page, setPage] = useState("lab");
  const [advanced, setAdvanced] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Job | null>(null);
  const [replay, setReplay] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [help, setHelp] = useState(false);
  const [settings, setSettings] = useState(false);
  const [switching, setSwitching] = useState(false);
  const live = !!run && ["running", "stopping"].includes(run.status);
  const busy = live || starting;
  const shown = useMemo(
    () => (run && replay !== null ? replayAt(run, replay) : run),
    [run, replay],
  );

  async function refreshHistory() {
    setHistory(await api<HistoryItem[]>("/runs"));
  }
  async function switchEnvironment(mode: "aws" | "local") {
    setSwitching(true);
    try {
      const next = await api<Session>("/environment", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });
      setSession(next);
      setRun(null);
      setReplay(null);
      setPlaying(false);
      setSelected(null);
      setError("");
      await refreshHistory();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSwitching(false);
    }
  }
  async function openRun(id: string) {
    try {
      setRun(await api<Run>(`/runs/${id}`));
      setPage("lab");
      setReplay(null);
      setSelected(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    let mounted = true;
    api<Session>("/session")
      .then(async (info) => {
        if (!mounted) return;
        setSession(info);
        const items = await api<HistoryItem[]>("/runs");
        if (!mounted) return;
        setHistory(items);
        if (info.active_run_id) {
          const active = await api<Run>(`/runs/${info.active_run_id}`);
          if (mounted) setRun(active);
        }
      })
      .catch((e) => setError(`Backend unavailable. ${e.message}`));
    return () => {
      mounted = false;
    };
  }, []);
  useEffect(() => {
    if (!run || !live) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const next = await api<Run>(`/runs/${run.id}`);
        if (disposed) return;
        setRun(next);
        if (["running", "stopping"].includes(next.status))
          timer = setTimeout(tick, 500);
        else await refreshHistory();
      } catch (e) {
        if (!disposed) {
          setError((e as Error).message);
          timer = setTimeout(tick, 2000);
        }
      }
    };
    timer = setTimeout(tick, 250);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [run?.id, live]);
  useEffect(() => {
    if (!playing || !run || replay === null) return;
    const duration = Math.max(
      1000,
      (run.finished_at || run.created_at) - run.created_at,
    );
    const id = setInterval(
      () =>
        setReplay((value) => {
          const next = Math.min(1, (value || 0) + 100 / duration);
          if (next === 1) setPlaying(false);
          return next;
        }),
      100,
    );
    return () => clearInterval(id);
  }, [playing, run?.id]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelected(null);
        setHelp(false);
        setSettings(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  async function start() {
    setError("");
    setStarting(true);
    setReplay(null);
    setPlaying(false);
    setSelected(null);
    try {
      setRun(
        await api<Run>("/runs", {
          method: "POST",
          body: JSON.stringify(config),
        }),
      );
      await refreshHistory();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }
  async function stop() {
    try {
      await api(`/runs/${run!.id}/stop`, { method: "POST" });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const displayedConfig = live ? run!.config : config;
  const job =
    selected &&
    (shown?.jobs.find(
      (j) => j.id === selected.id && j.lane === selected.lane,
    ) ||
      selected);
  const totalCompleted = shown
    ? shown.metrics.direct.completed + shown.metrics.queued.completed
    : 0;
  const currentCount = shown?.config.count || config.count;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("lab");
          }}
        >
          <span className="brand-mark">
            <Zap size={23} fill="currentColor" />
          </span>
          BurstLab<span className="brand-period">.</span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">
            <FlaskConical size={17} />
          </span>
          <div>
            Personal workspace<small>Cloud systems laboratory</small>
          </div>
        </div>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          {[
            { id: "lab", label: "Experiment lab", icon: Activity },
            { id: "history", label: "Run archive", icon: Clock3 },
            { id: "architecture", label: "Architecture", icon: GitBranch },
          ].map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-item selected" : "nav-item"}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === "history" && (
                <span className="nav-count">{history.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="help-link" onClick={() => setSettings(true)}>
            <Settings2 size={17} />
            Settings
            <ArrowUpRight size={15} />
          </button>
          <button className="help-link" onClick={() => setHelp(true)}>
            <CircleHelp size={17} />
            How this lab works
            <ArrowUpRight size={15} />
          </button>
          <div className="sidebar-footer">
            <span className="avatar">SP</span>
            <div>
              Your experiment space<small>BurstLab / v0.1</small>
            </div>
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace</span>
            <ChevronRight size={13} />
            <span>
              {page === "lab"
                ? "Experiment lab"
                : page === "history"
                  ? "Run archive"
                  : "Architecture"}
            </span>
          </div>
          <div className="topbar-right">
            <button
              className="button secondary"
              onClick={() => setSettings(true)}
              aria-label="Execution settings"
            >
              <Settings2 size={15} />
              Settings
            </button>
            <span className="desktop-only">
              QR worker <span className="mono">v1.0</span>
            </span>
          </div>
        </header>
        <div className="page-content">
          {session?.mode === "aws" && !session.configured && (
            <section className="aws-setup-card" role="status">
              <div>
                <span className="eyebrow">CONNECT YOUR ENVIRONMENT</span>
                <h2>Your lab. Your AWS stack.</h2>
                <p>{session.setup_message}</p>
                <p>
                  Deploy with AWS SAM → save the stack configuration → enable
                  the queue → restart BurstLab.
                </p>
              </div>
              <button
                className="button secondary"
                onClick={() => setSettings(true)}
              >
                Open settings <Settings2 size={15} />
              </button>
            </section>
          )}
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {page === "lab" && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span /> OBSERVE. COMPARE. UNDERSTAND.
                  </div>
                  <h1>
                    Compare processing paths<span>.</span>
                  </h1>
                  <p>
                    A small workload. Two architectures. See what happens in
                    between.
                  </p>
                </div>
                <button
                  className="button secondary"
                  disabled={!run}
                  onClick={() =>
                    run && window.open(`/api/runs/${run.id}/report`, "_self")
                  }
                >
                  <ArrowDownToLine size={16} />
                  Export run
                </button>
              </section>
              <section className="experiment-card">
                <div className="section-top">
                  <div className="section-title">
                    <Settings2 size={17} />
                    <h2>Configure your experiment</h2>
                  </div>
                  <span className="subtle-label">01 / SETUP</span>
                </div>
                <div className="preset-grid">
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      disabled={busy}
                      className={`preset ${preset === p.id ? "active" : ""}`}
                      onClick={() => {
                        setPreset(p.id);
                        setConfig({ ...config, ...p.values });
                      }}
                    >
                      <span className="preset-icon">
                        <p.icon size={19} />
                      </span>
                      <span>
                        <strong>{p.title}</strong>
                        <small>{p.description}</small>
                      </span>
                      <span className="radio-circle">
                        {preset === p.id && <span />}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="config-row">
                  <NumberField
                    label="Jobs per path"
                    value={displayedConfig.count}
                    min={1}
                    max={100}
                    disabled={busy}
                    onChange={(count) => setConfig({ ...config, count })}
                  />
                  <NumberField
                    label="Arrival rate"
                    value={displayedConfig.rate}
                    min={1}
                    max={30}
                    suffix="jobs/s"
                    disabled={busy || config.pattern === "burst"}
                    onChange={(rate) => setConfig({ ...config, rate })}
                  />
                  <NumberField
                    label="Worker concurrency"
                    value={displayedConfig.concurrency}
                    min={2}
                    max={5}
                    suffix="per path"
                    disabled={busy}
                    onChange={(concurrency) =>
                      setConfig({ ...config, concurrency })
                    }
                  />
                  <div className="run-action">
                    <span>Bounded experiment · real QR output</span>
                    {live ? (
                      <button
                        className="button stop"
                        disabled={run?.status === "stopping"}
                        onClick={stop}
                      >
                        <Square size={14} fill="currentColor" />
                        {run?.status === "stopping"
                          ? "Draining accepted jobs…"
                          : "Stop new arrivals"}
                      </button>
                    ) : (
                      <button
                        className="button primary"
                        disabled={
                          !session ||
                          (session.mode === "aws" && !session.configured) ||
                          starting ||
                          switching
                        }
                        onClick={start}
                      >
                        {starting ? (
                          <LoaderCircle className="spin" size={17} />
                        ) : (
                          <Play size={16} fill="currentColor" />
                        )}
                        {starting ? "Preparing…" : "Run experiment"}
                        <ArrowUpRight size={17} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="config-foot">
                  <span>
                    <span className="tiny-dot" />
                    Injected delay: <b>{displayedConfig.delay_ms}ms</b>
                    <span className="dot-divider">·</span>First-attempt
                    failures: <b>{displayedConfig.failure_percent}%</b>
                  </span>
                  <button
                    onClick={() => setAdvanced(!advanced)}
                    aria-expanded={advanced}
                  >
                    Advanced settings
                    <ChevronDown
                      size={14}
                      className={advanced ? "rotate" : ""}
                    />
                  </button>
                </div>
                {advanced && (
                  <div className="advanced-grid">
                    <label className="text-field">
                      <span>Text or URL prefix</span>
                      <input
                        value={config.payload}
                        disabled={busy}
                        onChange={(e) =>
                          setConfig({ ...config, payload: e.target.value })
                        }
                      />
                      <small>
                        A job suffix is added; URLs are encoded, never visited.
                      </small>
                    </label>
                    <NumberField
                      label="Injected delay (ms)"
                      value={config.delay_ms}
                      min={0}
                      max={1000}
                      disabled={busy}
                      onChange={(delay_ms) =>
                        setConfig({ ...config, delay_ms })
                      }
                    />
                    <NumberField
                      label="First-attempt failure (%)"
                      value={config.failure_percent}
                      min={0}
                      max={50}
                      disabled={busy}
                      onChange={(failure_percent) =>
                        setConfig({ ...config, failure_percent })
                      }
                    />
                    <NumberField
                      label="Queued attempt limit"
                      value={config.max_attempts}
                      min={1}
                      max={5}
                      disabled={busy}
                      onChange={(max_attempts) =>
                        setConfig({ ...config, max_attempts })
                      }
                    />
                    <NumberField
                      label="Reproducible seed"
                      value={config.seed}
                      min={0}
                      max={999999}
                      disabled={busy}
                      onChange={(seed) => setConfig({ ...config, seed })}
                    />
                    <label className="text-field">
                      <span>Run first</span>
                      <select
                        value={config.first_lane}
                        disabled={busy}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            first_lane: e.target.value as Lane,
                          })
                        }
                      >
                        <option value="direct">Direct path</option>
                        <option value="queued">Queued path</option>
                      </select>
                    </label>
                  </div>
                )}
              </section>

              <div className="experiment-strip">
                <div>
                  <span className={`status-light ${live ? "pulsing" : ""}`} />
                  <strong>
                    {replay !== null
                      ? "Recorded replay"
                      : live
                        ? `${run?.phase === "direct" ? "Direct" : "Queued"} trial in progress`
                        : run
                          ? `${statusName(run.status)} experiment`
                          : "Ready when you are"}
                  </strong>
                  <span className="mono subtle-label">
                    {run ? run.name : "Start a run to see measured behavior"}
                  </span>
                </div>
                {run && (
                  <span className="subtle-label">
                    {totalCompleted} / {currentCount * 2} COMPLETED
                  </span>
                )}
              </div>
              {run && !live && (
                <div className="replay-bar">
                  <button
                    className="icon-button"
                    aria-label={playing ? "Pause replay" : "Play replay"}
                    onClick={() => {
                      if (replay === null || replay >= 1) setReplay(0);
                      setPlaying(!playing);
                    }}
                  >
                    {playing ? <Square size={13} /> : <Play size={14} />}
                  </button>
                  <span>
                    {replay === null
                      ? "Replay recorded events"
                      : "REPLAY · original event timing"}
                  </span>
                  <input
                    aria-label="Replay position"
                    type="range"
                    min="0"
                    max="1000"
                    value={replay === null ? 1000 : replay * 1000}
                    onChange={(e) => {
                      setReplay(+e.target.value / 1000);
                      setPlaying(false);
                    }}
                  />
                  <button
                    onClick={() => {
                      setReplay(null);
                      setPlaying(false);
                    }}
                  >
                    Latest result
                  </button>
                </div>
              )}
              <div className="lanes">
                {(["direct", "queued"] as Lane[]).map((lane) => (
                  <LanePanel
                    key={lane}
                    lane={lane}
                    run={shown}
                    count={currentCount}
                    onSelect={setSelected}
                    live={live && replay === null}
                  />
                ))}
              </div>
              <div className="legend">
                <span>
                  <i className="planned" />
                  Not sent
                </span>
                <span>
                  <i className="waiting" />
                  Waiting
                </span>
                <span>
                  <i className="running" />
                  Processing
                </span>
                <span>
                  <i className="succeeded" />
                  Completed
                </span>
                <span>
                  <i className="failed" />
                  Failed / rejected
                </span>
                <span>
                  <i className="retrying" />
                  Retry pending
                </span>
                <span className="legend-hint">
                  Each tile is a real job. Click to inspect.
                  <ArrowUpRight size={12} />
                </span>
              </div>
              <div className="bottom-grid">
                <section className="chart-card">
                  <div className="section-top">
                    <div>
                      <h2>Completion over time</h2>
                      <p>
                        Unique completed jobs · seconds since each trial began
                      </p>
                    </div>
                    <div className="chart-key">
                      <span>
                        <i />
                        Direct
                      </span>
                      <span>
                        <i />
                        Queued
                      </span>
                    </div>
                  </div>
                  <CompletionChart run={shown} />
                </section>
                <details className="events-card">
                  <summary>
                    Event log <ChevronDown size={14} />
                  </summary>
                  <div className="section-top">
                    <div className="section-title">
                      <Terminal size={16} />
                      <h2>Event stream</h2>
                    </div>
                    <span className="live-pill">
                      {live ? "LIVE" : "OBSERVED"}
                    </span>
                  </div>
                  <div className="event-list" aria-live="off">
                    {shown?.events
                      .filter((e) => e.job)
                      .slice(-6)
                      .reverse()
                      .map((e) => (
                        <div className="event-row" key={e.seq}>
                          <time>
                            {new Date(e.at).toLocaleTimeString([], {
                              hour12: false,
                            })}
                          </time>
                          <span
                            className={`event-indicator ${e.job!.status}`}
                          />
                          <span>
                            <b>{e.job!.id}</b>
                            <small>
                              {e.lane} / {statusName(e.job!.status)}
                            </small>
                          </span>
                          <span className="attempt-count">
                            a{e.job!.attempts}
                          </span>
                        </div>
                      )) || (
                      <div className="empty-events">
                        <Radio size={27} />
                        <strong>Waiting for the first signal</strong>
                        <p>
                          Job transitions appear here as the backend observes
                          them.
                        </p>
                      </div>
                    )}
                  </div>
                </details>
              </div>
              <div className="method-note">
                <ShieldCheck size={17} />
                <p>
                  <b>Honest experiments, useful evidence.</b> Paths run
                  sequentially with the same workload and capacity. Direct
                  requests get one attempt; queued requests may retry. AWS
                  delivery timing and account limits affect results.
                </p>
                <button onClick={() => setPage("architecture")}>
                  See the design
                  <ArrowRight size={14} />
                </button>
              </div>
              {run?.error && <div className="error-banner">{run.error}</div>}
            </>
          )}

          {page === "history" && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span /> YOUR EXPERIMENT NOTEBOOK
                  </div>
                  <h1>
                    Keep the evidence<span>.</span>
                  </h1>
                  <p>
                    Saved configurations, measured outcomes, and every observed
                    event.
                  </p>
                </div>
                <button
                  className="button secondary"
                  onClick={() => setPage("lab")}
                >
                  <FlaskConical size={16} />
                  Back to lab
                </button>
              </section>
              <section className="history-card">
                <div className="section-top">
                  <h2>Run archive</h2>
                  <span className="subtle-label">
                    {history.length} SAVED RUNS
                  </span>
                </div>
                {history.length === 0 ? (
                  <div className="large-empty">
                    <Clock3 size={32} />
                    <h3>Your first experiment belongs here.</h3>
                    <p>
                      Run the lab once. Results are saved automatically on this
                      computer.
                    </p>
                    <button
                      className="button primary"
                      onClick={() => setPage("lab")}
                    >
                      Start an experiment
                      <ArrowRight size={16} />
                    </button>
                  </div>
                ) : (
                  <div className="history-table">
                    <div className="history-head">
                      <span>EXPERIMENT</span>
                      <span>MODE</span>
                      <span>DIRECT</span>
                      <span>QUEUED</span>
                      <span>STATUS</span>
                      <span />
                    </div>
                    {history.map((r) => (
                      <button
                        className="history-row"
                        key={r.id}
                        disabled={live && run?.id !== r.id}
                        onClick={() => openRun(r.id)}
                      >
                        <span>
                          <b>{r.name}</b>
                          <small>
                            {new Date(r.created_at).toLocaleString()} ·{" "}
                            {r.config.count} jobs/path
                          </small>
                        </span>
                        <span className="small-tag">
                          {r.mode === "aws" ? "AWS" : "Local demo"}
                        </span>
                        <span>
                          {r.metrics.direct.completed}/{r.config.count}
                        </span>
                        <span>
                          {r.metrics.queued.completed}/{r.config.count}
                        </span>
                        <span className={`history-status ${r.status}`}>
                          {statusName(r.status)}
                        </span>
                        <ArrowUpRight size={17} />
                      </button>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}

          {page === "architecture" && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span /> BUILT TO BE UNDERSTOOD
                  </div>
                  <h1>
                    Same work. Different paths<span>.</span>
                  </h1>
                  <p>
                    A small experiment in buffering, backpressure, and recovery.
                  </p>
                </div>
                <span className="small-tag">LAMBDA · SQS · S3</span>
              </section>
              <section className="architecture-hero">
                <div>
                  <span className="subtle-label">THE QUESTION</span>
                  <h2>
                    What changes when
                    <br />
                    work can wait?
                  </h2>
                  <p>
                    Both paths turn text into a QR image. A direct request
                    competes for capacity immediately. A queue accepts work
                    first, then workers process it as capacity becomes
                    available.
                  </p>
                </div>
                <div className="architecture-paths">
                  <div>
                    <span>DIRECT</span>
                    <b>Controller</b>
                    <ArrowRight />
                    <b>Lambda</b>
                    <ArrowRight />
                    <b>S3</b>
                  </div>
                  <div>
                    <span>QUEUED</span>
                    <b>Controller</b>
                    <ArrowRight />
                    <b className="queue-node">SQS</b>
                    <ArrowRight />
                    <b>Lambda</b>
                    <ArrowRight />
                    <b>S3</b>
                  </div>
                  <p>
                    <Database size={16} />
                    DynamoDB records job state · CloudWatch captures diagnostics
                  </p>
                </div>
              </section>
              <div className="principle-grid">
                {[
                  {
                    icon: Layers3,
                    title: "One shared worker",
                    body: "The same QR generation code runs behind both adapters. Inputs, memory, and concurrency are kept comparable.",
                  },
                  {
                    icon: Gauge,
                    title: "Conditions ≠ conclusions",
                    body: "You choose the load, delay, and faults. The backend records what actually happens. A queue is not automatically faster.",
                  },
                  {
                    icon: ShieldCheck,
                    title: "Small by design",
                    body: "100 jobs per path, one active run, bounded retries. AWS handles execution; the dashboard runs on your computer.",
                  },
                ].map((p) => (
                  <section key={p.title}>
                    <p.icon size={24} />
                    <h3>{p.title}</h3>
                    <p>{p.body}</p>
                  </section>
                ))}
              </div>
              <section className="design-details">
                <h2>What the demo proves—and what it doesn’t</h2>
                <p>
                  The AWS deployment invokes Lambda workers through direct calls
                  or SQS. DynamoDB records job state and S3 stores the QR
                  images. The workload, capacity limits, and retry policy
                  determine the results.
                </p>
                <p>
                  Injected delays make the queue visible, but are not QR
                  processing costs. The direct baseline has no retries; queued
                  processing has bounded retries. Read failure counts alongside
                  latency, since latency statistics include only successful
                  jobs.
                </p>
                <p>
                  Stopping a run stops new arrivals. Accepted jobs drain. An
                  interrupted AWS run can leave work in the cloud; use the queue
                  helper before starting another experiment.
                </p>
              </section>
            </>
          )}
          <footer className="page-footer">
            <span>
              <Zap size={13} />
              BURSTLAB
            </span>
            <span>Understand the system. Not just the output.</span>
            <span className="mono">POC / 0.1</span>
          </footer>
        </div>
      </main>

      {job && (
        <div className="drawer-backdrop" onClick={() => setSelected(null)}>
          <aside
            className="job-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Job details"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-heading">
              <span className="eyebrow">INSIDE THE REQUEST</span>
              <button
                className="icon-button"
                aria-label="Close job details"
                onClick={() => setSelected(null)}
              >
                <X size={20} />
              </button>
            </div>
            <h2>{job.id}</h2>
            <span className={`job-status ${job.status}`}>
              {statusName(job.status)}
            </span>
            <div className="qr-preview">
              {job.result_url ? (
                <img
                  src={job.result_url}
                  alt={`QR code containing ${job.payload}`}
                />
              ) : (
                <>
                  <QrCode size={54} />
                  <p>
                    {job.status === "planned"
                      ? "This job hasn’t been sent."
                      : "No completed artifact yet."}
                  </p>
                </>
              )}
            </div>
            <div className="detail-grid">
              <span>
                Path
                <b>
                  {job.lane === "direct"
                    ? "Direct invocation"
                    : "Queued processing"}
                </b>
              </span>
              <span>
                Attempts<b>{job.attempts}</b>
              </span>
              <span>
                Latest processing<b>{milliseconds(job.duration_ms)}</b>
              </span>
              <span>
                Injected first failure
                <b>{job.fail_first ? "Selected" : "No"}</b>
              </span>
            </div>
            <label className="detail-label">ENCODED PAYLOAD</label>
            <div className="payload-box">{job.payload}</div>
            {job.error && <div className="job-error">{job.error}</div>}
            <h3>Attempt history</h3>
            {job.attempt_log.length ? (
              job.attempt_log.map((a, i) => (
                <div className="attempt-row" key={i}>
                  <span
                    className={`event-indicator ${a.outcome === "succeeded" ? "succeeded" : "failed"}`}
                  />
                  <span>
                    Attempt {a.attempt}
                    <small>{statusName(a.outcome)}</small>
                  </span>
                  <b>{milliseconds(a.duration_ms)}</b>
                </div>
              ))
            ) : (
              <p className="muted">No completed attempts recorded yet.</p>
            )}
            {job.result_url && (
              <a
                className="button primary download-artifact"
                href={job.result_url}
                target="_blank"
                rel="noreferrer"
              >
                <ArrowUpRight size={16} />
                Open QR image
              </a>
            )}
          </aside>
        </div>
      )}
      {settings && (
        <div className="modal-backdrop" onClick={() => setSettings(false)}>
          <section
            className="help-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Execution environment"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="Close settings"
              onClick={() => setSettings(false)}
            >
              <X />
            </button>
            <span className="brand-mark">
              <Settings2 />
            </span>
            <h2>Execution environment</h2>
            <p>
              Choose where the next experiment runs. Your preference is saved on
              this computer.
            </p>
            <div className="environment-options">
              <button
                className={
                  session?.mode === "aws"
                    ? "environment-option chosen"
                    : "environment-option"
                }
                disabled={busy || switching}
                onClick={() => switchEnvironment("aws")}
              >
                <strong>
                  AWS {session?.mode === "aws" && <Check size={16} />}
                </strong>
                <span>
                  Run against your deployed Lambda, SQS, S3, and DynamoDB
                  resources.
                </span>
                <small>
                  {session?.configured
                    ? `Configured in ${session.region}. Deployment is checked before each run.`
                    : "Setup required: deploy the stack, save its configuration, then restart."}
                </small>
              </button>
              <button
                className={
                  session?.mode === "local"
                    ? "environment-option chosen"
                    : "environment-option"
                }
                disabled={busy || switching}
                onClick={() => switchEnvironment("local")}
              >
                <strong>
                  Local demo {session?.mode === "local" && <Check size={16} />}
                </strong>
                <span>
                  Generate real QR images on your computer, without AWS calls or
                  charges.
                </span>
                <small>
                  Capacity and retry scheduling are simulated. These results are
                  not AWS benchmarks.
                </small>
              </button>
            </div>
            {run && (
              <p>
                Displayed run environment:{" "}
                <b>{run.mode === "aws" ? "AWS" : "Local demo"}</b>.
              </p>
            )}
            {busy && (
              <p>
                Finish or stop and drain the current experiment before
                switching.
              </p>
            )}
            <button
              className="button primary"
              disabled={switching}
              onClick={() => setSettings(false)}
            >
              Done <Check size={16} />
            </button>
          </section>
        </div>
      )}
      {help && (
        <div className="modal-backdrop" onClick={() => setHelp(false)}>
          <section
            className="help-modal"
            role="dialog"
            aria-modal="true"
            aria-label="How BurstLab works"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="Close help"
              onClick={() => setHelp(false)}
            >
              <X />
            </button>
            <span className="brand-mark">
              <Zap fill="currentColor" />
            </span>
            <h2>Make the invisible visible.</h2>
            <p>
              Pick a preset and run an experiment. Every tile represents a
              QR-generation job. Click one to see its attempts and the actual
              output.
            </p>
            <ol>
              <li>
                <b>Steady stream</b> gives you a baseline with no injected
                delays or failures.
              </li>
              <li>
                <b>Traffic burst</b> sends all jobs together under a chosen
                capacity limit.
              </li>
              <li>
                <b>Recovery test</b> deliberately fails selected first attempts
                to reveal retry behavior.
              </li>
            </ol>
            <p>
              Choose your execution environment in Settings. Start small; when
              using AWS, disable the queue trigger after the session to limit
              idle polling.
            </p>
            <button className="button primary" onClick={() => setHelp(false)}>
              Back to the experiment
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  suffix,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  disabled?: boolean;
  onChange: (n: number) => void;
}) {
  return (
    <label className="number-field">
      <span>{label}</span>
      <div>
        <input
          aria-label={label}
          type="number"
          min={min}
          max={max}
          value={value}
          disabled={disabled}
          onChange={(e) => {
            const n = Number(e.target.value);
            onChange(Math.min(max, Math.max(min, n)));
          }}
        />
        {suffix && <small>{suffix}</small>}
      </div>
    </label>
  );
}

function LanePanel({
  lane,
  run,
  count,
  onSelect,
  live,
}: {
  lane: Lane;
  run: Run | null;
  count: number;
  onSelect: (j: Job) => void;
  live: boolean;
}) {
  const jobs = run?.jobs.filter((j) => j.lane === lane) || [];
  const metrics = run?.metrics[lane] || metric([]);
  const active = live && run?.phase === lane;
  const done = !!run?.phases[lane]?.ended_at;
  const working = jobs.some((j) => j.status === "running");
  const waiting = jobs.filter((j) =>
    ["waiting", "retrying"].includes(j.status),
  ).length;
  return (
    <section className={`lane-card ${lane} ${active ? "active-lane" : ""}`}>
      <div className="lane-heading">
        <div>
          <span className="lane-number">{lane === "direct" ? "01" : "02"}</span>
          <div>
            <h2>
              {lane === "direct" ? "Direct processing" : "Queued processing"}
            </h2>
            <p>
              {lane === "direct"
                ? "Request → worker → result"
                : "Request → buffer → worker → result"}
            </p>
          </div>
        </div>
        <span className={`lane-state ${active ? "active" : ""}`}>
          {active ? (
            <>
              <span className="online-dot" />
              RUNNING
            </>
          ) : done ? (
            <>
              <Check size={12} />
              FINISHED
            </>
          ) : (
            "STANDBY"
          )}
        </span>
      </div>
      <div className={`pipeline ${working ? "flowing" : ""}`}>
        <div className="pipeline-node">
          <span>
            <ArrowRight size={19} />
          </span>
          <b>Ingress</b>
          <small>{metrics.dispatched} sent</small>
        </div>
        <div className="connector">
          <i />
          <ChevronRight size={12} />
        </div>
        {lane === "queued" && (
          <>
            <div className="pipeline-node buffer-node">
              <span>
                <Layers3 size={21} />
                {waiting > 0 && <em>{waiting}</em>}
              </span>
              <b>Queue</b>
              <small>{waiting} pending</small>
            </div>
            <div className="connector">
              <i />
              <ChevronRight size={12} />
            </div>
          </>
        )}
        <div className={`pipeline-node ${working ? "working" : ""}`}>
          <span className="lambda-symbol">λ</span>
          <b>Worker</b>
          <small>{metrics.counts.running || 0} active</small>
        </div>
        <div className="connector">
          <i />
          <ChevronRight size={12} />
        </div>
        <div className="pipeline-node">
          <span>
            <Box size={20} />
          </span>
          <b>Output</b>
          <small>{metrics.completed} images</small>
        </div>
      </div>
      <div className="job-map-head">
        <span>JOB MAP</span>
        <span>
          {jobs.length
            ? `${jobs.filter((j) => terminal.has(j.status)).length} / ${count} resolved`
            : `${count} jobs ready to send`}
        </span>
      </div>
      <div className="job-map">
        {jobs.length
          ? jobs.map((j) => (
              <button
                key={j.id}
                className={`job-tile ${j.status}`}
                title={`${j.id}: ${statusName(j.status)}`}
                aria-label={`${lane} ${j.id}: ${statusName(j.status)}`}
                onClick={() => onSelect(j)}
              >
                {j.status === "succeeded" ? (
                  <Check size={10} />
                ) : j.status === "running" ? (
                  <span />
                ) : j.status === "retrying" ? (
                  <RotateCcw size={9} />
                ) : [
                    "failed",
                    "rejected",
                    "dead_letter",
                    "unresolved",
                  ].includes(j.status) ? (
                  <X size={9} />
                ) : null}
              </button>
            ))
          : Array.from({ length: count }, (_, i) => (
              <span key={i} className="job-tile planned" />
            ))}
      </div>
      <div className="lane-stats">
        <div>
          <span>COMPLETED</span>
          <strong>
            {metrics.completed}
            <small>/{count}</small>
          </strong>
        </div>
        <div>
          <span>P95 LATENCY</span>
          <strong>{milliseconds(metrics.p95_ms)}</strong>
        </div>
        <div>
          <span>{lane === "direct" ? "UNSUCCESSFUL" : "RETRIES"}</span>
          <strong
            className={
              lane === "direct" && metrics.unsuccessful ? "orange-text" : ""
            }
          >
            {lane === "direct" ? metrics.unsuccessful : metrics.retries}
          </strong>
        </div>
      </div>
      <div className="lane-foot">
        <span>
          <span className="tiny-dot" />
          {lane === "direct"
            ? "No caller retries"
            : "Bounded automatic retries"}
        </span>
        <span>{run ? run.config.concurrency : 2} workers max</span>
      </div>
    </section>
  );
}

function CompletionChart({ run }: { run: Run | null }) {
  const width = 580,
    height = 172,
    left = 28,
    bottom = 144,
    top = 18,
    right = 566;
  const maxCount = run?.config.count || 24;
  const duration = Math.max(
    1,
    ...(["direct", "queued"] as Lane[]).map(
      (l) =>
        ((run?.phases[l]?.ended_at || run?.finished_at || Date.now()) -
          (run?.phases[l]?.started_at || Date.now())) /
        1000,
    ),
  );
  const paths = (["direct", "queued"] as Lane[]).map((lane) => {
    const start = run?.phases[lane]?.started_at;
    const completions =
      run?.jobs
        .filter((j) => j.lane === lane && j.status === "succeeded")
        .sort((a, b) => a.finished_at - b.finished_at) || [];
    let d = `M ${left} ${bottom}`;
    if (start)
      completions.forEach((j, i) => {
        const x =
          left +
          Math.max(0, (j.finished_at - start) / 1000 / duration) *
            (right - left);
        const y = bottom - ((i + 1) / maxCount) * (bottom - top);
        d += ` H ${x} V ${y}`;
      });
    return { lane, d };
  });
  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Cumulative completed jobs by seconds since each trial started"
      >
        {[0, 0.5, 1].map((n) => (
          <g key={n}>
            <line
              x1={left}
              y1={bottom - n * (bottom - top)}
              x2={right}
              y2={bottom - n * (bottom - top)}
              stroke="#e2e8f0"
              strokeDasharray="3 5"
            />
            <text
              x={left - 10}
              y={bottom - n * (bottom - top) + 4}
              textAnchor="end"
            >
              {Math.round(maxCount * n)}
            </text>
          </g>
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((n) => (
          <text
            key={n}
            x={left + n * (right - left)}
            y={height - 7}
            textAnchor="middle"
          >
            {(duration * n).toFixed(1)}s
          </text>
        ))}
        {run &&
          paths.map((p) => (
            <path
              key={p.lane}
              d={p.d}
              stroke={p.lane === "direct" ? "#d98256" : "#2563eb"}
              strokeWidth="2.5"
              fill="none"
            />
          ))}
      </svg>
      {!run && (
        <div className="chart-empty">
          <Activity size={19} />
          <span>Your next run draws the first line.</span>
        </div>
      )}
    </div>
  );
}
