# Taste 参数调整｜只看这一页

你日常只需要调整下面 4 个数字：

```json
{
  "generation_evidence_threshold": 2,
  "exploration_rate": 0.15,
  "half_life_days": 270.0,
  "personalization_scale": 0.5,
  "prior_strength": 2.5,
  "decay_floor": 0.0
}
```

配置文件生成在 `evaluation/taste/simulation/custom_config.json`（本地评估产物，不提交到 Git）。修改后运行：

```bash
make taste-simulation-custom
```

程序只会比较两组：

1. 当前生产默认值；
2. 你在 `custom_config.json` 中填写的值。

结果在 `evaluation/taste/simulation/custom/report.md`。

## 最常调整的参数怎么理解

| 参数 | 调小 | 调大 | 当前建议 |
|---|---|---|---:|
| `generation_evidence_threshold` | 学得快，但容易受偶然反馈影响 | 更稳定，但冷启动慢 | 候选 2 |
| `exploration_rate` | 推荐更保守、重复 | 尝试更多新搭配，短期命中可能降低 | 候选 0.15 |
| `half_life_days` | 更快忘记旧偏好，适应变化快 | 长期偏好更稳定，适应变化慢 | 候选 270 |
| `personalization_scale` | 个性化影响小，但较少饱和 | 个性化影响强，容易全部封顶 | 候选 0.5 |

两阶段参数搜索后，threshold=2、exploration=0.15、half-life=270、scale=0.5、prior=2.5、decay floor=0 已于2026年10月29日提升为生产 `taste-profile-v2` 默认值。配置文件初始值与生产相同；要测试新挑战者时，只修改其中一个数字。

## 看结果时只看三个指标

| 指标 | 含义 | 方向 |
|---|---|---|
| `mean_ndcg_at_10` | 学到的前十排序接近用户真实偏好的程度 | 越高越好 |
| `mean_regret` | 推荐结果距离用户最喜欢结果的损失 | 越低越好 |
| `final_saturation_rate` | 多少候选同时触及分数上限 | 越低越好 |

如果自定义参数只提高 NDCG，但 saturation 或偏好变化恢复明显恶化，先不要改生产值。

## 推荐调整顺序

1. 固定 threshold=2、exploration=0.15、half-life=270，只比较 scale=0.35、0.5、0.75。
2. 确定不饱和的 scale 后，再比较 threshold=1、2、3。
3. 最后才调整 exploration 和 half-life。
4. 每次只改一个参数，否则无法解释结果为什么变化。
