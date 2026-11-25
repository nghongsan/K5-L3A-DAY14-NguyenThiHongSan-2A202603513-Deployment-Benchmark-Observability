# Deployment Information

## Public URL
https://agent-production-541c6525.up.railway.app

## Platform
Railway (project `k5-day14-agent`: service `agent` build bằng `Dockerfile` + service `Redis`). Deploy thư mục `06-lab-complete/`.

## Test Commands

```bash
BASE=https://agent-production-541c6525.up.railway.app
# AGENT_API_KEY là biến môi trường đã đặt trên Railway (không ghi trong repo)

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"    # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy ngày 2026-11-25: `200`, `200`, `401`, `200`.

Ví dụ gọi có key:

```bash
curl -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."}
```

Ví dụ đọc lại lịch sử hội thoại (lưu trong Redis):

```bash
curl "$BASE/history/test" -H "X-API-Key: $AGENT_API_KEY"
# {"user_id":"test","count":2,"messages":[{"role":"user",...},{"role":"assistant",...}]}
```

## Environment Variables Set (chỉ tên, không ghi giá trị)

| Biến | Đặt ở đâu |
|---|---|
| `AGENT_API_KEY` | Railway variables (secret, sinh ngẫu nhiên) |
| `REDIS_URL` | Railway variables, tham chiếu `${{Redis.REDIS_URL}}` tới service Redis |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | Railway tự cấp, Dockerfile đọc `${PORT:-8000}` |
| `USER_MONTHLY_BUDGET_USD`, `MONTHLY_BUDGET_USD`, `HISTORY_MAX_MESSAGES` | Không đặt trên platform, dùng giá trị mặc định trong code (10.0, 10.0, 20) |

Danh sách biến thật đang đặt trên Railway (secret đã che): [screenshots/railway-variables.png](screenshots/railway-variables.png).

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png): ảnh chụp thật dashboard Railway (service `agent` và `Redis` đều Online)
- [Biến môi trường trên Railway](screenshots/railway-variables.png): ảnh chụp thật giao diện Railway (tab Variables của service `agent`, 6 service variables), giá trị secret đã che
- [Service running](screenshots/running.png): trình duyệt mở `/health` của URL public
- [Test results](screenshots/test.png): ảnh chụp màn hình terminal thật khi chạy 4 lệnh ở trên trên URL public, kết quả `200 / 200 / 401 / 200`
