# AWS Emulator: Team Guide

*Last updated: 16 Nov 2026. Based on the official AWS docs, an independent hands-on review, and our own testing on Ubuntu (x86_64).*

---

## 1. What is it?

AWS Emulator is AWS's own **local emulator of the AWS APIs**. It is a program that runs on your machine and serves an AWS-compatible endpoint. You point the AWS CLI or an AWS SDK at it, and your code talks to the emulator instead of real AWS.

- Endpoint: `https://127.0.0.1:9297` (HTTPS, self-signed certificate)
- No AWS account needed, no AWS bill
- Everything you create is kept **in memory** and disappears when the emulator stops
- It is **not** real AWS infrastructure, and it has **no web console or UI**

**Mental model**

```
Real AWS:     [Your app on EC2]  ->  S3, DynamoDB, SQS ...
With emulator: [Your app on laptop/CI]  ->  [AWS Emulator: simulated S3, DynamoDB, SQS ...]
```

Your laptop plays the role of the server, and the emulator plays the role of the AWS services your app calls.

---

## 2. Installation (Linux, Debian/Ubuntu)

### 2.1 Install the package

```bash
# x86_64 / amd64
curl -fsSLo aws-emulator.deb https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator_amd64.deb
sudo apt-get install -y ./aws-emulator.deb

# ARM machines: use aws-emulator_arm64.deb instead
```

Notes:
- The download is large (about 163 MiB), and it unpacks to one binary of roughly 926 MiB.
- The package adds the `aws-emulator` command to `/usr/bin/`.
- Other platforms: RPM packages exist for Amazon Linux / RHEL-family systems. On macOS and Windows you run it in Docker from an image you build yourself with the Dockerfile in the AWS docs (no ready-made image is published).

### 2.2 Optional: verify the package signature

AWS signs each package. To verify before installing:

```bash
curl -fsSLo aws-publishing.asc https://downloads.aws.com/keys/gpg/current.asc
gpg --import aws-publishing.asc
gpg --fingerprint ssm-publishing@amazon.com
# Fingerprint must be: 98BC F336 A3BE 53B7 34E9 67C5 2E5B F49B D940 F624
# If it differs, do NOT install the package.

# Download the .sig file next to the package (same name + .sig), then:
gpg --verify aws-emulator_amd64.deb.sig aws-emulator_amd64.deb
# Expect: Good signature from "SSM Publishing <ssm-publishing@amazon.com>"
```

### 2.3 Confirm and start

```bash
aws-emulator -v                  # prints the version
aws-emulator --telemetry off     # starts the emulator; keep this terminal open
```

The emulator sends anonymous usage/error data to AWS by default. `--telemetry off` turns that off.

To run it in the background instead:

```bash
nohup aws-emulator --telemetry off > ~/aws-emulator.log 2>&1 &
tail -f ~/aws-emulator.log      # watch the log
pkill aws-emulator               # stop it
```

On first start it generates its own credentials, config and CA certificate in `~/.aws/emulator/9297/`.

### 2.4 Health check

```bash
curl --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health
# Expected output: ok
```

> Do **not** open `https://127.0.0.1:9297` in a browser. It is an API endpoint, not a website. Opening it over plain `http://` gives `ERR_INVALID_HTTP_RESPONSE`, and over `https://` you only get a certificate warning.

### 2.5 Install the AWS CLI (it is not bundled)

```bash
curl -fsSLo /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip"
cd /tmp && unzip -qo awscliv2.zip && sudo ./aws/install --update
aws --version
```

---

## 3. Pointing the CLI and SDKs at the emulator

Create `~/aws-emulator.env`:

```bash
export AWS_SHARED_CREDENTIALS_FILE=$HOME/.aws/emulator/9297/emulator_credentials
export AWS_CONFIG_FILE=$HOME/.aws/emulator/9297/config
export AWS_CA_BUNDLE=$HOME/.aws/emulator/9297/ca.pem
export NODE_EXTRA_CA_CERTS=$HOME/.aws/emulator/9297/ca.pem
export AWS_EC2_METADATA_DISABLED=true
export AWS_DISABLE_HOST_PREFIX_INJECTION=true
export AWS_REGION=us-east-1
export AWS_PAGER=""
```

Load it **in every terminal** where you want to use the emulator:

```bash
source ~/aws-emulator.env
```

Verify:

```bash
aws sts get-caller-identity     # should show account 000000000000
```

Try some calls:

```bash
aws s3 mb s3://demo-bucket
echo "hello" > hello.txt
aws s3 cp hello.txt s3://demo-bucket/
aws s3 ls s3://demo-bucket
aws sqs create-queue --queue-name demo
aws sqs list-queues
aws dynamodb list-tables
```

Python (boto3) example. It needs no hardcoded endpoint when the env vars are set:

```python
import boto3
s3 = boto3.client("s3")
s3.create_bucket(Bucket="py-demo")
s3.put_object(Bucket="py-demo", Key="hello.txt", Body=b"hello from python")
print(s3.list_objects_v2(Bucket="py-demo")["Contents"])
```

### Safety tip: know which account you are talking to

Before any destructive command (`aws s3 rb`, `terraform apply`, and so on), run:

```bash
aws sts get-caller-identity
```

- `000000000000` means the **emulator**.
- A different 12-digit ID means **real AWS**.

---

## 4. Features and capabilities

- Works with the **AWS CLI and AWS SDKs** without code changes. Only the endpoint and credentials come from environment variables.
- Services are generated from the **official AWS API models** (the same ones behind the SDKs), so new AWS services and APIs appear over time.
- Supports calls that **cross services** (for example, code that uses S3 and SQS together).
- Reproduces AWS-style **validation errors**. For example, a too-short DynamoDB table name is rejected with the same error as AWS.
- **Embedded mode** for tests written in Rust with the AWS SDK for Rust.
- An **`aws-emulator` skill for AI coding agents** that can install, start and connect the emulator and check whether a project is expected to work.
- **Open source**: the code is CC0, with the `vendor/` directory under Apache 2.0.
- **Fidelity tests are public**, including the ones the emulator does not pass yet. Scores are published with every release.
- No extra service fee.

### How closely does it match AWS?

- It matches AWS most closely for **control plane** APIs (create, describe, update, delete, list).
- **Data plane** behavior and support for IaC tools (Terraform, CloudFormation, CDK) **varies by service**.
- Per-service fidelity scores are on the releases page: <https://github.com/aws/aws-emulator/releases>
- The test list is in the repo <https://github.com/aws/aws-emulator-evaluation-suite> (see `manifest.jsonl`).

---

## 5. Uses

1. **Develop without an AWS account or bill**: build and run code that uses S3, SQS, DynamoDB and so on, even offline.
2. **Automated tests and CI**: start the emulator, run integration tests, throw it away. Fast, free, and clean on every run.
3. **Safe experimenting**: try destructive or unfamiliar operations with no consequences. It is also a cheap way to learn the CLI and SDKs.
4. **Catch bugs early**: AWS-style validation errors show up before deployment.
5. **Prototyping with AI coding agents**: agents can build and run apps locally in a fast loop.

**Typical workflow**

1. Write code with the AWS SDK and no hardcoded endpoint.
2. Run it against the emulator during development and in CI.
3. Deploy the same code to real AWS.
4. Do final checks on real AWS (IAM, performance, region behavior).

---

## 6. Differences from real AWS

| Area | Real AWS | AWS Emulator |
|---|---|---|
| Infrastructure | Real servers and managed services | Simulation of the APIs on your machine |
| Persistence | Durable | In memory only; wiped when it stops |
| IAM and resource policies | Enforced | **Not evaluated like AWS**, so don't use it for security testing |
| Regions and accounts | Separate per Region and account | Accepts any, but **does not separate** resources by Region or account. Use one Region and one account per emulator. For several Regions, run one emulator per Region on separate ports |
| Verification | n/a | Checked against AWS in `us-west-2` (global services in `us-east-1`) only |
| Scale and duration | Production-grade | Not tested for long-running use or load testing |
| Console | AWS Management Console | **No GUI** (CLI, SDKs and IaC only) |
| Cost | Pay per use | Free |

---

## 7. Limitations

- **Not for production workloads.**
- **Not for security or IAM testing**: policies are not evaluated like on AWS.
- **One Region and one account** model (see the table above).
- **In-memory only**: all resources are deleted when the emulator stops.
- **Not tested for long-running use or load testing.** Start it for tests and stop it afterwards, or use `--idle-timeout` so it stops by itself.
- **Fidelity varies by service and feature.** Check the published scores for the services you rely on.
- **No UI.** Third-party UIs built for other emulators (for example LocalUI, MyDevStack) might work but are untested with this emulator, and they would need to trust the emulator's self-signed CA.
- **Resource limits reported by an independent review** (may have changed in newer releases):
  - at most 64 MiB in one bucket
  - at most 1,000 messages in one queue
  - the JavaScript SDK's SQS client sent a request to the real `sqs.us-east-1.amazonaws.com` by default. Verify that SQS calls really stay local if you use the JS SDK.
  - Terraform AWS provider 6.73.0 could not read back an S3 bucket. Try another provider version if you hit this.
- **Heavy install**: about 163 MiB download and a roughly 926 MiB binary.
- **Anonymous telemetry is on by default** (turn it off with `--telemetry off`).
- It is **new**, so there is less community experience than with older tools such as LocalStack.

---

## 8. Pros and cons

### Pros

- Free, fast, and works offline, with no account and no billing risk
- Made by AWS and generated from the official API models, so its API shapes should be close to real AWS
- Good for CI: every run starts from a clean state
- Open source and inspectable, with public fidelity tests
- Safe sandbox for experiments
- Same code for local and real AWS (only the endpoint and credentials change)

### Cons

- Simulation only: results can differ from real AWS
- No IAM or security testing
- No persistence and no GUI
- Single Region and single account model
- Fidelity gaps that depend on the service
- Known bugs and limits reported by early reviewers
- Large install, and telemetry on by default (can be disabled)
- New tool with a smaller community

---

## 9. FAQ and common doubts

**Q: Does the emulator run real AWS services locally?**
No. It imitates the AWS APIs. There is no real AWS infrastructure behind it.

**Q: Is the emulator at `https://127.0.0.1:9297`, and can I use it from code and the CLI?**
Yes. Load `~/aws-emulator.env`, then use the CLI or any SDK normally.

**Q: The browser shows `ERR_INVALID_HTTP_RESPONSE` for `127.0.0.1:9297`. Is it broken?**
No. It is an API endpoint served over HTTPS, not a web page. Test it with `curl --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health`.

**Q: Is there a console UI like the AWS Management Console?**
No. The official docs say there is no graphical interface. Options: use the CLI with `--output table`, or try a third-party UI built for other emulators (untested with this one).

**Q: Does it run EC2 and ECS?**
Their APIs respond. In our test on this machine, `aws ec2 describe-instances` and `aws ecs create-cluster` worked, and `run-instances` returned an instance with ID `i-00000000000000001` and IP `172.31.0.4`. The docs describe an API emulator with in-memory resources, and we found nothing saying it starts real VMs or containers. **We have not confirmed this**, so check `docker ps` and `ping <instance IP>` yourself after `run-instances` or `ecs run-task`. If you need real compute locally, use Docker directly, a Docker-backed emulator such as Floci or MiniStack (we have not compared their fidelity), or real AWS.

**Q: In real AWS we run our application on EC2. Can we do that here?**
Not in the same way, and you don't need to. Run your app on your laptop, in Docker, or in CI, and let the emulator stand in for the AWS services your app **calls** (S3, SQS, DynamoDB and so on). The EC2 API emulation is only useful for code that **manages** EC2 (launch, tag, stop, terminate), not for running your application.

**Q: `InvalidAMIID.Malformed` when running `run-instances`?**
The AMI ID must look like a real one (`ami-` plus 17 hex characters). `ami-12345678` was rejected, while `ami-0123456789abcdef0` was accepted.

**Q: I also have real AWS credentials configured. Will they clash?**
No, as long as you use the env file. `AWS_SHARED_CREDENTIALS_FILE` points the CLI at the emulator's own credentials file (`~/.aws/emulator/9297/emulator_credentials`). Your normal `~/.aws/credentials` is used in terminals where you did **not** source the env file. Check with `aws configure list` or `echo $AWS_SHARED_CREDENTIALS_FILE`. Never paste real keys into chats or commit them to git.

**Q: Can I run `aws-emulator` in a second terminal?**
Yes, from any terminal. But if it is already running, a second copy will conflict on port 9297. Check first with `ss -ltnp | grep 9297`.

**Q: Why are there no resources after I restart it?**
State is in memory only. Create test resources from a script so you can recreate them quickly.

**Q: Where are the emulator credentials and certificate?**
In `~/.aws/emulator/9297/` (`emulator_credentials`, `config`, `ca.pem`). Don't delete this folder. If you do, restart the emulator and it will regenerate the files.

**Q: How do I uninstall it?**
Likely `sudo apt-get remove aws-emulator` (the package name is assumed from the `.deb` file name), but check the "To uninstall AWS Emulator" section of the user guide to be sure.

---

## 10. Troubleshooting checklist

| Symptom | Check |
|---|---|
| Health check fails | Is it running? `ss -ltnp \| grep 9297`. Does `~/.aws/emulator/9297/ca.pem` exist? Check the startup log for the actual port. |
| CLI says credentials error, or hits real AWS | Run `source ~/aws-emulator.env` in that terminal. Then `aws configure list` and `aws sts get-caller-identity`. |
| Certificate errors from Node or other tools | Set `NODE_EXTRA_CA_CERTS` / `AWS_CA_BUNDLE` to `~/.aws/emulator/9297/ca.pem`. |
| CLI output stuck in a pager (`:` at the bottom) | Press `q`, and `export AWS_PAGER=""`. |
| Port already in use | Another emulator copy is running. Stop it with `pkill aws-emulator`. |
| Resources vanished | Normal. State is lost when the emulator stops. |

---

## 11. When to use it, and when not to

**Use it for:** local development, integration tests, CI, learning the CLI/SDKs, prototyping, and testing code that creates or manages AWS resources.

**Use real AWS (or another tool) for:** IAM and security checks, performance and load tests, multi-Region behavior, anything that must persist, and running real EC2/ECS workloads.

---

## 12. References

- AWS Emulator user guide: <https://docs.aws.amazon.com/emulator/latest/userguide/what-is-service.html>
- Fidelity in AWS Emulator: <https://docs.aws.amazon.com/emulator/latest/userguide/fidelity.html>
- Linux install guide: <https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html>
- Product page: <https://aws.amazon.com/products/developer-tools/emulator/>
- Source code: <https://github.com/aws/aws-emulator>
- Fidelity tests: <https://github.com/aws/aws-emulator-evaluation-suite>
- Releases and fidelity scores: <https://github.com/aws/aws-emulator/releases>
- AWS News Blog announcement: <https://aws.amazon.com/blogs/aws/test-your-applications-against-aws-locally-with-aws-emulator/>
- Independent hands-on review (source of the reported limits and bugs): <https://dev.to/devopsdaily/we-tested-aws-emulator-it-blocks-more-than-its-docs-say-and-less-than-aws-does-bg6>

> **Note:** This tool is new and updated frequently. Limits and bugs listed here may already be fixed, so re-check the release notes and fidelity scores for the services you rely on.