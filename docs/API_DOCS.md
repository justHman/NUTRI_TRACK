# Hướng dẫn kết nối API NutriTrack từ máy tính/thiết bị khác

Mặc định, API đang được cấu hình chạy với `host="0.0.0.0"`. Điều này có nghĩa là server lắng nghe mọi kết nối không chỉ từ máy tính hiện tại (localhost) mà còn từ **bất kỳ thiết bị nào cùng mạng local (chung mạng Wi-Fi/LAN)**.

## 1. Kết nối qua mạng nội bộ (LAN / Chung Wi-Fi)

Để thiết bị khác (như máy tính của đội Frontend, hoặc điện thoại di động) gọi được API, bạn cần thay `localhost` bằng **địa chỉ IP nội bộ (Local IP)** của máy chủ đang chạy API.

### Bước 1: Lấy địa chỉ IP của máy chủ
Vì bạn đang dùng Windows, hãy mở Command Prompt `cmd` hoặc `PowerShell` và gõ:
```bash
ipconfig
```
Lưu ý dòng **IPv4 Address** (ví dụ: `192.168.1.5` hoặc `10.0.0.X`). Đây là địa chỉ IP của bạn.

### Bước 2: Gọi API bằng cURL từ máy khác
Người khác cùng mạng Wi-Fi chỉ cần dùng IP đó thay cho localhost. Ví dụ IP của bạn là `192.168.1.5`:

**Kiểm tra Health Check:**
```bash
curl -X GET http://192.168.1.5:8000/health
```

**Gửi ảnh để phân tích:**
```bash
curl -X POST http://192.168.1.5:8000/analyze \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/đường/dẫn/đến/file/anh-test.jpg"
```

### Bước 3: Gọi API từ Frontend JavaScript (React / Vue / Vanilla)
Đội frontend ở máy khác sẽ code gọi fetch như sau:

```javascript
const formData = new FormData();
// Lấy file ảnh từ thẻ input HTML
formData.append('file', document.querySelector('input[type="file"]').files[0]);

// Gọi tới IP của máy chủ
fetch('http://192.168.1.5:8000/analyze', {
    method: 'POST',
    body: formData
})
.then(response => response.json())
.then(data => console.log('Kết quả:', data))
.catch(error => console.error('Lỗi kết nối:', error));
```

---

## 2. Kết nối từ Internet (Bất kỳ đâu trên thế giới)

Nếu bạn muốn gửi link cho người khác dùng thử mà họ **không dùng chung mạng Wi-Fi với bạn**, bạn phải public API này ra ngoài Internet (Expose Localhost). Cách phổ biến nhất là dùng **Ngrok**.

### Bước 1: Cài đặt và chạy Ngrok
1. Tải [Ngrok](https://ngrok.com/download) và cài đặt.
2. Mở terminal, trỏ tới port 8000 (port của NutriTrack API):
```bash
ngrok http 8000
```

### Bước 2: Lấy URL public
Ngrok sẽ cung cấp một đường link dạng: `https://abcd-123-45.ngrok-free.app`.
Đường link này trỏ thẳng về `http://localhost:8000` trên máy bạn.

### Bước 3: Người khác gọi API bằng cURL qua Internet
Người khác mở terminal ở máy họ, ở bất cứ mạng nào và gọi:

```bash
curl -X POST https://abcd-123-45.ngrok-free.app/analyze \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/đường/dẫn/đến/file/anh-test.jpg"
```

---

## 3. Cấu trúc JSON Phản hồi chung (Response Payload)

Dù gọi bằng cách nào, server cũng sẽ trả về JSON như sau:

**Thành công (200 OK):**
```json
{
  "success": true,
  "data": [
    {
      "name": "Pho bo",
      "vi_name": "Phở bò",
      "ingredients": [
        {
           "name": "Beef",
           "weight_g": 100
        }
      ],
      "total_nutrition": {
        "calories": 400,
        "protein": 25,
        "fat": 15,
        "carbs": 45
      }
    }
  ],
  "message": "Analysis successful"
}
```

**Lỗi (400 / 500):**
```json
{
  "detail": "Invalid file format."
}
```

> **Lưu ý về CORS**: Token API và CORS đã được mở (`allow_origins=["*"]`) trong `api.py` nên bất kỳ Web Frontend nào gọi vào từ IP hoặc Link Ngrok đều sẽ không bị lỗi CORS chặn lại.
