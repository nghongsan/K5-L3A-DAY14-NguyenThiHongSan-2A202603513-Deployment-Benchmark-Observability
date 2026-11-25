# Day 14 Lab - Mission Answers

> Họ tên: Nguyễn Thị Hồng Sản · MSSV: 2A202603513 · Lớp: K5-L3A
> Môi trường: MacBook Air (Apple Silicon, 8 CPU), macOS, Docker Desktop (Engine 29.9.3, Compose v5.7.1), Python 3.12.3 (venv).
> Mọi số đo bên dưới lấy từ lệnh đã chạy ngày 2026-11-25.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

1. **API key và mật khẩu DB hard-code** (dòng 17–18: `OPENAI_API_KEY = "sk-hardcoded-..."`, `DATABASE_URL = "postgresql://admin:password123@..."`). Push lên GitHub là lộ ngay, và không đổi được giữa dev/staging/prod mà không sửa code.
2. **Không có config management** (dòng 21–22: `DEBUG = True`, `MAX_TOKENS = 500` cố định trong code). Muốn đổi phải sửa code và build lại.
3. **Dùng `print()` thay vì logging có cấu trúc, và còn in ra secret** (dòng 33–38, đặc biệt dòng 34 `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`). Log chạy thật đã in ra khóa: tôi thấy dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this` trong log khi chạy.
4. **Không có health check** (dòng 42–43). `curl /health` trả **404**, nên platform không biết khi nào agent chết để restart.
5. **Port và host cố định** (dòng 47–53: `host="localhost"`, `port=8000`). `localhost` không nhận kết nối từ ngoài container; Railway/Render cấp cổng qua biến `PORT` nên app không lên được.
6. **`reload=True` ở production** (dòng 53): hot-reload dành cho dev, tốn tài nguyên và không an toàn.
7. **Không xử lý shutdown** (không có `lifespan`, không xử lý SIGTERM): deploy/scale xong có thể cắt ngang request đang chạy.
8. **Không xác thực, không validate input**: ai cũng gọi được `/ask`, câu hỏi nhận qua query param (dòng 31) nên lộ trong URL/log và không giới hạn độ dài.

### Exercise 1.2: Kết quả chạy bản develop

```bash
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -o /dev/null -w "%{http_code}" http://localhost:8000/health
404
```

Nó chạy, nhưng chưa production-ready: không health check (404), nhận `question` qua query (gửi JSON bị 422), và log in ra secret.

### Exercise 1.3: Comparison table (develop vs `production/app.py`, `production/config.py`)

| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config | Hard-code trong code (`app.py` dòng 17–22) | Đọc từ env qua `config.py` (`os.getenv("PORT", ...)`, `AGENT_API_KEY`, `DEBUG`...) | Cùng một image chạy ở dev/staging/prod, không lộ secret, đổi cấu hình không cần build lại (12-Factor) |
| Secrets | `sk-...`, `password123` nằm trong code | Không có secret trong code; `validate()` fail-fast nếu thiếu `AGENT_API_KEY` ở production (`config.py`) | Secret trong git là sự cố bảo mật |
| Health check | Không có (`/health` → 404) | `GET /health` (liveness, có uptime) và `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform dựa vào đó để restart (liveness) và quyết định route traffic (readiness) |
| Logging | `print()`, in cả secret | Log JSON có `event`, không log secret/nội dung nhạy cảm (`question_length` thay vì nội dung) | Log aggregator (Loki, Datadog) parse được; không rò rỉ dữ liệu |
| Host / Port | `localhost`, 8000 cố định, `reload=True` | `0.0.0.0`, port từ `PORT`, reload chỉ khi `DEBUG=true` | Container/PaaS cấp cổng qua env và cần nhận kết nối từ ngoài |
| Shutdown | Đột ngột, không có xử lý | `lifespan` + handler SIGTERM, uvicorn chờ request đang chạy | Không mất request khi deploy/scale |
| Input/response | Query param, không validate | Body JSON, trả 422 rõ ràng khi thiếu `question` | API ổn định, lỗi dễ hiểu |

Kết quả chạy bản production: `POST /ask` trả 200 kèm `"model":"gpt-4o-mini"`; `GET /health` trả `{"status":"ok","uptime_seconds":3.8,...}`; `GET /ready` trả `{"ready":true}`. Khi gửi SIGTERM, uvicorn in `Shutting down → Waiting for application shutdown → Finished server process`.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (bản đầy đủ gồm OS + Python runtime, rất nặng vì chứa cả compiler và công cụ build). Đây là đúng nội dung `02-docker/develop/Dockerfile`; chính vì nặng nên bản production ở Exercise 2.3 đổi sang `python:3.11-slim` (chỉ OS tối thiểu + Python runtime).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Vì sao `COPY requirements.txt` trước:** mỗi lệnh Dockerfile là một layer được cache. Dependencies ít thay đổi còn code thì đổi liên tục; nếu copy requirements và `pip install` trước, khi chỉ sửa code Docker dùng lại layer đã cache, không cài lại thư viện. Nếu `COPY . .` đứng trước thì mỗi lần sửa một dòng code là phải cài lại toàn bộ.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định, có thể bị ghi đè dễ dàng khi `docker run image <lệnh khác>`. `ENTRYPOINT` là chương trình cố định của container; tham số truyền vào `docker run` được nối thêm vào sau nó (muốn thay phải dùng `--entrypoint`). Thường dùng `ENTRYPOINT` cho chương trình chính và `CMD` cho tham số mặc định.

### Exercise 2.2: Build và run

```bash
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

(App develop nhận `question` qua query, đúng lưu ý số 3 trong README.)

### Exercise 2.3: Image size comparison (đo bằng `docker images`)

Stage 1 (builder) cài `gcc`, `libpq-dev` và chạy `pip install --user` để build dependencies. Stage 2 (runtime) bắt đầu lại từ `python:3.11-slim`, chỉ `COPY --from=builder` thư mục site-packages và mã nguồn, rồi chạy bằng user non-root. Image nhỏ hơn vì trình biên dịch, apt cache, pip cache và build tools ở stage 1 không được đưa sang image cuối, và base là bản `slim` thay vì bản đầy đủ.

```text
REPOSITORY:TAG        SIZE
my-agent:advanced     188MB
my-agent:develop      1.17GB
```

- Develop: **1170 MB** (1.169.510.072 byte)
- Production: **188 MB** (188.415.952 byte)
- Difference: giảm **83,9%** (nhỏ hơn khoảng 6,2 lần)

Bản production còn chạy bằng user `appuser` (kiểm tra `docker exec ... id` ra `uid=999(appuser)`), có `HEALTHCHECK`, và container báo `healthy`.

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

```text
                       Internet / curl
                             │  :80, :443
                             ▼
                     ┌────────────────┐
                     │  nginx (LB)    │  rate limit 10 r/s, security headers
                     └───────┬────────┘
                             │ http://agent:8000   (mạng nội bộ "internal")
                             ▼
                     ┌────────────────┐
                     │  agent (FastAPI)│  /ask /health /ready
                     └───┬────────┬───┘
            REDIS_URL    │        │   QDRANT_URL
                         ▼        ▼
                  ┌──────────┐ ┌──────────┐
                  │  redis   │ │  qdrant  │   volumes: redis_data, qdrant_data
                  │ (cache,  │ │ (vector  │
                  │ rate lim)│ │  DB/RAG) │
                  └──────────┘ └──────────┘
```

4 service được start: `agent`, `redis`, `qdrant`, `nginx`. Chỉ `nginx` mở cổng ra ngoài (80/443); agent, redis, qdrant chỉ nằm trong network `internal` và gọi nhau bằng tên service qua DNS của Docker. `agent` chỉ chạy khi `redis` và `qdrant` đã `healthy` (`depends_on: condition: service_healthy`).

```bash
$ docker compose -p k5-day14-docker ps
agent    Up 20 seconds (healthy)   8000/tcp
nginx    Up 15 seconds             0.0.0.0:80->80/tcp
qdrant   Up 31 seconds (healthy)   6333-6334/tcp
redis    Up 30 seconds (healthy)   6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":23.7,"version":"2.0.0",...}

$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy lên Railway (agent Part 6)

- **Nền tảng chính:** Railway
- **URL public:** https://agent-production-541c6525.up.railway.app
- **Cách làm** (trong `06-lab-complete/`, theo lưu ý số 8 của README):
  ```bash
  railway init --name k5-day14-agent            # tạo project
  railway add --database redis                  # Redis trên Railway
  railway add --service agent --variables "ENVIRONMENT=production" ...
  railway variables set AGENT_API_KEY=<giá trị ngẫu nhiên, không ghi vào repo>
  railway variables set 'REDIS_URL=${{Redis.REDIS_URL}}'   # tham chiếu tới service Redis
  railway up --service agent --ci               # build bằng Dockerfile và deploy
  railway domain --service agent                # nhận URL public
  ```
- `AGENT_API_KEY` đặt bằng biến môi trường trên Railway (sinh ngẫu nhiên bằng `secrets.token_urlsafe`), không có trong code hay repo. `REDIS_URL` là biến tham chiếu tới service Redis của cùng project nên không lộ mật khẩu Redis.
- Kết quả 4 lệnh tự kiểm ở CP6 (chạy ngày 2026-11-25): `/health` **200**, `/ready` **200** (Redis kết nối được), `POST /ask` không key **401**, có key **200**.
- Script chấm với URL public: `python check_production_ready.py --static-only --public-url https://agent-production-541c6525.up.railway.app` báo `✅ Public URL: GET .../health → 200`. (Máy tôi cần `SSL_CERT_FILE` trỏ tới bundle `certifi` vì Python cài từ python.org không có chứng chỉ gốc; không sửa script chấm.)
- Screenshot: [screenshots/running.png](screenshots/running.png) (trình duyệt mở `/health` của URL public), [screenshots/test.png](screenshots/test.png) (kết quả 4 lệnh tự kiểm), [screenshots/dashboard.png](screenshots/dashboard.png) (dashboard Railway).

### So sánh `railway.toml` với `render.yaml` (của `06-lab-complete/`)

| Khía cạnh | `railway.toml` | `render.yaml` |
|---|---|---|
| Phạm vi | Chỉ cấu hình **build và deploy của một service** (`[build]`, `[deploy]`) | Mô tả **cả hạ tầng** (Infrastructure as Code, Blueprint): web service **và** Redis (`keyvalue`) trong cùng một file |
| Build | `builder = "DOCKERFILE"` | `runtime: docker`, `dockerfilePath: ./Dockerfile` |
| Health check | `healthcheckPath = "/health"` | `healthCheckPath: /health` (khác cách viết hoa chữ C) |
| Restart | `restartPolicyType = "ON_FAILURE"` + số lần thử lại | Render tự restart, không khai báo trong file này |
| Biến môi trường và secret | **Không khai báo trong file**; đặt qua dashboard hoặc `railway variables set`; `REDIS_URL` tham chiếu `${{Redis.REDIS_URL}}` | Khai báo ngay trong file: giá trị thường (`ENVIRONMENT`), secret tự sinh (`generateValue: true` cho `AGENT_API_KEY`), và `REDIS_URL` lấy từ service Redis qua `fromService ... connectionString` |
| Redis | Tạo riêng (`railway add --database redis`), không nằm trong `railway.toml` | Khai báo cùng file, Blueprint dựng cả hai |
| Cách deploy | Đẩy code bằng CLI (`railway up`) hoặc kết nối GitHub | Push lên GitHub rồi **New → Blueprint** để Render đọc file |
| Tính tái lập | Phải chạy các lệnh `railway add/variables` bằng tay | Một file dựng lại được toàn bộ stack |

Vì sao khác: Railway coi file là "cách build và chạy service", còn tài nguyên (database, biến, domain) quản lý ở cấp project qua CLI/dashboard. Render coi file là nguồn sự thật của cả hạ tầng, nên đưa cả database và cách nối biến vào file. Ưu điểm của Render là tái lập tốt hơn; ưu điểm của Railway là nhanh hơn để bắt đầu. Cả hai đều nhận `PORT` từ platform, nên `CMD` của Dockerfile đọc `${PORT:-8000}`. Tôi chỉ deploy thực tế lên Railway; `render.yaml` được kiểm tra bằng script chấm (web service, `healthCheckPath`, secret không ghi thẳng giá trị) nhưng chưa deploy trên Render.

### Exercise 3.3: Pipeline Cloud Run (`cloudbuild.yaml`, `service.yaml`)

Cloud Build chạy theo thứ tự (mỗi bước dùng `waitFor` nên bước sau chỉ chạy khi bước trước thành công): (1) **test**: cài dependencies và chạy `pytest tests/`, fail thì dừng cả pipeline; (2) **build** image Docker, gắn tag `$COMMIT_SHA` và `latest`, dùng `--cache-from` để tận dụng layer cache; (3) **push** mọi tag lên Container Registry (`gcr.io`); (4) **deploy** lên Cloud Run vùng `asia-southeast1` với `min-instances=1` (tránh cold start), `max-instances=10`, và nạp secret `OPENAI_API_KEY` từ Secret Manager thay vì ghi trong code. Trigger là push lên `main`. `service.yaml` là định nghĩa Cloud Run dạng IaC (Knative): autoscale 1 đến 10 instance, mỗi instance tối đa 80 request đồng thời, giới hạn CPU/RAM, secret từ Secret Manager, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`. Tôi chỉ đọc hai file, không deploy.

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Check ở đâu:** hàm `verify_api_key` (dòng 39) dùng `APIKeyHeader(name="X-API-Key")`, được gắn vào `/ask` bằng `Depends(verify_api_key)` (dòng 70).
- **Sai key thì sao:** thiếu header → **401**; có header nhưng sai key → **403** (bản develop tách hai trường hợp). Bản Part 6 của tôi trả **401** cho cả hai vì script chấm yêu cầu vậy.
- **Rotate key:** key đọc từ biến môi trường `AGENT_API_KEY`, nên rotate là đặt giá trị mới trên platform và restart service, không sửa code. Để không gián đoạn thì cho phép tạm thời hai key cùng hợp lệ trong lúc client chuyển sang key mới, rồi thu hồi key cũ.

```bash
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production`)

Luồng: client gọi `POST /auth/token` với username/password → server kiểm tra trong `DEMO_USERS`, ký JWT (HS256, có `sub`, `role`, `iat`, `exp` 60 phút) bằng `JWT_SECRET` → client gửi `Authorization: Bearer <token>` ở các request sau → server chỉ cần xác minh chữ ký và `exp`, không phải tra database (stateless).

```bash
$ curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token":"<REDACTED>","token_type":"bearer","expires_in_minutes":60,...}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** Sliding Window Counter: mỗi user có một `deque` timestamp; mỗi lần gọi bỏ timestamp cũ hơn 60 giây rồi đếm số còn lại.
- **Limit:** user thường **10 request/phút**; admin **100 request/phút** (`rate_limiter_user`, `rate_limiter_admin`).
- **Bypass cho admin:** không bypass hẳn mà chọn limiter theo role (`app.py` dòng 141: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`), tức admin có hạn mức cao hơn.

Vòng lặp 15 request bằng token của `student` (đã che token):

```text
1..10: HTTP 200
11: HTTP 429 retry-after: 59
12: HTTP 429 retry-after: 59
13: HTTP 429 retry-after: 59
14: HTTP 429 retry-after: 59
15: HTTP 429 retry-after: 59

HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Hạn chế của bản này: state nằm trong RAM của từng process nên chạy nhiều instance thì mỗi instance đếm riêng. Vì vậy ở Part 6 tôi chuyển sang Redis.

### Exercise 4.4: Cost guard implementation (`06-lab-complete/app/cost_guard.py`)

Đề gợi ý `check_budget(user_id, estimated_cost)` với budget 10 USD/tháng cho **mỗi user**, theo dõi trong Redis, reset đầu tháng. Cách làm của tôi:

```python
def check_budget(user_id=None) -> None:      # gọi TRƯỚC khi gọi LLM
    day, month, user = _keys(user_id)         # cost:day:..., cost:month:..., cost:user:<hash>:YYYY-MM
    day_spent, month_spent, user_spent = r.mget(day, month, user or day)
    if day_spent   >= DAILY_BUDGET_USD:        raise HTTPException(402, "Daily budget exhausted")
    if month_spent >= MONTHLY_BUDGET_USD:      raise HTTPException(402, "Monthly budget exhausted")
    if user and user_spent >= USER_MONTHLY_BUDGET_USD:
                                               raise HTTPException(402, "User monthly budget exhausted")

def record_cost(input_tokens, output_tokens, user_id=None) -> float:   # gọi SAU khi gọi LLM
    cost = in/1000 * 0.00015 + out/1000 * 0.0006
    pipe.incrbyfloat(day, cost); pipe.incrbyfloat(month, cost); pipe.incrbyfloat(user, cost)  # + EXPIRE
```

- Chi phí mỗi request = `input_tokens/1000 × 0.00015 + output_tokens/1000 × 0.0006` (giá tham khảo gpt-4o-mini). Mock LLM không trả số token thật nên tôi ước lượng ~1,3 token/từ.
- **Ba tầng budget, đều lưu trong Redis** (không trong RAM) để mọi worker/instance dùng chung và không mất khi restart: theo ngày toàn hệ thống (`DAILY_BUDGET_USD`), theo tháng toàn hệ thống (`MONTHLY_BUDGET_USD`), và **theo từng user theo tháng** (`USER_MONTHLY_BUDGET_USD`, mặc định 10 USD đúng như đề). Cộng dồn bằng `INCRBYFLOAT` trong một pipeline, kèm `EXPIRE` (2 ngày, 35 ngày) để key cũ tự dọn. Reset đầu ngày/tháng diễn ra tự nhiên vì tên key chứa ngày/tháng.
- User lấy từ trường `user_id` trong body; nếu client không gửi thì tính chung theo API key. `user_id` được băm SHA-256 trước khi làm tên key, nên độ dài key cố định và client không chèn được ký tự lạ vào tên key Redis.
- Tầng theo-user đảm bảo một user đốt hết phần của mình không làm chết các user khác; tầng toàn hệ thống đảm bảo tổng chi phí không vượt ngân sách dù có nhiều user.
- Nếu Redis lỗi, `check_budget` trả 503 (fail closed) thay vì cho qua, vì cost guard là lớp bảo vệ tiền.
- Khác đề ở một điểm: đề kiểm tra `current + estimated_cost > 10` rồi cộng luôn; tôi kiểm tra **số đã tiêu** trước khi gọi LLM và ghi chi phí **thực** sau khi gọi (vì chỉ biết số token của câu trả lời sau khi có câu trả lời). Hệ quả: request cuối cùng có thể làm tổng vượt budget một chút.
- Hạn chế còn lại: `user_id` do client tự khai, nên một client có thể đổi `user_id` để né budget theo-user (budget toàn hệ thống vẫn chặn được tổng). Ở production thật phải lấy user từ danh tính đã xác thực (JWT `sub`) thay vì từ body.

Kiểm chứng bằng Redis thật, 2 worker, `USER_MONTHLY_BUDGET_USD=0.00003` (mỗi request ≈ 0,0000125 USD), `DAILY/MONTHLY_BUDGET_USD=1000`:

```text
alice gọi 5 lần:  200 200 200 402 402
bob (user khác):  200 200              <- không bị ảnh hưởng

cost:user:81b637d8fcd2c6da:2026-11 = 0.0000237     (bob)
cost:user:2bd806c97f0e00af:2026-11 = 0.00003735    (alice, vượt 0.00003 ở request thứ 3 nên request thứ 4 bị chặn)
```

Kiểm chứng tầng toàn hệ thống, `DAILY_BUDGET_USD=0.00004`: 4 request đầu 200, request thứ 5 và 6 trả `402 {"detail":"Daily budget exhausted"}`; key `cost:day:2026-11-25` và `cost:month:2026-11` đều có TTL (172800 s và 3024000 s).

Khác biệt giữa hai lớp bảo vệ: rate limit bảo vệ **tốc độ** (chặn bot/spam, trả 429), cost guard bảo vệ **tiền** (kể cả người dùng hợp lệ gọi đều đặn vẫn bị chặn khi hết ngân sách, trả 402). Cần cả hai: gọi chậm mà đều vẫn có thể đốt hết ngân sách, còn gọi nhanh nhưng rẻ thì chỉ cần rate limit.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

- `GET /health` (liveness): trả 200 kèm uptime và kiểm tra memory khi process còn sống. Fail → platform **restart** container.
- `GET /ready` (readiness): trả 200 khi đã khởi động xong và không đang shutdown, 503 nếu chưa sẵn sàng. Fail → load balancer **ngừng route traffic** nhưng không restart.

```bash
$ curl -i localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":3.8,...,"checks":{"memory":{"status":"ok","used_percent":86.4}}}
$ curl -i localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

Ở Part 6 tôi áp dụng đúng quy tắc này: `/health` **không** phụ thuộc Redis (luôn 200 khi process sống, để Redis chết không làm platform restart agent vô ích), còn `/ready` ping Redis và trả **503** khi Redis mất kết nối hoặc đang shutdown.

### Exercise 5.2: Graceful shutdown

Gửi một request `POST /ask` rồi `kill -TERM` ngay sau 50 ms:

```text
[request] HTTP 200 sau 3.015151s            <- request đang chạy vẫn hoàn tất
INFO:     Shutting down
INFO:     Waiting for application shutdown.
... INFO 🔄 Graceful shutdown initiated...
... INFO ✅ Shutdown complete
INFO:     Finished server process [15140]
```

Request đang chạy vẫn trả 200 sau khi process nhận SIGTERM, rồi mới thoát. Cơ chế: uvicorn bắt SIGTERM, ngừng nhận kết nối mới, chờ request in-flight xong (`timeout_graceful_shutdown`), sau đó chạy phần sau `yield` của `lifespan` để dọn dẹp. Lưu ý: nếu tự đăng ký signal handler SIGTERM thì phải gọi lại handler của uvicorn, nếu không process không bao giờ tắt. Ở Part 6, `docker stop` mất 0,5 giây và exit code 0 (script chấm kiểm tra).

### Exercise 5.3: Stateless design

Đề yêu cầu refactor đoạn code lưu hội thoại trong RAM thành lưu trong Redis. Tôi làm việc này trong agent Part 6 bằng module mới `06-lab-complete/app/history.py`.

**Trước (anti-pattern):** state nằm trong biến toàn cục của process.

```python
conversation_history = {}                      # RAM của TỪNG worker / instance

@app.post("/ask")
def ask(user_id: str, question: str):
    history = conversation_history.get(user_id, [])
    ...
    conversation_history[user_id] = history + [...]
```

Hỏng khi chạy `uvicorn --workers 2` hoặc nhiều instance: request thứ hai rơi vào worker khác thì không thấy hội thoại; restart là mất hết.

**Sau (stateless):** mỗi user có một Redis list `history:<hash(user_id)>`.

```python
def append_turn(user_id, question, answer):
    pipe.rpush(key, json.dumps({"role": "user", "content": question}))
    pipe.rpush(key, json.dumps({"role": "assistant", "content": answer}))
    pipe.ltrim(key, -HISTORY_MAX_MESSAGES, -1)   # chỉ giữ N tin nhắn gần nhất
    pipe.expire(key, 7 * 24 * 3600)              # tự dọn sau 7 ngày

def get_history(user_id):
    return [json.loads(m) for m in r.lrange(key, 0, -1)]
```

`/ask` gọi `append_turn` khi có `user_id`, và có thêm `GET /history/{user_id}` (cần `X-API-Key`) để đọc lại. Đây là tính năng phụ: nếu Redis lỗi thì bỏ qua, không làm hỏng `/ask` (khác rate limiter và cost guard, vốn là lớp bảo vệ nên fail closed).

Kiểm chứng (Redis thật, `uvicorn --workers 2`, user `alice` gọi `/ask` 3 lần thành công):

```text
history trước restart:       count 6 | tin đầu: {'role': 'user', 'content': 'What is deployment?'}
(kill agent, khởi động lại)
history SAU khi restart:     count 6
GET /history/alice không key: 401
```

Trên Railway (URL public, user tạm `demo-<timestamp>`, 2 lần `/ask`): `GET /history/<user>` trả `count 4`, vai trò `['user','assistant','user','assistant']`.

Ngoài ra bản `05-scaling-reliability/production/app.py` có sẵn cùng nguyên tắc (`setex(f"session:{id}", ...)`), và Exercise 5.4/5.5 bên dưới chứng minh nó chạy được trên 3 instance. Lý do chung: khi scale ra nhiều instance mỗi instance có RAM riêng, còn Redis là nơi chung mà instance nào cũng đọc được.

### Exercise 5.4: Load balancing (3 instance sau Nginx)

```bash
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
agent-1 / agent-2 / agent-3 (healthy), redis (healthy), nginx

# 10 request lần lượt, cột 2 là served_by
1 instance-7a72e9      6 instance-ddc556
2 instance-19b1c0      7 instance-7a72e9
3 instance-ddc556      8 instance-19b1c0
4 instance-7a72e9      9 instance-ddc556
5 instance-19b1c0     10 instance-7a72e9
```

Nginx chia round-robin đều cho 3 instance (7a72e9, 19b1c0, ddc556 luân phiên).

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: 59610376-10f6-4f19-b27b-68866e457d23
Request 1: [instance-19b1c0]  Request 2: [instance-ddc556]  Request 3: [instance-7a72e9]
Request 4: [instance-19b1c0]  Request 5: [instance-ddc556]
Total requests: 5
Instances used: {'instance-ddc556', 'instance-7a72e9', 'instance-19b1c0'}
✅ All requests served despite different instances!
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

5 request trong cùng một session đi qua 3 instance khác nhau mà history vẫn đủ 10 tin nhắn, vì state nằm ở Redis. Tôi còn thử thêm: `docker stop k5-day14-scaling-agent-1` rồi gửi tiếp 4 request cùng `session_id`: Nginx chuyển hết sang 2 instance còn lại (7a72e9, 19b1c0), request vẫn 200 và history đếm được 10 tin nhắn của session đó.

## Part 6: Kết quả `check_production_ready.py`

Chạy trong `06-lab-complete/` với Docker (chế độ đầy đủ), exit code 0:

```text
📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Ghi chú kết quả: image cuối **207 MB** (< 500 MB); `docker stop` mất 0,5 giây, exit code 0; rate limit trả 429 sau đúng 5 request (`RATE_LIMIT_PER_MINUTE=5`) và vẫn bị chặn sau khi restart agent (state nằm trong Redis); cost guard trả 402 ở request đầu tiên khi budget 0,000001 USD (Redis tạm dùng chung cho cả script nên đã có chi phí tích luỹ từ các bước test trước).

Các quyết định thiết kế chính trong `06-lab-complete/app/`:

- `config.py`: đọc mọi cấu hình từ biến môi trường; `AGENT_API_KEY` mặc định rỗng và khi rỗng thì **từ chối mọi request** (an toàn khi quên cấu hình).
- `auth.py`: `secrets.compare_digest` để so sánh key hằng thời gian; thiếu hoặc sai key đều trả 401.
- `rate_limiter.py`: sliding window bằng Redis sorted set, kiểm tra và ghi trong **một Lua script** nên atomic giữa 2 worker; key Redis dùng hash SHA-256 của API key thay vì key thật; 429 kèm `Retry-After`.
- `cost_guard.py`: budget theo ngày, theo tháng và theo từng user (xem Exercise 4.4).
- `history.py`: lịch sử hội thoại trong Redis, `GET /history/{user_id}` (xem Exercise 5.3).
- `redis_client.py`: `redis.from_url()` không kết nối ngay nên app vẫn khởi động được khi chưa có Redis; timeout 1 giây để `/ready` không treo.
- `main.py`: log JSON mỗi dòng (middleware ghi `method`, `path`, `status`, `ms`); handler lỗi trả JSON rõ ràng (422 liệt kê trường lỗi, 500 chỉ trả "Internal server error", stack trace chỉ nằm trong log nội bộ); lifespan đặt cờ `shutting_down` và đóng Redis.
- Nếu Redis lỗi trong lúc xử lý `/ask`, rate limiter và cost guard trả 503 (fail closed) thay vì bỏ qua giới hạn.
- `Dockerfile`: 2 stage (builder tạo venv, runtime chỉ copy venv), `python:3.11-slim`, user non-root, `HEALTHCHECK`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000}"]` để uvicorn là PID 1.

## AI log

> Theo RULES.md mục 1. Các code và số đo bên dưới được tạo trong các phiên làm việc với Claude Code (agent chạy trong terminal của tôi); mọi con số lấy từ lệnh chạy thật trong phiên đó.

| # | Hỏi gì | Nhận gì | Tôi tự sửa / kiểm tra thế nào |
|---|--------|---------|-------------------------------|
| 1 | Đọc repo và hỏi cần chuẩn bị gì trước khi làm lab | Danh sách điều kiện (Python 3.11+, Docker, Railway CLI, tài khoản cloud) và lộ trình theo CP0–CP8 | Chạy `python --version`, `docker compose version`, `railway whoami` để kiểm tra từng điều kiện trên máy |
| 2 | Viết các TODO của Part 6 (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) | Bản cài đặt đầy đủ như mô tả ở mục Part 6 | Chạy `check_production_ready.py --static-only` (28/28 check tĩnh), rồi bản đầy đủ với Docker: `PASS 12/12`. Tự thử thêm cost guard với Redis thật (402 ở request thứ 5) |
| 3 | Chạy Part 1, 2, 4, 5 và ghi kết quả | Các lệnh chạy và output ở trên | Số đo (MB, HTTP code, `served_by`) là output thật của lệnh, không chép từ README. Tôi chỉ che token JWT |
| 4 | Sau khi tự chấm, sửa các điểm yếu: cost guard theo từng user (Exercise 4.4), lịch sử hội thoại trong Redis (Exercise 5.3), bổ sung câu trả lời Exercise 2.1 | `app/cost_guard.py` mới, `app/history.py`, endpoint `/history/{user_id}` | Lần đầu code lỗi 500 do thiếu `import hashlib`, tôi đọc log để tìm ra rồi sửa. Test lại bằng Redis thật (alice 402, bob vẫn 200; history còn nguyên sau restart), chạy lại script chấm: vẫn `PASS 12/12`, redeploy Railway rồi gọi `/history` trên URL public |
| 5 | Chạy Part 7: load test, eval, sửa `KNOWLEDGE_BASE`, stack Docker | Xem `BENCHMARK_REPORT.md` | Số trong report khớp file JSON/CSV trong `reports/` và `benchmark-results/`. Phát hiện và sửa lỗi Dockerfile của Part 7 (xem mục Lỗi gặp phải trong BENCHMARK_REPORT) |

## Lưu ý về Docker Hub

Trong lúc build stack Part 7 gặp một lần `429 Too Many Requests` khi tải `python:3.11-slim` (giới hạn pull ẩn danh của Docker Hub). Chờ vài giây rồi `docker pull` lại là qua, không cần đổi code.
