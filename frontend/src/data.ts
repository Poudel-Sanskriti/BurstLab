import type {Config, Job, Lane, Metric, Run} from './types'

export const defaultConfig: Config = {name: 'Recovery under pressure', count: 24, rate: 12, concurrency: 2, delay_ms: 350, failure_percent: 20, max_attempts: 3, pattern: 'steady', payload: 'https://example.com/burstlab', seed: 42, first_lane: 'direct'}
export const terminal = new Set(['succeeded', 'failed', 'rejected', 'dead_letter', 'cancelled', 'unresolved'])
export const statusName = (status: string) => ({succeeded: 'Completed', dead_letter: 'Exhausted', retrying: 'Retry pending', planned: 'Not sent', rejected: 'Rejected'}[status] || status.replaceAll('_', ' ').replace(/^./, x => x.toUpperCase()))
export const milliseconds = (n: number | null | undefined) => n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`
export function metric(jobs: Job[], start?: number, end?: number): Metric {
  const counts: Record<string, number> = {}
  jobs.forEach(j => {counts[j.status] = (counts[j.status] || 0) + 1})
  const latencies = jobs.filter(j => j.status === 'succeeded').map(j => Math.max(0, j.finished_at - j.submitted_at)).sort((a,b) => a-b)
  const waits = jobs.filter(j => j.started_at).map(j => Math.max(0, j.started_at-j.submitted_at)).sort((a,b) => a-b)
  const p95 = (a: number[]) => a.length ? a[Math.ceil(a.length*.95)-1] : null
  const elapsed = start ? Math.max(0,(end || Date.now())-start) : 0
  return {counts, total: jobs.length, completed: counts.succeeded || 0, unsuccessful: jobs.filter(j => ['failed','rejected','dead_letter','unresolved'].includes(j.status)).length, dispatched: jobs.filter(j => j.submitted_at).length, attempts: jobs.reduce((n,j)=>n+j.attempts,0), retries: jobs.reduce((n,j)=>n+Math.max(0,j.attempts-1),0), p50_ms: latencies.length ? latencies[Math.ceil(latencies.length*.5)-1] : null, p95_ms:p95(latencies),wait_p95_ms:p95(waits),elapsed_ms:elapsed,throughput: elapsed ? latencies.length/(elapsed/1000) : 0,latency_samples:latencies.length}
}
export function replayAt(run: Run, fraction: number): Run {
  const until = run.created_at + ((run.finished_at || run.created_at)-run.created_at)*fraction
  const jobs: Job[] = run.jobs.map(j => ({...j,status:'planned',attempts:0,attempt_log:[],submitted_at:0,started_at:0,finished_at:0,result_url:undefined,error:undefined}))
  const events = run.events.filter(e=>e.at<=until)
  for (const event of events) if (event.job) {
    const index = jobs.findIndex(j=>j.id===event.job!.id && j.lane===event.job!.lane)
    if (index >= 0) jobs[index] = event.job
  }
  const metrics = Object.fromEntries((['direct','queued'] as Lane[]).map(lane => [lane, metric(jobs.filter(j=>j.lane===lane), run.phases[lane]?.started_at && run.phases[lane]!.started_at<=until ? run.phases[lane]!.started_at : undefined, Math.min(until,run.phases[lane]?.ended_at || until))])) as Record<Lane,Metric>
  return {...run,jobs,events,metrics}
}
