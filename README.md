# BurstLab

**A visual lab for systems under pressure.** Compare direct and queued processing, inspect real QR outputs, and replay what happened to every job.

## Run the demo

Requirements: Python 3.11+ and Node.js 20.19+ (or a current Node 22/24 release). The Lambda deployment uses Python 3.13.

```bash
bash scripts/dev.sh
```

Open **http://127.0.0.1:8000**. The first launch installs dependencies and builds the frontend; subsequent launches reuse the installed dependencies. Stop the server with Ctrl+C.

**Default mode is local. No AWS account, credentials, or paid API is needed.** Local mode runs real QR generation and writes actual images. Its concurrency rejection, queue, and short retry delay are local models—not measurements of AWS behavior. The UI labels this clearly.

Choose **Recovery test**, then **Run experiment**. Direct requests compete for limited capacity; the queued path buffers work and retries selected first-attempt failures. Click a tile to inspect the payload, attempts, and QR image. Completed runs can be replayed and exported as JSON or CSV.

## What is implemented

- Shared Python QR workload with bounded UTF-8 inputs and deterministic PNG results.
- Direct and queued Lambda adapters with conditional job claims, retry accounting, private S3 outputs, and DynamoDB state.
- AWS SAM template for two Lambda functions, SQS and a dead-letter queue, S3, DynamoDB, and one-day CloudWatch logs.
- Local controller with sequential comparison trials, seeded fault selection, stop-arrivals control, SQLite history, metrics, and exports.
- AWS controller adapter with configuration preflight, synchronous direct invocation, SQS submissions, and run reconciliation.
- React/TypeScript dashboard with presets, animated processing paths, job tiles, chart, event stream, details, archive, and replay.

**Live AWS deployment and cloud measurements are pending.** The account is not available yet. Passing local tests does not validate AWS quotas, IAM access, deployment packaging, or live timing. See [AWS setup](docs/AWS_SETUP.md) when ready.

## Stack and layout

```text
backend/
  worker/          Shared QR logic and Lambda adapters
  app.py           Local, session-protected FastAPI server
  engine.py        Experiment lifecycle and local execution
  cloud.py         Real AWS invocation and polling adapter
  store.py         SQLite history
frontend/          React + TypeScript + Vite dashboard
infra/             AWS SAM/CloudFormation template
scripts/           Local launcher and explicit AWS controls
tests/             Focused backend unit tests
.data/             Ignored run history, images, and AWS identifiers
```

The sibling `artifacts` directory belongs outside this repository and is not published with it. No credentials belong in source control.

## Controls and interpretation

| Control | Meaning |
| --- | --- |
| Jobs per path | 1–100 distinct jobs sent to each architecture |
| Arrival rate | Requested jobs/second for steady runs; burst sends all scheduled jobs together |
| Worker concurrency | Equal capacity in each local lane; must match deployed Lambda caps in AWS mode |
| Injected delay | Deliberate sleep, not a QR computation benchmark |
| First-attempt failures | Seeded subset fails once before generating its output |
| Queued attempt limit | Maximum application processing attempts; direct requests have no caller retries |

Trials run **sequentially** to reduce shared resource contention. Both use the same payload manifest, with an added job suffix. Flip the first path in Advanced settings for another run. The chart aligns each trial to its own start time.

Latency percentiles include **successful jobs only**. Read them alongside unsuccessful counts. Waiting time includes scheduling and transport. Throughput is unique completions divided by the phase observation duration. The direct baseline and queued path have different retry policies; results do not establish that buffering alone caused every difference.

**Stop new arrivals** does not cancel already accepted work. It drains existing jobs. Local history is retained in `.data/`; restarting the controller marks interrupted experiments rather than pretending they completed. For an interrupted AWS run, inspect the actual queues before continuing.

## Focused tests

```bash
.venv/bin/python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run build
```

The unit tests cover QR output, bounds, queue partial failures, job accounting, retry recovery, stopping, local API restrictions, and frontend metric/replay calculations. They are a small PoC suite, not a production certification.

For frontend development in two terminals:

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

Vite proxies API requests to the controller. Production assets are built and served by FastAPI for the single-command demo.

## Cost and remaining limitations

- Local experiments incur no AWS service charges. Installed development tools and your existing AI subscriptions are separate.
- Cloud deployment is manual; the queue trigger starts disabled. Enable it for testing, then disable it.
- No NAT gateway, hosted control plane, paid inference, always-on VM, or provisioned concurrency.
- Storage expires after one day in AWS; expiration is asynchronous. Logs retain one day. Provisioning artifacts and resources can still cost money until cleaned up.
- The suggested $5 development budget is a target, not an enforced billing cap. Use a few small runs and check your account's actual usage.
- Local execution does not model AWS cold starts, SQS visibility timing, or approximate queue metrics.
- AWS telemetry is polled every two seconds and may skip short visual transitions; it preserves observed events and authoritative job state. Events are not a transactional audit log.
- App-level exhausted retries are labeled **Exhausted**; physical SQS redrive happens separately. A message rejected before job state exists may remain unresolved until the queue is inspected.
- Local history is for one developer, not a multi-user hosted product. QR encodings are tested as real PNG outputs; comprehensive scanner interoperability remains future work.

