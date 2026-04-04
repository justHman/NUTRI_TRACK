# NutriTrack Infrastructure via Terraform

This folder contains the Infrastructure-as-Code (IaC) files to provision NutriTrack on AWS via Terraform. The architecture is 100% private. ECS tasks run in Private Subnets, fetching cache from S3, pulling images from ECR, storing logs on CloudWatch, and connecting to AWS Bedrock — all securely via **AWS PrivateLink (VPC Endpoints)** without requiring a NAT Gateway!

## Prerequisites

1. **Terraform CLI**: Download and install Terraform (v1.5+).
2. **AWS CLI**: Installed and configured securely.

## 0. Bootstrap (Important Step for State Management)
Because we are using an `S3` backend to store the persistent Terraform state across environments (and CI/CD pipelines!), the specified bucket and Dynamodb table must literally be created first.
Go to AWS Console or CLI and execute this manually once before initializing terraform:

1. Create S3 Bucket `nutritrack-api-tfstate-bucket` (enable bucket versioning).
2. Create DynamoDB Table `nutritrack-api-tfstate-lock` with Partition Key `LockID` (String).

## 1. Local Initialization
Check that your AWS credentials are active.
```bash
cd infra/terraform
terraform init
terraform plan
```

## 2. GitHub Actions
We provided two CI/CD workflows:
- `.github/workflows/terraform-plan.yml` (Triggers on PR)
- `.github/workflows/terraform-apply.yml` (Triggers when merging to `main`)

Ensure `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` repository secrets are configured in Github.
