from diagrams import Diagram, Cluster, Edge
from diagrams.aws.general import MobileClient, InternetAlt1
from diagrams.aws.network import APIGateway, Privatelink, ALB, NATGateway, InternetGateway, Endpoint
from diagrams.aws.compute import Fargate, ECR
from diagrams.aws.storage import S3
from diagrams.aws.security import SecretsManager
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock
import os

os.environ["PATH"] += os.pathsep + r"C:\Program Files\Graphviz\bin"

with Diagram("NutriTrack Secure AWS Architecture", show=False, direction="LR", outformat="png", filename="diagram_aws_secure"):
    client_user = MobileClient("Client\n(Web/Mobile/Postman)")

    with Cluster("AWS Cloud"):
        api_gw = APIGateway("API Gateway\n(Rate Limit, WAF)")
        
        with Cluster("VPC Network"):
            vpc_link = Privatelink("VPC Link")
            
            with Cluster("Public Subnet"):
                alb = ALB("Application Load Balancer")
                nat = NATGateway("NAT Gateway")
                igw = InternetGateway("Internet Gateway")
                
            with Cluster("Private Subnet"):
                fargate = Fargate("ECS Fargate Task\n(NutriTrack API)")
                
            with Cluster("VPC Endpoints"):
                s3_vpce = Endpoint("S3 Gateway Endpoint")
                interface_vpce = Endpoint("Interface Endpoints")
                
        with Cluster("AWS Internal Services"):
            bedrock = Bedrock("Amazon Bedrock\n(Model Qwen3-VL)")
            s3 = S3("Amazon S3\n(Result Cache)")
            ecr = ECR("Amazon ECR")
            secrets = SecretsManager("Secrets Manager")
            cw = Cloudwatch("CloudWatch Logs")
            
    with Cluster("External APIs (third_apis)"):
        usda = InternetAlt1("USDA API")
        off = InternetAlt1("OpenFoodFacts")
        avocavo = InternetAlt1("AvocavoNutrition")

    # Flow
    client_user >> Edge(label="Call API /analyze") >> api_gw
    api_gw >> Edge(label="Forward Internal") >> vpc_link
    vpc_link >> alb
    alb >> Edge(label="Load Balancing") >> fargate
    
    # Egress Flow
    fargate >> Edge(label="Outbound Request") >> nat
    nat >> igw
    igw >> usda
    igw >> off
    igw >> avocavo
    
    # Internal Services Flow
    fargate >> s3_vpce
    s3_vpce >> s3
    
    fargate >> interface_vpce
    interface_vpce >> bedrock
    interface_vpce >> ecr
    interface_vpce >> secrets
    interface_vpce >> cw
