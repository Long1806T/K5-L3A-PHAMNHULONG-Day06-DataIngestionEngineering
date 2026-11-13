| Strategy | Split | Hit@1 strict (n/N) | Evidence Hit@3 strict (n/N) | Hit@1 adjudicated | Hit@3 adjudicated | Chunk count | Embed time | Cost |
|---|---|---|---|---|---|---|---|---|
| A | dev | 4/16 | 10/16 | 9/16 | 14/16 | 553 | 26.34 s | $0 |
| A | test | 1/6 | 3/6 | 2/6 | 5/6 | 553 | 26.34 s | $0 |
| B | dev | 5/16 | 10/16 | 6/16 | 12/16 | 399 | 31.98 s | $0 |
| B | test | 2/6 | 3/6 | 3/6 | 5/6 | 399 | 31.98 s | $0 |
| C | dev | 5/16 | 10/16 | 6/16 | 12/16 | 399 | 0.0 s (vectors of B reused) | $0 |
| C | test | 2/6 | 3/6 | 3/6 | 5/6 | 399 | 0.0 s (vectors of B reused) | $0 |

| Strategy | Coherence mean /2 (n) | Metadata complete & correct (n/N) | Filter compliant dev / test | Grounding 0/1/2 (questions) and mean /2 |
|---|---|---|---|---|
| A | 0.9 (10) | 13/18 | 2/3 / 0/1 (filter not applied) | 1/0/5 -> 1.67 |
| B | 1.7 (10) | 18/18 | 2/3 / 0/1 (filter not applied) | 0/1/5 -> 1.83 |
| C | 1.7 (10) | 18/18 | 3/3 / 1/1 | 0/1/5 -> 1.83 |
