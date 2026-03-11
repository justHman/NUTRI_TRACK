# Hướng dẫn Deploy NutriTrack API: AWS App Runner

**AWS App Runner** là cách nhanh nhất và đơn giản nhất để deploy NutriTrack API. Bạn không cần biết về VPC, Subnet hay Load Balancer; AWS sẽ tự động hóa toàn bộ việc quản lý hạ tầng và bảo mật HTTPS cho bạn.

---

## 🌟 Tại sao chọn App Runner cho NutriTrack?

- **Hỗ trợ HTTPS sẵn**: Bạn nhận được một URL chính chủ `https://...` cực kỳ chuyên nghiệp để gắn vào Mobile App.
- **Auto-Scaling**: Tự động tăng số lượng instance khi có nhiều user phân tích ảnh cùng lúc.
- **Giá rẻ khi nhàn rỗi**: Khi không có traffic, CPU sẽ được hạ về 0, bạn chỉ trả tiền duy trì RAM.

---

## 🚀 Các bước triển khai

### Bước 1: Chuẩn bị Source (GitHub)
Vì App Runner không hỗ trợ trực tiếp Docker Hub, cách tốt nhất là kết nối thẳng với **GitHub**. Hệ thống sẽ tự động build từ `Dockerfile` của bạn mỗi khi có code mới.

### Bước 2: Khởi tạo App Runner Service
1. Truy cập **AWS Console** > **AWS App Runner**.
2. Nhấn **Create service**.
3. **Source and deployment**:
   - Repository type: Chọn **Source code repository** (Đây là cách dễ nhất).
   - Kết nối với tài khoản GitHub của bạn và chọn Repository `nutritrack`.
   - **Deployment settings**: Chọn **Automatic** (Mỗi lần `git push` là server tự cập nhật).
4. **Build settings**:
   - Configuration file: Chọn **Use a configuration file** (nếu có file `apprunner.yaml`) hoặc **Configure all settings here**.
   - Runtime: Chọn **Python 3**.
   - Build command: `pip install -r requirements.txt`.
   - Start command: `uvicorn templates.api:app --host 0.0.0.0 --port 8000`.
   - Port: **8000**.

### Bước 3: Cấu hình Service (Service Configuration)
1. **Service name**: `nutritrack-app-runner`.
2. **Virtual CPU & Memory**: Chọn **1 vCPU & 2 GB RAM**.
3. **Network**: Chọn **Public access** (Mặc định).
4. **Environment variables**: **CỰC KỲ QUAN TRỌNG:** Không bao giờ đưa API Key vào file `apprunner.yaml` vì nó sẽ bị lộ trên GitHub. Hãy cuộn xuống dưới cùng của trang này sẽ thấy mục **Environment variables**. Nhấn **Add environment variable** để thêm từng cái một:
   - `USDA_API_KEY`: [Dán Key vào đây]
   - `AWS_S3_CACHE_BUCKET`: [Tên bucket]
   - `AWS_ACCESS_KEY_ID`: [Access Key]
   - `AWS_SECRET_ACCESS_KEY`: [Secret Key]
   *(Lưu ý: AWS sẽ mã hóa các giá trị này, chúng không bao giờ hiển thị ra ngoài sau khi bạn nhấn lưu).*
5. **Port**: Nhập **8000** (Cổng của FastAPI).

### Bước 4: Tạo & Cấp quyền Instance Role (Bedrock & S3)
Đây là bước "sống còn" để Code Python có thể gọi AI. Bạn cần tạo một cái "thẻ bài" (Role) cho server mượn dùng.

#### A. Tạo Role trên IAM Console (Làm trước khi Deploy):
Nếu bạn không tìm thấy "App Runner" trong danh sách dịch vụ phổ biến của IAM, hãy làm theo cách "Custom" này, nó luôn hoạt động:
1. Truy cập **IAM Console** -> **Roles** -> **Create role**.
2. Select type of trusted entity: Chọn **Custom trust policy**.
3. **Dán đoạn mã JSON này vào**:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Service": "tasks.apprunner.amazonaws.com"
         },
         "Action": "sts:AssumeRole"
       }
     ]
   }
   ```
4. Nhấn **Next**.
5. **Add permissions**: Tìm và tick chọn 2 quyền:
   - `AmazonBedrockFullAccess`
   - `AmazonS3FullAccess`
6. Nhấn **Next**. Tên Role đặt là: `nutritrack-apprunner-instance-role`.
7. Nhấn **Create role**.

#### B. Gắn Role vào App Runner (Lúc Deploy):
1. Tại trang **Configure service** của App Runner, cuộn xuống mục **Security**.
2. Ở phần **Instance role**, nhấn nút **Refresh** 🔄 và chọn cái tên `nutritrack-apprunner-instance-role` bạn vừa tạo.
3. Nhấn **Next** và **Create & Deploy**.

---

## 📈 Quản lý và Tối ưu chi phí

### 1. Trạng thái "Khởi động ảo" (Provisioned Instances)
App Runner giữ cho ứng dụng của bạn luôn sẵn sàng. Khi không có request, bạn chỉ trả phí cho RAM (~$0.007/GB/giờ). 
- **Chi phí tối thiểu**: Khoảng **$5 - $10/tháng** nếu ứng dụng ít người dùng.

### 2. Tạm dừng Service (Pause)
Nếu bạn không dùng API trong vài ngày (ví dụ cuối tuần):
- Vào service App Runner -> **Actions** -> **Pause**.
- Khi này **chi phí sẽ bằng 0**. Khi nào cần dùng lại, nhấn **Resume** (mất khoảng 1-2 phút để bật lại).

---

## 🔗 Cách kết nối
Sau khi deploy thành công (Status: `Running`), App Runner sẽ cung cấp một **Default domain** dạng:
`https://abcd123.us-east-1.awsapprunner.com`

Bạn có thể test trực tiếp tại:
`https://abcd123.us-east-1.awsapprunner.com/docs` (FastAPI Swagger UI).
