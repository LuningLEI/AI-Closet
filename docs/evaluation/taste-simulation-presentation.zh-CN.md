# AI Closet Preference Learning Simulation

## Result Chart

| Metric | `taste-profile-v1` | `taste-profile-v2` | Interpretation |
|---|---:|---:|---|
| Stable NDCG@10 ↑ | 0.149 | **0.459** | The top-10 ranking became much closer to the simulated user’s true preference. |
| Noisy-feedback NDCG@10 ↑ | 0.148 | **0.410** | The new configuration remained effective with 20% incorrect feedback. |
| Mean regret ↓ | 2.786 | **1.646** | The utility lost relative to the ideal recommendation decreased by about 41%. |
| Score saturation ↓ | 100% | **0%** | Candidate scores no longer collapse at the ±20 limit. |
| Activation step ↓ | 5.2 | **3.7** | Personalization starts after fewer feedback opportunities. |
| Preference-drift recovery ↓ | **31.3** | 57.4 | Trade-off: v2 adapts more slowly when a user’s preference changes abruptly. |

## Oral Presentation

> AI Closet learns a separate taste profile for each user from likes, actual wears, manually created outfits, and reason-based negative feedback. Instead of assuming that the original learning parameters were correct, I evaluated them through simulation.
>
> I created synthetic users with hidden preferences, so I knew the ideal ranking for every outfit. The production taste reducer could only observe simulated user feedback. I tested three conditions: stable preferences, twenty percent incorrect feedback, and a preference change halfway through the experiment. I searched forty-eight parameter configurations and validated the top six with thirty users and one hundred and twenty feedback opportunities per user.
>
> The main metric was NDCG at ten, which measures how closely the system’s top ten recommendations match the user’s ideal top ten ranking. I also measured regret, cold-start speed, score saturation, and recovery after preference changes.
>
> The key finding was that version one learned a reasonable preference direction, but its personalization scale was too large. Eventually, every candidate reached the score limit, so different outfits became indistinguishable. After tuning the parameters, version two increased stable NDCG at ten from 0.149 to 0.459, reduced mean regret by about forty-one percent, and reduced score saturation from one hundred percent to zero. It also began personalizing earlier. The main trade-off is that it adapts more slowly when preferences change suddenly.
>
> I promoted the selected configuration to `taste-profile-v2` and versioned the change so profiles can be deterministically rebuilt or rolled back. These results show that version two is better under the simulation assumptions, but the next step is validation with consented real-user feedback and a user-level A/B test.
