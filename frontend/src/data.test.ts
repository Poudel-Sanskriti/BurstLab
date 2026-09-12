import { describe, expect, it } from 'vitest'
import { metric, milliseconds, replayAt, defaultConfig } from './data'
import type { Job, Run } from './types'

const job: Job = {id:'job-001',lane:'queued',payload:'hello',status:'succeeded',attempts:2,submitted_at:1000,started_at:1200,finished_at:2000,attempt_log:[],fail_first:true}
describe('measured results',()=>{
  it('counts unique completions and extra attempts',()=>{
    const result=metric([job,{...job,id:'job-002',status:'rejected',attempts:0}],1000,3000)
    expect(result.completed).toBe(1)
    expect(result.retries).toBe(1)
    expect(result.p95_ms).toBe(1000)
    expect(result.throughput).toBe(.5)
  })
  it('does not invent latency for an empty run',()=>{
    expect(metric([]).p95_ms).toBeNull()
    expect(milliseconds(null)).toBe('—')
  })
  it('replays only observed transitions',()=>{
    const run={id:'r',created_at:1000,finished_at:3000,config:defaultConfig,jobs:[job],phases:{queued:{started_at:1000,ended_at:3000}},events:[{seq:1,at:2000,kind:'job',job}]} as Run
    expect(replayAt(run,.1).jobs[0].status).toBe('planned')
    expect(replayAt(run,1).metrics.queued.completed).toBe(1)
  })
})
