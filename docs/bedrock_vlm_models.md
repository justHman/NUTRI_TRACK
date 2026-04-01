# 🔍 VLM (Vision Language Model) trên AWS Bedrock — ap-southeast-1 & ap-southeast-2

> **Nguồn dữ liệu**: [AWS Bedrock Regional Availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html) · [AWS Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
> **Cập nhật**: Tháng 3/2026 · Giá tính theo **Standard On-Demand** · **USD / 1M tokens**

---

## 📋 Tổng quan nhanh

VLM (Vision Language Model) = model có thể nhận **hình ảnh** làm input, hỗ trợ các tác vụ **OCR**, **suy luận hình ảnh**, **mô tả nội dung**, **phân tích biểu đồ**.

> [!IMPORTANT]
> **`ap-southeast-1` (Singapore)** hiện có **rất ít model VLM In-Region**. Phần lớn model chỉ có thể truy cập qua **Global Cross-Region Inference** (data có thể xử lý ở bất kỳ region nào).
> **`ap-southeast-2` (Sydney)** có **nhiều model VLM In-Region hơn đáng kể** — đây là lựa chọn tốt hơn cho APAC.

---

## 🗺️ Bảng VLM theo Region — Sắp xếp giá tăng dần (Input Token)

### 🇸🇬 ap-southeast-1 (Singapore)

| # | Model | Provider | Vision | OCR | Suy luận | Truy cập | Input $/1M | Output $/1M | Ghi chú |
|:-:|:------|:---------|:------:|:---:|:--------:|:--------:|:----------:|:-----------:|:--------|
| 1 | **Nova 2 Lite** | Amazon | ✅ | ✅ | ✅ | 🌐 Global | ~$0.06 | ~$0.18 | Mới, context 1M token, siêu rẻ |
| 2 | **Claude 3 Haiku** | Anthropic | ✅ | ✅ | ✅ | 🟢 In-Region | $0.25 | $1.25 | Nhanh, rẻ, tốt cho OCR cơ bản |
| 3 | **Claude 3.5 Sonnet** | Anthropic | ✅ | ✅ | ✅ | 🟢 In-Region | $3.00 | $15.00 | Vision mạnh, OCR chính xác cao |
| 4 | **Claude Sonnet 4.6** | Anthropic | ✅ | ✅ | ✅ | 🌐 Global | $3.00 | $15.00 | Thế hệ mới nhất, suy luận mạnh |
| 5 | **Claude Haiku 4.5** | Anthropic | ✅ | ✅ | ✅ | 🌐 Global | $0.80 | $4.00 | Cân bằng giá/hiệu năng |
| 6 | **Claude Sonnet 4.5** | Anthropic | ✅ | ✅ | ✅ | 🌐 Global | $3.00 | $15.00 | Extended thinking, hybrid reasoning |
| 7 | **Claude Opus 4.5** | Anthropic | ✅ | ✅ | ✅ | 🌐 Global | $15.00 | $75.00 | Mạnh nhất Anthropic, đắt nhất |
| 8 | **Claude Opus 4.6** | Anthropic | ✅ | ✅ | ✅ | 🌐 Global | $15.00 | $75.00 | Top-tier reasoning |

> [!NOTE]
> 🌐 **Global** = Request **có thể bị route sang region khác** (VD: us-east-1). Giá tính theo giá source region.
> 🟢 **In-Region** = Request xử lý **hoàn toàn trong Singapore**, data không rời region.

---

### 🇦🇺 ap-southeast-2 (Sydney) — ⭐ Nhiều model hơn, giá tốt hơn

| # | Model | Provider | Vision | OCR | Suy luận | Truy cập | Input $/1M | Output $/1M | Ghi chú |
|:-:|:------|:---------|:------:|:---:|:--------:|:--------:|:----------:|:-----------:|:--------|
| 1 | **Gemma 3 4B IT** | Google | ✅ | ⚠️ | ⚠️ | 🟢 In-Region | $0.0412 | $0.0824 | Siêu rẻ, VLM nhẹ 4B params |
| 2 | **gpt-oss-20b** | OpenAI | ✅ | ✅ | ✅ | 🟢 In-Region | $0.0721 | $0.3090 | Open-source, chi phí cực thấp |
| 3 | **Gemma 3 12B IT** | Google | ✅ | ✅ | ✅ | 🟢 In-Region | $0.0927 | $0.2987 | VLM 12B, cân bằng chi phí |
| 4 | **gpt-oss-120b** | OpenAI | ✅ | ✅ | ✅ | 🟢 In-Region | $0.1545 | $0.6180 | Open-source, reasoning tốt |
| 5 | **Qwen3 Next 80B A3B** | Qwen | ✅ | ✅ | ✅ | 🟢 In-Region | $0.1545 | $1.2360 | MoE hiệu quả, đa ngôn ngữ |
| 6 | **NVIDIA Nemotron Nano 2 VL** | NVIDIA | ✅ | ✅ | ✅ | 🟢 In-Region | $0.2060 | $0.6180 | VL model chuyên dụng |
| 7 | **Gemma 3 27B PT** | Google | ✅ | ✅ | ✅ | 🟢 In-Region | $0.2369 | $0.3914 | VLM lớn nhất Gemma, OCR khá |
| 8 | **Claude 3 Haiku** | Anthropic | ✅ | ✅ | ✅ | 🟢 In-Region | $0.25 | $1.25 | OCR nhanh, giá rẻ |
| 9 | **Qwen3 VL 235B A22B** | Qwen | ✅ | ✅ | ✅ | 🟢 In-Region | $0.5459 | $2.7398 | **VLM mạnh nhất Qwen**, OCR xuất sắc |
| 10 | **Nova Lite** | Amazon | ✅ | ✅ | ✅ | 🟢 In-Region | $0.06 | $0.18 | Giá rẻ, multimodal, tốt cho OCR |
| 11 | **Nova Pro** | Amazon | ✅ | ✅ | ✅ | 🟢 In-Region | $0.80 | $3.20 | Cân bằng, accuracy cao hơn Lite |
| 12 | **Claude Haiku 4.5** | Anthropic | ✅ | ✅ | ✅ | 🟠 Geo (AU) | $0.80 | $4.00 | Nhanh, rẻ, vision tốt |
| 13 | **Claude 3 Sonnet** | Anthropic | ✅ | ✅ | ✅ | 🟢 In-Region | $3.00 | $15.00 | Vision mạnh, reasoning tốt |
| 14 | **Claude 3.5 Sonnet v2** | Anthropic | ✅ | ✅ | ✅ | 🟢 In-Region | $3.00 | $15.00 | Improved vision |
| 15 | **Claude Sonnet 4.6** | Anthropic | ✅ | ✅ | ✅ | 🟠 Geo (AU) | $3.00 | $15.00 | Thế hệ mới nhất |
| 16 | **Claude Sonnet 4.5** | Anthropic | ✅ | ✅ | ✅ | 🟠 Geo (AU) | $3.00 | $15.00 | Extended thinking |
| 17 | **Claude Opus 4.5** | Anthropic | ✅ | ✅ | ✅ | 🌐 Global | $15.00 | $75.00 | Top-tier |
| 18 | **Claude Opus 4.6** | Anthropic | ✅ | ✅ | ✅ | 🟠 Geo (AU) | $15.00 | $75.00 | Mạnh nhất Anthropic |

> [!TIP]
> 🟠 **Geo (AU)** = Data chỉ route trong geography APAC (AU), không ra ngoài khu vực Châu Á-Thái Bình Dương.

---

## 🏆 So sánh nhanh: Top VLM cho OCR & Suy luận

### 💰 Rẻ nhất cho OCR (Trích xuất text từ hình ảnh)

| Rank | Model | Region | Input $/1M | Output $/1M | Tổng chi phí OCR 1000 ảnh* |
|:----:|:------|:------:|:----------:|:-----------:|:--------------------------:|
| 🥇 | Gemma 3 4B IT | Sydney 🟢 | $0.0412 | $0.0824 | ~$0.04 |
| 🥈 | Nova Lite | Sydney 🟢 | $0.06 | $0.18 | ~$0.08 |
| 🥉 | gpt-oss-20b | Sydney 🟢 | $0.0721 | $0.3090 | ~$0.12 |
| 4 | Gemma 3 12B IT | Sydney 🟢 | $0.0927 | $0.2987 | ~$0.12 |
| 5 | NVIDIA Nemotron Nano 2 VL | Sydney 🟢 | $0.2060 | $0.6180 | ~$0.30 |

*Ước tính: mỗi ảnh ~300 input tokens + ~200 output tokens

### 🧠 Tốt nhất cho Suy luận cao cấp (Phân tích phức tạp, biểu đồ, reasoning)

| Rank | Model | Region | Input $/1M | Output $/1M | Chất lượng |
|:----:|:------|:------:|:----------:|:-----------:|:----------:|
| 🥇 | Claude Sonnet 4.6 | Sydney 🟠 Geo | $3.00 | $15.00 | ⭐⭐⭐⭐⭐ |
| 🥈 | Qwen3 VL 235B A22B | Sydney 🟢 | $0.5459 | $2.7398 | ⭐⭐⭐⭐½ |
| 🥉 | Claude Opus 4.6 | Sydney 🟠 Geo | $15.00 | $75.00 | ⭐⭐⭐⭐⭐+ |
| 4 | Nova Pro | Sydney 🟢 | $0.80 | $3.20 | ⭐⭐⭐⭐ |
| 5 | Claude 3.5 Sonnet v2 | Sydney 🟢 | $3.00 | $15.00 | ⭐⭐⭐⭐½ |

### 🎯 Best Value — Cân bằng giá/chất lượng cho dự án thực tế

| Use Case | Model đề xuất | Region | Input $/1M | Output $/1M |
|:---------|:-------------|:------:|:----------:|:-----------:|
| OCR đơn giản (hóa đơn, receipt) | **Nova Lite** | Sydney 🟢 | $0.06 | $0.18 |
| OCR + suy luận nhẹ | **Qwen3 Next 80B A3B** | Sydney 🟢 | $0.1545 | $1.2360 |
| OCR chính xác cao + multi-language | **Claude 3 Haiku** | Singapore 🟢 / Sydney 🟢 | $0.25 | $1.25 |
| Phân tích biểu đồ/tài liệu phức tạp | **Claude Sonnet 4.6** | Sydney 🟠 | $3.00 | $15.00 |
| Max accuracy, no cost concern | **Claude Opus 4.6** | Sydney 🟠 | $15.00 | $75.00 |

---

## 📊 Bảng chi tiết tất cả VLM — Sắp xếp theo giá input tăng dần

### Toàn bộ model VLM available trong ap-southeast-1 + ap-southeast-2

| Model | Provider | Input $/1M | Output $/1M | ap-se-1 | ap-se-2 | Vision | OCR |
|:------|:---------|:----------:|:-----------:|:-------:|:-------:|:------:|:---:|
| Gemma 3 4B IT | Google | $0.0412 | $0.0824 | ❌ | 🟢 | ✅ | ⚠️ basic |
| Nova Lite | Amazon | $0.06 | $0.18 | ❌ | 🟢 | ✅ | ✅ |
| Nova 2 Lite | Amazon | ~$0.06 | ~$0.18 | 🌐 | 🌐 | ✅ | ✅ |
| gpt-oss-20b | OpenAI | $0.0721 | $0.3090 | ❌ | 🟢 | ✅ | ✅ |
| Gemma 3 12B IT | Google | $0.0927 | $0.2987 | ❌ | 🟢 | ✅ | ✅ |
| gpt-oss-120b | OpenAI | $0.1545 | $0.6180 | ❌ | 🟢 | ✅ | ✅ |
| Qwen3 Next 80B A3B | Qwen | $0.1545 | $1.2360 | ❌ | 🟢 | ✅ | ✅ |
| NVIDIA Nemotron Nano 2 VL | NVIDIA | $0.2060 | $0.6180 | ❌ | 🟢 | ✅ | ✅ |
| Gemma 3 27B PT | Google | $0.2369 | $0.3914 | ❌ | 🟢 | ✅ | ✅ |
| Claude 3 Haiku | Anthropic | $0.25 | $1.25 | 🟢 | 🟢 | ✅ | ✅ |
| Qwen3 VL 235B A22B | Qwen | $0.5459 | $2.7398 | ❌ | 🟢 | ✅ | ✅ |
| Claude Haiku 4.5 | Anthropic | $0.80 | $4.00 | 🌐 | 🟠 Geo | ✅ | ✅ |
| Nova Pro | Amazon | $0.80 | $3.20 | ❌ | 🟢 | ✅ | ✅ |
| Claude 3 Sonnet | Anthropic | $3.00 | $15.00 | ❌ | 🟢 | ✅ | ✅ |
| Claude 3.5 Sonnet | Anthropic | $3.00 | $15.00 | 🟢 | ❌ | ✅ | ✅ |
| Claude 3.5 Sonnet v2 | Anthropic | $3.00 | $15.00 | ❌ | 🟢 | ✅ | ✅ |
| Claude Sonnet 4.5 | Anthropic | $3.00 | $15.00 | 🌐 | 🟠 Geo | ✅ | ✅ |
| Claude Sonnet 4.6 | Anthropic | $3.00 | $15.00 | 🌐 | 🟠 Geo | ✅ | ✅ |
| Claude Opus 4.5 | Anthropic | $15.00 | $75.00 | 🌐 | 🌐 | ✅ | ✅ |
| Claude Opus 4.6 | Anthropic | $15.00 | $75.00 | 🌐 | 🟠 Geo | ✅ | ✅ |

---

## 🔑 Giải thích ký hiệu

| Icon | Ý nghĩa |
|:----:|:--------|
| 🟢 | **In-Region**: Data xử lý hoàn toàn trong region, không rời đi |
| 🟠 Geo | **Geographic Cross-Region**: Route trong cùng geography (AU/APAC), data không rời khu vực |
| 🌐 | **Global Cross-Region**: Data có thể route sang bất kỳ region nào trên thế giới |
| ❌ | Không available tại region này |
| ✅ | Hỗ trợ đầy đủ |
| ⚠️ | Hỗ trợ hạn chế / chất lượng trung bình |

---

## 💡 Khuyến nghị cho NutriTrack

Dựa trên use case OCR nhãn sản phẩm dinh dưỡng + phân tích thành phần:

> [!TIP]
> ### Phương án tối ưu chi phí — Sydney (`ap-southeast-2`)
> 
> **Tier 1 — OCR cơ bản**: `Nova Lite` ($0.06 input) → Trích xuất text từ nhãn
> **Tier 2 — OCR + suy luận**: `Claude 3 Haiku` ($0.25 input) → Phân tích chi tiết  
> **Tier 3 — Complex reasoning**: `Claude Sonnet 4.6` via Geo ($3.00 input) → Phân tích phức tạp
> 
> Ước tính chi phí: **~$0.50–2.00/ngày** cho 100–500 requests hỗn hợp

> [!WARNING]
> ### Lưu ý khi dùng Global/Geo Cross-Region
> - Data **có thể xử lý ở region khác** → ảnh hưởng latency (+50–200ms)
> - Nếu có yêu cầu **data residency** nghiêm ngặt → chỉ dùng model 🟢 In-Region
> - Giá Global/Geo = giá source region (không phụ thu)

---

*Nguồn: [AWS Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/) · [Regional Availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html) · Giá có thể thay đổi, luôn kiểm tra trang chính thức.*
