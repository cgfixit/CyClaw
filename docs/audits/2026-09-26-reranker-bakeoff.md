# Reranker bake-off results (issue #1456, Phase 3b)

Dated 2026-09-26. Measured by `scripts/rerank_bakeoff.py` in CI run
[36275510609](https://github.com/cgfixit/CyClaw/actions/runs/36275510609)
(job `rerank-bakeoff`, PR #1464, head `46c32454`), on one `ubuntu-latest`
runner with every candidate loaded in float32. The rule was committed in
`5fb454ce`, and the procedure was corrected in `a9d544f7` and `6eca6c94`, each
time before any bake-off output had been read (PR #1464's "Pre-registration
record").

## Verdict: no threshold ships

The pre-registered rule selected `Alibaba-NLP/gte-reranker-modernbert-base`,
scoring whole chunks, at a logit threshold of 1.7137. On the fresh held-out
probes it lost 4 of the 19 answerable windows on `data/corpus` + `docs/`
(21%), over the 15% limit per corpus, so it fails. `retrieval.min_rerank_score`
stays `null` (shadow mode) and `models.reranker` stays
`cross-encoder/ms-marco-MiniLM-L6-v2`.

The verdict does not hinge on the selection step. No configuration in the
bake-off passes the fresh test at its own calibrated threshold (see the
results table in the next section). The selected model is also the only one
that beats "no veto" by a wide margin on the fresh probes: its J is 0.760 with
either scoring, where no veto scores 1.5 and every other model scores 1.22 to
1.47.

## Results for every configuration

Every probe in `tests/ci_rag_smoke.py` and `tests/rerank_probes.py` was run
through `HybridRetriever.hybrid_search` on two fresh indexes. A window counts
only when its best cosine clears `retrieval.min_semantic_score` (0.30), since
the veto can only turn a vault hit into a miss. A window is a good hit when
one of its probe's answer keys appears in its 10 chunks, and a bad hit
otherwise. The labels come from retrieval text alone, never from a score.

| Corpus | Chunks | Calibration good / bad | Fresh good / bad |
|---|---|---|---|
| `data/corpus` | 259 | 23 / 13 | 17 / 9 |
| `data/corpus` + `docs/` | 2,834 | 30 / 18 | 19 / 14 |

The rule: J = 1.5 × (share of bad hits kept) + (share of good hits lost),
averaged over both corpora; no veto scores 1.5. Each configuration's threshold
is the midpoint of the gap in calibration scores with the lowest J, among gaps
that lose at most 10% of good hits per corpus. The choice has the lowest
calibration J among configurations averaging at most 3,000 ms per calibration
window (within 0.05 of that J, the fastest wins). It then passes if, on the
fresh probes, it loses at most 15% of good hits per corpus and its mean J is at
most 1.0.

| Model | Scoring | ms per window | Threshold (logit) | Calibration J | Calibration AUC, small / big | Fresh J | Fresh answers lost, small / big | Fresh false hits kept, small / big |
|---|---|---|---|---|---|---|---|---|
| ms-marco-MiniLM-L6-v2 (shipped) | chunk | 213 | -5.0679 | 0.520 | 0.963 / 0.841 | 1.364 | 5/17 / 8/19 | 5/9 / 11/14 |
| ms-marco-MiniLM-L6-v2 (shipped) | passage | 455 | -5.3490 | 0.678 | 0.943 / 0.820 | 1.470 | 2/17 / 5/19 | 7/9 / 13/14 |
| mxbai-rerank-xsmall-v1 | chunk | 775 | -3.3069 | 0.739 | 0.957 / 0.791 | 1.388 | 1/17 / 3/19 | 7/9 / 13/14 |
| mxbai-rerank-xsmall-v1 | passage | 1,519 | -3.0167 | 0.722 | 0.930 / 0.780 | 1.418 | 1/17 / 3/19 | 8/9 / 12/14 |
| **gte-reranker-modernbert-base** | **chunk** | **1,861** | **1.7137** | **0.338** | **0.993 / 0.878** | **0.760** | **1/17 / 4/19** | **3/9 / 7/14** |
| gte-reranker-modernbert-base | passage | 3,686 (over 3,000) | 1.7735 | 0.515 | 0.997 / 0.865 | 0.760 | 1/17 / 4/19 | 3/9 / 7/14 |
| granite-embedding-reranker-english-r2 | chunk | 1,905 | 1.2471 | 0.803 | 0.930 / 0.759 | 1.221 | 1/17 / 5/19 | 5/9 / 12/14 |
| granite-embedding-reranker-english-r2 | passage | 3,762 (over 3,000) | 1.2529 | 1.059 | 0.883 / 0.733 | 1.388 | 1/17 / 3/19 | 7/9 / 13/14 |
| qnli-electra-base | chunk | 1,380 | 1.1560 | 1.183 | 0.829 / 0.661 | 1.286 | 3/17 / 3/19 | 7/9 / 10/14 |
| qnli-electra-base | passage | 2,900 | 3.1245 | 1.103 | 0.803 / 0.631 | 1.419 | 1/17 / 1/19 | 8/9 / 13/14 |

"small" is `data/corpus`, "big" is `data/corpus` + `docs/`. Times are the mean
per calibration window of 10 chunks on the 4-vCPU CI runner, after one untimed
warm-up call. AUC is the chance that a good hit outscores a bad one, with no
threshold involved. "Passage" scores each chunk as sentence-aligned passages of
at most 48 words and keeps each chunk's best. No other configuration came
within 0.05 of the selected one's calibration J, so the latency tie-break
played no part.

## Why the selected configuration failed

- **The answers it lost are CyClaw's own technical documentation.** All four
  windows lost with `docs/` indexed ask about the system itself: which web
  framework serves the API, why the project does not download the
  sentence-splitting data, which algorithm hashes console passwords, and the
  overall time limit for one question. They scored 1.60 to 1.65 against the
  1.7137 threshold. The web-framework question is also the one window lost on
  `data/corpus` alone, whose CyClaw overview answers it.
- **It is not a one-probe miss.** Passing allowed at most 2 of the 19 to be
  lost, so two more of those four would have had to survive.
- **False hits it kept.** 3 of 9 bad windows on `data/corpus` and 7 of 14 with
  `docs/`. Four of the seven are answerable questions whose window holds none
  of their answer keys: retrieval left the answer out, or the window words it
  differently from the keys. Either way the context is on topic, so a relevance
  model passes it. The other three are look-alikes: a Helm chart deployment,
  the SWE-bench leaderboard, and Eric McLuhan's publications.
- **The samples are small.** 95% Wilson intervals: answers lost with `docs/`,
  4/19 = 21% (9% to 43%); on `data/corpus`, 1/17 = 6% (1% to 27%). False hits
  kept with `docs/`, 7/14 = 50% (27% to 73%); on `data/corpus`, 3/9 = 33%
  (12% to 65%). The result is evidence, not a precise rate.

## The shipped model at its own best threshold

`cross-encoder/ms-marco-MiniLM-L6-v2`, the model shipped in shadow mode, would
have done far worse with a threshold. At its calibrated -5.0679, scoring whole
chunks, it lost 5 of 17 and 8 of 19 fresh answers and kept 5 of 9 and 11 of 14
false hits (fresh J 1.364). That confirms PR #1463's finding: this model's
thresholds do not carry over to reworded questions.

## What the float32 fix changed

Only `mixedbread-ai/mxbai-rerank-xsmall-v1` stores float16 weights, and
transformers 5 loads a checkpoint in its saved dtype. Before `6eca6c94`, the
bake-off ran it in float16, which is slow on a CPU without native half
precision: the job ran for over two hours before it was superseded, unread.
Scored in float32, it took 775 ms per window chunk by chunk. Its calibration J
(0.739 and 0.722) was far from the winner's, so the fix did not decide the
choice. `retrieval/rerank.py` now loads the reranker in float32 as well, which
changes nothing for the shipped float32 model.

## What a next round would need

- **New held-out probes.** The fresh probes above are spent: a new round would
  use them as calibration data and judge its choice on probes no model has
  scored.
- **More of the probes that failed.** The losses cluster on questions answered
  by CyClaw's technical docs, and several look-alikes imitate those docs. With
  19 good windows, one probe moves the loss rate by 5 points, so a 15% limit
  needs more windows of both kinds to be judged fairly.
- **The candidate to beat.** `Alibaba-NLP/gte-reranker-modernbert-base` scoring
  whole chunks: a 598 MB download and about 1.9 s per query window on the CI
  runner, against 0.2 s for the shipped model.
- **Not a looser limit.** Raising the 15% limit after seeing these numbers
  would not be a new round. It would fit the rule to the result.

## Reproducing

Run `python scripts/rerank_bakeoff.py --cache-dir DIR --json PATH` with the
full install and Hugging Face access. The snapshots measured were:

| Model | Snapshot |
|---|---|
| `cross-encoder/ms-marco-MiniLM-L6-v2` | `233902d25c440f23af6f7d6e94d2946bac0bee0a` |
| `mixedbread-ai/mxbai-rerank-xsmall-v1` | `b5c6e9da73abc3711f593f705371cdbe9e0fe422` |
| `Alibaba-NLP/gte-reranker-modernbert-base` | `f7481e6055501a30fb19d090657df9ec1f79ab2c` |
| `ibm-granite/granite-embedding-reranker-english-r2` | `d09d3d6971b689bf9c23839e45a470874d46e13a` |
| `cross-encoder/qnli-electra-base` | `c7dea87c98b2269a935686c31336e97e837cbbeb` |

Every window's score per configuration is in the run's job log and in its
`rerank-bakeoff` artifact, which GitHub keeps for 30 days. Two builds of the
same index can put a different chunk at the edge of a window, so a rerun can
label a probe or two differently.
