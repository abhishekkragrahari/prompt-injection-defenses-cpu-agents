# Supplementary analyses (post-hoc, exploratory)

## Exact McNemar, A1, competent tasks

| contrast | pairs | B0 only | defense only | cond. OR [95% CI] | Cohen's h | p | p Holm |
|---|---|---|---|---|---|---|---|
| qwen3-4b/B1 | 66 | 51 | 0 | 0 [0, 0.075] | -2.15 | 8.88e-16 | 7.11e-15 |
| qwen3-4b/B2 | 66 | 4 | 2 | 0.5 [0.0452, 3.49] | -0.07 | 0.688 | 1 |
| qwen3-4b/B3 | 66 | 0 | 0 | n/a [n/a, n/a] | 0.00 | 1 | 1 |
| qwen3-4b/B4 | 66 | 49 | 0 | 0 [0, 0.0782] | -1.80 | 3.55e-15 | 2.49e-14 |
| granite4-micro/B1 | 30 | 18 | 0 | 0 [0, 0.227] | -1.77 | 7.63e-06 | 4.58e-05 |
| granite4-micro/B2 | 30 | 1 | 0 | 0 [0, 39] | -0.07 | 1 | 1 |
| granite4-micro/B3 | 30 | 0 | 0 | n/a [n/a, n/a] | 0.00 | 1 | 1 |
| granite4-micro/B4 | 30 | 14 | 0 | 0 [0, 0.301] | -1.02 | 0.000122 | 0.00061 |

## GEE logistic regression (n = 384 episodes, 32 clusters)

| term | OR [95% CI] | p |
|---|---|---|
| Intercept | 3.3 [1.83, 5.94] | 6.96e-05 |
| C(defense)[T.B2] | 0.859 [0.666, 1.11] | 0.24 |
| C(defense)[T.B3] | 1 [1, 1] | 1 |
| C(defense)[T.B4] | 0.0239 [0.00901, 0.0636] | 7.03e-14 |
| C(model)[T.granite4-micro] | 0.417 [0.159, 1.09] | 0.0744 |

B4 x model interaction: ratio of ORs 11.2, p = 0.0191

## Latency, paired Wilcoxon signed-rank (A1)

| contrast | n | median diff (s) | Hodges-Lehmann (s) | p | p Holm |
|---|---|---|---|---|---|
| qwen3-4b/B1 | 96 | -28.6 | -34.2 | 4.39e-16 | 3.51e-15 |
| qwen3-4b/B2 | 96 | -0.2 | -2.2 | 0.294 | 0.589 |
| qwen3-4b/B3 | 96 | 3.0 | 2.8 | 0.00239 | 0.00957 |
| qwen3-4b/B4 | 96 | 2.9 | 6.7 | 0.000136 | 0.000817 |
| granite4-micro/B1 | 96 | -16.3 | -18.3 | 6.27e-15 | 4.39e-14 |
| granite4-micro/B2 | 96 | 0.8 | 0.7 | 0.452 | 0.589 |
| granite4-micro/B3 | 96 | -1.1 | -1.1 | 0.00462 | 0.0139 |
| granite4-micro/B4 | 96 | 0.3 | 8.6 | 0.00153 | 0.00767 |

Minimum informative tasks for significance at rank 1 of Holm (m = 16): 10; competent tasks: {'qwen3-4b': 22, 'granite4-micro': 10}
