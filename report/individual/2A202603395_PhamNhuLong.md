# Báo cáo cá nhân — Day 6

**Học viên:** Phạm Như Long · 2A202603395 · L3A
**Ngày chạy:** 2026-11-14 (UTC 2026-11-13T17:51Z) · **Lệnh:** `cd starter && python -m src.run all && python -m scripts.audit_metrics` · log: [results/run_log.txt](../../results/run_log.txt)

> **Về việc dùng AI (RULES.md).** Code, bộ câu hỏi, các lần chạy và nhãn chấm thủ công đều do trợ lý AI Claude (Anthropic) thực hiện theo yêu cầu của học viên. Học viên đã đọc lại và chịu trách nhiệm giải thích bài làm. Các bước kiểm chứng đã làm:
> - So embedding với giá trị similarity công bố trên model card.
> - Tự động kiểm tra mọi evidence có nằm trong unit gold.
> - Kiểm tra nạp lại không nhân đôi và kiểm tra khi tài liệu bị sửa.
> - Chạy lại toàn bộ pipeline: trace top-3 trùng khớp 100%.
>
> Nhãn thủ công do AI chấm (một người chấm, cũng là bên xây pipeline), nên có nguy cơ thiên lệch. Quy tắc chấm và lý do của từng nhãn nằm trong [results/audit/](../../results/audit/README.md).

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang**
  - **Corpus:** 10 Python Enhancement Proposals (PEP 8, 257, 498, 557, 572, 585, 604, 618, 634, 636), lấy từ snapshot `python/peps@2a71e92` (truy cập 2026-11-14). Mỗi file ghi rõ *"placed in the public domain"* hoặc *"public domain or CC0-1.0-Universal"*, nên được phép xử lý và tái phân phối; các file gốc nằm trong `data/corpus/peps/`.
  - **Quy tắc tính trang:** file reStructuredText không có trang vật lý, nên mỗi PEP (đã bỏ header và mục Copyright) được chia **theo thứ tự** thành các *unit* ≥1.500 ký tự đã chuẩn hóa. Chỉ cắt ở ranh giới đoạn; phần đuôi ngắn được gộp vào unit trước. `page` = số thứ tự unit trong tài liệu, ID có dạng `pep-0572#u07`.
  - **Kết quả:** **130 unit, cả 130 đều ≥1.500 ký tự**, tổng 223.306 ký tự đã chuẩn hóa (từ 254.163 ký tự thô; email tác giả trong header của bản lưu local đã được thay bằng `<email redacted>`). Số unit theo tài liệu: 26 / 5 / 13 / 19 / 26 / 6 / 3 / 7 / 12 / 13.
  - Danh sách unit, số ký tự và giấy phép từng tài liệu nằm trong [data/manifest.json](../../data/manifest.json) và `manifest.csv`.
- **Chuẩn hóa, lỗi và giới hạn**
  - **Các bước chuẩn hóa:**
    - Unicode NFC; chuyển CRLF thành LF, tab thành 4 khoảng trắng, NBSP thành khoảng trắng.
    - Bỏ ký tự điều khiển và khoảng trắng cuối dòng.
    - Heading RST chuyển thành metadata `section`.
    - Bỏ dòng directive nhưng giữ nội dung bên trong, bỏ comment và link target.
    - Gỡ markup inline (`:pep:`, ``code``, `text <url>`_).
    - Bỏ header tác giả và email (chỉ giữ Title, Type, Status, Created, Python-Version) và bỏ mục Copyright.
  - **Log lỗi:** [results/ingestion_log.csv](../../results/ingestion_log.csv) chỉ có các dòng INFO ghi việc bỏ mục Copyright. Không có trang rỗng, không cần OCR.
  - **Giới hạn đã thấy khi đọc unit:**
    - Markup inline trải qua 2 dòng không gỡ được, ví dụ ``` ``for i part establishes that i`` ``` ở `pep-0572#u07` và `` `C implementation <url>`_ `` ở `pep-0618#u03`.
    - `:pep:` chỉ còn lại con số ("484 and 526 propose…").
    - Một directive nhiều dòng ở đầu PEP 585 để sót câu "and the documentation for object.__class_getitem__" vào `pep-0585#u01`.
    - Code mất thụt lề tương đối ở dòng đầu.
- **Embedding, vector store, metric, lệnh chạy và chi phí**
  - **Embedding:** `sentence-transformers/all-MiniLM-L6-v2`, bản export ONNX có sẵn mean pooling (output `sentence_embedding`), **384 chiều**.
    - Nguồn file: `github.com/clems4ever/all-minilm-l6-v2-go@98aaab5` (Apache-2.0), sha256 ghi trong `starter/scripts/download_model.sh`.
    - Chạy bằng onnxruntime 1.29.0 (CPU), numpy 2.5.3, Python 3.13.18.
    - Tokenizer BERT WordPiece được viết lại trong `embeddings.py` (lowercase, bỏ dấu, tối đa 256 token như `max_seq_length` của model), vector được chuẩn hóa L2. Query và document mã hóa giống nhau.
    - **Kiểm chứng** (`python -m scripts.check_embedder`): similarity giữa 3 câu ví dụ trên model card ra **0,6660 / 0,1046 / 0,1411**, trùng giá trị công bố. Kết quả không đổi khi padding (sai khác 1,5e-8).
  - **Vector store:** PostgreSQL 16.15 + **pgvector 0.8.7**. Bảng `chunks` có cột `strategy`, khóa chính `(strategy, chunk_id)`, cột `vector(384)`. Khoảng cách **cosine** (`<=>`), **tìm kiếm exact** (không có index ANN). Filter là mệnh đề `WHERE` so sánh bằng.
  - **Chi phí $0** (model local).
  - **Thời gian** (CPU sandbox, chạy 1 lần):
    - ingest 0,18 s;
    - embedding: A 26,3 s, B 32,0 s; C dùng lại vector của B vì chunk giống hệt;
    - upsert: 0,17 / 0,14 / 0,12 s;
    - evaluate (22 query × 3 chiến lược): 3,3 s;
    - toàn bộ `run all`: 65,7 s.
  - **Ghi chú môi trường:** sandbox không có mạng để cài gói và không có Docker. Vì vậy pgvector được biên dịch từ mã nguồn chính thức (tag v0.8.7, cùng phiên bản với image `pgvector/pgvector:0.8.7-pg16` của starter). `store.py` gọi `psql` thay cho psycopg, truyền tham số qua biến psql `:'var'` để PostgreSQL tự quote, và chỉ cho phép filter trên một whitelist cột. Có thể đổi sang `PSQL_BIN="docker exec -i … psql"` để dùng container.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn**
  - **Bắt buộc:** `document_id` (`pep-0572`), `source` (đường dẫn file), `page` (int = số unit), `unit_id`.
  - **Bổ sung:** `section` (text, heading RST gần nhất), `title`, `status`. Hai trường dùng để lọc:
    - `pep_type` (text, header `Type:`): Process 1 tài liệu / Informational 2 / Standards Track 7.
    - `python_version` (text, header `Python-Version:`; ghi `none` khi header không có, như PEP 8 và 257): 3.6 / 3.7 / 3.8 / 3.9 mỗi bản 1 tài liệu, 3.10 có 4 tài liệu.
  - **Lý do chọn:** mọi giá trị đều đọc trực tiếp từ header của nguồn, không suy đoán. Bộ câu hỏi chỉ dùng các giá trị filter bao trùm **≥2 tài liệu** (Informational, Standards Track, 3.10), để filter không trùng với gold source. Câu hỏi về pattern matching rất cần filter, vì đặc tả (PEP 634, Standards Track) và tutorial (PEP 636, Informational) nói cùng một nội dung.

## Cấu hình và benchmark

- **A / B / C**, cùng corpus, model và store; chunk không bao giờ vượt qua ranh giới unit:
  - **A:** cửa sổ ký tự cố định **500, overlap 50**. `section` lấy theo heading tại ký tự đầu chunk.
  - **B:** gộp các đoạn **cùng heading**, tối đa **1.000 ký tự**, gặp heading mới thì mở chunk mới, đoạn quá dài được cắt ở ranh giới câu, không overlap.
  - **C:** **chunk và vector giống hệt B**. Khác biệt duy nhất giữa B và C là filter metadata (`pep_type` hoặc `python_version`), chỉ áp dụng cho 4 câu có filter đi kèm (d13, d14, d15, t05); các câu khác C chạy không filter.
  - A và B chỉ khác cách chunk (cùng metadata, không filter).
- **≥20 câu** ([benchmark/questions.json](../../benchmark/questions.json)): **22 câu, 16 dev / 6 test**.
  - Loại câu: 7 trực tiếp, 4 diễn đạt lại, 4 có điều kiện, 3 ngoại lệ, 4 cần filter (3 dev: d13, d14, d15; 1 test: t05).
  - Mỗi câu có `expected_answer`, `gold_source_id`, `gold_page` (số unit), `evidence_quote`; t02 có thêm một gold thay thế.
  - **Kiểm chứng evidence:** `python -m src.run verify-benchmark` xác nhận evidence (dạng chuẩn hóa) nằm trong đúng unit gold, giá trị filter tồn tại và unit gold thỏa filter. Kết quả: [results/benchmark_verification.json](../../results/benchmark_verification.json), `ok: true`.
  - Bộ câu hỏi được commit (`bbc8def`) **trước lần truy xuất đầu tiên**.
  - **Nguy cơ rò rỉ:** dev và test dùng chung 5 tài liệu (PEP 8, 257, 498, 557, 572), nhưng test hỏi về các mục khác. Không có tham số nào được chỉnh theo dev: cấu hình A/B/C cố định từ đầu.
- **Tiêu chí chọn, chốt trước khi xem test:** dev Evidence Hit@3 cao nhất; hòa thì xét dev Hit@1; hòa nữa thì xét ít chunk / ingest nhanh hơn.
  - A, B, C hòa nhau ở Hit@3 (10/16). A bị loại ở Hit@1 (4 so với 5). B và C vẫn hòa sau mọi tiêu chí.
  - Tiêu chí phụ được thêm vào sau khi xem dev, **trước khi đọc test**: chọn C vì C bảo đảm phạm vi kết quả khi câu hỏi có filter (ở d13, top-3 của B có một chunk PEP 634 nằm ngoài phạm vi Informational) mà không tốn thêm chi phí. Quyết định được ghi và commit tại [results/strategy_choice.md](../../results/strategy_choice.md).

## Kết quả

*Strict* là chỉ số chính: tự động, so với evidence của gold đã đóng băng. *Adjudicated* là chỉ số phụ: cộng thêm các trường hợp người chấm xác nhận có bằng chứng tương đương ([equivalent_evidence.csv](../../results/audit/equivalent_evidence.csv)), được chấm **sau khi đã xem test**.

| Strategy | Split | Hit@1 strict (n/N) | Evidence Hit@3 strict (n/N) | Hit@1 adjudicated | Hit@3 adjudicated | Chunk count | Thời gian embed | Chi phí |
|---|---|---|---|---|---|---|---|---|
| A | dev | 4/16 | 10/16 | 9/16 | 14/16 | 553 | 26,3 s | $0 |
| A | test | 1/6 | 3/6 | 2/6 | 5/6 | 553 | 26,3 s | $0 |
| B | dev | 5/16 | 10/16 | 6/16 | 12/16 | 399 | 32,0 s | $0 |
| B | test | 2/6 | 3/6 | 3/6 | 5/6 | 399 | 32,0 s | $0 |
| C | dev | 5/16 | 10/16 | 6/16 | 12/16 | 399 | 0 s (dùng lại vector B) + upsert 0,12 s | $0 |
| C | test | 2/6 | 3/6 | 3/6 | 5/6 | 399 | như trên | $0 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) dev · test | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,90 (10): 1×0, 9×1, 0×2 | 13/18 | 2/3 · 0/1 (không áp filter) | 1/0/5 → 1,67 |
| B | 1,70 (10): 0×0, 3×1, 7×2 | 18/18 | 2/3 · 0/1 (không áp filter) | 0/1/5 → 1,83 |
| C | 1,70 (10, cùng chunk với B) | 18/18 | **3/3 · 1/1** | 0/1/5 → 1,83 |

Tài nguyên khác ([results/index_stats.json](../../results/index_stats.json)):

| | A | B / C |
|---|---|---|
| Tổng ký tự (A tính cả overlap) | 244.456 | 222.772 |
| Token | 61.817 | 54.975 |
| Độ dài chunk trung vị / tối đa (ký tự) | 500 / 500 | 560 / 1.000 |
| Chunk dài hơn 256 token, bị model cắt bớt | **4** | **21 (5,3%)** |

Kiểm tra nạp lại: nạp lần hai cùng phiên bản cho kết quả 0 inserted / 0 updated / 0 deleted, số dòng bằng số ID khác nhau (553 / 399 / 399). Mô phỏng sửa PEP 604 (đổi chunk đầu, xóa 2 chunk cuối) cho kết quả updated 1, deleted 2, số dòng từ 14 xuống 12.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace top-3 đầy đủ (text, score, metadata, cờ hit): [results/traces.jsonl](../../results/traces.jsonl). Kết quả từng câu: [per_question.csv](../../results/per_question.csv).
- Nhãn thủ công: [results/audit/](../../results/audit/README.md).
- **Coherence:** 10 vị trí cố định trong code từ trước khi chấm, là ký tự giữa của unit `u02` của mỗi tài liệu.
- **Metadata:** 6 câu test × top-3 = 18 bản ghi mỗi chiến lược.
- **Grounding:** cả 6 câu test.

## Phân tích và kết luận

- **A–B (chỉ đổi cách chunk).**
  - **Retrieval:** strict Hit@3 hòa nhau (dev 10/16, test 3/6), B hơn 1 câu Hit@1 ở mỗi split.
  - **Chunk và metadata:** B tốt hơn rõ rệt về coherence (1,70 so với 0,90) và metadata (18/18 so với 13/18). Cả 5 lỗi của A đều là `section` sai, vì cửa sổ ký tự bắt đầu ở cuối một mục rồi chạy sang mục sau; ví dụ `pep-0257#u03:A001` ghi "One-line Docstrings" nhưng 460/494 ký tự thuộc "Multi-line Docstrings".
  - **Tài nguyên:** B dùng ít hơn 28% chunk và 11% token, nhưng embed lâu hơn (32,0 s so với 26,3 s) vì chuỗi dài hơn. B cũng có 21 chunk dài hơn 256 token: phần đuôi của những chunk này không được đưa vào vector.
  - **Adjudicated:** A lại hơn trên dev (Hit@3 14 so với 12, Hit@1 9 so với 6). Cửa sổ 500 ký tự thường chứa gọn một quy tắc, nên được xếp hạng cao. Đôi khi đó là bằng chứng tương đương ở unit khác (d02, d11). Có lúc câu evidence gốc bị cắt mất phần đầu (d03, d12) nên trượt strict, nhưng ý trả lời vẫn còn.
  - Chênh lệch chỉ 1–3 câu trên N=16, chưa đủ để kết luận A hay B truy xuất tốt hơn.
- **B–C (chỉ đổi filter).**
  - Kết quả hit giống hệt trên cả 22 câu. Filter chỉ thay đổi top-3 của d13 (`pep-0634#u05` được thay bằng `pep-0636#u11`) và t05 (`pep-0585#u01`, thuộc Python 3.9, được thay bằng `pep-0604#u01:C004`).
  - Mức tuân thủ phạm vi tăng từ 2/4 lên 4/4.
  - Filter không tăng recall ở đây vì embedding vốn đã xếp tài liệu đúng lên cao. Giá trị của filter là loại bỏ đoạn gần giống từ tài liệu ngoài phạm vi (spec và tutorial) mà không tốn thêm chi phí.
- **Ví dụ sai:**
  1. **d01, B/C trượt** (gold `pep-0008` unit 2: "Use 4 spaces per indentation level."). Chunk `pep-0008#u02:B001` (897 ký tự) gộp câu quy tắc ngắn với nhiều ví dụ code, làm embedding bị loãng. Top-1 lại là `pep-0008#u04:B001` ("Tabs or Spaces?"): cùng chủ đề nhưng không nêu con số. Cửa sổ 500 ký tự của A xếp đúng ở hạng 1.
  2. **d12, cả ba trượt strict** (gold `pep-0572` unit 7). Ở A, câu quy tắc bị cắt đôi giữa `A000` và `A001`. Ở B, đoạn quy tắc (`B000`) và đoạn ví dụ (`B001`) nằm ở hai chunk khác nhau, và chỉ `B001` được truy xuất (hạng 2). Chunk này vẫn nói rõ `[i := i+1 for i in range(5)]` là invalid và gây SyntaxError, nên người chấm chấp nhận là bằng chứng tương đương.
  3. **t02, cả ba trượt strict** (gold `pep-0557` unit 12, thay thế unit 8). Cả ba chiến lược đều lấy được `pep-0557#u13` ở hạng 3, chunk này có `field(default_factory=list)`, một câu trả lời đúng nhưng chưa có trong gold. Đây là thiếu sót của bộ câu hỏi, phát hiện sau khi xem test. Gold không bị sửa; trường hợp này chỉ được tính trong adjudicated và grounding.
  4. **d02** (gold `pep-0008` unit 4). Mục "Maximum Line Length" trải qua unit 4 và 5. Cả ba chiến lược lấy unit 5, có câu "requires limiting lines to 79 characters". Vì chunk không được vượt ranh giới unit, B không gộp được trọn mục này.
- **Chiến lược chọn: C**, theo quyết định đã ghi trước khi xem test.
  - Lý do: hòa về retrieval, nhưng C có coherence và metadata của B, cộng thêm bảo đảm phạm vi khi câu hỏi có filter. Chi phí bằng B.
  - **Đánh đổi:** C phụ thuộc vào filter đúng. `python_version` mang nghĩa "phiên bản PEP được đưa vào", nên filter `3.10` sẽ loại PEP 585 (3.9) dù cú pháp `list[int]` vẫn dùng được ở 3.10.
  - **Khi nào nên dùng gì:**
    - C, khi câu hỏi có phạm vi rõ ràng và corpus có tài liệu chồng chéo;
    - B, khi không có filter;
    - A, đáng cân nhắc cho tra cứu một câu (Hit@1 adjudicated cao hơn trên dev), nhưng phải chấp nhận chunk khó đọc và `section` sai.
- **Hạn chế:**
  - Test chỉ có 6 câu: mỗi câu tương đương 17 điểm phần trăm, nên chênh lệch 1–2 câu không có ý nghĩa thống kê.
  - Nhãn do một người chấm (AI, cũng là bên xây pipeline), không có người chấm thứ hai. Phần adjudication làm sau khi đã xem test.
  - Câu hỏi được viết sau khi đọc unit, có thể thiên về các từ khóa trùng với văn bản.
  - Corpus và model chỉ có tiếng Anh.
  - Thời gian chỉ đo một lần trên một máy CPU.
  - Chunk B bị model cắt ở 256 token.
  - Ranh giới unit 1.500 ký tự cắt ngang các mục (d02, t04).
  - Metadata lọc chỉ ở cấp tài liệu.
- **Nếu làm lại hoặc mở rộng:**
  - Giới hạn chunk theo token (≤256) thay vì theo ký tự.
  - Thêm `title` và `section` vào đầu text của chunk (contextual header), rồi so trên dev.
  - Cho phép chunk B vượt qua ranh giới unit, kèm danh sách các trang mà chunk trải qua.
  - Thử hybrid BM25 cho từ khóa chính xác ("79 characters", "FrozenInstanceError").
  - Viết quy tắc chấp nhận bằng chứng tương đương **trước** khi chạy, mở rộng test lên ≥20 câu và có người chấm thứ hai.
  - Dùng model đa ngữ (ví dụ multilingual-e5) nếu cần hỏi bằng tiếng Việt.
