"""Explicit AWS setup/queue controls. Never deploys or starts an experiment."""

import argparse
import json
from pathlib import Path
import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["configure", "enable", "disable", "status"])
    parser.add_argument("--stack", default="burstlab")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--profile")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    session = boto3.Session(region_name=args.region, profile_name=args.profile)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)[
        "Stacks"
    ][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    if args.action == "configure":
        (root / ".data").mkdir(exist_ok=True)
        (root / ".data" / "aws-config.json").write_text(
            json.dumps(
                {"region": args.region, "profile": args.profile, "outputs": outputs},
                indent=2,
            )
        )
        print(
            "Saved stack identifiers (no credentials). Enable the queue, then restart the app."
        )
    client = session.client("lambda")
    mappings = client.list_event_source_mappings(
        FunctionName=outputs["QueuedFunction"], EventSourceArn=outputs["QueueArn"]
    )["EventSourceMappings"]
    for mapping in mappings:
        if args.action in ("enable", "disable"):
            response = client.update_event_source_mapping(
                UUID=mapping["UUID"], Enabled=args.action == "enable"
            )
            print(
                "Queue trigger:", response["State"], "(run status again before testing)"
            )
        else:
            print("Queue trigger:", mapping["State"])
    sqs = session.client("sqs")
    for key in ("QueueUrl", "DeadLetterUrl"):
        state = sqs.get_queue_attributes(
            QueueUrl=outputs[key],
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )["Attributes"]
        print(key, state)


if __name__ == "__main__":
    main()
