# Day 06 · Data Ingestion Engineering

> ## Bài làm — Phạm Như Long (2A202603395, L3A)
>
> **Corpus:** 10 PEP (Python Enhancement Proposals; public domain / CC0), gồm 130 đơn vị nội dung ≥1.500 ký tự. Xem [data/manifest.json](data/manifest.json).
> **Model:** `sentence-transformers/all-MiniLM-L6-v2` (bản ONNX, 384 chiều, chạy local bằng onnxruntime, chi phí $0).
> **Store:** PostgreSQL 16 + pgvector 0.8.7, khoảng cách cosine, tìm kiếm exact.
> **Benchmark:** 22 câu (16 dev / 6 test, 4 câu có filter), xem [benchmark/questions.json](benchmark/questions.json).
> **Báo cáo:** [report/individual/2A202603395_PhamNhuLong.md](report/individual/2A202603395_PhamNhuLong.md)
>
> ### Chạy lại
>
> ```bash
> cd starter
> python3 -m venv .venv && source .venv/bin/activate
> python -m pip install -r requirements.txt
> cp .env.example .env                       # DATABASE_URL, PSQL_BIN
> docker compose -p day6_student_starter up -d --wait   # PostgreSQL 16 + pgvector 0.8.7
> # nếu máy không có psql: đặt PSQL_BIN="docker exec -i day6_student_starter-postgres-1 psql"
> #   và DATABASE_URL=postgresql://day6:day6_local_only@localhost:5432/day6_lab (cổng bên trong container)
> bash scripts/download_model.sh             # model.onnx + tokenizer.json (90 MB, có kiểm tra sha256)
> python -m scripts.check_embedder           # so với giá trị similarity trên model card: 0.6660 / 0.1046
> python -m src.run all                      # ingest → verify-benchmark → index → evaluate → audit-samples
> python -m scripts.audit_metrics            # gộp nhãn thủ công → results/metrics_tables.md
> ```
>
> | Thư mục / file | Nội dung |
> |---|---|
> | `starter/src/` | ingestion, chunking, embeddings, store (pgvector qua `psql`), evaluation, run |
> | `data/corpus/peps/` · `data/manifest.*` · `data/processed/units.jsonl` | dữ liệu gốc, manifest (nguồn, giấy phép, unit, số ký tự), các unit đã chuẩn hóa |
> | `benchmark/questions.json` | câu hỏi, split, gold source/unit, evidence, filter |
> | `results/` | `run_log.txt`, `index_stats.json`, `traces.jsonl` (top-3 đầy đủ), `retrieval_summary.json`, `per_question.csv`, `strategy_choice.md`, `audit/` (nhãn thủ công), `metrics_tables.md` |
> | `artifacts/experiment_log.csv` | cấu hình và giả thuyết của A/B/C |
>
> ---

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
