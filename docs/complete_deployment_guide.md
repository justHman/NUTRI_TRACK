# Hướng Dẫn Deploy NutriTrack API Lên AWS ECS — Toàn Tập

Tài liệu này gộp toàn bộ quy trình setup từ đầu đến cuối: từ tạo bộ nhớ đệm S3, cất giữ API Key an toàn, phân quyền IAM, dựng hạ tầng mạng, build image, deploy theo 2 cách Fargate (x86 Standard và ARM + Spot), chọn kiểu bảo mật mạng, xem log CloudWatch, cập nhật code mới, đến cách tắt server không tốn tiền.

---

## 📋 Mục lục

1. [Tổng quan kiến trúc hệ thống](#1-tổng-quan-kiến-trúc-hệ-thống)
2. [Bước 1 — Tạo S3 Bucket (Bộ nhớ đệm Cache)](#2-bước-1--tạo-s3-bucket-bộ-nhớ-đệm-cache)
3. [Bước 2 — Cất API Key vào Secrets Manager](#3-bước-2--cất-api-key-vào-secrets-manager)
4. [Bước 3 — Cấu hình IAM Roles](#4-bước-3--cấu-hình-iam-roles)
5. [Bước 4 — Dựng hạ tầng mạng VPC](#5-bước-4--dựng-hạ-tầng-mạng-vpc)
6. [Bước 5 — Build & Push Docker Image](#6-bước-5--build--push-docker-image)
7. [Bước 6 — Deploy: Cách A — Standard Fargate (x86)](#7-bước-6--deploy-cách-a--standard-fargate-x86)
8. [Bước 7 — Deploy: Cách B — Fargate ARM + Spot (Tiết kiệm 70%)](#8-bước-7--deploy-cách-b--fargate-arm--spot-tiết-kiệm-70)
9. [Bước 8 — Map Secrets Manager vào Task Definition](#9-bước-8--map-secrets-manager-vào-task-definition)
10. [Bước 9 — Bảo mật mạng (2 Giải pháp)](#10-bước-9--bảo-mật-mạng-2-giải-pháp)
11. [Bước 10 — Xem Logs & CloudWatch](#11-bước-10--xem-logs--cloudwatch)
12. [Bước 11 — Cập nhật Docker Image (Khi sửa code)](#12-bước-11--cập-nhật-docker-image-khi-sửa-code)
13. [Bước 12 — Tắt Server Để Không Tốn Tiền](#13-bước-12--tắt-server-để-không-tốn-tiền)
14. [Phụ lục — Bảng tổng hợp biến môi trường](#14-phụ-lục--bảng-tổng-hợp-biến-môi-trường)

---

## 1. Tổng quan kiến trúc hệ thống

Trước khi bắt đầu, hãy nắm rõ bức tranh toàn cảnh để hiểu tại sao mỗi bước lại cần thiết.

```
┌──────────────────────────────────────────────────────────────────┐
│                        AWS Cloud (us-east-1)                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   VPC: nutritrack-vpc                       │ │
│  │                                                             │ │
│  │  ┌────────────────────┐    ┌────────────────────────────┐  │ │
│  │  │   Public Subnet    │    │     Private Subnet (GP2)   │  │ │
│  │  │                    │    │                            │  │ │
│  │  │  ┌─────────────┐   │    │  ┌──────────────────────┐  │  │ │
│  │  │  │ Fargate Task│   │    │  │   Fargate Task       │  │  │ │
│  │  │  │ (GP1: Rẻ)   │   │    │  │   (GP2: Chuyên nghiệp│  │  │ │
│  │  │  └─────────────┘   │    │  └──────────────────────┘  │  │ │
│  │  └────────────────────┘    └─────────────┬──────────────┘  │ │
│  │                                          │ (chỉ qua ALB)   │ │
│  │       ┌──────────────────────────────────▼──────────────┐  │ │
│  │       │         Application Load Balancer (ALB)         │  │ │
│  │       └──────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │  S3 Bucket   │  │  Secrets Manager │  │   AWS Bedrock     │  │
│  │ (USDA Cache) │  │  (API Keys)      │  │  (QWEN3-VL AI)    │  │
│  └──────────────┘  └──────────────────┘  └───────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                  Internet / Client Request
```

### Các thành phần chính

| Thành phần | Vai trò |
| :--- | :--- |
| **ECS Fargate** | Chạy container Docker (FastAPI + Uvicorn) không cần quản lý server |
| **S3 Bucket** | Lưu cache kết quả tìm kiếm USDA để tiết kiệm lượt gọi API |
| **Secrets Manager** | Cất giữ API Key bên thứ ba (`USDA_API_KEY`) an toàn, mã hoá |
| **IAM Roles** | Phân quyền: `ecsTaskExecutionRole` (khởi động hệ thống) vs `ecsTaskRole` (runtime code) |
| **VPC + Subnet** | Mạng nội bộ riêng — kiểm soát luồng traffic vào/ra |
| **Security Group** | "Tường lửa" cấp port — chỉ mở cổng cần thiết |
| **ALB** | *(Giải pháp 2)* Load Balancer — người tiếp tân duy nhất, che giấu IP thật của container |
| **CloudWatch** | Thu thập và lưu trữ toàn bộ log từ container |

---

## 2. Bước 1 — Tạo S3 Bucket (Bộ nhớ đệm Cache)

Khi deploy lên ECS, container bị huỷ/tạo liên tục nên không thể dùng ổ đĩa local để cache. S3 đóng vai trò kho lưu trữ cache vĩnh viễn, giúp tiết kiệm đáng kể số lượt gọi USDA API.

### 2.1 Tạo Bucket trên AWS Console

1. Đăng nhập AWS Console, tìm kiếm **S3** → Click **S3 (Scalable Storage in the Cloud)**.
2. Nhấn nút cam **Create bucket**.
3. **Cấu hình Bucket**:
   - **Bucket name**: Đặt tên độc nhất toàn cầu. Gợi ý: `nutritrack-cache-[tên-bạn]-2026`.
   - **AWS Region**: Chọn cùng khu vực với Bedrock (thường là `us-east-1`). Đúng region = tốc độ rất nhanh + không phát sinh phí data transfer.
   - **Object Ownership**: Giữ `ACLs disabled (recommended)`.
   - **Block Public Access**: Giữ nguyên **Block all public access** — Không được tắt vì đây là file cache nội bộ. Code Python vẫn đọc/ghi được nhờ `ecsTaskRole` ở Bước 3.
   - **Bucket Versioning**: Để `Disable` — không cần lưu lịch sử sửa đổi file cache.
4. Cuộn xuống cuối, nhấn **Create bucket**.

### 2.2 Khai báo vào file `.env` (Chạy Local)

Mở file `app/config/.env`, thêm dòng sau:

```env
# Tên S3 Bucket lưu cache USDA
AWS_S3_CACHE_BUCKET=nutritrack-cache-[tên-bạn]-2026
```

> **Lưu ý:** Ở máy local, file `.env` kết hợp với credentials từ `aws configure` là đủ để `boto3` tương tác với S3. Trên ECS, giá trị này sẽ được khai báo lại qua Environment Variables trong Task Definition (xem Bước 6/7).

---

## 3. Bước 2 — Cất API Key vào Secrets Manager

Thay vì nhét `USDA_API_KEY` dạng plaintext vào Task Definition (ai có quyền xem console cũng thấy), ta dùng AWS Secrets Manager để mã hoá và lưu an toàn. Đây là tiêu chuẩn bảo mật chuyên nghiệp.

### 3.1 Tạo Secret (Key-value pairs)

1. Truy cập **Secrets Manager** → Nhấn **Store a new secret**.
2. **Secret type**: Chọn **Other type of secret**.
3. **Key/value pairs**: Điền các API Key bên thứ ba (không điền AWS Access Key vào đây — phần đó để IAM Role xử lý):
   - Key: `USDA_API_KEY` | Value: `<token USDA của bạn>`
   - *(Nhấn **Add row** nếu có thêm key khác)*
4. **Encryption key**: Giữ mặc định `aws/secretsmanager` — AWS quản lý giùm, hoàn toàn **miễn phí**. Không cần tạo Customer managed key (tốn $1/tháng/key).
5. Nhấn **Next**.

### 3.2 Đặt tên cho Secret

1. **Secret name**: `nutritrack/prod/api-keys`
2. **Description** *(tuỳ chọn)*: `API Keys cho NutriTrack chạy trên ECS`
3. Nhấn **Next** → Bỏ qua phần Auto-rotation → Nhấn **Next** → Kiểm tra lại → Nhấn **Store**.

### 3.3 Copy Secret ARN

Sau khi lưu, nhấn vào tên secret `nutritrack/prod/api-keys`. Sao chép **Secret ARN** — chuỗi trông như sau:

```
arn:aws:secretsmanager:us-east-1:123456789012:secret:nutritrack/prod/api-keys-xxxxxx
```

> Bạn sẽ cần ARN này ở **Bước 3** (cấp quyền cho Role) và **Bước 8** (map vào Task Definition).

---

## 4. Bước 3 — Cấu hình IAM Roles

Đây là bước nhiều người dễ nhầm nhất. ECS dùng **2 Role khác nhau** cho 2 mục đích hoàn toàn tách biệt.

### 4.1 Hiểu sự khác nhau giữa 2 Role

| Role | Ai dùng | Dùng để làm gì |
| :--- | :--- | :--- |
| **`ecsTaskExecutionRole`** | Hệ thống AWS ECS (nền) | Kéo Docker Image từ registry, ghi log ra CloudWatch, mở khoá Secrets Manager để lấy biến môi trường trước khi bật container |
| **`ecsTaskRole`** | Code Python đang chạy trong container | Gọi AWS Bedrock (AI), đọc/ghi S3 Cache — bất cứ thứ gì code `boto3` cần |

> **Quy tắc vàng:** `ecsTaskExecutionRole` = "chuẩn bị bàn ăn". `ecsTaskRole` = "ăn bữa cơm". Thiếu/sai một trong hai đều gây lỗi `AccessDeniedException`.

---

### 4.2 Cấu hình `ecsTaskExecutionRole` — Cấp quyền mở Secrets Manager

Role này thường đã tồn tại sẵn với policy `AmazonECSTaskExecutionRolePolicy`. Ta chỉ cần **thêm quyền đọc Secret** vừa tạo.

1. Truy cập **IAM** → **Roles** → Tìm kiếm `ecsTaskExecutionRole`.
2. Nhấn vào tên Role → **Add permissions** → **Create inline policy**.
3. Chuyển sang tab **JSON**, dán nội dung sau (thay ARN bằng ARN bạn copy ở Bước 2):

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": [
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:nutritrack/prod/api-keys-xxxxxx"
            ]
        }
    ]
}
```

4. Nhấn **Next** → Đặt tên policy là `NutriTrackSecretsPolicy` → Nhấn **Create policy**.

---

### 4.3 Tạo `ecsTaskRole` — Quyền Runtime cho Code Python

Đây là role mới cần tạo từ đầu.

1. Truy cập **IAM** → **Roles** → Nhấn **Create role**.
2. **Trusted entity type**: Chọn **AWS service**.
3. **Use case**: Tìm và chọn **Elastic Container Service Task**.
4. Nhấn **Next**.
5. **Gắn permissions** cho role (chọn 1 trong 2 cách):

   **Cách nhanh (cho Dev/Test):** Tìm và attach 2 policy có sẵn:
   - `AmazonBedrockFullAccess`
   - `AmazonS3FullAccess`

   **Cách bảo mật cao (cho Production):** Bỏ qua bước attach policy trên, sau khi tạo role xong thì **Create inline policy** với nội dung sau (thay tên bucket và region/account-id):

   ```json
   {
       "Version": "2012-10-17",
       "Statement": [
           {
               "Effect": "Allow",
               "Action": [
                   "bedrock:InvokeModel",
                   "bedrock:InvokeModelWithResponseStream"
               ],
               "Resource": "*"
           },
           {
               "Effect": "Allow",
               "Action": [
                   "s3:GetObject",
                   "s3:PutObject",
                   "s3:DeleteObject",
                   "s3:ListBucket"
               ],
               "Resource": [
                   "arn:aws:s3:::nutritrack-cache-[tên-bạn]-2026",
                   "arn:aws:s3:::nutritrack-cache-[tên-bạn]-2026/*"
               ]
           }
       ]
   }
   ```

6. Nhấn **Next** → **Role name**: `ecsTaskRole` → Nhấn **Create role**.

---

## 5. Bước 4 — Dựng hạ tầng mạng VPC

Container cần mạng để nhận request từ người dùng và gọi ra ngoài (Bedrock, S3). Phần này cài đặt VPC riêng — không dùng VPC mặc định của AWS để tránh xung đột.

### 5.1 Tạo VPC

1. Truy cập **VPC Console** → **Your VPCs** → **Create VPC**.
2. Chọn **VPC only**.
3. **Name tag**: `nutritrack-vpc`
4. **IPv4 CIDR**: `10.0.0.0/16`
5. Nhấn **Create VPC**.

### 5.2 Tạo Internet Gateway — "Cổng ra thế giới"

1. VPC Console → **Internet gateways** → **Create internet gateway**.
2. **Name tag**: `nutritrack-igw`
3. Sau khi tạo xong: **Actions** → **Attach to VPC** → Chọn `nutritrack-vpc` → **Attach**.

### 5.3 Tạo Public Subnet

1. VPC Console → **Subnets** → **Create subnet**.
2. **VPC ID**: Chọn `nutritrack-vpc`.
3. **Subnet name**: `nutritrack-public-subnet`
4. **Availability Zone**: Chọn bất kỳ (VD: `us-east-1a`).
5. **IPv4 CIDR block**: `10.0.1.0/24`
6. Nhấn **Create subnet**.
7. **Quan trọng:** Sau khi tạo, tick chọn subnet → **Actions** → **Edit subnet settings** → Tick **Enable auto-assign public IPv4 address** → **Save**.

### 5.4 Cấu hình Route Table — Kết nối Subnet ra Internet

1. VPC Console → **Route tables** → Chọn bảng định tuyến của `nutritrack-vpc`.
2. Đổi tên thành `nutritrack-public-rt`.
3. Tab **Routes** → **Edit routes** → **Add route**:
   - **Destination**: `0.0.0.0/0`
   - **Target**: Chọn **Internet Gateway** → Chọn `nutritrack-igw`
4. Nhấn **Save changes**.
5. Tab **Subnet associations** → **Edit subnet associations** → Tick `nutritrack-public-subnet` → **Save**.

---

## 6. Bước 5 — Build & Push Docker Image

Tuỳ theo cách deploy, bạn cần build image theo đúng kiến trúc chip. Làm **một trong hai** cách dưới đây (hoặc cả hai nếu muốn so sánh).

Mở Terminal tại thư mục `app` (nơi có `Dockerfile`):

```bash
cd d:/Project/Code/nutritrack-documentation/app
```

---

### 6.A — Image cho Fargate Standard (x86_64)

**Bước 1:** Build image

```bash
docker build -t <your-dockerhub-username>/nutritrack-api:latest .
```

**Bước 2:** Đăng nhập Docker Hub (nếu chưa)

```bash
docker login
```

**Bước 3:** Push lên Docker Hub

```bash
docker push <your-dockerhub-username>/nutritrack-api:latest
```

---

### 6.B — Image cho Fargate ARM64 (Graviton Spot — Tiết kiệm 70%)

Vì máy tính Intel/AMD không thể build trực tiếp image ARM, cần dùng `docker buildx` để cross-compile.

**Bước 1:** Khởi tạo buildx *(chỉ cần làm 1 lần duy nhất)*

```bash
docker buildx create --use
```

**Bước 2:** Build và Push trực tiếp image ARM64 lên Docker Hub

```bash
docker buildx build --platform linux/arm64 \
  -t <your-dockerhub-username>/nutritrack-api:arm \
  --push .
```

> **Tại sao ARM?** Chip AWS Graviton xử lý các tác vụ Python (FastAPI, Pillow) nhanh hơn, mát hơn và rẻ hơn đến 20% so với x86 cùng cấu hình. Kết hợp Fargate Spot giảm thêm 70% nữa.

---

## 7. Bước 6 — Deploy: Cách A — Standard Fargate (x86)

Cách triển khai cơ bản nhất. Phù hợp khi cần môi trường ổn định, không bị AWS thu hồi đột ngột.

### 7.1 Tạo ECS Cluster

1. Truy cập **ECS** → **Create cluster**.
2. **Cluster name**: `nutritrack-cluster`
3. **Infrastructure**: Chọn **AWS Fargate (serverless)**
4. Nhấn **Create**.

### 7.2 Tạo Task Definition

1. **Task definitions** → **Create new task definition** → **Create new task definition with console**.
2. **Task definition family name**: `nutritrack-api-task`
3. **Infrastructure requirements**:
   - **Launch type**: `AWS Fargate`
   - **OS/Architecture**: `Linux/X86_64`
   - **CPU**: `1 vCPU`
   - **Memory**: `3 GB`
   - **Task execution role**: Chọn `ecsTaskExecutionRole`
   - **Task role**: Chọn `ecsTaskRole` *(vừa tạo ở Bước 3)*
4. **Container - 1**:
   - **Name**: `api-container`
   - **Image URI**: `<your-dockerhub-username>/nutritrack-api:latest`
   - **Port mappings**: Container port `8000`, Protocol `TCP`
5. **Environment variables**: Thêm các biến sau *(phần Secrets sẽ cấu hình ở Bước 8)*:
   - Key: `AWS_S3_CACHE_BUCKET` | Type: `Value` | Value: `nutritrack-cache-[tên-bạn]-2026`
   - Key: `AWS_DEFAULT_REGION` | Type: `Value` | Value: `us-east-1`
6. Cuộn xuống nhấn **Create**.

### 7.3 Chạy ECS Service

1. Vào Cluster `nutritrack-cluster` → tab **Services** → **Create**.
2. **Compute configuration**: Chọn **Launch type** → **Fargate**.
3. **Deployment configuration**:
   - **Application type**: `Service`
   - **Task definition**: `nutritrack-api-task` (Revision mới nhất)
   - **Service name**: `nutritrack-api-service`
   - **Desired tasks**: `1`
4. **Networking**:
   - **VPC**: `nutritrack-vpc`
   - **Subnets**: `nutritrack-public-subnet`
   - **Auto-assign public IP**: **BẬT** *(tắt là container mất internet, không gọi được Bedrock)*
   - **Security group**: **Create new**
     - **Name**: `nutritrack-api-sg`
     - **Inbound rules**: Xóa rule cũ, thêm rule mới:
       - Type: `Custom TCP` | Port: `8000` | Source: `0.0.0.0/0`
   - **Outbound rules**: Giữ nguyên `All traffic` → `0.0.0.0/0`
5. Nhấn **Create**.

### 7.4 Lấy Public IP và Test

1. Vào Service → tab **Tasks** → Đợi status chuyển sang `RUNNING`.
2. Click vào Task ID đang chạy → Tab **Configuration** → Copy **Public IP**.
3. Truy cập: `http://<Public IP>:8000/docs` để test Swagger UI 🎉

---

## 8. Bước 7 — Deploy: Cách B — Fargate ARM + Spot (Tiết kiệm 70%)

Cách triển khai tối ưu chi phí. Dùng chip ARM (Graviton) + hạ tầng Spot (giá thanh lý). Phù hợp cho Dev, Test và Demo đồ án.

### 8.1 Tạo Task Definition ARM64

1. **Task definitions** → **Create new task definition** (tạo mới, không dùng bản x86 cũ).
2. **Task definition family name**: `nutritrack-api-task-arm`
3. **Infrastructure requirements**:
   - **Launch type**: `AWS Fargate`
   - **OS/Architecture**: **`Linux/ARM64`** ← Bắt buộc phải chọn đúng
   - **CPU**: `1 vCPU`
   - **Memory**: `2 GB` *(ARM hiệu quả hơn, 2GB là đủ)*
   - **Task execution role**: `ecsTaskExecutionRole`
   - **Task role**: `ecsTaskRole`
4. **Container**:
   - **Image URI**: `<your-dockerhub-username>/nutritrack-api:arm` ← Dùng tag `:arm` vừa build
   - **Port**: `8000`
5. Thêm **Environment variables** tương tự Bước 6.2.
6. Nhấn **Create**.

### 8.2 Chạy Service với Capacity Provider Fargate Spot

1. Vào Cluster `nutritrack-cluster` → tab **Services** → **Create**.
2. **Compute configuration (Environment)**:
   - Chọn **Capacity provider strategy** *(không chọn Launch type)*
   - Nhấn **Add capacity provider** → Chọn **FARGATE_SPOT**
   - **Weight**: `1` *(100% task chạy trên Spot)*
3. **Deployment configuration**:
   - **Task definition**: `nutritrack-api-task-arm` (Revision mới nhất)
   - **Service name**: `nutritrack-api-spot`
   - **Desired tasks**: `1`
4. **Networking**: Cấu hình VPC, Subnet, Security Group như Bước 6.3.
5. Nhấn **Create**.

### 8.3 So sánh chi phí

| Loại Fargate | vCPU/Giờ | RAM/Giờ | Ước tính 1 tháng chạy 24/7 |
| :--- | :--- | :--- | :--- |
| **Standard x86** | $0.04048 | $0.004445 | ~$34 USD |
| **ARM Graviton** | $0.03238 | $0.003556 | ~$27 USD |
| **ARM + Spot** | **$0.01295** | **$0.001422** | **~$10 USD** ✅ |

> **Lưu ý về Fargate Spot:** AWS có quyền thu hồi Task Spot khi thiếu capacity, nhưng ECS sẽ tự động khởi động task thay thế ngay lập tức. Với dự án cá nhân/đồ án — hoàn toàn chấp nhận được.

---

## 9. Bước 8 — Map Secrets Manager vào Task Definition

Sau khi tạo Task Definition (Bước 6 hoặc 7), quay lại **chỉnh sửa** để kết nối `USDA_API_KEY` từ Secrets Manager thay vì điền plaintext.

### 9.1 Chỉnh sửa Task Definition

1. **ECS** → **Task definitions** → Chọn task của bạn → **Create new revision**.
2. Phần **Container** → Mục **Environment variables**.
3. Nhấn **Add environment variable** → Khai báo như sau:
   - **Key**: `USDA_API_KEY`
   - **Type**: Chọn **`ValueFrom`** *(không phải `Value`)*
   - **Value**: Điền **đầy đủ chuỗi ARN + tên key** theo cú pháp:

```
[Secret_ARN]:[Tên_Key_Bên_Trong_Secret]::
```

**Ví dụ cụ thể:**

```
arn:aws:secretsmanager:us-east-1:123456789012:secret:nutritrack/prod/api-keys-xxxxxx:USDA_API_KEY::
```

> ⚠️ **Chú ý cú pháp:** Phần cuối là `::` (2 dấu hai chấm kép). Thiếu hoặc sai sẽ khiến container không khởi động được với lỗi `ResourceInitializationError`.

4. Nhấn **Create** (tạo revision mới).
5. Quay lại Service → **Update** → Chọn revision mới nhất → **Force new deployment** → **Update**.

### 9.2 Luồng hoạt động khi Container khởi động

```
ECS Agent (dùng ecsTaskExecutionRole)
  → Gõ cửa Secrets Manager bằng thẻ IAM
  → Lấy chuỗi USDA_API_KEY
  → Nhét vào env của container: export USDA_API_KEY="..."
  → Bật Uvicorn + FastAPI
  → Code: os.getenv("USDA_API_KEY") ← đọc được ngay ✅
```

---

## 10. Bước 9 — Bảo mật mạng (2 Giải pháp)

Chọn **1 trong 2** giải pháp tùy mục tiêu của bạn.

---

### Giải pháp 1: Security Group Chặt chẽ (Tiết kiệm tối đa — Miễn phí)

**Mô hình:** Container chạy trong Public Subnet, bảo vệ bằng "tường lửa" Security Group — chỉ mở đúng cổng API.

#### Ưu & Nhược điểm

| | |
| :--- | :--- |
| ✅ **Ưu điểm** | Miễn phí, cài đặt nhanh (~15 phút), đủ an toàn cho đồ án |
| ❌ **Nhược điểm** | Container có IP Public lộ ra ngoài. Sai cấu hình SG = bị tấn công |

#### Cấu hình Security Group `nutritrack-api-sg`

**Inbound Rules (Quyền đi vào):**

| Type | Protocol | Port | Source | Mục đích |
| :--- | :--- | :--- | :--- | :--- |
| Custom TCP | TCP | 8000 | `0.0.0.0/0` | Cho phép gọi API từ mọi nơi |

> ❌ **TUYỆT ĐỐI KHÔNG** mở thêm port 22 (SSH), 3306 (MySQL), 5432 (PostgreSQL) hay bất kỳ port nào khác.

**Outbound Rules (Quyền đi ra):**

| Type | Destination | Lý do |
| :--- | :--- | :--- |
| All traffic | `0.0.0.0/0` | Code Python cần gọi Bedrock/S3 qua Internet. Security Group là **Stateful** — chỉ cho phản hồi về đúng phiên kết nối mà code đã khởi tạo, nên hoàn toàn an toàn. |

---

### Giải pháp 2: ALB + Private Subnet (Chuyên nghiệp — "Show off" Kỹ năng)

**Mô hình:** Container ẩn trong Private Subnet (không có IP Public). Chỉ ALB (Load Balancer) đứng ngoài tiếp nhận request rồi chuyển vào.

#### Ưu & Nhược điểm

| | |
| :--- | :--- |
| ✅ **Ưu điểm** | Bảo mật tuyệt đối — hacker không thể tấn công trực tiếp container. URL chuyên nghiệp dạng `nutritrack-lb-123.us-east-1.elb.amazonaws.com` thay vì lộ IP số |
| ❌ **Nhược điểm** | Tốn thêm ~$15-20/tháng phí ALB. Cài đặt phức tạp hơn (~60 phút) |

#### Sơ đồ kiến trúc

```
👦 Client
    │  HTTP/HTTPS
    ▼
⚖️  ALB (Public Subnet) ← Security Group: Cho phép port 80/443 từ Internet
    │  Port 8000
    ▼
🐋  Fargate Task (Private Subnet) ← Security Group: CHỈ cho port 8000 từ SG của ALB
    │
    ├──► 🧠 AWS Bedrock (qua VPC Endpoint)
    └──► 🪣 AWS S3 Cache (qua VPC Endpoint)
```

#### Bước A: Tạo Private Subnet

1. VPC Console → **Subnets** → **Create subnet**.
2. VPC: `nutritrack-vpc`
3. **Subnet name**: `nutritrack-private-subnet`
4. **Availability Zone**: Chọn `us-east-1b` (khác AZ với public subnet để tăng tính sẵn sàng).
5. **IPv4 CIDR block**: `10.0.2.0/24`
6. Nhấn **Create subnet**.
7. **QUAN TRỌNG:** **Không bật** "Auto-assign public IP". Route Table của subnet này **không được** trỏ đến Internet Gateway.

#### Bước B: Tạo Application Load Balancer (ALB)

1. **EC2 Console** → **Load Balancers** → **Create Load Balancer** → Chọn **Application Load Balancer**.
2. **Load balancer name**: `nutritrack-lb`
3. **Scheme**: `Internet-facing`
4. **Network mapping**: Chọn `nutritrack-vpc` và các **Public Subnets**.
5. **Security Group cho ALB**: Tạo mới `nutritrack-alb-sg`:
   - Inbound: Port `80` từ `0.0.0.0/0`
   - *(Nếu có HTTPS, thêm port 443)*
6. **Listeners and routing**: Port `80` → Tạo **Target Group** mới:
   - **Target type**: `IP addresses`
   - **Protocol**: `HTTP`, Port `8000`
   - **Health check path**: `/health` hoặc `/` (tuỳ API)
7. Nhấn **Create load balancer**.

#### Bước C: Chuỗi Security Group (Security Group Chain)

Đây là phần thể hiện tư duy bảo mật thực sự:

**SG của ALB (`nutritrack-alb-sg`):**
- Inbound: Port `80` từ `0.0.0.0/0`

**SG của Fargate Task (`nutritrack-task-sg`):**
- Inbound: Port `8000` **CHỈ từ Source = `nutritrack-alb-sg`** *(không phải từ IP)*
  - *(Hacker biết IP nội bộ container cũng không thể gọi thẳng — bắt buộc phải qua ALB)*

#### Bước D: Giải quyết vấn đề gọi Bedrock từ Private Subnet (VPC Endpoints)

Private Subnet không có Internet, nhưng code Python cần gọi Bedrock và S3. Thay vì dùng NAT Gateway (tốn $32+/tháng), dùng **VPC Endpoints** (rẻ hơn nhiều):

1. **VPC Console** → **Endpoints** → **Create endpoint**.
2. Tạo lần lượt 2 endpoint:
   - **Service**: Tìm `com.amazonaws.us-east-1.bedrock-runtime` → Type: **Interface**
   - **Service**: Tìm `com.amazonaws.us-east-1.s3` → Type: **Gateway** *(Gateway endpoint S3 miễn phí!)*
3. **VPC**: `nutritrack-vpc`
4. **Subnets**: Chọn `nutritrack-private-subnet`
5. **Security Group** cho Interface Endpoint: Cho phép port `443` (HTTPS) từ `nutritrack-task-sg`.

#### Bước E: Map Fargate Task vào Private Subnet

Khi tạo/cập nhật ECS Service:
- **Subnets**: Thay bằng `nutritrack-private-subnet`
- **Auto-assign public IP**: **TẮT** *(container ẩn hoàn toàn)*
- **Load balancing**: Chọn ALB `nutritrack-lb`, Target Group đã tạo ở Bước B

---

#### So sánh 2 Giải pháp

| Tiêu chí | Giải pháp 1 (Public Subnet + SG) | Giải pháp 2 (ALB + Private Subnet) |
| :--- | :--- | :--- |
| **Bảo mật** | Khá (dựa trên port) | **Tuyệt đối** (dựa trên kiến trúc mạng) |
| **Độ khó cài đặt** | Dễ (~15 phút) | Trung bình (~60 phút) |
| **Chi phí thêm** | **$0** | ~$15–20/tháng (phí ALB) |
| **Dạng URL** | `http://3.86.xx.xx:8000` | `http://nutritrack-lb-xxx.elb.amazonaws.com` |
| **Khuyên dùng** | Dev, Test nhanh | Đồ án cuối kỳ, Demo hệ thống lớn |

> 💡 **Mẹo đồ án:** Nếu chọn Giải pháp 2, hãy chụp ảnh sơ đồ mạng ở trên đưa vào báo cáo — giáo viên sẽ đánh giá rất cao khả năng thiết kế hạ tầng Cloud bài bản!

---

## 11. Bước 10 — Xem Logs & CloudWatch

### 11.1 Ai ghi log? Ai xem log?

Nhiều người nhầm lẫn về cơ chế này:

- **Người GHI log:** Hệ thống ECS Agent, dùng quyền của `ecsTaskExecutionRole` để đẩy (push) log từ container lên CloudWatch. Không có quyền này = log rơi vào khoảng không, mất hút.
- **Người XEM log:** Tài khoản AWS của **bạn** — truy cập bằng trình duyệt, không cần Role đặc biệt.

---

### 11.2 Cách 1: Xem nhanh ngay trong ECS Console (Tiện nhất)

Dùng khi cần kiểm tra nhanh request vừa gửi hoặc lỗi vừa xảy ra.

1. **ECS** → Chọn Cluster → tab **Services** → Chọn `nutritrack-api-service`.
2. Nhấn vào tab **Logs** (hàng tab ngang phía trên).
3. Toàn bộ output Terminal của FastAPI/Uvicorn hiện ra theo thời gian thực — y hệt cửa sổ đen trên máy local.

---

### 11.3 Cách 2: Điều tra kỹ qua CloudWatch (Log lịch sử, hệ thống chết giữa đêm)

Dùng khi container đã bị restart hoặc crash, không còn xem được qua ECS nữa.

1. Truy cập **CloudWatch** → Cột trái: **Logs** → **Log groups**.
2. Tìm group tên `/ecs/nutritrack-api-task` → Click vào.
3. Tab **Log streams**: Chọn stream gần nhất (theo thời gian).
4. Dùng ô **Filter events** để tìm lỗi nhanh:
   - Gõ `ERROR` để lọc dòng lỗi
   - Gõ `Exception` để lọc exception
   - Gõ `Traceback` để lọc stack trace Python

---

## 12. Bước 11 — Cập nhật Docker Image (Khi sửa code)

Khi sửa code local (VD: `pipeline.py`, `ui.py`) và muốn đưa bản mới lên server.

### Bước 1: Build lại Image với code mới

```bash
cd d:/Project/Code/nutritrack-documentation/app

# Nếu đang dùng Fargate x86 (Cách A):
docker build -t <your-dockerhub-username>/nutritrack-api:latest .

# Nếu đang dùng Fargate ARM Spot (Cách B):
docker buildx build --platform linux/arm64 \
  -t <your-dockerhub-username>/nutritrack-api:arm \
  --push .
```

### Bước 2: Đăng nhập Docker (nếu cần)

```bash
docker login
```

### Bước 3: Push lên Docker Hub (chỉ cần cho x86)

```bash
# ARM đã được push ngay trong lệnh buildx ở trên.
# Chỉ cần chạy dòng này nếu build x86:
docker push <your-dockerhub-username>/nutritrack-api:latest
```

### Bước 4: Bắt ECS kéo image mới về

Dù Docker Hub đã có bản mới, container AWS vẫn đang giữ image cũ. Phải ép nó update:

1. **ECS** → Cluster → tab **Services** → Tick chọn Service → **Update**.
2. Tick vào **Force new deployment**.
3. Cuộn xuống cuối → **Update**.

ECS tự động kéo bản `:latest` (hoặc `:arm`) mới nhất và thay container cũ. Quá trình mất khoảng 1–2 phút.

---

## 13. Bước 12 — Tắt Server Để Không Tốn Tiền

AWS ECS Fargate tính tiền **theo giây** — quên tắt là tiền bay mỗi ngày. Sau khi test xong hoặc trước khi đi ngủ, hãy tắt ngay!

---

### Cách 1: Tạm dừng — Giữ nguyên cấu hình (Khuyên dùng)

Phù hợp khi muốn tắt tạm, hôm sau bật lại tiếp không cần thiết lập lại.

1. **ECS** → Cluster → tab **Services** → Tick chọn Service → **Update**.
2. Tìm ô **Desired tasks** (đang là `1`) → Sửa thành **`0`**.
3. Cuộn xuống cuối → **Update**.

Container ngay lập tức bị dừng, CPU/RAM trả lại cho Amazon, **tiền phí dừng hoàn toàn**.

Khi muốn bật lại: Làm y chang, đổi `0` thành `1` → Container khởi động lại sau ~2 phút.

---

### Cách 2: Xóa sạch hoàn toàn (Cleanup)

Dùng khi chấm điểm xong, muốn xóa toàn bộ không để lại gì.

1. **ECS** → Cluster → Select Service → **Delete**.
2. Sau khi xóa Service xong: **Delete cluster** (nút góc trên bên trái).
3. **Amazon ECR** → Repository `nutritrack-api` → **Delete** (tiết kiệm vài cent lưu trữ image).
4. **Secrets Manager** → Tên secret → **Delete Secret** (dọn sạch).
5. **S3** → Bucket → **Empty bucket** → **Delete bucket**.
6. **VPC Console** → Xóa (theo thứ tự): Internet Gateway → Subnet → Route Table → VPC.

---

## 14. Phụ lục — Bảng tổng hợp biến môi trường

Danh sách đầy đủ các biến cần khai báo trong ECS Task Definition:

| Tên biến | Type | Giá trị | Ghi chú |
| :--- | :--- | :--- | :--- |
| `AWS_S3_CACHE_BUCKET` | `Value` | `nutritrack-cache-[tên]-2026` | Tên S3 Bucket |
| `AWS_DEFAULT_REGION` | `Value` | `us-east-1` | Region chứa Bedrock và S3 |
| `USDA_API_KEY` | `ValueFrom` | `[Secret ARN]:USDA_API_KEY::` | Kéo từ Secrets Manager |

### Checklist tổng trước khi Deploy

- [ ] ✅ S3 Bucket đã tạo xong
- [ ] ✅ Secret `nutritrack/prod/api-keys` đã có `USDA_API_KEY`, đã copy ARN
- [ ] ✅ `ecsTaskExecutionRole` đã có policy `NutriTrackSecretsPolicy`
- [ ] ✅ `ecsTaskRole` đã có quyền Bedrock + S3
- [ ] ✅ VPC, Subnet, IGW, Route Table đã cấu hình đúng
- [ ] ✅ Docker Image đã build và push lên Docker Hub (đúng tag: `:latest` hoặc `:arm`)
- [ ] ✅ Task Definition đã chọn đúng `ecsTaskRole` + `ecsTaskExecutionRole`
- [ ] ✅ Container port `8000` mở trong Security Group
- [ ] ✅ `Desired tasks` = `1` để bật, = `0` sau khi test xong

---

*Tài liệu được tổng hợp từ: `aws_s3_deploy_guide.md`, `aws_secrets_manager_guide.md`, `ecs_deployment_guide.md`, `ecs_fargate_arm_spot_guide.md`, `ecs_secure_networking_guide.md`, `docker_update_and_cloudwatch_guide.md`.*
