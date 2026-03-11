# Hướng dẫn Cấu hình CI/CD cho NutriTrack API (GitHub ➡️ AWS)

Tài liệu này hướng dẫn 2 cách để khi bạn `git push` code lên GitHub, hệ thống sẽ tự động build và deploy bản mới nhất lên AWS.

---

## Cách 1: CI/CD Tự động với AWS App Runner (Dễ nhất)

AWS App Runner hỗ trợ kết nối trực tiếp với GitHub mà không cần viết script phức tạp.

### Bước A: Kết nối GitHub Source
1. Khi tạo service App Runner (hoặc vào phần **Source** của service đang chạy):
2. Chọn **Source code repository** -> Chọn **GitHub**.
3. Bấm **Add new** để kết nối tài khoản GitHub của bạn với AWS.
4. Chọn đúng repo `nutritrack` và branch muốn deploy (ví dụ: `main`).

### Bước B: Cấu hình Build
Bạn có thể cấu hình trực tiếp trên Console hoặc tạo file `apprunner.yaml` ở root của repo:

**File `apprunner.yaml` mẫu:**
```yaml
version: 1.0
runtime: python310
build:
  commands:
    - pip install -r requirements.txt
run:
  command: uvicorn templates.api:app --host 0.0.0.0 --port 8000
  network:
    port: 8000
```
- **Deployment settings**: Chọn **Automatic** -> **Yes**.
- Khi này, mỗi lần bạn `git push`, App Runner sẽ tự kéo code về, cài thư viện và khởi động lại API server.

---

## Cách 2: CI/CD cho ECS Fargate (Dùng GitHub Actions)

Nếu bạn dùng ECS, bạn cần một script "Pipeline" để build image -> Đẩy lên ECR -> Cập nhật Task Definition.

### Bước A: Tạo GitHub Secrets
Vào Repo trên GitHub -> **Settings** -> **Secrets and variables** -> **Actions**. Thêm các biến sau:
- `DOCKERHUB_USERNAME`: Tên đăng nhập Docker Hub của bạn.
- `DOCKERHUB_TOKEN`: Token (Access Token) từ Docker Hub (tạo trong Account Settings -> Security).
- `AWS_ACCESS_KEY_ID`: Chìa khóa truy cập AWS.
- `AWS_SECRET_ACCESS_KEY`: Mật mã truy cập AWS.
- `AWS_REGION`: Ví dụ `us-east-1`.

### Bước B: Viết file Workflow
Tạo file tại đường dẫn: `.github/workflows/deploy.yml` trong repo của bạn:

```yaml
name: Deploy to Amazon ECS

on:
  push:
    branches: [ "main" ]

env:
  DOCKER_REPOSITORY: <your-dockerhub-username>/nutritrack-api
  ECS_SERVICE: nutritrack-api-service
  ECS_CLUSTER: nutritrack-cluster
  ECS_TASK_DEFINITION: app/docs/nutritrack-task-def.json
  CONTAINER_NAME: api-container

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v1
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push to Docker Hub
        id: build-image
        env:
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t ${{ env.DOCKER_REPOSITORY }}:$IMAGE_TAG -t ${{ env.DOCKER_REPOSITORY }}:latest ./app
          docker push ${{ env.DOCKER_REPOSITORY }} --all-tags
          echo "image=${{ env.DOCKER_REPOSITORY }}:$IMAGE_TAG" >> $GITHUB_OUTPUT

      - name: Fill in the new image ID in the Amazon ECS task definition
        id: task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: ${{ env.ECS_TASK_DEFINITION }}
          container-name: ${{ env.CONTAINER_NAME }}
          image: ${{ steps.build-image.outputs.image }}

      - name: Deploy Amazon ECS task definition
        uses: aws-actions/amazon-ecs-deploy-task-definition@v1
        with:
          task-definition: ${{ steps.task-def.outputs.task-definition }}
          service: ${{ env.ECS_SERVICE }}
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
```

### Bước C: Export Task Definition
Để GitHub Action có thể chạy, bạn cần export cấu hình Task Definition hiện tại thành file JSON và lưu vào repo:
```bash
aws ecs describe-task-definition --task-definition nutritrack-api-task --query taskDefinition > app/docs/nutritrack-task-def.json
```

---

## 💡 So sánh 2 cách CI/CD

| Tiêu chí | App Runner (Native) | ECS + GitHub Actions |
| :--- | :--- | :--- |
| **Độ khó** | Cực dễ (Config trên web) | Trung bình (Cần viết code YAML) |
| **Tốc độ Build** | Chậm hơn (AWS build từ đầu) | Nhanh hơn (GitHub build song song) |
| **Độ linh hoạt** | Thấp (chỉ deploy được web) | Cao (có thể chạy test, scan bảo mật trước khi deploy) |
| **Phí duy trì** | Miễn phí (tính vào phí App Runner) | Miễn phí (với repo Public) |

**Khuyên dùng cho đồ án:** Hãy dùng **App Runner Native GitHub Support** vì nó không bao giờ lỗi script và bạn có thể nhìn thấy tiến trình build trực tiếp trên màn hình AWS Console cực kỳ dễ dàng.
