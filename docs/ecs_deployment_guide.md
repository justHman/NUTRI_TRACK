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

## 🌐 3. Thiết lập Hạ tầng Mạng (VPC Custom)

Để container có thể truy cập Internet (để gọi Bedrock) và người dùng có thể truy cập API, bạn cần một hệ thống mạng cơ bản gồm: VPC, Subnet, Internet Gateway và Route Table.

### Bước 1: Tạo VPC
1. Truy cập **VPC Console** -> **Your VPCs** -> **Create VPC**.
2. Chọn **VPC only**. 
3. Name tag: `nutritrack-vpc`.
4. IPv4 CIDR: `10.0.0.0/16`.
5. Nhấn **Create VPC**.

### Bước 2: Tạo Internet Gateway (IGW) - "Cổng ra thế giới"
1. Tại VPC Console -> **Internet gateways** -> **Create internet gateway**.
2. Name tag: `nutritrack-igw`.
3. Sau khi tạo xong, nhấn **Actions** -> **Attach to VPC**.
4. Chọn `nutritrack-vpc` vừa tạo và nhấn **Attach**.

### Bước 3: Tạo Subnet (Mạng con)
1. Tại VPC Console -> **Subnets** -> **Create subnet**.
2. VPC ID: Chọn `nutritrack-vpc`.
3. Subnet name: `nutritrack-public-subnet`.
4. Availability Zone: Chọn bất kỳ (VD: `us-east-1a`).
5. IPv4 CIDR block: `10.0.1.0/24`.
6. Nhấn **Create subnet**.
7. **Lưu ý quan trọng**: Sau khi tạo, tick chọn subnet đó -> **Actions** -> **Edit subnet settings** -> Tick vào **Enable auto-assign public IPv4 address** -> **Save**.

### Bước 4: Cấu hình Route Table (Bảng định tuyến)
Để Subnet thực sự là "Public", nó cần biết đường đi ra Internet Gateway.
1. Tại VPC Console -> **Route tables** -> Chọn bảng định tuyến có sẵn của `nutritrack-vpc`.
2. Name tag: Đổi tên thành `nutritrack-public-rt`.
3. Tab **Routes** -> **Edit routes**.
4. Nhấn **Add route**:
   - Destination: `0.0.0.0/0`
   - Target: Chọn **Internet Gateway** -> Chọn `nutritrack-igw`.
5. Nhấn **Save changes**.
6. Tab **Subnet associations** -> **Edit subnet associations** -> Chọn `nutritrack-public-subnet` -> **Save**.

---

## 🚀 4. Deploy Lên AWS ECS (Fargate)

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
   - Chọn VPC vừa tạo: `nutritrack-vpc`. 
   - Ở trường Subnets: Chọn `nutritrack-public-subnet`.
   - BẬT **Auto-assign public IP** (Cực kỳ quan trọng, nếu TẮT thì container không ra được Internet và cũng không nạp IP để test được).
   - **Security group**: Chọn tuỳ chọn **Create a new security group**. Đặt tên và ghi chú cho nó (ví dụ: `nutritrack-api-sg`).
   - Xóa các rule cũ, và thiết lập cấu hình **Inbound rules** (Quyền đi vào máy chủ) mới như sau để mở cửa cho FastAPI (`Uvicorn` cổng 8000):
     - **Type**: Chọn `Custom TCP`
     - **Port range**: Gõ `8000`
     - **Source**: Chọn `Anywhere` hoặc nhập `0.0.0.0/0` (Nghĩa là cho phép mọi máy/mọi điện thoại đều có quyền phi tới).
6. Nhấn **Create** để hệ thống ECS cấp phát Fargate Container. 

### Bước 4: Chờ Service Status (Running) và Lấy Public IP
- Trong thông tin the Service vừa lập, vào tab **Tasks**.
- Refresh và Đợi khi task Status chuyển từ `PROVISIONING`, `PENDING` sang `RUNNING`.
- Click vào `Task ID` đang chạy. Tại tab **Configuration**, bạn sẽ tìm thấy IP dạng: **Public IP: 3.86.xx.xx**.
- Call API trực tiếp tại `http://<Public IP>:8000/docs` !! 🥳

---

## 🗄️ 4. Phân biệt & Cấp quyền IAM Roles trên ECS (Rất quan trọng)

Trong bảng thiết lập ECS Task Definition, bạn sẽ thấy có 2 loại Role khác nhau. Việc hiểu sai 2 role này sẽ khiến ứng dụng sinh lỗi Access Denied hoặc không thể khởi động.

### 4.1. Task Execution Role (ecsTaskExecutionRole)
- **Ai sử dụng:** Chính hệ thống máy chủ AWS ECS tĩnh ở dưới nền.
- **Dùng để làm gì:** Kéo Image từ ECR về, ghi Log ra CloudWatch, và **mở khoá AWS Secrets Manager** để nhét biến môi trường vào cho Container (Như đã trình bày ở file `aws_secrets_manager_guide.md`).
- **Cách cấu hình:** Chọn mặc định `ecsTaskExecutionRole`. Bạn chỉ edit Role này khi cần cấp thêm quyền lấy Secret (`secretsmanager:GetSecretValue`).

### 4.2. Task Role
- **Ai sử dụng:** Phần mềm/Code Python thực tế đang chạy bên trong Container (Thư viện `boto3`).
- **Dùng để làm gì:** Gọi các dịch vụ AWS do logic code yêu cầu. Với NutriTrack, code cần gọi AWS Bedrock (`QWEN3-VL-235B`) và AWS S3 (để lưu Cache).
- **Cách cấu hình:** 
   1. Bấm **Create new role** ở mục Task Role (hoặc vào thẳng giao diện IAM Role).
   2. Tạo một Role mang tên `ecsTaskRole` (hoặc tên bất kỳ bạn thích), chọn Trusted Entity là `Elastic Container Service Task`.
   3. Gắn các quyền (Permissions) cho Role này:
      - **Cách nhanh nhất:** Attach 2 policy có sẵn của AWS: `AmazonBedrockFullAccess` và `AmazonS3FullAccess`.
      - **Cách cho môi trường siêu bảo mật:** Tạo *Inline Policy* chỉ giới hạn đúng quyền `InvokeModel` và `Get/PutObject` cho đúng tên Bucket của bạn.
   4. Quay lại trang tạo Task Definition, Refresh lại danh sách và chọn `ecsTaskRole` làm **Task Role**.

> **Kết luận:** Hệ thống (Execution Role) cần chìa khóa để lắp ráp phần cứng & kéo mật khẩu; còn Code bên trong (Task Role) cần chìa khóa để chạy thuật toán AI và lưu file Caching. Việc tách biệt này là tiêu chuẩn bảo mật tối cao của nền tảng AWS Cloud.

---

## 🛑 5. Cách Tắt Server Để Không Bị Tốn Tiền (Sống Còn cho Đồ Án)

AWS ECS Fargate tính tiền theo **giây** dựa trên số vCPU và Memory mà bạn đăng ký chạy. Nếu bạn để nó chạy quên ngày tháng, tiền bill sẽ tăng lên mỗi ngày. Khi test xong hoặc muốn đi ngủ, bạn PHẢI tắt nó đi!

### Cách Tạm Dừng (Chỉ Tắt Container, Giữ Lại Cấu Hình):
Cách này thích hợp khi bạn muốn hôm sau rảnh bật lên chấm điểm tiếp mà không cần thiết lập lại từ đầu.

1. Bật AWS Console -> Truy cập **Elastic Container Service (ECS)**.
2. Bấm vào Cluster của bạn (`nutritrack-cluster`).
3. Dưới tab **Services**, tick chọn cái Service đang chạy (`nutritrack-api-service`) và nhấn nút **Update** ở góc trên.
4. Cuộn chuột tìm đến ô **Desired tasks** (Số lượng Task mong muốn). Cột này đang là `1`. Ngay lập tức sửa nó thành `0`.
5. Cuộn thẳng xuống cuối cùng nhấn **Update** để lưu.
   *Hệ quả: ECS sẽ ra lệnh "Bắn bỏ" cái Container đang chạy, giải phóng CPU và RAM trả lại cho Amazon. Tiền phí sẽ DỪNG hoàn toàn ngay thời điểm Fargate bị bắn. Lúc nào bạn muốn thi trình diễn lại cho Giáo viên xem, vào lại làm theo y chang Bước 3, biến số `0` thành số `1` là container tự động khởi động lại sau 2 phút!*

### Cách Xoá Sạch Vĩnh Viễn (Cleanup Hoàn Toàn):
Nếu bạn đã chấm xong đồ án, hoặc code lỗi nhiều quá muốn xóa làm lại:
1. Cũng tại giao diện Cluster, chọn Service `nutritrack-api-service` và nhấn nút **Delete** để xóa service.
2. Xóa service xong, nếu không dùng đến Cluster nữa thì nhấn nút **Delete cluster** ở góc trái trên cùng để xóa trắng cụm.
3. Qua Amazon ECR -> Cấp chọn Repository tên `nutritrack-api` và nhấn Xoá (Tiết kiệm vài cent tiền lưu trữ ổ cứng 2GB image hằng tháng).
4. Qua Amazon Secrets Manager -> Tìm Két sắt và chọn lệnh **Delete Secret** (Dù nó không đáng bao nhiêu tiền nhưng dọn sạch cho gọn).
