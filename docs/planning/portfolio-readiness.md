# AI Closet Portfolio Readiness Plan

Status: active
Updated: 2026-10-29

## Goal

Turn the current working system into a project that a professor, recruiter, or
repository reviewer can evaluate quickly. The remaining work focuses on current-version
evidence, reproducibility, operating cost, and presentation rather than adding
more product features.

## P0 — Current-version evidence

### 1. Complete the Taste Before/After human evaluation

- [ ] Blind the Before and After condition labels during rating.
- [ ] Complete all human ratings in the existing 10-persona, 140-row workbook.
- [ ] Measure persona-preference win rate, tie rate, and loss rate.
- [ ] Confirm that personalization does not reduce structural wearability.
- [ ] Report results overall and per persona with sample counts and confidence intervals.
- [ ] Record the exact runtime snapshot and workbook checksum used for the result.

**Acceptance:** one reviewed result table can support a statement such as
“personalization improved preference win rate from X% to Y% while preserving Z%
structural wearability.” Synthetic simulation results must remain labeled as
synthetic.

### 2. Build one canonical current-version results table

- [ ] Re-evaluate Category and Subtype accuracy on a held-out, human-labeled set using the current recognition version.
- [ ] Re-evaluate generated-outfit structural wearability using the current three-stage outfit pipeline.
- [ ] Add the Taste simulation NDCG@10 and regret results with a synthetic-data label.
- [ ] Add Taste Before/After human results after annotation is complete.
- [ ] Add recognition failure rate, accepted-outfit yield, cost, and latency.
- [ ] Include baseline, current result, sample size, evaluation method, version, and limitations for every metric.

Target schema:

| Module | Baseline | Current | Sample | Method | Version |
|---|---:|---:|---:|---|---|
| Category accuracy | TBD | TBD | TBD | Held-out human labels | TBD |
| Outfit structural wearability | TBD | TBD | TBD | Blinded human review | TBD |
| Taste ranking NDCG@10 | 0.149 | 0.459 | 30 users/scenario | Synthetic simulation | taste-profile-v2 |
| Taste preference win rate | TBD | TBD | 140 paired rows | Blinded human review | TBD |
| Recognition failure rate | TBD | TBD | TBD | Production-style replay | TBD |
| Cost per accepted outfit | TBD | TBD | TBD | Recorded provider usage | TBD |
| End-to-end latency | TBD | TBD | TBD | Worker event timing | TBD |

**Acceptance:** README, résumé, professor presentation, and interview answers use
this same table instead of mixing results from incompatible historical versions.

## P1 — Production evidence

### 3. Measure cost, latency, and capacity

- [ ] Measure recognition cost and P50/P95 latency per garment.
- [ ] Measure model calls, tokens, and cost per anchor and per accepted outfit.
- [ ] Attribute cost to clothing generation, accessory selection, and final review.
- [ ] Measure accepted-outfit yield and retry recovery rate.
- [ ] Measure candidate selection and database latency at 100, 500, and 1,000 items.
- [ ] Compare worker concurrency 1, 2, and 4 for throughput and peak memory.
- [ ] Verify stale jobs are rejected after item edit, image replacement, and deletion.
- [ ] Document the workload, machine, provider, model, and confidence interval.

**Acceptance:** publish a compact cost/latency table and identify the current
capacity bottleneck without claiming unmeasured production scale.

### 4. Validate the provider boundary

- [ ] Select one lower-cost OpenAI-compatible or self-hosted model candidate.
- [ ] Run the same held-out recognition and outfit sample through both providers.
- [ ] Compare quality, schema-valid response rate, latency, and cost.
- [ ] Record provider/model versions and the same prompt/configuration snapshot.

**Acceptance:** demonstrate that `AIGateway` supports a real provider trade-off,
not only an interface abstraction. This is an optional stretch goal after the
current-provider evidence is complete.

## P1 — Demonstration

### 5. Prepare a reviewer-safe demo

- [ ] Deploy the API and required workers from one tagged commit.
- [ ] Create a synthetic or explicitly consented demo closet with no private user data.
- [ ] Precompute recognition and outfit results to prevent reviewer-triggered model cost.
- [ ] Record a 60–90 second walkthrough covering upload, recognition, tag correction, outfit generation, Today, Like/Not for Me, and Taste-driven ranking.
- [ ] Add four to six current screenshots to the repository README.
- [ ] Provide a read-only or controlled-cost demo account if deployment permits.

**Acceptance:** a reviewer can understand the product and personalization loop
without installing Xcode or spending provider credits.

## P1 — Repository release

### 6. Publish a portfolio release

- [ ] Organize the current work into reviewable commits.
- [ ] Ensure `main` passes backend tests, lint, type boundaries, migration checks, OpenAPI drift, documentation links, and iOS build.
- [ ] Confirm no secrets, signed image URLs, private photos, or private evaluation workbooks are tracked.
- [ ] Put the architecture diagram, canonical results table, demo media, setup path, and evaluation limitations near the top of README.
- [ ] Add a CI badge and create a tagged `v1.0.0-portfolio` GitHub Release.
- [ ] Verify every résumé metric links to a reproducible artifact or documented evaluation.

**Acceptance:** a fresh reviewer can clone the repository, understand the system,
run the documented checks, and trace every public performance claim.

## Recommended order

1. Finish the Taste Before/After annotation and analysis.
2. Produce the canonical current-version results table.
3. Run cost, latency, and capacity measurements.
4. Prepare the safe demo and short video.
5. Clean the commit history and publish `v1.0.0-portfolio`.
6. Benchmark a lower-cost provider if time remains.

## Claims policy

- Never combine metrics from different model, prompt, taxonomy, or pipeline versions without labeling them.
- Distinguish human-labeled, synthetic-simulation, retrospective-edit, and operational metrics.
- Always report sample size and evaluation method beside a percentage.
- Do not call a retrospective single-user edit audit a general model accuracy benchmark.
- Do not describe simulated personas as real users.
