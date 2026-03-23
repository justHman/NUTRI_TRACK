# Terraform Starter - NutriTrack ECS

This folder provisions AWS infrastructure for NutriTrack in two modes:

- `public`: ECS task in public subnet with public IP and SG inbound `8000`.
- `private_alb`: ECS task in private subnet behind a public ALB.

## Prerequisites

- Terraform >= 1.6
- AWS credentials configured
- Docker image already pushed to Docker Hub

## Remote state backend

Create backend resources once (S3 bucket + DynamoDB table), then:

```bash
cd infra/terraform
terraform init -backend-config=backend.hcl
```

Use `backend.hcl.example` as template.

## Plan / Apply

```bash
terraform fmt -recursive
terraform validate
terraform plan -var-file=environments/dev.tfvars -var="usda_api_key=YOUR_KEY" -var="avocavo_api_key=YOUR_KEY"
terraform apply -var-file=environments/dev.tfvars -var="usda_api_key=YOUR_KEY" -var="avocavo_api_key=YOUR_KEY"
```

## GitHub Actions Workflow

- `terraform-plan.yml` runs on pull requests and performs `fmt`, `validate`, and `plan` for both `dev` and `prod` with backend disabled.
- `terraform-apply.yml` is manual (`workflow_dispatch`) and applies to the selected environment using remote state in S3 + DynamoDB.

Required repository secrets for apply:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `TF_STATE_BUCKET`
- `TF_STATE_LOCK_TABLE`
- `USDA_API_KEY`
- `AVOCAVO_API_KEY` (can be empty)

## Important variables

- `deployment_mode`: `public` or `private_alb`
- `container_image`: Docker image URI used by ECS task definition
- `usda_api_key`: stored in Secrets Manager and injected into ECS task

## Outputs

- ECS cluster/service names
- S3 cache bucket
- ALB DNS (if `private_alb`)
