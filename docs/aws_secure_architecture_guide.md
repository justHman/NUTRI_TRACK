# Hướng Dẫn Chi Tiết: Kiến Trúc Bảo Mật Nâng Cao cho NutriTrack API trên AWS (ECS Fargate)

Tài liệu này giải thích chi tiết thiết kế kiến trúc bảo mật, mở rộng và tối ưu chi phí cho NutriTrack API. Sơ đồ kiến trúc tương ứng nằm tại: `docs/generated-diagrams/aws_secure_diagram.md`.

---

## 1. Yêu cầu & Bối cảnh Kiến trúc
Kiến trúc này được thiết kế dựa trên các tiêu chí (Best Practices) của **AWS Solutions Architect Professional**, nhằm giải quyết 3 bài toán lớn của phiên bản trước:
1. **Bảo mật (Security):** Ẩn hoàn toàn Server (Fargate) khỏi Internet, không cho phép truy cập trực tiếp bằng IP / Port.
2. **Khả năng mở rộng dự phòng (Dynamic Scaling):** Tự động thêm tài nguyên khi lượng truy cập tăng đột biến, giúp API nhận diện thực phẩm không bị gián đoạn.
3. **Tối ưu chi phí & Hiệu suất (Cost & Performance Optimization):** Routing thông minh, gọi các APIs bên ngoài (3rd-party) và dịch vụ AWS (Bedrock, S3) với chi phí mạng lưới (Networking) thấp nhất.

---

## 2. Chi tiết các Phân lớp Kiến trúc (Layers)

### 2.1. Phân lớp Front-door & Ingress (Luồng gọi vào hệ thống)
*Hành trình user gọi API từ Web/Mobile/Postman.*

- **Amazon API Gateway (HTTP API):** 
  - Đóng vai trò là điểm tiếp nhận duy nhất (Entry point) ra ngoài Internet.
  - **Lợi ích:** Cung cấp tính năng Throttling (Rate Limiting - Ví dụ: Tối đa 50 requests/sec mỗi IP) để chống Spam và DDoS. Rẻ hơn nhiều so với REST API, hiệu năng định tuyến cực cao.
- **VPC Link & Application Load Balancer (ALB):**
  - Traffic từ API Gateway sẽ thông qua **VPC Link** (Đường hầm bảo mật) nối thẳng vào ALB nội bộ nằm ở Public Subnet. 
  - ALB tiếp tục phân phối tải (Load Balancing) chia đều gánh nặng xuống các Fargate Tasks nội bộ.

### 2.2. Phân lớp Tính toán (Compute Layer - ECS Fargate)
*Nơi chạy Code Python thực thi NutriTrack API.*

- **Private Subnets:** Fargate Tasks giờ đây ĐƯỢC ĐẶT TRONG Private Subnets với cờ `assign_public_ip = false`.  
- **Ý nghĩa bảo mật:** Task hoàn toàn "tàng hình", không sở hữu IP Public, không ai trên Internet có thể gọi, ping, hay scan port của Server. Cách thức duy nhất chạm đến Server là đi qua API Gateway hợp lệ ở trên.

### 2.3. Phân lớp Egress (Luồng gọi API ngoài Data Center)
*Phục vụ cho các module kết nối `third_apis` (USDA, OpenFoodFacts, AvocavoNutrition).*

- Vì nằm trong Private Subnets, Fargate không có đường truyền ra ngoài. Để giải quyết, chúng ta sử dụng **NAT Gateway** (hoặc NAT Instance) nằm ở Public Subnet.
- Khi Fargate cần gọi USDA API, request sẽ được "đẩy" qua NAT -> Internet Gateway (IGW) -> Mạng Internet. 
- **Lựa chọn Tối ưu Chi phí:**
  - *Enterprise / Sản xuất:* Sử dụng **Managed NAT Gateway** của AWS (Ổn định tuyệt đối, giá duy trì ~$32/tháng + Phí băng thông).
  - *Ngân sách hẹp (Budget-friendly):* Chạy một EC2 t4g.nano/micro làm **NAT Instance** (Ví dụ public AMI `fck-nat`). Chi phí rớt xuống chỉ còn ~$3-4/tháng nhưng bạn tự chịu trách nhiệm nếu Instance bị sập.

### 2.4. Phân lớp Giao tiếp Mạng nội bộ AWS (Tối ưu Cost/Speed)
*Phục vụ ECS gọi Bedrock Model Qwen3-VL-235B, đọc ghi Caching trên S3, lấy Key từ Secrets Manager.*

Nếu các cuộc gọi này đi vòng qua NAT Gateway (ở mục 2.3), bạn sẽ tốn 1 khoản phí lớn mang tên "NAT Data Processing Cost", đồng thời giảm tốc độ. Do đó, ta thiết lập **VPC Endpoints (AWS PrivateLink)**:
- **S3 Gateway Endpoint (BẮT BUỘC):** Là đường truyền dẫn thẳng từ VPC sang Amazon S3 hoàn toàn trên cáp quang nội bộ AWS. **Free 100%**. Nó giúp Fargate lưu và tải file JSON cache siêu tốc không rớt 1 byte ra ngoài Internet.
- **Interface Endpoints (Tùy chọn cân nhắc):** Khác với Gateway, Interface Endpoint (cho Bedrock, ECR, Cloudwatch...) tốn phí duy trì giờ (~$7.2/tháng mỗi service).
  - *Lời khuyên:* Đồ thị Request sang Bedrock sẽ truyền tải file hình ảnh dung lượng lớn, nếu traffic gọi rầm rộ, Interface Endpoint đường riêng sẽ rẻ hơn việc chịu tải và phí ở NAT. Nhưng nếu traffic siêu thấp trong giai đoạn đầu, bạn KHÔNG cần Interface Endpoint mà cứ cho Bedrock "quá giang" chung đường qua NAT Gateway để tiết kiệm $7.2/tháng/dịch vụ ban đầu.

---

## 3. Cơ chế Khả năng Mở Rộng Tự Động (Dynamic Auto Scaling)

Hệ thống được thiết kế với **Target Tracking Scaling Policies**:
- **Baseline (Bình thường):** Duy trì số lượng Fargate task tối thiểu chặn rò rỉ chi phí (VD: `min_capacity = 1`).
- **Scale-out (Mở rộng):** Cài đặt metric khi **CPU Utilization (hoặc Memory) > 70%**. ALB sẽ tự động theo dõi, nếu lượng truy cập đẩy CPU lên mức này, AWS sẽ tự động rẽ nhánh sinh thêm Task số 2, số 3. Quá trình mất 30-60 giây nhưng đảm bảo API luôn "sống chăn" trước mọi đợt gọi dữ liệu hình ảnh phức tạp.
- **Scale-in (Thu hẹp):** Khi traffic tan (đêm khuya, lúc rảnh rỗi), ECS thu hồi task lại về trạng thái min_capacity. Chế độ "xài bao nhiêu trả bấy nhiêu" nguyên bản của Serverless Fargate.

---

## 4. Tổng hợp To-Do List cho DevOps / SysAdmin
Để chuyển dịch từ hệ thống hiện tại sang kiến trúc trên, quy trình IAM/Terraform của bạn cần thực hiện:

1. **VPC & Networking:**
   - Đảm bảo VPC có chia 2 lớp mạng: Public Subnets (cho ALB, NAT) và Private Subnets (cho Fargate).
   - Dựng NAT Gateway và thiết lập Route Table cho Private Subnet trỏ `0.0.0.0/0` qua NAT.
   - Thêm Gateway Endpoint `com.amazonaws.<region>.s3` vào VPC.

2. **ECS & Load Balancer:**
   - Dựng Internal/Internet-facing ALB trong Public/Private subnet.
   - Cập nhật ECS Service: Đặt `assign_public_ip = false`.
   - Kết nối ECS Service vào Target Group của ALB.
   - Áp dụng Auto Scaling block trong Terraform cho `aws_appautoscaling_target` và `aws_appautoscaling_policy`.

3. **API Gateway:**
   - Khởi tạo API Gateway V2 (HTTP API).
   - Khởi tạo VPC Link trỏ vào các subnets nhóm ALB.
   - Thiết lập Gateway Route và Integration qua VPC Link tới HTTP/8000 của ALB.
   - Cài đặt cơ chế Rate Throttling trong Stage.

---
*Tài liệu được soạn thảo đáp ứng tiêu chuẩn Well-Architected Framework: Tính bảo mật, Độ tin cậy, Tối ưu hóa chi phí và Hiệu suất.*
