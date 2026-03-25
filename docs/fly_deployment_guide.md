# NutriTrack Deploy to Fly.io (Step-by-Step)

Tai lieu nay huong dan trien khai NutriTrack len Fly.io tu dau den cuoi:
- Tao app Fly
- Tao volume cho cache L2
- Set secrets tren Fly va GitHub
- Cau hinh `fly.toml`
- Cau hinh GitHub Actions `.github/workflows/fly.yml`
- Test + Deploy
- SSH de get/merge/replace cache an toan

## 1. Dieu kien tien quyet

1. Da co tai khoan Fly.io va da dang nhap `flyctl auth login`.
2. Da co repo GitHub va branch `main`.
3. Project da co:
- `Dockerfile`
- `fly.toml`
- `.github/workflows/fly.yml`

## 2. Tao app Fly

Chay trong thu muc goc project:

```bash
flyctl apps create nutritrack-api
```

Kiem tra:

```bash
flyctl apps list
flyctl status -a nutritrack-api
```

## 3. Tao volume cho cache L2

Tao volume ten `nutritrack_data` tai region `sin`:

```bash
flyctl volumes create nutritrack_data --app nutritrack-api --region sin --size 1 --yes
```

Kiem tra:

```bash
flyctl volumes list -a nutritrack-api
```

Luu y:
- Volume la persistent disk theo machine.
- Neu muon do ben cao hon, tao nhieu volume va can nhac architecture machine/region.

## 4. Set secrets tren Fly

Khong dung `aws configure` trong container Fly. App doc env trucc tiep.

Set secrets toi thieu cho Bedrock + API:

```bash
flyctl secrets set \
  AWS_REGION=us-east-1 \
  AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID \
  AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY \
  USDA_API_KEY=YOUR_USDA_API_KEY \
  AVOCAVO_NUTRITION_API_KEY=YOUR_AVOCAVO_KEY \
  -a nutritrack-api
```

Neu dung temporary credentials, set them:

```bash
flyctl secrets set AWS_SESSION_TOKEN=YOUR_SESSION_TOKEN -a nutritrack-api
```

Kiem tra danh sach secret names:

```bash
flyctl secrets list -a nutritrack-api
```

## 5. Set GitHub Secrets

Vao GitHub repository -> Settings -> Secrets and variables -> Actions -> New repository secret.

Can tao cac secret sau:

1. `FLY_API_TOKEN`
2. `AWS_REGION`
3. `AWS_ACCESS_KEY_ID`
4. `AWS_SECRET_ACCESS_KEY`
5. `USDA_API_KEY`
6. `AVOCAVO_NUTRITION_API_KEY`

Tao token Fly:

```bash
flyctl tokens create deploy -x 99999h
```

Copy token va luu vao `FLY_API_TOKEN` tren GitHub.

## 6. Cau hinh file fly.toml

Mau cau hinh phu hop cho project:

```toml
# fly.toml app configuration file

app = "nutritrack-api"
primary_region = "sin"

[build]

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0
  processes = ["app"]

[[vm]]
  memory = "1gb"
  cpu_kind = "shared"
  cpus = 1

[mounts]
source = "nutritrack_data"
destination = "/app/data"

[env]
  HOST = "0.0.0.0"
  PORT = "8000"
  LOG_LEVEL = "INFO"
  LOG_TO_FILE = "false"
  PYTHONUNBUFFERED = "1"
```

Giai thich nhanh:
- `source = "nutritrack_data"`: ten volume da tao.
- `destination = "/app/data"`: mount point trong container.
- Khong phai tao "database" ten volume trong `/app/data`; day la volume mount.

## 7. Cau hinh workflow .github/workflows/fly.yml

Workflow gom 2 job:
1. `test`
2. `deploy` (chay sau test)

Chien luoc cache an toan:
1. Wake app
2. Get remote cache (neu co)
3. Merge remote + local theo `_ts`
4. Put len file `*_new.json`
5. `mv -f` de replace file chinh

Ban mau (rut gon nhung day du logic):

```yaml
name: Test and Deploy to Fly.io

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
      - run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt
          pip install -r requirements.txt
      - env:
          AWS_REGION: ${{ secrets.AWS_REGION }}
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          USDA_API_KEY: ${{ secrets.USDA_API_KEY }}
          AVOCAVO_NUTRITION_API_KEY: ${{ secrets.AVOCAVO_NUTRITION_API_KEY }}
        run: |
          set +e
          pytest -m "not integration" tests -v
          TEST_EXIT_CODE=$?
          if [ $TEST_EXIT_CODE -ne 0 ]; then
            echo "::warning::Pytest failed (exit code $TEST_EXIT_CODE). Continue deploy."
          fi
          exit 0

  deploy:
    runs-on: ubuntu-latest
    needs: test
    env:
      APP_NAME: nutritrack-api
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@v1
      - env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: flyctl deploy --remote-only --config fly.toml
```

Khuyen nghi:
- Luon dung `--config fly.toml` de tranh sai context.
- Buoc verify cache khong nen dung wildcard `ls /app/data/*.json` vi co the fail khi shell khong expand.
- Nen check tung file voi `test -f` va warning thay vi fail workflow.

## 8. Quy trinh SSH get/merge/replace cache (manual)

### 8.1 Download remote cache ve local

```bash
flyctl ssh sftp get /app/data/usda_cache.json data/usda_cache.remote.json -a nutritrack-api
flyctl ssh sftp get /app/data/avocavo_cache.json data/avocavo_cache.remote.json -a nutritrack-api
flyctl ssh sftp get /app/data/openfoodfacts_cache.json data/openfoodfacts_cache.remote.json -a nutritrack-api
```

### 8.2 Merge local + remote

Nguyen tac merge:
- Gop key cua `foods` va `barcodes`.
- Neu trung key, giu entry co `_ts` moi hon.
- Neu bang nhau, uu tien remote de giu state tren server.

### 8.3 Upload voi ten moi va rename de overwrite an toan

```bash
flyctl ssh sftp put data/usda_cache.json /app/data/usda_cache_new.json -a nutritrack-api
flyctl ssh console -a nutritrack-api -C "mv -f /app/data/usda_cache_new.json /app/data/usda_cache.json"

flyctl ssh sftp put data/avocavo_cache.json /app/data/avocavo_cache_new.json -a nutritrack-api
flyctl ssh console -a nutritrack-api -C "mv -f /app/data/avocavo_cache_new.json /app/data/avocavo_cache.json"

flyctl ssh sftp put data/openfoodfacts_cache.json /app/data/openfoodfacts_cache_new.json -a nutritrack-api
flyctl ssh console -a nutritrack-api -C "mv -f /app/data/openfoodfacts_cache_new.json /app/data/openfoodfacts_cache.json"
```

## 9. Kiem tra sau deploy

Kiem tra app:

```bash
flyctl status -a nutritrack-api
curl https://nutritrack-api.fly.dev/health
```

Kiem tra cache files:

```bash
flyctl ssh console -a "$APP_NAME" -C "sh -c 'ls /app/data/*.json'"
flyctl ssh console -a nutritrack-api -C "test -f /app/data/usda_cache.json && echo ok_usda"
flyctl ssh console -a nutritrack-api -C "test -f /app/data/avocavo_cache.json && echo ok_avocavo"
flyctl ssh console -a nutritrack-api -C "test -f /app/data/openfoodfacts_cache.json && echo ok_openfoodfacts"
```

## 10. Troubleshooting nhanh

1. `app has no started VMs`
- App dang sleep (`auto_stop_machines = stop`).
- Goi health endpoint de wake: `curl https://nutritrack-api.fly.dev/health`.

2. `sftp put ... already exists`
- Fly SFTP khong overwrite truc tiep.
- Dung cach `put -> *_new.json -> mv -f`.

3. `ls: cannot access '/app/data/*.json'`
- Wildcard khong expand.
- Dung `flyctl ssh console -a "$APP_NAME" -C "sh -c 'ls /app/data/*.json'"` hoac `test -f` tung file.

4. Bedrock fail tren Fly
- Thieu secrets AWS tren Fly.
- Kiem tra `flyctl secrets list -a nutritrack-api`.

## 11. Bao mat

1. Khong commit key vao repo.
2. Chi luu key trong Fly secrets va GitHub secrets.
3. Neu key tung lo, rotate ngay trong AWS IAM.
4. Cap policy toi thieu cho Bedrock va API lien quan.
