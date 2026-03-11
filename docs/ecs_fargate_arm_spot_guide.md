# Hướng dẫn Deploy NutriTrack API: ECS Fargate ARM + Fargate Spot

Tài liệu này hướng dẫn cách tối ưu chi phí (tiết kiệm đến 70%) bằng cách chạy backend API của **NutriTrack** trên kiến trúc **ARM (Graviton)** kết hợp với chế độ **Fargate Spot**.

---

## 🏗️ 1. Build Docker Image cho kiến trúc ARM

Vì hầu hết máy tính cá nhân chạy chip Intel/AMD (x86_64) nhưng server chúng ta sẽ chạy chip ARM (ARM64), bạn cần dùng `docker buildx` để build đúng định dạng.

Mở Terminal tại thư mục `app`:

```bash
# 1. Khởi tạo buildx (chỉ cần làm 1 lần duy nhất)
docker buildx create --use

# 2. Build image cho platform ARM64
# Thay <your-docker-hub-username> bằng tên tài khoản của bạn
docker buildx build --platform linux/arm64 -t <your-docker-hub-username>/nutritrack-api:arm --push .
```

> [!TIP]
> Chip ARM (AWS Graviton) không chỉ rẻ hơn mà còn xử lý các tác vụ Python (như FastAPI và xử lý ảnh Pillow) nhanh hơn và mát hơn so với chip x86 truyền thống.

---

## 🚀 2. Thiết lập ECS Task Definition (Cấu hình ARM)

1. Truy cập **ECS Console** > **Task definitions** > **Create new task definition**.
2. **Infrastructure requirements**:
   - Operating system/Architecture: Chọn **Linux/ARM64** (Bắt buộc).
   - CPU: **1 vCPU**
   - Memory: **2 GB** (Đã đủ cho NutriTrack chạy mượt).
3. **Task Role & Execution Role**:
   - Giữ nguyên như hướng dẫn cơ bản (Cần quyền Bedrock và S3 cho Task Role).
4. **Container details**:
   - Image URI: Dùng image Docker Hub có tag `:arm` (VD: `<your-docker-hub-username>/nutritrack-api:arm`).
   - Port: **8000**.
5. Nhấn **Create**.

---

## 💸 3. Chạy Service với Chế độ Fargate Spot

Đây là bước quan trọng nhất để tiết kiệm tiền. Fargate Spot sử dụng hạ tầng dư thừa của AWS với giá cực rẻ.

1. Vào Cluster của bạn > tab **Services** > Nhấn **Create**.
2. **Compute configuration (Environment)**:
   - Chọn **Capacity provider strategy**.
   - Bấm **Add capacity provider**.
   - Chọn **FARGATE_SPOT**.
   - Thiết lập **Weight**: `1` (Nghĩa là 100% các task sẽ chạy trên chế độ Spot).
3. **Deployment configuration**:
   - Chọn Task Definition phiên bản ARM bạn vừa tạo.
   - Service name: `nutritrack-api-spot`.
   - Desired tasks: `1`.
4. **Networking**:
   - Chọn VPC, Subnets và Security Group (mở port 8000) như bình thường.
   - **Auto-assign public IP**: BẬT.
5. Nhấn **Create**.

---

## ⚠️ Lưu ý về Fargate Spot

- **Tính ổn định**: Vì là "hàng thanh lý", AWS có quyền thu hồi Task Spot của bạn nếu họ cần dung lượng cho khách hàng trả phí cao. Tuy nhiên, ECS sẽ tự động khởi động một Task khác để thay thế ngay lập tức.
- **Phù hợp cho**: Môi trường Dev, Test, Demo đồ án hoặc các API không yêu cầu độ ổn định 100.00% (High Availability). Với dự án cá nhân, đây là lựa chọn **Số 1** để tránh "cháy túi".

---

## 📊 So sánh giá (Ước tính mỗi tháng)

| Loại Fargate | vCPU/Giờ | RAM/Giờ | Tổng cộng (1 tháng - 24/7) |
| :--- | :--- | :--- | :--- |
| **Standard x86** | $0.04048 | $0.004445 | ~$34 USD |
| **ARM (Graviton)** | $0.03238 | $0.003556 | ~$27 USD |
| **ARM + Spot** | **$0.01295** | **$0.001422** | **~$10 USD** (Tiết kiệm >70%) |

> [!IMPORTANT]
> Dù dùng Spot, hãy nhớ chỉnh **Desired tasks về 0** khi đi ngủ để tiết kiệm triệt để nhất!
