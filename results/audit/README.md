# Audit thủ công — cách làm và người chấm

**Người chấm:** toàn bộ nhãn trong thư mục này do trợ lý AI (Claude, Anthropic) gán khi đọc từng chunk. Học viên (Phạm Như Long) cần đọc lại các nhãn trước khi nộp. Người chấm cũng là bên đã xây pipeline, nên có nguy cơ thiên lệch. Để hạn chế điều đó, quy tắc chấm được ghi ra trước, và mọi nhãn đều kèm lý do để người khác kiểm tra lại. Không dùng LLM judge tự động nào.

| File | Nội dung | Mẫu |
|---|---|---|
| `coherence_sample.json` | Chunk chứa vị trí mẫu, sinh tự động (`python -m src.run audit-samples`) | Vị trí = ký tự giữa của unit `u02` trong mỗi tài liệu (10 vị trí, cố định trong code trước khi chấm) |
| `coherence_labels.csv` | Điểm 0–2 kèm lý do cho A và B. C dùng **đúng** các chunk của B nên điểm giống B | 10 vị trí × 2 |
| `metadata_check.csv` | Kiểm tra `source`, `page`, `section`, `pep_type`, `python_version` của 6 câu test × top-3 | 18 bản ghi / chiến lược |
| `grounding_labels.csv` | Điểm 0–2 cho cả top-3 của từng câu test, kèm chunk hỗ trợ | 6 câu test × 3 |
| `equivalent_evidence.csv` | Quyết định chấp nhận / từ chối bằng chứng tương đương (GUIDE §4.1) | Mọi trường hợp được xem xét |
| `audit_summary.json` | Số liệu tổng hợp (`python -m scripts.audit_metrics`) | — |

## Quy tắc chấm

- **Coherence:** 0 = bị cắt giữa ý hoặc thiếu chủ thể nên không hiểu được; 1 = hiểu được một phần nhưng thiếu ngữ cảnh (bắt đầu hoặc kết thúc giữa câu, hoặc phần dẫn nằm ở chunk khác); 2 = tự hiểu được và giữ trọn ý. Một nhãn treo ở cuối chunk (ví dụ `# Wrong:`) mà nội dung nằm ở chunk sau thì không bị trừ điểm, miễn các ý chính đã đủ.
- **Metadata:** `page` đúng khi text của chunk nằm trong đúng unit đã ghi. `source`, `pep_type`, `python_version` đúng khi khớp header của file nguồn (manifest). `section` đúng khi là heading chứa phần lớn ký tự của chunk. Script đánh dấu các dòng sai, sau đó từng dòng bị đánh dấu được đọc lại bằng tay; cả 5 lỗi của A đều được xác nhận.
- **Grounding** (chỉ xét bằng chứng truy xuất, không phải độ đúng của câu trả lời LLM): 2 = top-3 có câu trả lời trực tiếp kèm điều kiện cần thiết và truy được nguồn; 1 = có bằng chứng liên quan nhưng thiếu, bị cắt, hoặc chỉ ngụ ý; 0 = không có bằng chứng.
- **Bằng chứng tương đương:** chỉ chấp nhận khi **riêng chunk đó** nói rõ câu trả lời (bằng lời, hoặc bằng chú thích tường minh như `# INVALID`). Không chấp nhận bằng chứng chỉ ngụ ý hoặc chỉ là code ví dụ. Việc này được làm **sau khi đã xem test**, nên chỉ số "adjudicated" là chỉ số phụ. Chỉ số chính vẫn là Hit@1 / Evidence Hit@3 tự động trên gold đã đóng băng; `benchmark/questions.json` không bị sửa.
