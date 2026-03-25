module "networking" {
  source = "./modules/networking"

  name_prefix         = local.name_prefix
  vpc_cidr            = var.vpc_cidr
  public_subnet_cidr  = var.public_subnet_cidr
  private_subnet_cidr = var.private_subnet_cidr
  create_private      = local.use_private_alb_mode
}

module "security" {
  source = "./modules/security"

  name_prefix       = local.name_prefix
  vpc_id            = module.networking.vpc_id
  container_port    = var.container_port
  enable_alb_chain  = local.use_private_alb_mode
}

module "storage" {
  source = "./modules/storage"

  name_prefix  = local.name_prefix
  bucket_name  = var.s3_bucket_name
}

module "secrets" {
  source = "./modules/secrets"

  secret_name      = var.secrets_name
  usda_api_key     = var.usda_api_key
  avocavo_api_key  = var.avocavo_api_key
}

module "iam" {
  source = "./modules/iam"

  name_prefix          = local.name_prefix
  secret_arn           = module.secrets.secret_arn
  cache_bucket_arn     = module.storage.bucket_arn
}

module "alb" {
  source = "./modules/alb"

  enabled            = local.use_private_alb_mode
  name_prefix        = local.name_prefix
  vpc_id             = module.networking.vpc_id
  subnet_ids         = module.networking.public_subnet_ids
  security_group_id  = module.security.alb_sg_id
  health_check_path  = "/health"
  container_port     = var.container_port
}

module "ecs" {
  source = "./modules/ecs"

  name_prefix          = local.name_prefix
  cluster_name         = coalesce(var.ecs_cluster_name, "${local.name_prefix}-cluster")
  service_name         = coalesce(var.ecs_service_name, "${local.name_prefix}-service")
  task_family          = coalesce(var.ecs_task_family, "${local.name_prefix}-task")
  secondary_enabled    = var.ecs_arm_spot_enabled
  secondary_service_name = coalesce(var.ecs_service_arm_spot_name, "${local.name_prefix}-spot-service")
  secondary_desired_count = var.ecs_arm_spot_desired_count
  region               = var.aws_region
  container_name       = var.container_name
  container_image      = var.container_image
  container_port       = var.container_port
  cpu                  = var.container_cpu
  memory               = var.container_memory
  desired_count        = var.desired_count

  subnet_ids           = local.use_private_alb_mode ? module.networking.private_subnet_ids : module.networking.public_subnet_ids
  security_group_ids   = local.use_private_alb_mode ? [module.security.private_task_sg_id] : [module.security.public_task_sg_id]
  assign_public_ip     = local.use_private_alb_mode ? false : true
  target_group_arn     = module.alb.target_group_arn

  execution_role_arn   = module.iam.execution_role_arn
  task_role_arn        = module.iam.task_role_arn

  cache_bucket_name    = module.storage.bucket_name
  secret_arn           = module.secrets.secret_arn
  log_retention_in_days = var.log_retention_in_days
}
