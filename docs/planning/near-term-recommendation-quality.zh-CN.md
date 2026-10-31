# 推荐与 Taste 闭环短期优化计划

状态：Active
原始审计日期：2026-10-29
用途：记录当前推荐闭环最直接的质量、成本与实验缺口。

## 1. 候选召回可能提前丢掉正确单品

当前先排除明显不适合的品类、风格和叠穿关系，然后在每个槽位中按照以下信息排序：

- Anchor 与候选的 semantic vector 相似度
- Style、Season、Occasion、Warmth、Formality
- 固定搭配优先级
- Taste Profile 分数

相关逻辑在 [`catalog.py`](../../backend/app/outfits/catalog.py)。

### Vector 相似不等于搭配兼容

例如：

- 白衬衫和黑色职业裙在语义上不一定最相似，但很适合搭配。
- 两件运动上衣可能语义非常相似，却不能组成 Outfit。
- Anchor 鞋子与相似鞋子的向量距离很近，但用户需要的是互补的衣服。

当前依靠硬规则和 Metadata 弥补了一部分，但还没有专门学习：

\[
Compatibility(anchor,candidate)
\]

### Top 40 是不可逆的瓶颈

一旦真正适合的单品没有进入 40 件候选，后面的视觉模型再强也看不到它。
当前最需要补充的指标是：

> Recall@40：人工认为合适的搭配单品，有多少成功进入了前 40 件候选？

### 验收

- 建立带人工兼容单品标记的 Anchor 样本。
- 报告整体及各槽位 Recall@40。
- 单独分析因为硬排除和因为排序截断丢失的正确候选。

## 2. Taste 在召回中的权重仍是手动设定

候选排序中 Taste 目前通过类似下面的方式参与：

```text
rank_score + 0.08 * item_taste_score
```

其中 `0.08` 是工程参数，不是从真实用户数据中学习出来的。这可能导致：

- Taste 权重太小，几乎不改变候选。
- Taste 权重太大，把兼容性一般的衣服推到前面。
- 不同用户、不同场合仍使用同一个权重。

Reducer 参数已经通过 Simulation 优化，但还没有系统测试 Taste 加入真实候选召回后，Recall@40、NDCG@10 和最终愿穿率是否提高。现有 Before/After Outfit 表用于回答这个问题，人工标注仍需完成。

### 验收

- 比较 Taste 权重为 0、当前值和至少两个挑战者值。
- 同时报告 Recall@40、NDCG@10、结构可穿率和愿穿率。
- 兼容性指标不得因为 Taste 权重增加而下降。

## 3. Taste 学习无法准确归因到用户真正喜欢的部分

假设用户 Like：

```text
白衬衫 + 黑色裙子 + 黑色高跟鞋
```

当前 reducer 会给 Outfit 中的多种特征同时增加正面证据，例如 White、Black、Business、Shirt、Skirt、Solid、Work，以及颜色组合和品类组合。但用户可能只喜欢白衬衫与黑裙的组合、裙子的版型或整体正式程度。

这是 **Credit Attribution Problem（反馈归因问题）**。负反馈有可选原因，可以限制到 Color、Style、Occasion 等范围；Like 和 Wear 没有正面原因选择，容易把整套 Outfit 的全部特征当作正面证据。

候选改进：

- Like 时允许填写可选正面原因。
- 记录用户替换了哪个单品。
- 将 `A 被 B 替换` 记为 Pairwise Preference：`B > A`。
- 区分“喜欢整套”和“只喜欢其中某件”。

其中替换单品是高价值但尚未进入 Taste 学习的信号。

## 4. 无原因的 Not for Me 学得非常慢

当前设计：

- 有原因的 `Not for me`：更新对应范围的负面特征。
- 无原因的 `Not for me`：立即隐藏完全相同的组合。
- 相似负反馈达到 20 次后，才形成 latent dislike cluster。

该设计可以防止一次误点伤害整个画像，但 20 次门槛可能让系统继续推荐相似风格。目前的聚类也只是相同特征签名计数，不是真正的无监督聚类。

候选改进：

- Outfit embedding 聚类。
- 相似负反馈密度。
- 随证据增长的置信度。
- 中等证据先轻微扣分，高证据再进入明确 Avoid。

## 5. Taste Profile 仍然是加法模型

当前核心形式接近：

\[
TasteScore(o)=\sum_f w_f x_{o,f}
\]

它能学习颜色、Style、Pattern、Occasion 和部分组合，但不擅长表达复杂条件，例如：

- 喜欢粉色，但只在 Date 场合喜欢。
- 喜欢衬衫，但不喜欢衬衫配 Leggings。
- 喜欢花纹上衣，但下装必须是纯色。
- 喜欢靴子，但只适合冬季长裤。

当前保存了部分 `occasion_style`、颜色组合和品类组合特征，但仍是有限的人工交叉特征。当前没有学习式 Pairwise Ranker、Contextual Bandit、非线性交互模型或每个场合独立的 Taste 子画像。因此它能学习方向，但对“在什么条件下喜欢”表达能力有限。

## 6. Exploration 的实现比例并不精确

目标探索率是 15%，但生成最多 8 套时，如果使用：

\[
ceil(8 \times 0.15)=2
\]

实际单批配额为 25%。模型也可能返回 0 套、3 套或其他不符合要求的数量，从而造成 ValidationError、重试和额外费用。

建议：

- 不要求每批严格达到 15%。
- 在多次推荐曝光中维持长期平均 15%。
- 由后端决定探索候选和累计配额。
- 模型只从给定探索池生成合法搭配。
- 不因探索数量错误而重试完整视觉调用。

## 7. 用户反馈不会立即明显改变现有 Outfit 库顺序

当前已实现：

- `Not for me` 隐藏完全相同的组合。
- Like 状态保存。
- Wear 进入近期穿着排除和衰减。
- Taste Profile 更新后，新生成任务读取最新画像。
- 推荐评分和最终视觉复核读取 Taste Profile。
- Taste 更新不会自动重新生成所有旧 Outfit，以控制成本。

仍需验证 Closet 中已有 Outfit Library 的展示顺序是否完整读取最新 Taste。目标行为是：

- 不重新调用模型。
- 读取现有 Outfit 时重新计算 `outfit_taste_score`。
- 根据最新 Taste、最近穿着、Like 和场合排序。
- 只有用户主动 Regenerate 时才生成新 Outfit。

这样反馈可以立即影响展示，同时不增加模型费用。

## 8. 前端反馈信号还不完整

当前已有 Like、Not for Me、可选负面原因、Wear It Today、Personal Outfit、自由文本和 Reset Taste Profile。

仍缺少 Impression Log：

```text
用户看到了什么
排在第几位
是否点开
停留多久
是否替换单品
是否跳过
是否最终穿着
```

“不点击”不能直接视为负面，因为用户可能没有看到。但没有曝光日志，就无法判断未选择是因为不喜欢还是没有曝光，也无法校正 Position Bias 和 Exposure Bias，更无法证明 Exploration 获得了实际展示机会。

## 9. 自由文本反馈进入系统较慢，也缺少可验证性

当前流程是先保存自由文本，达到阈值后低频调用模型总结，将结果写入 `free_text_summary`，生成和视觉复核读取 Summary。

主要问题：

1. 用户写完后不一定马上感受到变化。
2. 模型总结可能丢失细节或产生错误概括。

应补充：

- 原始文本到 Summary 的证据引用。
- Summary 版本。
- 用户查看和修正总结的能力。
- 新旧 Summary 差异。
- 哪条推荐使用了哪条偏好证据。

## 10. 当前实验还不足以证明真实闭环有效

### Simulation 已经证明

- Reducer 能学习偏好方向。
- v2 比 v1 更少出现分数饱和。
- NDCG 和 Regret 在合成环境中改善。

它使用虚拟用户，不能证明真实用户满意。

### Before/After Outfit Preview 当前具备

- 10 个 Persona。
- Before：无 Taste。
- After：5–7 条反馈。
- 相同衣橱和 Anchor。

当前限制：

- 只使用一个共同 Anchor。
- 每个条件只有一轮模型输出。
- 模型生成有随机性。
- Before/After 需要严格盲化确认。
- 人工评分尚未完成。
- 不是线上真实用户 A/B Test。

当前可以对外表述：

> The personalization loop is technically complete, but its real recommendation uplift is still under human evaluation.

暂时不能表述：

> Taste learning has already been proven to improve real-user satisfaction.

## 当前最值得先修的五件事

1. **测量 Recall@40**：确认正确单品有没有在视觉模型看图前被候选召回漏掉。
2. **完成 Before/After 人工评分**：得到 Preference rating、Would-wear rate 和 Wearability 的真实差值。
3. **现有 Outfit 按最新 Taste 免费重排**：不调用模型，让用户反馈立即反映在展示顺序上。
4. **记录 Impression 和 Replace 行为**：尤其把“用 B 替换 A”变成明确的 Pairwise Preference。
5. **重做 Exploration 配额**：从每批严格配额改为跨曝光长期维持约 15%，减少 ValidationError 和模型重试。

## 与长期计划的边界

本文件回答“推荐闭环下一步修什么”。项目展示、成本实验、Demo 和正式 Release 由 [Portfolio Readiness Plan](portfolio-readiness.md) 管理。
