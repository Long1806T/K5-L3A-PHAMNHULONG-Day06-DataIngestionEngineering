# Strategy choice (written after dev results, BEFORE looking at test results)

Pre-registered rule (benchmark/questions.json): highest dev Evidence Hit@3 -> higher dev Hit@1 -> fewer chunks / lower ingest time.

| Strategy | dev Hit@1 | dev Evidence Hit@3 | chunks |
|---|---|---|---|
| A | 4/16 | 10/16 | 553 |
| B | 5/16 | 10/16 | 399 |
| C | 5/16 | 10/16 | 399 |

* Evidence Hit@3 ties (10/16 for all three); Hit@1 eliminates A (4/16).
* B and C have identical chunks and dev scores, so the pre-registered rule does **not** separate them.
  Additional tie-break added at this point (not pre-registered, recorded here before test):
  prefer C because, for questions that come with a scope, it guarantees that 3/3 top-3 results respect the
  scope (on dev d13 B returned a pep-0634 chunk outside the requested Informational scope) at zero extra cost.
* Chosen: **C** (paragraph/heading chunking, max 1000 chars, metadata filter when the question provides one).
* Nothing in chunking, model, filter or benchmark is changed after this point; test is read once.
