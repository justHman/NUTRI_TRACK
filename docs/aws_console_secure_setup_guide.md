# Hướng Dẫn Từng Bước (Step-by-Step): Setup Kiến Trúc NutriTrack API (Secure) Trên AWS Console

Dựa trên thiết kế kiến trúc bảo mật tại `aws_secure_diagram.md` và `aws_secure_architecture_guide.md`, đây là bản hướng dẫn "cầm tay chỉ việc" để thiết lập toàn bộ hệ thống bằng giao diện web **AWS Management Console**.

---

## 🚀 Bước 1: Khởi tạo Network Foundation (VPC, Subnets, Endpoints & NAT)
*Chỉ với 1 click, AWS sẽ dựng toàn bộ khung xương mạng chuẩn chỉ nhất.*

1. Đăng nhập AWS Console, gõ tìm **VPC** > Chọn **VPC dashboard** > Chọn nút **Create VPC**.
2. Phía trên cùng (VPC settings), chọn mốc **VPC and more**.
3. **Name tag auto-generation**: Nhập `nutritrack` (Hệ thống sẽ dựa vào chữ này để đặt tên tự động cho toàn bộ Subnet/Route table).
4. **IPv4 CIDR block**: `10.0.0.0/16`.
5. **Number of Availability Zones (AZs)**: Chọn `2` (Để đảm bảo High Availability).
6. **Number of public subnets**: Chọn `2` (Dành cho Application Load Balancer và NAT Gateway).
7. **Number of private subnets**: Chọn `2` (Dành cho ECS Fargate chứa API, ẩn hoàn toàn).
8. **NAT gateways**: Chọn **In 1 AZ** (Để tiết kiệm chi phí nhưng vẫn đảm bảo kết nối gọi USDA, Bedrock. Nếu có điều kiện, chọn *1 per AZ*).
9. **VPC endpoints**: Chọn **S3 Gateway** (Rất quan trọng! Để Fargate đọc ghi Cache miễn phí).
10. Cuộn xuống dưới cùng và bấm **Create VPC**. Đợi vài phút để AWS nối dây và hoàn thiện.

---

## 🛡️ Bước 2: Thiết lập Tường lửa (Security Groups - SG)
*Nguyên tắc: API Gateway gọi ALB, ALB gọi Fargate.*

1. Qua **EC2 Console** > Nhìn menu bên trái bờ dưới cùng chọn **Security Groups** > Bấm **Create security group**.
2. **Tạo SG cho Load Balancer (`nutritrack-alb-sg`)**:
   - Tên và Mô tả: `nutritrack-alb-sg`.
   - VPC: Chọn `nutritrack-vpc` (hoặc cái vpc bạn vừa tạo).
   - Inbound rules: Bấm Add rule > Loại: **HTTP** (Port 80) / Source: **0.0.0.0/0** (Mọi nơi). 
   *(Sau này VPC Link của API Gateway sẽ bắn thẳng vào port 80 của ALB này)*.
   - Bấm **Create**.
3. **Tạo SG cho Fargate Tasks (`nutritrack-fargate-sg`)**:
   - Lặp lại quy trình bấm Create.
   - Tên và Mô tả: `nutritrack-fargate-sg`.
   - VPC: `nutritrack-vpc`.
   - Inbound rules: Bấm Add rule > Loại: **Custom TCP** (Port `8000` - tùy vào port app Python bạn đang bind).
   - **Source**: Chọn biểu tượng cái kính lúp nhỏ nhỏ > Gõ tên SG của load balancer vừa tạo (`nutritrack-alb-sg`) và ấn chọn nó.
   *(Quy tắc rào cản: Fargate từ chối tất cả, CHỈ MỞ CỬA NGHÊNH ĐÓN YÊU CẦU TỪ LOAD BALANCER CỦA CHÚNG TA!)*
   - Bấm **Create**.

---

## 🔀 Bước 3: Tạo Application Load Balancer (ALB) Internal
*Load Balancer chìm (Internal) sẽ phân bổ request xuống các Fargate container.*

1. Trong **EC2 Console** > Nhìn menu trái khúc Load Balancing > Chọn **Load Balancers** > **Create load balancer**.
2. Ngay cục đầu tiên (Application Load Balancer), nhấn **Create**.
3. **Basic configuration**:
   - Load balancer name: `nutritrack-internal-alb`.
   - **Scheme**: BẮT BUỘC CHỌN **Internal** *(Cực kỳ quan trọng để bảo mật, ẩn khỏi Internet)*.
4. **Network mapping**:
   - VPC: Chọn `nutritrack-vpc`.
   - Mappings: Tick vào cả 2 AZ, **NHƯNG CHỈ CHỌN `Private subnet`** cho từng AZ. *(Vì ALB là Internal nên nhốt luôn nó chung vào Private)*.
5. **Security groups**: Tắt chọn default đi, chọn `nutritrack-alb-sg` bạn đã làm ở Bước 2.
6. **Listeners and routing**:
   - Ở Port 80, mục Default action, bấm vào đường link mờ mờ **Create target group**.
   - Tab mới mở ra: Choose a target type > CHỌN **IP addresses** *(Thứ duy nhất ECS Fargate xài được)*.
   - Target group name: `nutritrack-tg`.
   - Protocol/Port: `HTTP` / `8000`.
   - VPC: `nutritrack-vpc`.
   - Bấm Next > Ở bước *Register targets* khoan chọn gì cả > Bấm **Create target group**.
7. Quay lại tab tạo ALB, bấm nút xoay tròn Refresh nhỏ nhỏ bên cạnh dropdown Target Group > Chọn `nutritrack-tg` vừa tạo.
8. Cuộn xuống và ấn **Create load balancer**.

---

## 📦 Bước 4: Tạo Hệ Sinh Thái ECS Fargate "Đóng Mật"
*Hạt nhân xử lý nằm đây. Chạy Code Python của NutriTrack API.*

### 4A. Tạo ECS Cluster & Roles
1. Khuyên bạn qua **IAM Console** dọn đường trước: Tạo 1 Role tên `nutritrack-ecs-task-role` gán Policy `AmazonBedrockFullAccess` + `AmazonS3FullAccess` + `SecretsManagerReadWrite`. (Dành cho lúc code Python thực thi). Đảm bảo `ecsTaskExecutionRole` đã được AWS tạo mặc định.
2. Sang **ECS Console** > Chọn **Clusters** > **Create cluster**.
3. Tên Cluster: `nutritrack-cluster`. Base infrastructure: Để check **AWS Fargate** > Bấm Create.

### 4B. Khai báo Task Definition
1. Chuyển qua mũi tên **Task definitions** bên menu trái > **Create new task definition** > Create new...
2. Tên Task: `nutritrack-api-definition`.
3. Infrastructure: Check **Fargate**.
4. Chọn Role:
   - Task role: `nutritrack-ecs-task-role` (Đã tạo ở 4A).
   - Task execution role: `ecsTaskExecutionRole`.
5. Đẩy thông số CPU và RAM phù hợp (Ví dụ 1 vCPU / 2GB RAM cho xử lý Bedrock thoải mái).
6. Ở ô Container bên dưới:
   - Tên Container: `nutritrack-app`.
   - Image URI: Dán đường dẫn ECR của bạn vào (Ví dụ: `<tài-khoản>.dkr.ecr.<region>.amazonaws.com/nutri:latest`).
   - Container port: Nhập `8000`.
7. Bấm **Create**.

### 4C. Deploy ECS Service & Khóa cửa Fargate
1. Quay về **Clusters** > Bấm vào `nutritrack-cluster` > Nằm luôn ở tab *Services*, gõ **Create**.
2. **Compute configuration**: Sẵn **Capacity provider strategy** (Fargate).
3. **Deployment configuration**:
   - Application type: Service.
   - Family (Task Definition): Chọn `nutritrack-api-definition` vừa làm.
   - Desired tasks: `1` (Khởi động sương sương 1 cái test thử).
4. Sổ dọc **Networking** ra (QUAN TRỌNG NHẤT BƯỚC NÀY):
   - VPC: Chọn `nutritrack-vpc`.
   - **Subnets**: Kiểm tra gắt gao, Vứt bỏ các Public Subnets, CHỈ TICK CHỌN CÁC **Private Subnets**.
   - Security group: Chọn **Use existing ...** > Gõ chọn `nutritrack-fargate-sg`.
   - **Public IP**: Chọn **TURN OFF**. *(Chiếc khiên vững trãi ẨN THÂN DIỆT TÍCH server Fargate)*.
5. Sổ dọc **Load balancing** ra:
   - Load balancer type: Chọn Application Load Balancer.
   - Tắt cái default đi, chỉ đích danh chọn Load balancer có chữ `nutritrack-internal-alb`.
   - Container to load balance: `nutritrack-app:8000:8000`.
   - **Target group**: Bấm *Use existing* > Chọn tên `nutritrack-tg`.
6. Cuộn tít xuống bấm **Create** và chờ Fargate thức giấc. 

---

## 🔥 Bước 5: Cài "Cửa Nhựa" Chống Đạn - API Gateway Rate Limit
*Phơi mặt ra nhận request của người dùng, phân phối an toàn vào VPC qua công nghệ VPC Link.*

### 5A. Đúc đường hầm VPC Link
1. Mở tap ẩn tìm **API Gateway Console** > Cột trái chọn tít dưới mốc **VPC links** > Bấm **Create**.
2. Chọn phiên bản nhẹ rẻ mạnh: **VPC link for HTTP APIs**.
3. Tên: `nutritrack-vpc-link`.
4. Chọn VPC `nutritrack-vpc`.
5. Subnets: Chọn 2 Private Subnets. Security groups: Chọn `nutritrack-alb-sg`.
6. Bấm Create. Phải đợi 2-5 phút trạng thái mới sáng đèn xanh (Available).

### 5B. Lắp ráp API Gateway
1. Quay lại trang đầu API Gateway > Cuộn tìm box ghi **HTTP API** > Nút **Build**.
2. Tại màn hình Integrations, bấm ngay *Add integration*.
   - Ở Dropdown bốc vội chữ **Private resource**.
   - Target details > Trỏ con mắt sang **ALB/NLB** (Tích vô đó).
   - Chọn trúng Load Balancer Internal huyền thoại `nutritrack-internal-alb`.
   - Phía dưới cắm thẻ VPC Link bằng cách chọn cái Link vừa đỏ đèn.
   - Listener: HTTP 80.
3. Tên đỉnh phong của bạn API Name: `NutriTrack-Gateway`. Bấm Next.
4. Chỗ Configure routes: Đổi Method cái Dropdown thành **ANY**. Path để y xì `/{proxy+}`. Integration target ngó ngó châm chước qua `nutritrack-internal-alb`. Bấm Next > Bấm Create.

### 5C. Ép Rate Limit
1. Trong menu con của API vừa sinh ra > Chuyển qua tab chữ **Throttling**.
2. Nhìn giữa màn hình tick nhẹ ô **Default route throttling** nằm trên cùng dòng `$default` stage (Bấm Edit trước).
3. *Rate limit*: Thả nhẹ con số `50` (Tương đương cho phép max nhồi 50 lượt gọi cẩu huyết mỗi giây băm vào). *Burst*: `100`. Bấm **Save**.

---
🎊 **THÀNH CÔNG RỒI ĐÓ BẠN! LẤY URL RA XÀI THÔI!** 
Vào mục **Stages** trong API Gateway, thấy cái Invoke URL (Có dạng `https://xxx.execute-api.region.amazonaws.com`). Lấy dán vào Browser hoặc Postman thay cho IP Public cũ là bạn đã có 1 hệ thống Serverless xưng vương xưng bá rồi!  Vẫn gọi được USDA, Bedrock phà phà, tàng hình trước giang hồ và không sợ F5 sập nguồn!
