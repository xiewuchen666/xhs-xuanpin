# AGENTS.md

## 项目目标

开发 Windows 小红书人工选品工作台。范围以 `prd.md` 为准，未经确认不得扩展。

## 开发前必读

按顺序读取：

1. `prd.md` — 产品范围与验收标准。
2. `design/visual-contract.md` — 已确认视觉与交互硬约束。
3. `TECHNICAL.md` — 已确认技术方案。
4. `CURRENT_TASK.md` — 当前唯一开发任务。

`DESIGN.md` 是基础视觉语言；与项目级约定冲突时，以 `design/visual-contract.md` 为准。

## 硬规则

- 不自行更换已确认布局、配色、字号、字重和核心交互。
- 不修改 `E:\project\rednote-commerce-hub`；只读取和迁移必要采集逻辑。
- 新项目独立 SQLite，不与旧项目共库。
- 不绕过验证码、登录验证、风控或平台安全机制。
- 真实能力必须真实验证；失败就记录失败，不用 mock 代替通过。
- V1 不引入 AI、云后端、Redis、MySQL、消息队列、React/Vue、第二套模拟器。
- 新增重大依赖或改变架构前先停下确认。
- 每完成一个可独立验收的小步骤再提交 Git，提交信息写清本次变化。
