# Hướng Dẫn Khởi Tạo & Gắn AWS S3 Cache Bucket Cho Dự Án

Trong dự án NutriTrack, Amazon S3 được dùng để lưu trữ lại toàn bộ các Response tìm kiếm từ USDA để tiết kiệm số lượt gọi API (Caching). Khi deploy lên ECS, chúng ta không thể dùng ổ đĩa cứng vật lý (Disk Cache) như dưới máy tính local được vì các Container sẽ bị hủy đi bật lại liên tục (văng mất dữ liệu bộ nhớ đệm).

Tài liệu này sẽ hướng dẫn bạn tạo 1 chiếc Bucket trên AWS S3 và khai báo nó vào file `.env`.

---

## 🪣 Bước 1: Tạo Bộ Nhớ S3 trên AWS Console

1. Đăng nhập vào tài khoản AWS của bạn, trên thanh tìm kiếm gõ chữ **S3**. Click vào kết quả đầu tiên **S3 (Scalable Storage in the Cloud)**.
2. Tại màn hình chính của S3, bấm nút cam **Create bucket**.
3. **General configuration**:
   * **Bucket name**: Đặt tên cho thùng chứa của bạn. Tên thùng trên AWS phải là **độc nhất vô nhị trên toàn thế giới** (không được trùng với bất kì ai khác).
     * Mẹo: Đặt kèm với tên mã sinh viên hoặc tên dự án, như `nutritrack-cache-storage-2026`, hoặc `nutritrack-[tên_bạn]-cache`.
   * **AWS Region**: Chọn khu vực gần nhất hoặc cùng khu vực với Bedrock của bạn (Thường là `us-east-1` - US N. Virginia). Chọn đúng khu vực sẽ giúp tốc độ truyền tải cực kỳ nhanh.
4. **Object Ownership**: Chọn `ACLs disabled (recommended)` (Mặc định).
5. **Block Public Access settings for this bucket**: Check vào ô `Block all public access` (Mặc định) - Tuyệt đối không mở cái này ra vì đây là file cache bí mật của hệ thống. Nhờ có `ecsTaskRole`, ứng dụng của bạn không cần Public mà vẫn đọc/ghi được.
6. **Bucket Versioning**: Để `Disable`. Không cần lưu lịch sử các phiên bản sửa đổi file cache làm gì cho tốn tiền.
7. Cuộn thẳng xuống cuối cùng, click nút **Create bucket**.

---

## 💻 Bước 2: Cài đặt vào file `.env` chạy ở Local

Bây giờ bạn đã có 1 cái Bucket hoàn chỉnh (giả sử bạn vừa đặt tên là `nutritrack-cache-storage-2026`).

1. Mở file `d:/Project/Code/nutritrack-documentation/app/config/.env` bằng VSCode.
2. Xuống dòng dưới cùng, thêm một dòng khai báo tên Bucket như sau:

```env
# Lưu file Cache cho hệ thống USDA và Qwen
AWS_S3_CACHE_BUCKET=nutritrack-cache-storage-2026
```

> **Ghi chú**: Ở dưới máy cá nhân của bạn hiện tại, file `.env` này kết hợp với chứng chỉ cấp trong lúc bạn lệnh `aws configure` lúc trước là đủ bộ giúp Python của bạn tương tác trơn tru với Bucket. Tự động khi chạy code, file cache sẽ được "push/pull" từ thư mục `USDA.py` (nếu bạn đã cấu hình codebase chuyển sang xài module `boto3 s3`).

---

## ☁️ Bước 3: Đem cấu hình này lên AWS ECS

Khi deploy dự án lên ECS, Fargate Container không đọc được file `.env` ở máy bạn, nên bạn phải chuyển "biến môi trường" ấy khai báo lại trên Cloud.

1. Bật bảng cấu hình tạo/cập nhật **Task Definition** bên trong ECS.
2. Ở ô **Environment Variables** (Mục Container), thêm dòng mã sau:
   * **Key**: `AWS_S3_CACHE_BUCKET`
   * Type: Giữ nguyên mặc định là `Value` (Vì thông tin tên Bucket không phải là khoá tối mật, không cần phải cho vào két sắt Secrets Manager tốn thời gian).
   * **Value**: Nhập lại y chang tên Bucket bạn gõ ở Bước 2 (`nutritrack-cache-storage-2026`).
3. Xác nhận cập nhật phiên bản Task (*Create/Update*) mới.

Vậy là ứng dụng của bạn đã biết chính xác "kho đệm" của nó trải dài trên khắp nước Mỹ của AWS S3 nằm ở toạ độ nào rồi đó!