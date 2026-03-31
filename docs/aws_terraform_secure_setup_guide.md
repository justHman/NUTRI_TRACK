# Hướng Dẫn Setup Tự Động Kiến Trúc NutriTrack API bằng Terraform

Thay vì phải click thủ công hàng chục bước trên AWS Console, tài liệu này hướng dẫn cách cấu hình Hạ tầng dưới dạng Code (Infrastructure as Code - IaC) bằng **Terraform** dựa vào kiến trúc bảo mật tiên tiến nhất mà chúng ta vừa vạch ra ở `aws_secure_diagram.md`. 

Đây là phương pháp **"Best Practices"** dành riêng cho DevOps/Automation Engineers!

---

## 1. Cấu trúc Thư mục Đề xuất (`infra/terraform/`)
Để dễ quản lý, bạn không nên nhét tất cả code vào `main.tf`. Khuyến nghị chia nhỏ Terraform theo các Core-Modules:
- `vpc.tf`: Mạng lưới, Subnets, NAT Gateway, S3 VPC Endpoints.
- `security_groups.tf`: Tường lửa SG cho ALB và Fargate.
- `alb.tf`: Application Load Balancer ẩn (Internal).
- `ecs.tf`: Cluster, Task Definition, Service Fargate đóng kín.
- `api_gateway.tf`: HTTP API Gateway, VPC Link, Rate Limiting chống DDOS.
- `autoscaling.tf`: Cơ chế Dynamic Auto-Scaling (CPU Rate Tracking).

---

## 2. Các Block Tài Nguyên (Resources) Trọng Tâm

### 2.1. VPC & Networking (`vpc.tf`)
Sử dụng Community AWS Module sẽ tiết kiệm cho bạn hàng trăm dòng code khai báo Route Tables dài thòng.
```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "nutritrack-secure-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"] # Nhốt Fargate
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"] # Nhốt NAT & Public Elements

  # Bật NAT Gateway duy nhất cho Fargate Private đi gọi USDA / 3rd Party APIs.
  enable_nat_gateway = true
  single_nat_gateway = true # Dùng 1 NAT để tiết kiệm tiền (budget-friendly)

  # [QUAN TRỌNG] S3 VPC Endpoint hoàn toàn miễn phí, Caching nội bộ êm mượt.
  enable_s3_endpoint = true
}
```

### 2.2. Tường Lửa Mắt Xích (`security_groups.tf`)
```hcl
resource "aws_security_group" "alb_sg" {
  name   = "nutritrack-alb-sg"
  vpc_id = module.vpc.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Tạm mở để VPC Link vọt vào (VPC link internal ko lo lắm)
  }
}

resource "aws_security_group" "fargate_sg" {
  name   = "nutritrack-fargate-sg"
  vpc_id = module.vpc.vpc_id

  # Cửa cuốn Fargate chỉ mở nhận Request của đúng tên ALB này thọc xuống.
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"] # Bắn Outbound ra NAT để lấy Data Third-parties
  }
}
```

### 2.3. Cân Bằng Tải Internal `alb.tf`
```hcl
module "alb" {
  source  = "terraform-aws-modules/alb/aws"
  version = "~> 9.0"

  name    = "nutritrack-internal-alb"
  vpc_id  = module.vpc.vpc_id
  subnets = module.vpc.private_subnets

  # BIẾN THÁI & TINH DIỆU LÀ CHỮ INTERNAL NÀY! ẨN KHỎI TRẦN THẾ TOÀN TẬP.
  internal        = true
  security_groups = [aws_security_group.alb_sg.id]

  listeners = {
    http = {
      port     = 80
      protocol = "HTTP"
      forward = { target_group_key = "fargate-tg" }
    }
  }

  target_groups = {
    fargate-tg = {
      name        = "nutritrack-fargate-tg"
      protocol    = "HTTP"
      port        = 8000
      target_type = "ip" # Target loại IP là BẮT BUỘC ĐỐI VỚI ECS FARGATE
      vpc_id      = module.vpc.vpc_id
    }
  }
}
```

### 2.4. Khóa Trái Cửa Fargate API (`ecs.tf`)
Không bật Public IP của AWS, để cho Task "mù Internet" hoàn toàn ngoài việc out-bound NAT.
```hcl
resource "aws_ecs_cluster" "main" {
  name = "nutritrack-secure-cluster"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "nutritrack-api-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_exec.arn
  task_role_arn            = aws_iam_role.ecs_task.arn # Cần gài policy Bedrock + S3 vô đây

  container_definitions = jsonencode([{
    name      = "nutritrack-app"
    image     = "XXX.dkr.ecr.region.amazonaws.com/nutri:latest"
    essential = true
    portMappings = [{ containerPort = 8000, hostPort = 8000 }]
  }])
}

resource "aws_ecs_service" "main" {
  name            = "nutritrack-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.fargate_sg.id]
    subnets          = module.vpc.private_subnets
    assign_public_ip = false # CHỐNG DDOs MỨC MẠNG BẰNG FALSE
  }

  load_balancer {
    target_group_arn = module.alb.target_groups["fargate-tg"].arn
    container_name   = "nutritrack-app"
    container_port   = 8000
  }
}
```

### 2.5. Tạo "Lá Chắn" API Gateway Cấp Mạng (`api_gateway.tf`)
Tạo HTTP API + VPC Link nối trượt dốc vào Private ALB, bóp cò Throttling.
```hcl
# Thiết lập đường link bưng request cắm thẳng vào mạng Private VPC.
resource "aws_apigatewayv2_vpc_link" "main" {
  name               = "nutritrack-vpc-link"
  security_group_ids = [aws_security_group.alb_sg.id]
  subnet_ids         = module.vpc.private_subnets
}

# HTTP API cực rẻ và siêu tốc
resource "aws_apigatewayv2_api" "main" {
  name          = "nutritrack-gateway"
  protocol_type = "HTTP"
}

# Cột chặt đùm đùm kéo request ném cho ALB qua VPC Link
resource "aws_apigatewayv2_integration" "alb" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "HTTP_PROXY"
  integration_uri    = module.alb.listeners["http"].arn
  integration_method = "ANY"
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.main.id
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.alb.id}"
}

# Đậy nắp Stage chặn Đê bằng Rate Limit
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50 # Sập hầm nếu gọi hơn 50 cái 1 giây (Cứu sập Sever)
  }
}
```

### 2.6. Ma Thuật Dynamic Scaling (`autoscaling.tf`)
Chỉ mất 2 Block Terraform biến Fargate thành "Cao Su".
```hcl
resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = 5
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.main.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "scale-by-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0 # Nếu CPU Fargate trung bình > 70% là Scale Mới
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
```

---
Dùng Terraform sẽ giúp kiến trúc khổng lồ và phức tạp trên được tạo ra chỉ bởi vài dòng Run Command:
```bash
terraform init
terraform plan
terraform apply -auto-approve
```
Và 8 phút rưỡi sau, AWS tự tạo cho bạn 1 Hệ thống Serverless xưng Danh Vương Miện! Mọi lúc bạn muốn hủy toàn bộ để không charge tiền ban đêm, bạn gõ `terraform destroy`! Rất dũng mãnh và an toàn!
