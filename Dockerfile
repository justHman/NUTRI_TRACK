# Sử dụng Python 3.10 slim để giảm dung lượng image
FROM python:3.10-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết (nếu có)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements và cài đặt python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn vào container
COPY . .

# Tạo thư mục data/results và logs nếu chưa có
RUN mkdir -p data/results logs

# Mở cổng 8000 (cần khớp với cấu hình trong api.py)
EXPOSE 8000

# Biến môi trường
ENV PYTHONUNBUFFERED=1

# Lệnh khởi chạy ứng dụng
# Lưu ý: file api.py nằm trong folder templates/
CMD ["uvicorn", "templates.api:app", "--host", "0.0.0.0", "--port", "8000"]
