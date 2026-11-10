# Sandy 11 待办

更新日期：2026-11-10

## 目标

下一阶段集中解决四件事：一级品类识别可靠性、自然语言旅行推荐、新用户偏好冷启动，以及鞋履/配饰变化后的低成本增量优化。原则是保留现有 Recognition、Outfit Library 和 Taste Profile，不用一次局部变化触发全衣橱重新生成。

## 当前状态

| 方向 | 当前已有 | 主要缺口 |
|---|---|---|
| Recognition | 严格 Schema、用户 Taxonomy、人工修正保护、识别历史 | Tops、Bottoms、Dresses 的轮廓一致性仍可能出错，例如裙子被识别成 Shirt/Sweater |
| Agent Chat | Chat box、结构化 intent、Recommendation Skill、统一的 Preference-aware ranking | 地点、日期、旅行天数、活动和天气没有形成完整 Trip Context；Miami 容易退回默认温度和 Everyday |
| 新用户问卷 | 现有 4 步 Onboarding：Basic、Preference、Catalog、Final | 问题还没有围绕现有推荐参数形成清晰冷启动；缺少天气敏感度、探索/轮换和明确的 avoid 信息 |
| 鞋履/配饰更新 | 鞋与配饰可以作为候选和 Optional Addition；已经关闭 pool 变化触发全量 Outfit 重跑 | 新单品可能比旧鞋/配饰更适合某些现有 Outfit，但目前没有低成本的局部升级机制 |

---

## 1. 修复上衣、下装和连衣裙识别混乱

### 要做什么

将 Recognition 拆成“一级轮廓判断”和“品类内 Subtype 判断”，但首版仍保持一次视觉调用：

1. 在结构化输出中增加独立的轮廓证据，例如 `body_region`、`one_piece`、`waistband_visible`、`neckline_or_collar_visible` 和 `leg_openings_visible`。
2. 先根据轮廓确定 `Tops / Bottoms / Dresses`，再只允许模型从该 Category 对应的 Subtype 中选择。
3. 增加确定性一致性校验：
   - `lower_body + waistband/leg openings` 不能输出 Tops；
   - `upper_body + neckline/sleeves` 不能输出 Bottoms；
   - `one_piece + upper/lower continuous silhouette` 才允许 Dresses。
4. 如果 Category 与轮廓冲突，先用原始返回做本地规范化；只有图片本身仍无法判断时才进入一次有针对性的视觉复核。
5. 用户人工修改 Category 后，保留保护标记，并将 `model_category → corrected_category` 写入评估数据。

### 如何验证

- 从现有人工修改记录建立 Tops / Bottoms / Dresses confusion matrix。
- 单独报告一级 Category accuracy、Subtype accuracy 和跨一级品类错误率。
- 建立至少包含裙子、毛衣、衬衫、长裤的冻结困难样本集。
- 验收标准：跨一级品类误判明显下降，且不能通过把大量结果变成 Unknown 来虚增准确率。

### 完成定义

- [ ] 新轮廓字段和严格 Schema 已版本化。
- [ ] 一致性校验与修复路径有自动化测试。
- [ ] 困难样本 Before/After 结果已导出。
- [ ] 前端人工修正仍能覆盖模型结果并保护不被后台写回覆盖。

---

## 2. 打通自然语言输入到多日推荐

示例：`我要去迈阿密旅游五天。`

### 现有问题

当前 Agent 已能识别“旅行”和“五天”，也能调用已有 Outfit 推荐，但还没有可靠地把 Miami 转换成地点、旅行日期、逐日天气和旅行场合。缺失信息时容易使用默认温度与 `Everyday`，因此可能出现运动服或毛衣比例异常。

### 目标链路

```text
Natural-language request
        ↓
Structured TripRequest
(destination, dates/days, activities, constraints)
        ↓
Location resolution + daily weather
        ↓
Daily RecommendationContext
(temperature, precipitation, occasion, style)
        ↓
Existing Outfit Library retrieval
        ↓
Preference/Taste ranking + hard weather rules
        ↓
Multi-day diversity and garment-reuse optimizer
        ↓
Five-day recommendation plan
```

### 实施内容

1. 扩展 Agent Schema：`destination`、`start_date`、`trip_days`、`activities`、`dress_code`、`luggage_constraints`。
2. 地点解析后读取逐日天气；没有日期时使用明确、稳定的默认策略，并在回复中说明假设。
3. 每一天建立独立 `RecommendationContext`，而不是五天共用一个默认温度。
4. 复用 Today/Recommendations 当前的同一套 Preference-aware ranking，不建立第三套推荐算法。
5. 在最终选择层加入多日约束：
   - 核心 Outfit 不重复；
   - 允许合理复用鞋、包和外套；
   - 控制同一件上衣/下装的重复频率；
   - 温度和天气是硬门槛，Style 多样性是软目标。
6. 输出每天的 Outfit、天气/场合依据，以及可复用单品；结果仍支持 Like、Not for me、Wear it today 和 Replace items。

### 完成定义

- [ ] Miami 五日请求能生成 5 个按天区分的 Context。
- [ ] 不再无依据使用默认 68°F/Everyday。
- [ ] 结果满足逐日天气硬规则和多日去重。
- [ ] Agent 返回的 Outfit 与普通推荐使用相同评分、Taste 和近期穿着规则。
- [ ] 中英文同义请求有端到端测试。

---

## 3. 完善基于 Preference System 的新用户问卷

### 结论

项目已经有初版，不需要重做。当前 `OnboardingView` 是四步流程，并已保存 Basic Profile、Daily Occasions、每个 Occasion 对应的 Style、Catalog 和 Personalization 设置。下一步应把它改造成短而可解释的推荐冷启动问卷。

### 建议问卷

1. **主要使用场景**：Everyday、Work、School、Travel、Date、Party、Formal、Workout。
2. **每个已选场景的 Style**：直接写入 `occasion_style_preferences`，不再用一组脱离场合的全局 Style。
3. **所在地与温度感受**：默认位置、温标、怕冷/正常/怕热，映射到 `temperature_sensitivity`。
4. **颜色、图案与版型偏好**：分别记录喜欢和避免；作为显式 prior，不伪造成 Like/Not for me 行为。
5. **推荐体验**：熟悉稳妥或愿意探索，映射到 `exploration_level` 和 `rotation_level`。
6. **Catalog 定制**：保留现有 Category/Subcategory 体系，并允许稍后在 Settings 修改。
7. **数据同意**：个性化开关与匿名跨用户训练同意分开，后者默认关闭。

### 数据原则

- 问卷答案存入 `user_preferences`，作为用户明确声明的 Preference。
- 行为学习继续存入独立 `user_taste_profiles`；不向用户展示内部 Learned Taste 权重。
- 显式 Preference 与学习结果冲突时，显式 Preference 优先；行为证据只做渐进调整。
- 所有选项必须能实际影响召回、排名或生成，不能保存“目前无人读取”的装饰性字段。

### 完成定义

- [ ] 现有问卷字段到后端字段和推荐评分的映射表完成。
- [ ] Onboarding 可跳过非关键问题，并可在 Settings 重新编辑。
- [ ] 新用户完成问卷后，无行为反馈也能看到可解释的排序变化。
- [ ] 问卷更新不会覆盖已经学习到的 Taste Profile。
- [ ] 增加 onboarding persistence 和 ranking-effect 测试。

---

## 4. 新鞋和新配饰的增量 Outfit 升级

### 已完成的安全措施

2026-11-10 已关闭“鞋履/配饰池版本变化 → 所有 Anchor 重新生成”的依赖。现在：

- 新增或修改 Shoes、Bags、Accessories 不会自动重跑整个 Outfit Library；
- 已有第一批 Qwen Outfit 与原鞋子保留；
- 普通服装单品的标签更新仍只生成该单品对应的新 Anchor 任务；
- 用户仍可手动对鞋子或配饰点击 Generate Outfit。

### 长期正确方案

不要重新运行 Outfit Generator，而是把生成拆成三个独立版本：

```text
Base clothing composition
        ↓ stable
Footwear enrichment
        ↓ independently refreshable
Optional accessory enrichment
        ↓ independently refreshable
Final affected-outfit review
```

新鞋或配饰进入衣橱后：

1. 用 Metadata、季节、温度、场合、Style、颜色和向量做廉价预筛选。
2. 通过 Outfit-item 倒排索引找到可能受影响的现有 Base Outfit，而不是扫描并生成全部 Anchor。
3. 比较新单品与当前鞋/配饰的确定性分数，只保留分数提升超过阈值的少量 Outfit。
4. 创建按 `item_id + affected_outfit_id + enrichment_stage` 去重的增量任务。
5. 仅对入选的 Outfit 重跑鞋履/配饰选择及最终视觉复核；Base clothing proposal 永不重跑。
6. 以新 Variant 发布，旧 Variant 在新结果通过前继续展示；失败时可直接回滚。
7. 多个新增单品在短时间内合并成一个批次，避免每上传一件就调用模型。

### 建议的首版默认值

| 参数 | 默认值 |
|---|---:|
| 新增单品批处理窗口 | 30 分钟 |
| 每个新鞋预筛选的现有 Outfit 上限 | 30 |
| 每个新配饰预筛选的现有 Outfit 上限 | 20 |
| 真正进入视觉复核的 Outfit 上限 | 10 |
| 同一 Outfit 的升级冷却期 | 7 天 |
| 分数提升门槛 | 先用离线实验确定，不直接拍脑袋上线 |

### 完成定义

- [ ] 新鞋/配饰不会创建任何 Base Outfit generation call。
- [ ] 只创建受影响 Outfit 的 enrichment jobs。
- [ ] 旧搭配在新 Variant 审核通过前始终可见。
- [ ] 模型调用量、延迟和升级成功率可审计。
- [ ] 自动化测试证明新增一个配饰不会产生全衣橱 Anchor jobs。

---

## 推荐顺序

| 优先级 | 工作 | 原因 |
|---|---|---|
| P0 | 一级 Category/轮廓一致性 | 错误标签会污染生成、检索和用户信任，是后续链路的输入质量问题 |
| P0 | 保持鞋/配饰全量重跑关闭 | 防止再次产生意外费用；当前安全措施已经完成 |
| P1 | Miami 五日 Agent 端到端链路 | 这是最直观的产品演示，也能验证天气、Preference 和多样性是否真正统一 |
| P1 | 新用户问卷完善 | 为没有行为反馈的新用户提供可解释的冷启动 |
| P2 | 鞋/配饰增量升级 | 在不增加 Base generation 成本的前提下逐步提升旧 Outfit |

## Sandy 11 的建议交付物

1. Recognition 困难样本集、confusion matrix 和 Before/After 报告。
2. `Miami + five days` 的中英文 Agent 端到端演示。
3. 新问卷字段映射图和可点击 iOS 流程。
4. 鞋/配饰增量 enrichment 的设计文档、任务表结构和成本上限。
