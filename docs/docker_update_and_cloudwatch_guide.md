# Hướng Dẫn Cập Nhật Docker Image & Xem CloudWatch Logs

Tài liệu này bao gồm 2 phần: (1) Cách cập nhật (viết đè) code mới của bạn lên Docker Hub và (2) Làm rõ cơ chế Ghi/Xem Logs trên hệ thống AWS CloudWatch.

---

## 🐳 1. Cách Thay Đổi/Cập Nhật Docker Image trên Docker Hub

Khi bạn đã sửa code ở máy Local (như sửa file `pipeline.py` hay `ui.py`) và muốn đưa bản code mới đó lên thay thế cho bản cũ trong kho `imjusthman/nutritrack-api`, bạn thực hiện theo các bước sau:

### Bước 1: Build lại Image với code mới
Mở Terminal, trỏ dòng lệnh vào thư mục `app` (nơi có file `Dockerfile`). Việc bạn sử dụng lại đúng cái tên và tag (`:latest`) cũ sẽ giúp Docker ghi đè phiên bản mới lên phiên bản cũ ở máy tính của bạn.
```bash
docker build -t imjusthman/nutritrack-api:latest .
```

### Bước 2: Đăng nhập Docker (Nếu có yêu cầu)
Nếu bạn được yêu cầu xác thực, chạy lệnh:
```bash
docker login
```
*(Bạn nhập username `imjusthman` và mật khẩu tài khoản Docker Hub của bạn).*

### Bước 3: Đẩy (Push) bản cập nhật lên Docker Hub
Chạy lệnh bên dưới để đẩy Image mới lên. Kho mạng Docker Hub sẽ tự động đổi chỗ bản cũ bằng bản mới của bạn.
```bash
docker push imjusthman/nutritrack-api:latest
```

### Bước 4: Khởi động lại Server AWS ECS để nạp code mới
Mặc dù Image trên thư viện Docker Hub đã mới, nhưng cái máy chủ (Task Fargate) trên AWS vẫn đang ôm giữ giữ cục Image cũ từ 3 ngày trước. Bạn phải ra lệnh cho nó cập nhật:
1. Lên AWS Console -> **Elastic Container Service** -> Chọn Cluster của đồ án.
2. Dưới tab **Services**, tick vào dòng `nutritrack-api-service` và nhấn nút **Update** (Bên phải).
3. Đánh check vào ô **Force new deployment** (Bắt buộc triển khai bản mới lập tức).
4. Cuộn thẳng xuống cuối bấm **Update** một lần nữa. ECS sẽ tự động kéo lại bản `:latest` mới nhất về và thay thế con Server cũ!

---

## 📋 2. Quyền Ghi Log của ExecutionRole & Hướng dẫn xem CloudWatch

### Phân biệt: Ai Ghi Log và Ai Xem Log?
Nhiều bạn thường nhầm lẫn việc dùng Role để "xem log". Sự thật trong kiến trúc Đám Mây là:
*   **Người GHI Log (`ecsTaskExecutionRole`):** Đây là thẻ ủy quyền dành cho bản thân con máy tính ảo nền của Amazon (ECS Agent). Con máy tính ảo này dựa vào thẻ Role mới được phép hứng những chữ (lỗi, thông báo khởi động) từ code ứng dụng của bạn để viết và gửi (Push) dữ liệu đó dồn lên hệ thống trung tâm CloudWatch. Không có role này, log của bạn sẽ rơi ra khoảng không mất hút.
*   **Người XEM Log (Lập trình viên):** Là tài khoản AWS chính của BẠN. Bạn dùng tài khoản của bản thân để truy cập giao diện AWS và xem bằng mắt nội dung. Nên bạn không cần Role để xem.

### Cách Xem Log của Ứng dụng ECS:

**Cách 1: Xem nhanh ngay tại sảnh ECS (Tiện lợi nhất)**
1. Mở dịch vụ **Elastic Container Service (ECS)**.
2. Chọn Cluster -> tab **Services** -> Chọn Service `nutritrack-api-service`.
3. Có một tab ngang phía trên tên là **Logs**. Bấm vào đó!
Toàn bộ cửa sổ Terminal báo Request/Lỗi code Python FastAPI (giống y hệt cửa sổ đen dưới máy tính Local của bạn) sẽ hiện ra tuôn trào theoo thời gian thực ở đây.

**Cách 2: Điều tra kỹ qua CloudWatch (Xem log Lịch sử/Lỗi thời gian dài)**
Khi container của bạn bất ngờ chết giữa đêm, bạn không thể xem Logs qua màn hình trên được, phải mở băng đĩa lưu lại:
1. Mở dịch vụ **CloudWatch**.
2. Cột menu trái, mục **Logs**, chọn **Log groups**.
3. Bạn sẽ tìm thấy một rổ chứa mang tên của Task (ví dụ: `/ecs/nutritrack-api-task`). Nhấn vào nó.
4. Ở tab **Log streams**, hệ thống chia log ra thành từng luồng thời gian (mỗi luồng theo mốc tạo server). Bấm vào luồng gần nhất.
5. Ở giao diện này, bạn có hẳn một ô tìm kiếm. Có thể gõ chữ `ERROR`, `Exception` hoặc `Traceback` để lọc ra duy nhất các dòng bị lỗi để Fix Code kịp thời.
