# AWS deployment and low-cost test session

**Status:** Prepared for deployment, not live-tested. Do this only after creating your AWS account. The launcher runs the dashboard/controller on your computer and never provisions AWS resources. Experiments require AWS.

## 1. Prerequisites

Install AWS CLI v2, AWS SAM CLI, and Docker for container-based Lambda builds. Configure a local AWS profile using your preferred credential mechanism; keep credentials outside the repository. Choose one region, such as `us-east-2`.

Check current free-plan eligibility, credits, and service availability. Set a small budget alert. Alerts do not stop spending. This account is assigned Ohio and initially has 10 concurrent Lambda executions. Leave UseReservedConcurrency=false: both workers enforce the same two-job admission limit using expiring DynamoDB permits, and SQS also limits concurrent delivery. Reports identify application-admission capacity. This does not claim that AWS rejected those requests through reserved concurrency.

## 2. Build and deploy

Run from the repository root:

```bash
sam build --template-file infra/template.yaml --use-container
sam deploy --guided
```

Choose stack name **burstlab**, worker concurrency **2**, **UseReservedConcurrency=false**, and **EnableQueue=false**. Review the IAM capabilities and changes before approving the deployment. Both workers should use the same code build, Python runtime, 256 MB memory, and 15-second timeout. The queue visibility timeout is 90 seconds and batch size is one.

The template creates no public API. Your local controller uses AWS SDK calls. Its development credentials need access to this stack's Lambda invocation/configuration, SQS submission/attributes, DynamoDB queries, and S3 result retrieval. The helper also needs CloudFormation stack reads and Lambda event-source mapping configuration. Use a dedicated development account/profile and restrict permissions to these resources where practical.

The Python QR dependency uses Pillow. Container-based SAM builds package the Linux dependencies for Lambda; do not copy your macOS virtual environment into the function.

## 3. Connect the local controller

```bash
.venv/bin/python scripts/aws.py configure --stack burstlab --region us-east-2
.venv/bin/python scripts/aws.py enable --stack burstlab --region us-east-2
.venv/bin/python scripts/aws.py status --stack burstlab --region us-east-2
```

Add `--profile your-profile` consistently if you use a named profile. The configure command saves resource identifiers in ignored `.data/aws-config.json`, not credentials. Wait until the status command reports the event-source mapping as **Enabled**.

Restart the local server in cloud mode:

```bash
bash scripts/dev.sh
```

The dashboard must show an AWS configuration; the run itself is verified by preflight. Before running, the controller checks both worker caps/settings and confirms the work and dead-letter queues appear empty. Queue counts are approximate; after interrupted work, inspect AWS before relying on that check.

## 4. Run only two or three small experiments

1. **Smoke:** Steady stream, 5 jobs per path, 1 job/second, no injected failures or delay. Open a result image.
2. **Burst:** 20 jobs per path, 350 ms injected delay, no failures. Record acceptance, unsuccessful jobs, and successful-job latency.
3. **Recovery, optional:** 10 jobs per path, 20% first-attempt failures, 3 application attempts. SQS retries may take 90 seconds or longer to appear. Do not repeatedly press Run while waiting.

Observe one full experiment at a time. AWS runs allow a ten-minute observation window per lane. Unresolved results are not proof of lost work. Direct invocation timeouts can still produce a later artifact; reconcile with stored state.

The cloud worker uses conditional leases to avoid concurrent finalization, and deterministic artifact names make retried QR work repeatable. It does not claim global exactly-once delivery. Do not use sensitive payloads in initial tests.

## 5. Finish the session

Export the run JSON and record the demo while results are available. Then disable background queue polling:

```bash
.venv/bin/python scripts/aws.py disable --stack burstlab --region us-east-2
.venv/bin/python scripts/aws.py status --stack burstlab --region us-east-2
```

Disabling the mapping does not stop in-flight Lambda executions. Stop the local controller and check that no work remains. For emergency interruption, disable the mapping and investigate the queues before deleting or replaying messages.

For full teardown, use the AWS console to inspect and empty **only this stack's result bucket**, after saving wanted outputs. Then run:

```bash
sam delete --stack-name burstlab --region us-east-2
```

Review the named stack/resources at the confirmation. A nonempty bucket may prevent stack deletion. Inspect SAM's deployment-artifact bucket and failed-deletion resources afterward; lifecycle rules do not guarantee immediate deletion or a zero bill.

## References

- [AWS free account plans](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)
- [SAM build](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-command-reference-sam-build.html)
- [Synchronous invocation behavior](https://docs.aws.amazon.com/lambda/latest/dg/invocation-sync.html)
- [SQS event-source configuration](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html)
- [SQS maximum concurrency](https://docs.aws.amazon.com/lambda/latest/api/API_ScalingConfig.html)
