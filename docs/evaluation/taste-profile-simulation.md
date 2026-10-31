# Taste Profile Learning Simulation

## Research question

The production Taste Profile uses deterministic evidence accumulation rather than model fine-tuning. The original `taste-profile-v1` defaults were engineering hypotheses: signal strengths, a three-observation evidence threshold, a 180-day half-life, a 30% decay floor, 10% exploration, prior shrinkage of 5, personalization scale 4, and a score bound of ±20. Unit tests verify implementation, but they cannot show whether these choices learn quickly, resist noisy feedback, recover from preference changes, or preserve ranking resolution. On 2026-10-29, the simulation-selected configuration was promoted as `taste-profile-v2`; the experiment artifacts preserve v1 as the baseline.

This simulation makes those properties measurable before an online experiment.

## Experimental design

The simulator creates synthetic wardrobes from combinations of style, color, pattern, occasion, category, subtype, warmth, and formality. Each virtual user receives a hidden preference function, with small seed-specific variation, so the oracle utility of every outfit is known. The recommendation loop observes only simulated Like, Wear, Personal Outfit, reason-scoped Not for Me, or no-feedback events.

Every event is passed through the production `reduce_sources` implementation. The experiment is therefore a simulation of user behavior and catalog exposure, while the learning algorithm itself is production code.

Three paired Monte Carlo scenarios use the same seeds for every parameter variant:

1. **Stable preference:** 5% feedback error and no latent-preference change.
2. **Noisy feedback:** 20% feedback error.
3. **Preference drift:** the hidden preference changes halfway through the run.

The current experiment uses 30 virtual users per parameter/scenario pair, 120 feedback opportunities per user, and one feedback opportunity every three simulated days. The parameter study changes one factor at a time:

- evidence threshold: 2, 3, or 5 observations;
- exploration rate: 0%, 10%, or 20%;
- half-life: 90, 180, or 365 days;
- prior strength: 2.5, 5, or 10;
- personalization scale: 1, 2, or 4;
- all signal strengths: 0.75×, 1×, or 1.5×;
- decay floor: 0%, 30%, or 50%.

## Metrics

- **NDCG@10:** agreement between learned ranking and the oracle top ten.
- **Preference alignment:** cosine similarity between eligible learned feature weights and hidden preference weights.
- **Mean regret:** oracle utility lost by the presented recommendation; lower is better.
- **Activation step:** feedback opportunities required before evidence can affect ranking and generation.
- **Alignment-50 step:** opportunities required to sustain preference alignment of at least 0.50.
- **Drift recovery:** post-change opportunities required to regain alignment of at least 0.50.
- **Catalog coverage:** distinct outfits presented.
- **Score saturation:** proportion of candidates at the ±20 personalization bound. High saturation removes ranking resolution even when the learned feature direction is correct.
- **95% confidence intervals:** uncertainty across virtual users.

## Current finding

The v1 production baseline activated after 5.2 feedback opportunities on average and reached 0.50 alignment after 16.6 opportunities. Its final stable-scenario feature alignment was 0.833. However, after 120 opportunities, 100% of candidates reached a score bound in this synthetic catalog, making their personalization score spread zero. The reducer learned a plausible direction, but the downstream bounded sum lost the ability to rank candidates.

Changing only the personalization scale from 4 to 1 reduced final saturation to 18.5%, increased mean stable NDCG@10 from 0.149 to 0.365, and reduced mean regret from 2.786 to 2.043. A subsequent two-stage search across 48 candidates selected scale 0.5 together with a lower evidence threshold, 15% exploration, a 270-day half-life, zero decay floor, and prior strength 2.5. That configuration was promoted to `taste-profile-v2`; real-data replay remains necessary because the selected defaults are optimal only under the stated synthetic assumptions.

Evidence thresholds mostly controlled cold-start speed: thresholds 2, 3, and 5 activated after approximately 3.7, 5.2, and 9.2 opportunities. Their long-run ranking differences were small once the default scale saturated. Exploration and decay comparisons are also partially masked by saturation and should be repeated after selecting a non-saturating scoring formulation.

Full results and confidence intervals are generated locally at `evaluation/taste/simulation/summary.csv`. Aggregated learning trajectories and SVG figures are stored in the same ignored output directory.

## Interpretation boundary

The simulation validates algorithm mechanics under explicit assumptions. Synthetic clicks are not evidence of real satisfaction, and one synthetic catalog cannot establish a universal optimal default. It is suitable for rejecting unstable defaults, finding failure modes, and narrowing parameter candidates.

After promoting the simulation-selected defaults, the validation sequence is:

1. replay consented, anonymized real feedback snapshots without modifying user profiles;
2. compare parameters separately for cold-start, sparse-feedback, and mature profiles;
3. test a normalized or centered feature aggregation to prevent common positive features from saturating all candidates;
4. pre-register one primary online metric and safety guardrails;
5. run a user-level A/B test with one parameter change at a time.

## Reproduction

```bash
make taste-simulation
```

For a narrower Monte Carlo confidence interval:

```bash
cd backend
python -m tools.evaluation.taste_learning_simulation \
  --runs 100 \
  --steps 120 \
  --output ../evaluation/taste/simulation
```

The command performs no database writes and makes no OpenAI calls.
