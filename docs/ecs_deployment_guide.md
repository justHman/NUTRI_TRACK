# Hướng dẫn Deploy NutriTrack lên AWS ECS

Tài liệu này hướng dẫn cách deploy backend API của dự án **NutriTrack** lên **AWS Elastic Container Service (ECS)** sử dụng AWS Fargate.

Bạn có thể lưu trữ Docker Image ở hai nơi: **Docker Hub** hoặc **Amazon ECR** (Elastic Container Registry).

---

## 🏗️ 1. Chuẩn Bị & Build Docker Image

Mở Terminal tại thư mục `app` của dự án (nơi có chứa file `Dockerfile`):

```bash
cd d:/Project/Code/nutritrack-documentation/app
```

> **Lưu ý quan trọng trước khi Build:**
> Đảm bảo file `.env` đã được cấu hình với các API Keys hợp lệ (nếu cần đưa vào image - mặc dù best practice là inject `.env` thông qua AWS ECS Task Definition).

### Xây dựng Image
Bạn cần build container tùy thuộc vào việc sẽ push nó đi đâu. 
Thay `<your-dockerhub-username>` hoặc `<aws-account-id>` bằng thông tin thực tế.

**Nếu dùng Docker Hub:**
```bash
docker build -t <your-dockerhub-username>/nutritrack-api:latest .
```

**Nếu dùng Amazon ECR:**
```bash
docker build -t nutritrack-api:latest .
```

---

## ⛴️ 2. Đẩy Image Lên Registry (Push Image)

Bạn có thể dùng Docker Hub (miễn phí, public/private) hoặc ECR (native của AWS).

### Cách 2.A: Sử Dụng Docker Hub
1. Đăng nhập Docker Hub (nếu chưa):
   ```bash
   docker login
   ```
2. Push image:
   ```bash
   docker push <your-dockerhub-username>/nutritrack-api:latest
   ```

### Cách 2.B: Sử Dụng Amazon ECR
1. Đăng nhập AWS CLI (Yêu cầu đã cài đặt và `aws configure`):
   ```bash
   # Lấy token đăng nhập và cung cấp cho Docker
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <aws-account-id>.dkr.ecr.us-east-1.amazonaws.com
   ```
2. Tạo Repository trên ECR (nếu chưa có):
   ```bash
   aws ecr create-repository --repository-name nutritrack-api --region us-east-1
   ```
3. Tag image để nối tới ECR:
   ```bash
   docker tag nutritrack-api:latest <aws-account-id>.dkr.ecr.us-east-1.amazonaws.com/nutritrack-api:latest
   ```
4. Push image:
   ```bash
   docker push <aws-account-id>.dkr.ecr.us-east-1.amazonaws.com/nutritrack-api:latest
   ```

---

## 🚀 3. Deploy Lên AWS ECS (Fargate)

AWS ECS Fargate cung cấp nền tảng chạy container hoàn toàn tự động, serverless (bạn không cần phải tự quản lý EC2).

### Bước 1: Khởi tạo ECS Cluster
1. Truy cập **AWS Web Console** > **ECS (Elastic Container Service)**.
2. Chọn **Create cluster**.
3. Điền tên: `nutritrack-cluster`.
4. Cơ sở hạ tầng: Chọn **AWS Fargate** (Serverless).
5. Nhấn **Create**.

### Bước 2: Khởi tạo Task Definition (Định nghĩa Container)
1. Ở danh mục bên trái, chọn **Task definitions**, nhấn **Create new task definition** > **Create new task definition with console**.
2. Đặt tên: `nutritrack-api-task`.
3. Trong phần **Infrastructure requirements**:
   - Launch type: Chọn **AWS Fargate**
   - OS, Architecture, CPU, Memory: Chọn **Linux/X86_64, 1 vCPU, 3 GB RAM** (có thể tăng tùy mức tiêu thụ RAM của Python Pillow + Requests).
   - Task execution role: Chọn **Tạo Role Mới** (hoặc role ecsTaskExecutionRole).
4. Trong phần **Container - 1**:
   - Name: `api-container`
   - **Image URI**: 
     - Nếu dùng Hub: `<your-dockerhub-username>/nutritrack-api:latest`
     - Nếu dùng ECR: `<aws-account-id>.dkr.ecr.us-east-1.amazonaws.com/nutritrack-api:latest`
   - Port mappings: Container port: `8000`, Protocol: `TCP`.
   - **Environment variables**: Khai báo thủ công các secrets từ `.env` vào đây (VD: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `USDA_API_KEY`, `AWS_S3_CACHE_BUCKET`).
5. Cuộn xuống nhấn **Create**.

### Bước 3: Chạy Service trên ECS Cluster
1. Quay lại Cluster `nutritrack-cluster`, tab **Services** > Nhấn **Create**.
2. Phần Compute configuration (Environment): Chọn **Launch type** > **Fargate**.
3. Phần Deployment configuration:
   - Application type: **Service**
   - Task definition: Chọn `nutritrack-api-task` khởi tạo ở trên (chọn Revision mới nhất).
   - Service name: `nutritrack-api-service`
   - Desired tasks (Số lượng Instance muốn chạy): `1`
4. Phần **Networking**:
   - Chọn VPC default. Cần chọn ít nhất một hoặc nhiều Subnets công khai.
   - BẬT **Auto-assign public IP** (Để bạn có thể gọi API trực tiếp từ Internet).
   - **Security group**: Create a new security group. Thêm Inbound rules cho phép truy cập port `8000` (để gọi từ Postman / Mobile / Web) từ mọi IPv4 (`0.0.0.0/0`).
5. (Tuỳ chọn) Cấu hình Load Balancer: Có thể bỏ qua nếu bạn chỉ chạy thử.
6. Nhấn **Create** để hệ thống ECS cấp phát Fargate Container. 

### Bước 4: Chờ Service Status (Running) và Lấy Public IP
- Trong thông tin the Service vừa lập, vào tab **Tasks**.
- Refresh và Đợi khi task Status chuyển từ `PROVISIONING`, `PENDING` sang `RUNNING`.
- Click vào `Task ID` đang chạy. Tại tab **Configuration**, bạn sẽ tìm thấy IP dạng: **Public IP: 3.86.xx.xx**.
- Call API trực tiếp tại `http://<Public IP>:8000/docs` !! 🥳

---

## 🗄️ 4. Quyền Truy Cập (IAM) cho S3 Cache & Bedrock
> **Quan Trọng:** Do bạn đã kích hoạt tính năng Hybrid Cache với S3 và sử dụng Bedrock Model (`QWEN3-VL-235B`), Task Fargate phải có quyền gọi dịch vụ này để không xả lỗi Access Denied.

Vào kho điều hướng **IAM** > **Roles**, tìm Role mang tên `ecsTaskExecutionRole` vừa nãy và đính kèm thủ công một Policy (`Add Permissions -> Create Inline Policy` - hoặc truyền API Key riêng vào biến môi trường bên bước 2) chứa các tính năng:
- S3 `GetObject`, `PutObject` cho Bucket đã chỉ định ở `AWS_S3_CACHE_BUCKET`.
- Bedrock `InvokeModel` cho model `arn:aws:bedrock:*::foundation-model/*`.

*(Nếu muốn dễ, ở bước khai báo Biến Môi trường [Environment Variables], cung cấp thẳng `AWS_ACCESS_KEY_ID` và `AWS_SECRET_ACCESS_KEY` là xong).*
