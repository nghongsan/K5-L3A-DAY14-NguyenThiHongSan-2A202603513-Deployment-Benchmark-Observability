# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ `reports/*.json`, `benchmark-results/*.csv`, ảnh trong `screenshots/` và các lệnh đã chạy ngày 2026-11-25.

**Họ tên:** Nguyễn Thị Hồng Sản
**Ngày chạy:** 2026-11-25
**Môi trường:** MacBook Air Apple M1 (8 CPU, 8 GB RAM), Docker Desktop cấp 8 CPU / 3,8 GB RAM, Python 3.12.3. Load generator và agent chạy **trên cùng một máy**, nên số đo bị ảnh hưởng bởi việc hai bên tranh CPU.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Câu trả lời LLM thường tính bằng giây; với mock có latency nền ~120–180 ms, 500 ms nghĩa là người dùng không thấy chậm. Dùng p95 vì 95% người dùng đều trải nghiệm được ngưỡng này, còn trung bình che mất tail (xem 2.2). Cũng là ngưỡng mặc định của `load_test.py` |
| Error rate `/ask` | < 2 % | Nguồn lỗi chính là upstream LLM 503 (mock đặt 1%). 2% cho phép dao động nhưng đủ chặt để thấy khi upstream xấu đi. Cùng ngưỡng mặc định của `load_test.py` (alert trong Prometheus đặt lỏng hơn, 5%, để tránh báo giả) |
| Accuracy trên golden dataset | ≥ 85 % | Ngưỡng quality gate của job CI (Exercise 7.3). Bản v2 sau khi sửa đạt 100% (23/23), ngưỡng 85% cho phép dư chút khi thêm câu hỏi mới nhưng vẫn chặn được regression lớn |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

Nguồn: `reports/load_v2_c{1,10,50,100}.json`. Agent v2 chạy local ở cổng 8002, một process uvicorn, `MOCK_SLOW_RATE` mặc định 0,03.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4,21 | 194,9 | 269,9 | 1717,2 | 1,67 % (5/300) | PASS |
| 10 | 37,52 | 191,7 | 221,1 | 1705,9 | 1,33 % (4/300) | PASS |
| 50 | 123,37 | 190,4 | 228,4 | 1685,3 | 1,00 % (3/300) | PASS |
| 100 | 51,00 | 650,0 | 3734,1 | 4036,5 | 0,67 % (2/300) | **FAIL** (p95) |

**Nhận xét:** RPS tăng gần tuyến tính từ 1 → 10 (4,21 → 37,52, ×8,9) vì mỗi request chủ yếu là chờ (mock LLM `sleep` ~190 ms, không tốn CPU) nên nhiều request chồng lên nhau. Từ 10 → 50 tăng chậm hơn (×3,3 so với ×5 của concurrency), và ở 100 thì **RPS giảm** (123 → 51) cùng lúc p95 vọt từ 228 ms lên 3734 ms, vi phạm SLO. Tôi chạy lại riêng mức 100 một lần nữa và kết quả tương tự (57 RPS, p50 360 ms, p95 3441 ms), nên đây không phải nhiễu một lần. Tôi **không đo trực tiếp** nguyên nhân; giả thuyết hợp lý nhất là điểm bão hòa của một process Python đơn luồng (event loop của agent) cộng với việc load generator Python cũng chạy trên cùng máy và phải mở 100 kết nối đồng thời trong một lần chạy chỉ kéo dài ~6 giây (300 request), nên thời gian khởi tạo kết nối chiếm tỉ trọng lớn. Để kiểm chứng cần chạy `--duration` dài hơn hoặc tách load generator sang máy khác. Error rate thấp ở mọi mức và không tăng theo tải: lỗi đến từ upstream mock 1%, không phải do quá tải.

### 2.2 Tail latency (agent v2, `--requests 300 --concurrency 20`)

Nguồn: `reports/load_v2_slow_{0,0.03,0.1}.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 190,1 | 220,4 | 241,4 |
| 0.03 (mặc định) | 254,8 | 478,0 | 1710,9 |
| 0.1 | 334,1 | 1690,3 | 1721,0 |

**Nhận xét:** từ 0 lên 0,03, avg chỉ tăng +65 ms (×1,3) trong khi p99 tăng +1470 ms (×7,1). Từ 0 lên 0,1, avg tăng +144 ms (×1,8) nhưng p95 tăng ×7,7 và p99 ×7,1. Lý do: request "slow" chỉ chiếm một phần nhỏ nên chỉ kéo trung bình lên theo tỉ lệ (0,03 × 1500 ms ≈ 45 ms; 0,1 × 1500 ms ≈ 150 ms, khớp với mức tăng avg đo được), nhưng khi tỉ lệ vượt 1% thì chúng chiếm đúng vị trí percentile thứ 99, và vượt 5% thì chiếm cả p95. Chỉ số nhạy nhất với request chậm là **p99, rồi p95**. SLO không nên đặt theo average vì avg 254 ms trông ổn (< 500 ms) trong khi 1–3% người dùng đang chờ gần 1,7 giây. Điều này cũng giải thích p99 ≈ 1700 ms ở mọi dòng của bảng 2.1: đó là đúng `MOCK_SLOW_MS` (1500 ms) cộng latency nền.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Golden dataset 23 câu (không sửa).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4,3 % (1/23) | 91,3 % (21/23) | **100 % (23/23)** |
| Avg tokens / câu | 56,7 | 109,0 | 113,7 |
| Tổng cost (USD) | 0,000399 | 0,000760 | 0,000790 |
| Cost / câu đúng (USD) | 0,00039855 | 0,00003619 | 0,00003436 |
| Quality gate | FAIL (accuracy < 80%) | PASS | PASS (`--min-accuracy 1.0`, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` (`develop/utils/mock_llm.py`) kích hoạt bởi `jwt`, nội dung nói rõ API key là chuỗi cố định không hết hạn còn JWT là token có chữ ký số, chứa thời điểm hết hạn |
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry kích hoạt bởi `hpa`, `kubernetes`, `autoscal`, nội dung liệt kê CPU, memory, custom metrics |

Trước khi sửa, v2 trả lời hai câu này bằng câu chung chung ("Tôi là AI agent được deploy lên cloud...") vì không có tài liệu nào khớp từ khóa. Sau khi sửa: `Câu được cải thiện: 2`, `Câu bị regression: 0`, exit code 0. Tôi không sửa `golden_dataset.jsonl`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 có thêm bước retrieval nên prompt dài hơn: tokens trung bình tăng ×1,9 (56,7 → 109,0) và tổng cost cũng ×1,9. Nhưng accuracy tăng từ 4,3% lên 91,3%, nên **cost trên mỗi câu đúng giảm khoảng 11 lần** (0,000399 → 0,0000362). Đây là lý do nên so sánh bằng "cost / câu đúng" chứ không phải "cost / câu": v1 rẻ hơn mỗi câu nhưng gần như không trả lời đúng gì nên tiền bỏ ra là vô ích. Latency p95 trong eval gần như không đổi giữa v1 và v2 (205,3 → 218,5 ms) vì retrieval chỉ thêm ~20 ms (`MOCK_RETRIEVAL_MS`).

Lưu ý khi đọc cột cuối: latency p95 của lần eval cuối là 1537,4 ms (so với 218,5 ms), không phải do tôi sửa knowledge base mà do ngẫu nhiên: eval chỉ có 23 request nên chỉ cần 2 request rơi vào nhóm "slow" (`MOCK_SLOW_RATE=0.03`, +1500 ms) là p95 nhảy vọt. Lần chạy kiểm tra exit code sau đó tôi tắt `MOCK_SLOW_RATE` nên không bị ảnh hưởng. Đây cũng là minh họa vì sao p95 trên mẫu nhỏ không đáng tin.

**Quality gate với exit code (Exercise 7.3, bài tập 4):**

- `run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json` (v1 so với baseline v2) → **exit code 1**, `Câu bị regression: 20`, gate FAIL. Chính exit code này chặn merge trong CI.
- v2 đã sửa với `--min-accuracy 0.85` → **exit code 0**.
- Job CI: [.github/workflows/eval.yml](.github/workflows/eval.yml) khởi động agent v2, chạy `run_eval.py --min-accuracy 0.85`. Bước nào trả exit code khác 0 thì job fail; bật "Require status checks to pass" cho check `quality-gate` trong branch protection thì PR không merge được. Workflow tắt `MOCK_ERROR_RATE` và `MOCK_SLOW_RATE` để eval không bị nhiễu ngẫu nhiên. (Tôi chưa chạy workflow này trên GitHub Actions, chỉ chạy các lệnh tương đương ở local.)

---

## 4. Observability stack (production)

Chạy bằng `docker compose -p k5-day14-observability up -d --build --scale agent=...` trong `06-lab-complete/benchmark-observability/production/`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png) (3 instance, 100 user Locust)
- [x] Một trace chậm trong Jaeger: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (503, span đánh dấu lỗi): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus có ≥ 2 alert đang firing: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png) (`LLMCostBurnRateHigh`, `AgentHighErrorRate`, `AgentInstanceDown` cùng firing, `AgentHighLatencyP95` đang pending)

Ảnh được chụp bằng Chrome chạy headless từ dòng lệnh; trong ảnh Jaeger, event `exception` nằm trong chi tiết của span lỗi (đã xác nhận qua API của Jaeger: span `chat mock-llm-small` và `agent.run` đều có event `exception`).

Trả lời Exercise 7.4:

1. **p95 và avg:** Locust 100 user, 3 instance (`scale_3_stats.csv`, `/ask`): avg 237,7 ms, p50 190 ms, p95 240 ms, p99 1700 ms. Grafana lúc có tải hiển thị p95 ≈ 294 ms. Avg và p95 gần nhau, còn p99 cao gấp ~7 lần: đa số request nhanh đồng đều, có một nhóm nhỏ (~3%) chậm bất thường, đúng với `MOCK_SLOW_RATE` mặc định.
2. **Nginx chia đều không:** trong lần đo trên stack 2 instance, số request `/ask` mỗi instance: 812 (49,9%) và 816 (50,1%). Có chia đều. Lưu ý khi scale lên 3 giữa chừng thì instance mới chỉ nhận traffic sau khi Nginx hỏi lại DNS (chu kỳ 10 giây), nên đầu lần chạy panel "Requests/s theo instance" chưa thấy đủ 3 đường (có thể thấy trong ảnh Grafana).
3. **Vì sao input tokens/s lớn hơn output:** prompt gồm system prompt + tài liệu retrieval + câu hỏi (trung bình ~91 token) còn câu trả lời chỉ ~55 token. Đo được 348 input vs 184 output token/s với agent v2.
4. **`curl http://localhost:8080/metrics`:** trả **404** (đã kiểm tra). Nginx chủ động chặn `/metrics` để người ngoài không đọc được số liệu nội bộ; Prometheus scrape trực tiếp từng agent trong mạng Docker.

Trả lời Exercise 7.1: Counter: `http_requests_total`; Gauge: `agent_in_flight_requests`; Histogram: `http_request_duration_seconds_bucket`. Nếu dùng `request.url.path` làm label `route` thì mỗi URL lạ mà bot quét (`/wp-admin`, `/.env`, `/a1b2c3`...) tạo một time series mới. Số series tăng không giới hạn (cardinality explosion), Prometheus tốn RAM/disk và truy vấn chậm dần đến chết; dùng route template cho phép gom tất cả vào `unmatched`. Tôi đã thêm metric `agent_question_length_chars` (Histogram) vào `develop/app.py`: sau 1 request, `agent_question_length_chars_count 1.0` và `_sum 40.0`.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust 10 user (~6 req/s) để baseline chi phí (0,63 USD/giờ) nằm dưới ngưỡng 2 USD/giờ. Mỗi lần đổi cấu hình bằng `.env` rồi `docker compose up -d`. Thời gian là từ lúc lệnh `up -d` trả về đến lúc alert chuyển sang `firing` (ghi bằng script poll `/api/v1/alerts`, 2 giây/lần).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (pending sau ~34 s) | **96 s** | Error rate (stat) và "Requests/s theo status code" (đường 503) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 đo được 1,92 s, p50 0,24 s, avg 0,67 s) | **142 s** | "Latency /ask — p50/p95/p99": p95/p99 vọt, p50 gần như phẳng |
| C | `LLM_MODEL=mock-llm-large` (giữ A) | `LLMCostBurnRateHigh` | **192 s** (cost burn 5,6 USD/giờ lúc firing, baseline 0,63) | "Cost burn rate (USD/giờ)" |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` | **40 s** (`for: 30s` + chu kỳ scrape) | "Instances up" giảm xuống 1 |
| E | `AGENT_VERSION=v1` | **Không có alert mới** (quan sát 15:55 → 15:59) | Không firing | "Retrieval hit ratio" mất, Tokens/s giảm (input 348 → 226, output 184 → 123), bảng "Phiên bản đang chạy" đổi sang v1 |

Ghi chú:

- A, C, D chạy chồng nhau: lúc 15:52:08 cả `AgentHighErrorRate`, `LLMCostBurnRateHigh` và `AgentInstanceDown` cùng firing (ảnh `prometheus-alert-firing.png`), còn `AgentHighLatencyP95` ở trạng thái pending (tôi chưa tách riêng nguyên nhân; có thể do model large chậm hơn 2,5 lần và/hoặc request tới instance bị pause phải chờ timeout, nhưng không đo riêng từng yếu tố).
- C chậm hơn A và D vì rule dùng cửa sổ 5 phút (`rate(...[5m])`) nên phải đợi chi phí mới kéo trung bình 5 phút vượt 2 USD/giờ, cộng thêm `for: 2m`. Alert theo cửa sổ dài thì ổn định nhưng phát hiện chậm.
- Ở thí nghiệm E, `LLMCostBurnRateHigh` vẫn đang firing lúc đổi cấu hình (dư lượng của B/C) và tự về inactive lúc 15:56:29; từ đó đến 15:59:27 không có alert nào firing, dù chất lượng giảm từ 91,3% xuống 4,3% accuracy.
- Mỗi lần recreate container, `AgentInstanceDown` nhảy `pending` vài giây rồi về inactive mà không bao giờ firing (nhờ `for: 30s`): đúng vai trò của `for` là lọc spike ngắn.
- Sau lần chạy tải nặng 100 user (mục 5, kết thúc khoảng 15:41), `LLMCostBurnRateHigh` vẫn firing đến 15:45:08 vì cửa sổ 5 phút còn dư tải cũ; tôi chờ nó về inactive rồi mới đo baseline.
- `promtool test rules prometheus/alert_rules_test.yml` báo `SUCCESS`.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Các alert hạ tầng chỉ nhìn thấy tốc độ, lỗi HTTP, độ chậm, tình trạng sống; agent v1 vẫn trả 200 nhanh (p95 0,218 s, error 0,6%) nhưng trả lời sai gần hết (accuracy 4,3%). Muốn bắt loại sự cố "chất lượng giảm" cần: (1) **chạy eval trước mỗi lần deploy** với golden dataset và chặn bằng quality gate (đã làm ở mục 3, đúng thí nghiệm này sẽ làm eval FAIL với 20 regression); (2) **metric về chất lượng/hành vi** như retrieval hit ratio (panel này giảm về 0 ngay khi chuyển v1) và đặt alert trên đó; (3) eval/canary định kỳ trên traffic thật (LLM-as-judge hoặc phản hồi 👍/👎 của người dùng) vì chính mock cũng chỉ là mô phỏng.

Lỗi cần ghi lại: `docker compose run locust` mặc định **khởi động lại các service phụ thuộc theo `replicas: 2`**, nên lần chạy `scale_1` đầu tiên thực ra có 2 instance (tôi nhận ra khi thấy "Instances up = 2" trên dashboard). Tôi dừng, xóa file CSV đó, scale về 1 instance và chạy lại với `docker compose run --rm --no-deps locust ...`; kết quả nộp là lần chạy đúng 1 instance.

Lỗi cần ghi lại (2): `Dockerfile` có sẵn của stack production (`06-lab-complete/benchmark-observability/production/Dockerfile`) khiến agent crash-loop với `ModuleNotFoundError: No module named 'uvicorn'`, vì user `agent` được tạo với home `/app` trong khi package được copy sang `/home/agent/.local`. Tôi sửa bằng `useradd -r -g agent -d /home/agent -m agent` (kèm comment giải thích); sau đó agent khỏe (`healthy`).

### 4.3 Debug bằng trace

Trace chậm nhất trong 1500 trace gần nhất (xếp theo tổng thời gian, lấy qua Jaeger API):

- `trace_id`: `5f8226348f412cf044832d3c37b55dd5`
- Tổng thời gian: **1793,2 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1648,5 ms, 91,9 %** tổng thời gian). Các span còn lại: `POST /ask` 1793,2 ms (root), `agent.run` 1671,1 ms, `agent.retrieve_context` 22,4 ms. Nghĩa là gần như toàn bộ độ trễ nằm ở lời gọi LLM (đây là request "slow" mock +1500 ms); retrieval chỉ 22 ms.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T08:40:44.725984+00:00", "level": "INFO", "service": "observable-agent", "instance": "306cec9571fd", "event": "llm_call", "trace_id": "5f8226348f412cf044832d3c37b55dd5", "span_id": "a2a04adc9c65712c", "request_id": "5e0f63c1b547", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1647.0}
{"ts": "2026-11-25T08:40:44.726640+00:00", "level": "INFO", "service": "observable-agent", "instance": "306cec9571fd", "event": "http_request", "trace_id": "5f8226348f412cf044832d3c37b55dd5", "span_id": "a2a04adc9c65712c", "request_id": "5e0f63c1b547", "method": "POST", "route": "/ask", "status": 200, "ms": 1792.5}
```

Log khớp trace: `llm_ms` 1647,0 ≈ span LLM 1648,5 ms; `ms` 1792,5 ≈ trace 1793,2 ms.

Trace lỗi: `trace_id` `e1fca5c78ae57affc916b1c266c69f38`, 144,4 ms, status 503. Span `chat mock-llm-small` (121,4 ms) và `agent.run` có event `exception`. Log cùng `trace_id`:

```json
{"ts": "2026-11-25T08:40:56.748493+00:00", "level": "INFO", "service": "observable-agent", "instance": "dfea99fa5ace", "event": "llm_error", "trace_id": "e1fca5c78ae57affc916b1c266c69f38", "span_id": "3474c6f6409ba917", "request_id": "9cebe55c8dd6", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T08:40:56.749687+00:00", "level": "INFO", "service": "observable-agent", "instance": "dfea99fa5ace", "event": "http_request", "trace_id": "e1fca5c78ae57affc916b1c266c69f38", "span_id": "3474c6f6409ba917", "request_id": "9cebe55c8dd6", "method": "POST", "route": "/ask", "status": 503, "ms": 143.8}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Nguồn: `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv`, dòng `/ask`. Lần chạy 1 instance đã xác nhận bằng `docker compose ps` (1 container agent) và Prometheus (1 target `up`); lần 3 instance xác nhận 3 target `up`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59,27 | 200 | 270 | 1700 | 76 / 7081 (1,07 %) |
| 3 | 59,63 | 190 | 240 | 1700 | 64 / 7120 (0,90 %) |

**Giải thích kết quả:** scale từ 1 lên 3 instance **gần như không đổi gì**: RPS 59,27 → 59,63 (+0,6%), p50 200 → 190 ms, p95 270 → 240 ms (cải thiện nhẹ, nằm trong mức dao động giữa các lần chạy), p99 vẫn 1700 ms. Đây là hệ quả của cách đo chứ không phải scale vô ích. Locust là tải **vòng kín**: mỗi user gửi một request rồi nghỉ 0,5–2 giây trước khi gửi tiếp (`wait_time = between(0.5, 2)`), nên 100 user chỉ tạo ra ~60 req/s bất kể có bao nhiêu instance. 1 instance (async, request chủ yếu là chờ mock LLM) xử lý 60 req/s thoải mái nên chưa bão hòa, thêm instance không có gì để cải thiện. p99 = 1700 ms là đúng 3% request "slow" của mock LLM (`MOCK_SLOW_MS` 1500 ms + latency nền); đây là nút thắt về **tail latency của upstream LLM** (xem panel "LLM latency" trên Grafana và span `chat mock-llm-small` chiếm 91,9% trong trace chậm), thêm bản sao agent không làm LLM nhanh hơn. Muốn thấy lợi ích của scale cần tăng tải đến mức 1 instance bão hòa (nhiều user hơn hoặc `wait_time` ngắn hơn); scale ngang còn có giá trị khác ngoài hiệu năng là **tính sẵn sàng** (thí nghiệm D: pause 1 instance, hệ thống vẫn phục vụ nhờ instance còn lại). Failures (~1%) là 503 từ upstream mock (`MOCK_ERROR_RATE=0.01`), nên cũng không phụ thuộc số instance.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Trung bình nói dối, percentile mới nói thật.** Thêm 3% request chậm chỉ làm avg tăng 65 ms nhưng p99 tăng 1470 ms (mục 2.2); nên đặt SLO theo p95/p99. Và percentile trên mẫu nhỏ cũng đáng ngờ: p95 eval 23 request nhảy từ 218 lên 1537 ms chỉ vì 2 request chậm.
  2. **Cách đo quyết định kết quả, phải kiểm chứng điều kiện thí nghiệm.** `scale_1` lần đầu thực ra chạy 2 instance vì `docker compose run` âm thầm khởi động dependency; và scale 1 → 3 không cải thiện RPS vì tải vòng kín bị giới hạn bởi think time. Nếu không kiểm tra, tôi đã nộp một kết luận sai.
  3. **Metric hạ tầng không thấy lỗi chất lượng.** Thí nghiệm E (v1: accuracy 4,3%) không alert nào firing; chỉ eval với golden dataset và quality gate bắt được. Cần cả hai: observability để biết hệ thống khỏe, eval để biết câu trả lời đúng.
- Nếu đưa agent này lên production thật, tôi sẽ thêm:
  - Alert theo **tỉ lệ 5xx tại Nginx/load balancer** và synthetic check từ bên ngoài (metric của agent không thấy lỗi 504 xảy ra ở tầng Nginx).
  - Alert **chất lượng**: retrieval hit ratio thấp bất thường, eval chạy định kỳ trên mẫu traffic thật, tỉ lệ phản hồi tiêu cực của người dùng.
  - Alert **budget theo ngày** (không chỉ burn rate) và per-user, kết hợp cost guard ở Part 6.
  - Alertmanager gửi cảnh báo qua Slack/PagerDuty (hiện stack chỉ hiển thị trạng thái firing trên Prometheus, chưa có kênh thông báo), và dashboard theo SLO / error budget burn.
  - Chính sách giữ log và lấy mẫu (sampling) trace: tôi chưa kiểm tra tỉ lệ lấy mẫu hiện tại của stack, với traffic thật cần đặt có chủ đích để không tốn chi phí lưu trữ.
