# Hướng Dẫn Sử Dụng AWS Secrets Manager Cho NutriTrack API

Tài liệu này hướng dẫn cách bảo mật `USDA_API_KEY` (và các API Keys quan trọng khác) bằng cách sử dụng **AWS Secrets Manager**, thay vì gõ trực tiếp plaintext vào mục Environment Variables của ECS Task Definition. Đây là tiêu chuẩn bảo mật chuyên nghiệp (Best Practice) trong doanh nghiệp.

---

## 🔐 1. Tạo Secret trong AWS Secrets Manager

Mục tiêu: Đưa các chuỗi API Key vào một "két sắt" được mã hóa trên AWS, và cấp cho "két sắt" đó một cái tên nhận diện (ARN - Amazon Resource Name).

### Bước 1: Khai báo các khóa (Key-value pairs) & Mã hóa (Encryption key)
1. Truy cập **AWS Web Console** -> Tìm kiếm dịch vụ **Secrets Manager**.
2. Bấm vào nút **Store a new secret** (Tạo secret mới).
3. Ở ô **Secret type**, chọn: **Other type of secret**.
4. Trong ô **Key/value pairs**, hãy định nghĩa các tên biến và giá trị của API bên thứ ba (Lưu ý: Không điền các Access Key của AWS vào đây, phần này hãy để cho IAM Roles xử lý).
   * Key: `USDA_API_KEY`
   * Value: `<Điền mã token của USDA vào đây>`
   (Bạn có thể bấm `Add row` để thêm nhiều chìa khóa bên thứ 3 khác nếu có).
5. **(Lưu ý về mục Encryption key)**: Ở dưới cùng của Bước này, bạn sẽ thấy mục **Encryption key**. Đây là công nghệ mã hóa (AWS KMS) được dùng để khóa két sắt của bạn lại:
   * Hãy **giữ nguyên mặc định là `aws/secretsmanager`**. Đây là khóa mã hóa do chính AWS quản lý giùm bạn, hoàn toàn **MIỄN PHÍ** và dễ sử dụng nhất.
   * Chức năng *Add new key (Customer managed key)* chỉ dành cho các tập đoàn lớn cần yêu cầu tạo khóa mã hóa riêng biệt, phức tạp và tính phí $1/tháng cho mỗi chìa khóa riêng này. Ta không cần dùng nó.
6. Nhấn **Next**.

### Bước 2: Đặt tên cho Két sắt
1. Sang trang tiếp theo, mục **Secret name**: Nhập tên cho két sắt. Ví dụ: `nutritrack/prod/api-keys`.
2. (Tuỳ chọn) Description: Ghi chú ngắn gọn "Keys cho ứng dụng NutriTrack API chạy trên ECS".
3. Nhấn **Next**.

### Bước 3: Hoàn tất
1. Bạn không cần cấu hình Auto-rotation (đổi khóa tự động) lúc này. Kéo xuống dưới cùng và nhấn **Next**.
2. Kiểm tra lại thông tin và nhấn **Store**.
3. Sau khi văng ra màn hình danh sách, nhấn vào tên Secret `nutritrack/prod/api-keys` vừa tạo. Hãy copy lại dải mã ở mục **Secret ARN** (nó trông giống như `arn:aws:secretsmanager:us-east-1:123456789012:secret:nutritrack/prod/api-keys-xxxxxx`). Bạn sẽ cần chuỗi ARN này cho ECS.

---

## 🛡️ 2. Cấp quyền cho ECS Fargate mở được Két sắt (Task Execution Role)

ECS muốn kéo được Biến môi trường lên thì nó cần có quyền `secretsmanager:GetSecretValue` từ cái két sắt bạn vừa tạo. 

1. Truy cập vào **IAM** -> **Roles**.
2. Tìm kiếm Role đang gán cho ECS của bạn, thường mặc định gọi là `ecsTaskExecutionRole`. (Lưu ý: Đây là Execution Role dùng để kéo hình ảnh và biến hệ thống lúc khởi tạo - khác với Task Role là quyền của code Python lúc Runtime).
3. Nhấn vào tên Role đó -> **Add permissions** -> **Create inline policy**.
4. Chuyển sang Tab **JSON**, dán đoạn nội dung sau vào (Nhớ sửa ô "Resource" thay bằng mã ARN bạn vừa Copy ở trên):
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
                   "arn:aws:secretsmanager:<region>:<account-id>:secret:nutritrack/prod/api-keys-xxxxxx"
               ]
           }
       ]
   }
   ```
5. Nhấn **Review policy**, đặt tên là `NutriTrackSecretsPolicy` và bấm **Create policy**.
> Bây giờ ECS đã có quyền thò tay vào két để lấy biến ra cho bạn.

---

## ⚙️ 3. Map Secrets Manager vào Task Definition trên ECS

Thay vì điền biến theo kiểu thông thường (Value), giờ chúng ta sẽ trỏ biến đó sang ValueFrom của Secrets Manager.

1. Bật giao diện tạo (hoặc cập nhật) **Task Definition** của ECS như hướng dẫn ECS thông thường.
2. Tại phần **Container**: Cuộn xuống mục **Environment**.
3. Tìm đến mục con **Environment variables**. Tại đây có 2 lựa chọn loại biến, thay vì sử dụng loại `Value` truyền thống, bạn hãy chuyển sang sử dụng phần **`ValueFrom`** (Trỏ từ ARN hệ thống). Trình đơn ở console cũ có thể gọi tên chức năng này là "Environment overrides bằng ARN" hoặc "Secrets".
   *(Trong giao diện Task Definiton mới nhất của ECS, phần này có tên là Environment -> Environment variables, bấm nút "Add environment variable", chọn tùy chọn `ValueFrom` ở ô Type thay vì chọn `Value`).*

4. Cấu hình dòng sau:
   * **Key** (Tên biến đưa vào code python): `USDA_API_KEY`
   * **ValueFrom** (Nguồn két sắt): Điền **đầy đủ mã ARN Secret** nối thêm `:<Tên Key bên trong két sắt>::`
   > **Cú pháp ghép chuỗi ValueFrom đòi hỏi cực kỳ chú ý:** 
   > `[Secret_ARN]:[Tên_Key_Bên_Trong_Secret]::`

   *Ví dụ, nếu Secret ARN của bạn là `arn:aws:secretsmanager:us-east-1:1111:secret:xxx` và cái Key lúc nãy lập ở Bước 1 tên là `USDA_API_KEY`, bạn phải điền vào ô ValueFrom chính xác dòng sau đây:*
   ```text
   arn:aws:secretsmanager:us-east-1:1111:secret:xxx:USDA_API_KEY::
   ```

5. Tiến hành lưu bảng Task Definition (nhấn **Create**).

---

## 🎉 4. Kết Quả

Bạn chạy AWS ECS Services với Revision mới nhất của Task Definition này.
Lúc khởi tạo, hệ thống ECS Fargate sẽ:
1. Mang cái `ecsTaskExecutionRole` chạy sang cửa tủ AWS Secrets Manager.
2. Xuất trình thẻ (IAM) phù hợp và mở cửa tủ.
3. Kéo dòng text `USDA_API_KEY` về.
4. Nó tự động biến dòng chữ đó thành một Environment Variable hệ thống tiêu chuẩn (`export USDA_API_KEY="..."`).
5. Cuối cùng mới bật code Python (Uvicorn / FastAPI) lên.

Khi dòng code `os.getenv("USDA_API_KEY")` trong chương trình NutriTrack của bạn tháo chuỗi ra đọc, nó sẽ thu được được mã token bảo mật tuyệt đối mà **không một dòng mã độc (hay console log plaintext nào) có thể dò quét (trace) ra được nguồn cung cấp!**

*(Việc giấu đi Secret Key của Cloud giúp hồ sơ kiến trúc Backend của bạn vượt qua được các vòng Security Audit cực kỳ dễ dàng khi đem nộp bài hoặc phỏng vấn doanh nghiệp System/DevOps).*
