# Hướng Dẫn Nâng Cấp Hệ Thống (Scale-up Phase): Thiết Lập Amazon SQS & ElastiCache (Redis) Qua AWS Console

Tài liệu này là hướng dẫn từng bước (step-by-step) để bạn thiết lập hạ tầng Message Queue (SQS) và In-Memory Database (Redis) trên giao diện AWS Console.

**Mục đích:** 
Chuyển đổi từ việc lưu tiến trình `job_store = {}` (trong RAM của 1 máy) hiện tại sang một hệ thống phân tán. Khi bạn có 10 container ECS (theo Auto-scaling config), việc kiểm tra trạng thái Job từ Client có thể rơi ngẫu nhiên vào bất kỳ container nào, do đó Redis sẽ đóng vai trò làm trung tâm chia sẻ trạng thái dùng chung. SQS sẽ đóng vai trò hàng đợi để phân bổ task (tùy chọn kết hợp với Celery).

---

## Phần 1: Thiết Lập Amazon ElastiCache (Redis)

### Bước 1: Tạo Subnet Group cho ElastiCache
Vì Redis nên được đưa vào vùng mạng Private để bảo mật:
1. Đăng nhập AWS Console, tìm kiếm **ElastiCache**.
2. Ở thanh menu bên trái, chọn **Subnet Groups** -> Nhấn **Create subnet group**.
3. **Tên:** `nutritrack-redis-subnet-group`.
4. **VPC ID:** Chọn `nutritrack-api-vpc`.
5. **Availability Zones:** Chọn 2 Zone mạng đang dùng.
6. **Subnet ID:** *Cực kỳ quan trọng*, chỉ chọn 2 Subnet **Private** (`nutritrack-api-private-subnet-ecs01` và `02`).
7. Nhấn **Create**.

### Bước 2: Khởi tạo cluster Redis
1. Vẫn ở menu ElastiCache, chọn **Redis OSS** -> Nhấn **Create Redis OSS cluster**.
2. **Cluster setting mode:** Nên chọn **Configure and create** thay vì Create Serverless (Serverless khá đắt nếu dùng tĩnh).
3. **Name:** `nutritrack-redis-cluster`.
4. **Node type:** Nhấn vào, chọn **cache.t3.micro** hoặc **cache.t4g.micro** (rẻ nhất, chỉ ~12$/tháng) nếu hệ thống lúc đầu chưa có quá nhiều dữ liệu.
5. **Number of replicas:** Đặt là `0` (để tiết kiệm tối đa) hoặc `1` (nếu cần chịu lỗi High Availability).
6. Ở bước **Connectivity**:
   - Network type: **IPv4**.
   - Mục Subnet group: Chọn subnet group đã tạo ở **Bước 1**.
7. Mục **Security**: Bỏ qua Enable encryption in transit (nếu không bắt buộc để kết nối dễ hơn) hoặc bật theo nhu cầu. 
8. Chọn **Create** và chờ khoảng 5-10 phút để cụm sáng lên `Available`.

### Bước 3: Cập nhật Security Group
Máy chủ ECS của bạn cần quyền chui vào cổng 6379 của Redis.
1. Khảo sát cụm Redis vừa tạo, copy địa chỉ **Primary Endpoint** (VD: `nutri-redis...xxx.cache.amazonaws.com`).
2. Vào **EC2** -> **Security Groups**. Tìm tới Security Group của Redis (thường sinh ra mặc định cùng cluster) hoặc tạo SG riêng.
3. Ở Tab **Inbound Rules** của nhóm Redis này: 
   - Add rule -> Type: **Custom TCP**, Port: **6379**, Source: Chọn ID của Security Group **`nutritrack-api-vpc-ecs-sg`** (Cho phép ECS chui vào).
4. Save Rule. Môi trường của bạn đã có Redis! Khi mang vào ứng dụng chạy, URL sẽ là: `redis://<Primary-Endpoint>:6379/0`.

---

## Phần 2: Thiết lập AWS SQS (Simple Queue Service)

Amazon SQS rất rẻ (miễn phí 1 triệu yêu cầu đầu tiên mỗi tháng). Bạn sẽ dùng nó để hàng đợi các luồng xử lý AI, tránh việc quá tải Bedrock.

### Bước 1: Tạo Queue
1. Tìm dịch vụ **SQS** trên AWS Console.
2. Nhấn nút **Create queue**.
3. **Type:** Chọn **Standard** (Rẻ hơn và Load lớn hơn FIFO, rất phù hợp xử lý ảnh vì một số ảnh có phân tích 2 lần cũng không ảnh hưởng tính đúng đắn).
4. **Name:** `nutritrack-analyze-job-queue`.

### Bước 2: Tinh chỉnh Configuration (Cực kỳ quan trọng)
FastAPI Background hoặc Celery khi nhận việc sẽ báo cho SQS ẩn message đi chờ xử lý xong.
1. **Visibility timeout:** Mặc định 30 giây. Hãy nâng lên **5 phút (300 giây)**. (Do AI chạy hết 10 giây, để 5 phút để bảo đảm dư giả thời gian xử lý nếu API USDA quá chậm).
2. **Message retention period:** Để mặc định (4 Days). Tránh tốn tiền lưu message rác.
3. **Delivery delay / Receive message wait time:** Để 0.

### Bước 3: Dead-Letter Queue (DLQ) (Tùy chọn nâng cao)
Đề phòng ảnh bị lỗi (lỗi BEDROCK Limit, lỗi quá lớn) không xử lý được, nó cứ nằm lặp cấu trúc ở hàng đợi mãi.
1. Ở dưới kéo xuống phần **Dead-letter queue**.
2. Trước hết bạn tạo một Queue SQS nữa tên là `nutritrack-analyze-dl-queue`.
3. Bật DLQ ở queue chính, trỏ vào `nutritrack-analyze-dl-queue` và số lần thử lại (**Maximum receives**) là `3`.
4. Nếu xử lý rớt 3 lần, job sẽ bị đẩy vào "nghĩa trang DLQ", bạn có thể login kiểm tra bằng tay ảnh nào bị lỗi.

### Bước 4: Lưu thông tin
1. Nhấn **Create queue**.
2. Lưu lại địa chỉ **URL** (VD: `https://sqs.ap-southeast-2.amazonaws.com/.../nutritrack-analyze-job-queue`). Tương tự, nếu bạn dùng ECS ở PrivateLink SQS thì URL vẫn khớp định danh này bên trong AWS.

---

## Kịch Bản Áp Dụng (Next Steps trong Codebase)
Sau khi có 2 thành phần này, bước Scale-up tiếp theo sẽ diễn ra trong backend như sau:

**1. Sửa `job_store` thành Redis:**
- Xóa `job_store = {}`.
- Dùng SDK `redis` hoặc `aioredis`. Khi bắt đầu gọi `/analyze-food` -> `redis.set(job_id, {"status": "processing"})`.
- Hàm Polling `/jobs/{job_id}` sẽ lấy trực tiếp `redis.get(job_id)`. Bất kỳ container nào được ALB tải dội vào đều biết job đang ở đâu.

**2. Sửa `BackgroundTasks` thành Celery + SQS (Tùy chọn Scale Dữ Dội)**
- Khi client gửi job vào FastAPI, code chỉ cần `boto3.client('sqs').send_message(QueueUrl, body=job_json)`. 
- Thiết lập một Container riêng biệt hoàn toàn (Celery worker). Chỉ worker này mới lắng nghe SQS để lấy việc làm. Frontend Web gửi ảnh nhẹ như tơ, chả tốn tí tài nguyên nào.
