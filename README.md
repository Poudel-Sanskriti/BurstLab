# BurstLab

**A visual AWS lab for systems under pressure.** Compare direct and queued processing, inspect generated QR images, and replay observed job events.

## Execution environment

AWS is the default environment. AWS experiments use your deployed Lambda workers, SQS queue, DynamoDB table, and S3 bucket. The dashboard/controller run on your computer to avoid hosted-server costs. Choose **Settings → Execution environment → Local demo** for free, simulated scheduling with real QR output.

Without an AWS configuration, Run is disabled in AWS mode. Settings lets you select Local demo instead. The main dashboard has no prominent simulation banner; Settings and JSON reports retain the actual environment. History and artifact access are scoped to the selected environment, so runs are not mixed. You cannot switch during an experiment, and your selection persists across restarts.

## Get started

1. Install Python 3.11+ and Node.js 20.19+ or a current Node 22/24 release.
2. Run `bash scripts/dev.sh` to install dependencies, build the dashboard, and open the controller at **http://127.0.0.1:8000**.
3. Follow [AWS setup](docs/AWS_SETUP.md): configure AWS credentials, build/deploy the SAM stack, save its outputs with the helper, and enable the queue trigger.
4. Restart `bash scripts/dev.sh`. No mode environment variable is needed; select AWS in Settings if you previously used Local demo.
5. Start with 5 jobs per path. The controller checks deployed resource settings before submitting work.

A saved configuration means the resource identifiers are available; it does not prove the deployment is healthy. The preflight check runs before an experiment. No cloud resources are created by the launcher.

## Implemented components

- Shared Python QR worker; direct synchronous Lambda and SQS-triggered Lambda adapters.
- Conditional DynamoDB claims, repeatable S3 artifact keys, bounded application retries, and partial-batch failure responses.
- SAM/CloudFormation template with private encrypted S3, DynamoDB, SQS, dead-letter queue, and short-lived CloudWatch logs.
- Python/FastAPI controller, real AWS invocation, state reconciliation, SQLite run history, JSON/CSV export, and stop-arrivals control.
- React/TypeScript dashboard with experiment presets, two processing lanes, job inspection, QR previews, charts, archive, and replay.

**Live AWS deployment and end-to-end verification are still pending.** Tests use isolated logic and AWS mocks; they do not validate live IAM permissions, service quotas, or packaging.

## Run controls

Maximum 100 jobs per path, one active experiment, 2–5 workers per path, 0–1000 ms injected delay, and up to 5 application attempts. Both functions must have matching deployed concurrency, memory, and timeout settings. Changing concurrency in the UI requires matching changes to the SAM deployment.

Paths run sequentially using the same payload manifest. Direct requests have one synchronous attempt; queued requests may retry. Injected delays and failures are deliberate conditions, not natural QR-processing performance. Latency percentiles include successful jobs only; compare them alongside unsuccessful outcomes. Stopping arrivals allows accepted work to drain.

## Tests and development

```bash
.venv/bin/python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run build
```

For frontend development, run the FastAPI controller and Vite in separate terminals:

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

The API is session-protected and loopback-bound. AWS credentials remain in the server-side SDK credential chain, never in browser code. Generated URLs are encoded into QR images without being visited.

## Cost and limitations

Keep tests small and disable the SQS event-source mapping after the session. No always-on VM, NAT gateway, hosted control plane, provisioned concurrency, or paid inference is required. Storage and logs use short retention, but expiry is asynchronous and budget alerts do not cap the bill.

SQS retries can take 90 seconds or longer. Telemetry is polled every two seconds; brief transitions may not animate even when recorded. Events are not a transactional audit log. App-level exhausted attempts and physical dead-letter queue routing are distinct. Interrupted cloud jobs can continue: inspect queues before another run. The lab does not predict arbitrary production capacity or promise exactly-once delivery.

