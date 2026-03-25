environment     = "prod"
deployment_mode = "private_alb"
desired_count   = 1
container_image = "docker.io/<dockerhub-username>/nutritrack-api:arm-latest"

ecs_cluster_name          = "nutritrack-api-cluster"
container_name            = "arm-nutritrack-api-container"
ecs_task_family           = "arm-nutritrack-api-task"
ecs_service_name          = "arm-nutritrack-api-service"
ecs_arm_spot_enabled      = true
ecs_service_arm_spot_name = "arm-spot-nutritrack-api-service"
ecs_arm_spot_desired_count = 1
