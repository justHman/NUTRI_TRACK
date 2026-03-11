# Hướng Dẫn CI/CD — NutriTrack API → AWS ECS (Toàn Tập)

Tài liệu này hướng dẫn thiết lập pipeline CI/CD hoàn chỉnh: mỗi khi bạn `git push` lên nhánh `main`, hệ thống sẽ **tự động build Docker Image → push lên Docker Hub → deploy lên AWS ECS** mà không cần thao tác tay.

Pipeline hỗ trợ đầy đủ cả 2 chiến lược deploy trong [`complete_deployment_guide.md`](./complete_deployment_guide.md):
- **Standard Fargate (x86)** → service `nutritrack-api-service`
- **Fargate ARM64 + Spot** → service `nutritrack-api-spot`

---

## 📋 Mục lục

1. [Tổng quan Pipeline](#1-tổng-quan-pipeline)
2. [Yêu cầu trước khi bắt đầu](#2-yêu-cầu-trước-khi-bắt-đầu)
3. [Bước 1 — Tạo IAM User cho GitHub Actions](#3-bước-1--tạo-iam-user-cho-github-actions)
4. [Bước 2 — Lấy Docker Hub Access Token](#4-bước-2--lấy-docker-hub-access-token)
5. [Bước 3 — Cấu hình GitHub Secrets](#5-bước-3--cấu-hình-github-secrets)
6. [Bước 4 — Đặt file Workflow vào đúng vị trí](#6-bước-4--đặt-file-workflow-vào-đúng-vị-trí)
7. [Bước 5 — Cách Pipeline hoạt động](#7-bước-5--cách-pipeline-hoạt-động)
8. [Bước 6 — Trigger thủ công (Manual Deploy)](#8-bước-6--trigger-thủ-công-manual-deploy)
9. [Bước 7 — Theo dõi trạng thái Deployment](#9-bước-7--theo-dõi-trạng-thái-deployment)
10. [Xử lý sự cố thường gặp](#10-xử-lý-sự-cố-thường-gặp)

---

## 1. Tổng quan Pipeline

```
Bạn chỉnh code → git push → GitHub Actions tự động chạy:

┌─────────────────────────────────────────────────────────────────┐
│                      GitHub Actions Pipeline                    │
│                                                                 │
│   [push main]                                                   │
│        │                                                        │
│        ├──► JOB 1: build-x86 ──────────────────────────────┐   │
│        │    • docker build --platform linux/amd64           │   │
│        │    • docker push :latest + :sha                    │   │
│        │                                              needs  │   │
│        │                                                     ▼   │
│        │                              JOB 3: deploy-standard     │
│        │                              • aws ecs describe-task    │
│        │                              • Inject new image         │
│        │                              • aws ecs deploy           │
│        │                              • Wait for stable ✅       │
│        │                                                         │
│        ├──► JOB 2: build-arm ───────────────────────────────┐   │
│        │    • docker buildx --platform linux/arm64           │   │
│        │    • docker push :arm + :arm-sha                    │   │
│        │                                              needs  │   │
│        │                                                     ▼   │
│        │                              JOB 4: deploy-arm-spot     │
│        │                              • aws ecs describe-task    │
│        │                              • Inject new ARM image     │
│        │                              • aws ecs deploy           │
│        │                              • Wait for stable ✅       │
│        │                                                         │
│        └──► JOB 1 + JOB 2 chạy song song (tiết kiệm thời gian)  │
└─────────────────────────────────────────────────────────────────┘
```

### Thời gian ước tính cho mỗi lần deploy

| Giai đoạn | Thời gian |
| :--- | :--- |
| Build x86 image | ~3–5 phút |
| Build ARM64 image | ~6–10 phút (cross-compile chậm hơn) |
| Deploy & chờ ECS ổn định | ~2–3 phút |
| **Tổng (chạy song song)** | **~10–13 phút** |

---

## 2. Yêu cầu trước khi bắt đầu

Trước khi thiết lập CI/CD, bạn cần đã hoàn thành các bước trong `complete_deployment_guide.md`:

- [x] ECS Cluster `nutritrack-cluster` đã tạo
- [x] Task Definition `nutritrack-api-task` (x86) đã tạo và từng deploy thành công ít nhất 1 lần
- [x] Task Definition `nutritrack-api-task-arm` (ARM64) đã tạo *(nếu dùng ARM Spot)*
- [x] ECS Service `nutritrack-api-service` và/hoặc `nutritrack-api-spot` đang chạy
- [x] Docker Hub repository đã tạo (public hoặc private)
- [x] Repo GitHub đã kết nối với codebase

> **Lưu ý:** CI/CD **không tạo** infrastructure từ đầu — nó chỉ cập nhật image và deploy lại. Bạn phải setup ECS thủ công 1 lần theo hướng dẫn chính trước.

---

## 3. Bước 1 — Tạo IAM User cho GitHub Actions

GitHub Actions cần một "tài khoản" AWS để thực hiện lệnh deploy. **Không được dùng tài khoản root** — tạo IAM User riêng với quyền tối thiểu.

### 3.1 Tạo IAM User

1. Truy cập **IAM** → **Users** → **Create user**.
2. **User name**: `github-actions-deployer`
3. **Access type**: Chỉ tick **Programmatic access** (không cần Console access).
4. Nhấn **Next**.

### 3.2 Gắn Policy cho User

Nhấn **Attach policies directly** → **Create policy** → Tab **JSON**, dán nội dung:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECSDeployPermissions",
            "Effect": "Allow",
            "Action": [
                "ecs:RegisterTaskDefinition",
                "ecs:DescribeTaskDefinition",
                "ecs:UpdateService",
                "ecs:DescribeServices",
                "ecs:ListTaskDefinitions"
            ],
            "Resource": "*"
        },
        {
            "Sid": "PassRoleToECS",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": [
                "arn:aws:iam::*:role/ecsTaskExecutionRole",
                "arn:aws:iam::*:role/ecsTaskRole"
            ]
        }
    ]
}
```

> **Tại sao cần `iam:PassRole`?** Khi GitHub Actions đăng ký Task Definition mới, nó cần xác nhận rằng 2 IAM Role (`ecsTaskExecutionRole` + `ecsTaskRole`) được phép gắn vào task. Thiếu quyền này sẽ gặp lỗi `User is not authorized to perform iam:PassRole`.

5. Đặt tên policy: `GitHubActionsECSDeployPolicy` → **Create policy**.
6. Attach policy vừa tạo vào user `github-actions-deployer` → **Create user**.

### 3.3 Lấy Access Keys

1. Nhấn vào user `github-actions-deployer` → Tab **Security credentials**.
2. **Access keys** → **Create access key**.
3. Chọn **Application running outside AWS**.
4. **Sao chép ngay** `Access key ID` và `Secret access key` — sẽ không xem lại được sau này.

---

## 4. Bước 2 — Lấy Docker Hub Access Token

Không nên dùng mật khẩu Docker Hub trực tiếp. Tạo Access Token riêng cho CI/CD:

1. Đăng nhập [hub.docker.com](https://hub.docker.com).
2. **Account Settings** → **Personal access tokens** → **Generate new token**.
3. **Token description**: `github-actions-nutritrack`
4. **Access permissions**: Chọn **Read & Write** (cần để push image).
5. Nhấn **Generate** → Sao chép token ngay.

---

## 5. Bước 3 — Cấu hình GitHub Secrets

Vào repo GitHub → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Thêm lần lượt 5 secrets sau:

| Secret Name | Giá trị | Lấy từ đâu |
| :--- | :--- | :--- |
| `DOCKERHUB_USERNAME` | Tên đăng nhập Docker Hub của bạn | Docker Hub profile |
| `DOCKERHUB_TOKEN` | Token vừa tạo ở Bước 2 | Docker Hub Personal Access Token |
| `AWS_ACCESS_KEY_ID` | Access key của `github-actions-deployer` | IAM User → Security credentials |
| `AWS_SECRET_ACCESS_KEY` | Secret access key của `github-actions-deployer` | IAM User → Security credentials |
| `AWS_REGION` | `us-east-1` | Hoặc region bạn đang dùng |

> ⚠️ **Bảo mật:** Secrets được mã hoá và không ai xem được sau khi lưu — kể cả bạn. Nếu mất, phải tạo lại và cập nhật secret mới.

---

## 6. Bước 4 — Đặt file Workflow vào đúng vị trí

File YAML của pipeline phải nằm tại đúng đường dẫn để GitHub nhận diện:

```
[repo-root]/
├── .github/
│   └── workflows/
│       └── deploy-ecs.yml        ← Đặt file tại đây
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── ...
└── README.md
```

**Tạo thư mục và file:**
```bash
# Tại root của repo (nutritrack-documentation/)
mkdir -p .github/workflows
# Copy file deploy-ecs.yml vào thư mục này
```

Sau đó commit và push lên GitHub:
```bash
git add .github/workflows/deploy-ecs.yml
git commit -m "ci: add ECS deployment pipeline"
git push origin main
```

Khi push xong, GitHub sẽ tự động nhận diện workflow và bắt đầu chạy.

---

## 7. Bước 5 — Cách Pipeline hoạt động

### 7.1 Điều kiện kích hoạt (Trigger)

Pipeline chạy khi:
- **Tự động:** `git push` lên nhánh `main` và có file thay đổi trong thư mục `app/`
- **Thủ công:** Vào tab Actions trên GitHub → Chọn workflow → **Run workflow**

> **Tại sao chỉ khi `app/**` thay đổi?** Nếu bạn chỉ sửa file `README.md` hay tài liệu thì không cần deploy lại container. Điều kiện `paths` giúp tiết kiệm thời gian và giảm nguy cơ deploy lỗi.

### 7.2 4 Jobs trong Pipeline

**JOB 1 — `build-x86`** (chạy song song với JOB 2):
```
Checkout code → Setup Buildx → Login Docker Hub
  → docker build --platform linux/amd64 ./app
  → Push tag :latest (để ECS dùng)
  → Push tag :<git-sha> (để rollback khi cần)
  → Output: image URL để JOB 3 dùng
```

**JOB 2 — `build-arm`** (chạy song song với JOB 1):
```
Checkout code → Setup QEMU (cross-compile) → Setup Buildx → Login Docker Hub
  → docker buildx --platform linux/arm64 ./app
  → Push tag :arm (để ECS dùng)
  → Push tag :arm-<git-sha> (để rollback khi cần)
  → Output: image URL để JOB 4 dùng
```

> **QEMU là gì?** GitHub Actions runner dùng máy x86. Để build image ARM64 trên máy x86, cần QEMU để giả lập môi trường ARM. Đây là lý do ARM build chậm hơn x86.

**JOB 3 — `deploy-standard`** (chờ JOB 1 xong):
```
Configure AWS credentials
  → Tải Task Definition x86 hiện tại (aws ecs describe-task-definition)
  → Thay link image cũ → link image mới vừa build
  → Đăng ký Task Definition revision mới lên ECS
  → Cập nhật ECS Service với revision mới
  → Chờ cho đến khi service ổn định (healthy)
```

**JOB 4 — `deploy-arm-spot`** (chờ JOB 2 xong):
```
Configure AWS credentials
  → Tải Task Definition ARM hiện tại
  → Thay link image ARM cũ → link image ARM mới
  → Đăng ký Task Definition ARM revision mới
  → Cập nhật ECS ARM Service
  → Chờ cho đến khi service ổn định
```

### 7.3 Tagging chiến lược

| Tag | Ví dụ | Mục đích |
| :--- | :--- | :--- |
| `:latest` | `user/nutritrack-api:latest` | Tag ECS dùng để kéo image (x86) |
| `:arm` | `user/nutritrack-api:arm` | Tag ECS dùng để kéo image (ARM64) |
| `:<git-sha>` | `user/nutritrack-api:a3f9c21` | Snapshot immutable — dùng để rollback |
| `:arm-<git-sha>` | `user/nutritrack-api:arm-a3f9c21` | Snapshot ARM — dùng để rollback |

---

## 8. Bước 6 — Trigger thủ công (Manual Deploy)

Đôi khi cần deploy thủ công mà không push code (VD: infrastructure thay đổi, rollback...).

### 8.1 Chạy qua GitHub UI

1. Vào repo GitHub → Tab **Actions**.
2. Chọn workflow **"🚀 Deploy NutriTrack → AWS ECS"**.
3. Nhấn **Run workflow** (góc phải).
4. Chọn **target**:
   - `both` — Build và deploy cả 2 service (default)
   - `standard` — Chỉ build x86 và deploy Fargate Standard
   - `arm-spot` — Chỉ build ARM64 và deploy Fargate ARM Spot
5. Nhấn **Run workflow** màu xanh.

### 8.2 Chạy qua AWS CLI (Rollback nhanh)

Nếu bản mới bị lỗi và cần rollback về bản trước ngay lập tức, không cần chạy lại pipeline:

```bash
# Xem danh sách revision của Task Definition
aws ecs list-task-definitions --family-prefix nutritrack-api-task

# Rollback về revision cụ thể (VD: revision 5)
aws ecs update-service \
  --cluster nutritrack-cluster \
  --service nutritrack-api-service \
  --task-definition nutritrack-api-task:5 \
  --force-new-deployment
```

---

## 9. Bước 7 — Theo dõi trạng thái Deployment

### 9.1 Xem trên GitHub Actions

1. Tab **Actions** → Chọn workflow run đang chạy.
2. Click vào từng job để xem log chi tiết trong thời gian thực.
3. Trạng thái:
   - 🟡 Vàng: Đang chạy
   - ✅ Xanh: Thành công
   - ❌ Đỏ: Thất bại (click vào để xem lỗi)

### 9.2 Xem trên AWS ECS Console

1. **ECS** → Cluster `nutritrack-cluster` → **Services**.
2. Cột **Last deployment** hiển thị thời gian và kết quả deployment gần nhất.
3. Tab **Events** của service hiển thị log sự kiện (task dừng, task khởi động...).

### 9.3 Xem trên CloudWatch

Nếu deployment thành công nhưng container crash ngay sau khi bật, kiểm tra log:

1. **CloudWatch** → **Log groups** → `/ecs/nutritrack-api-task`.
2. Chọn stream gần nhất → Tìm `ERROR` hoặc `Traceback`.

---

## 10. Xử lý sự cố thường gặp

### ❌ Lỗi: `User is not authorized to perform iam:PassRole`

**Nguyên nhân:** IAM User `github-actions-deployer` thiếu quyền `iam:PassRole`.

**Cách sửa:** Kiểm tra lại policy ở Bước 1 — đảm bảo có statement `PassRoleToECS` với đúng ARN của `ecsTaskExecutionRole` và `ecsTaskRole`.

---

### ❌ Lỗi: `could not find container name 'api-container' in task definition`

**Nguyên nhân:** Tên container trong task definition không phải `api-container`.

**Cách sửa:** Vào ECS → Task Definitions → Xem tên container thực tế → Sửa biến `CONTAINER_NAME` trong file YAML:

```yaml
env:
  CONTAINER_NAME: <tên-container-thực-tế>
```

---

### ❌ Lỗi: `ResourceInitializationError` hoặc container không khởi động

**Nguyên nhân thường gặp:**
1. Secrets Manager chưa có `USDA_API_KEY` hoặc ARN sai trong Task Definition.
2. `ecsTaskExecutionRole` thiếu quyền `secretsmanager:GetSecretValue`.
3. Image ARM build xong nhưng Task Definition vẫn cấu hình `Linux/X86_64` — bị crash ngay lập tức.

**Cách kiểm tra:**
```bash
# Xem lý do task bị dừng
aws ecs describe-tasks \
  --cluster nutritrack-cluster \
  --tasks <task-id>
```

---

### ❌ Lỗi: GitHub Actions build ARM image rất chậm (>20 phút)

**Nguyên nhân:** QEMU emulation chậm, đặc biệt khi cài packages Python (`pip install`).

**Cách tối ưu:** Thêm cache layer cho pip trong `Dockerfile`:

```dockerfile
# Cache pip downloads — không cài lại nếu requirements.txt không đổi
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt
```

---

### ❌ Giờ cao điểm: Fargate Spot bị AWS thu hồi, không có task nào chạy

**Nguyên nhân:** AWS thiếu capacity Spot → ECS thu hồi task.

**ECS tự xử lý:** Sau vài phút, ECS tự khởi động task Spot thay thế. Nếu không tự phục hồi:

```bash
# Ép ECS restart service
aws ecs update-service \
  --cluster nutritrack-cluster \
  --service nutritrack-api-spot \
  --force-new-deployment
```

---

## Phụ lục — Checklist thiết lập CI/CD

- [ ] IAM User `github-actions-deployer` đã tạo với policy `GitHubActionsECSDeployPolicy`
- [ ] Docker Hub Access Token đã tạo (Read & Write)
- [ ] 5 GitHub Secrets đã thêm: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
- [ ] File `deploy-ecs.yml` đặt tại `.github/workflows/deploy-ecs.yml` (root repo)
- [ ] ECS Service `nutritrack-api-service` hoặc `nutritrack-api-spot` đang ở trạng thái `ACTIVE`
- [ ] Thử push 1 thay đổi nhỏ vào `app/` → Kiểm tra tab Actions xem pipeline chạy không

---

*Tài liệu CI/CD này đi kèm với [`complete_deployment_guide.md`](./complete_deployment_guide.md) — Đọc hướng dẫn chính trước khi thiết lập CI/CD.*
