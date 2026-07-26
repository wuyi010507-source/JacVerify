# JacVerify LLM 功能现状

更新时间：2026-07-26

## 这次做了什么

本次只实现当前 FIFO 验证链路真正需要的两个 LLM 调用，没有让模型直接修改 RTL。当前按实验要求优先使用 Firecrawl Agent，Jac byLLM 作为备用。

### 1. 失败原因排序

输入是已经由仿真器产生并结构化的失败证据：

- FIFO 需求摘要；
- 失败类型，例如 `WRAP_MISMATCH`；
- expected / observed；
- cycle（如果测试台提供）；
- 原始仿真输出。

输出是类型化的三个候选原因：

- `rank`：排序；
- `claim`：可证伪的根因假设；
- `confidence`：0 到 1 的相对置信度；
- `next_action`：最小的下一步验证动作。

Firecrawl 代码位置：`jacverify/tool_adapter.py` 中的
`rank_hypotheses_firecrawl`。

备用 byLLM 代码位置：`jacverify/llm_calls.jac` 中的
`rank_fifo_failure`。

### 2. 验证 Artifact 建议

第二次调用根据失败证据和排名第一的假设，生成一个最小验证 Artifact 的说明：

- 类型：定向测试、SVA 断言或已审查 RTL 候选；
- 要验证的具体行为；
- 为什么它能区分当前假设。

Firecrawl 代码位置：`jacverify/tool_adapter.py` 中的
`generate_artifact_firecrawl`。

备用 byLLM 代码位置：`jacverify/llm_calls.jac` 中的
`propose_fifo_artifact`。

当前版本不会让 LLM 自由写文件或选择任意路径。它只能给出方案说明，实际复验仍固定使用仓库内已审查的：

`demo/fifo/fifo_fixed.sv`

这是刻意保留的安全边界，也符合目前一天黑客松的演示范围。

### 3. 接入现有 Walker

- `RankHypothesesWalker` 在 Firecrawl live 模式调用 Agent API；
- `GenerateArtifactWalker` 在 Firecrawl live 模式再次调用 Agent API；
- `JACVERIFY_LLM_BACKEND=byllm` 时使用原来的类型化 Jac 调用；
- mock 模式继续使用原有确定性结果，现有演示和测试不会依赖网络；
- LLM 输出先经过 Jac 类型校验，再转换成现有 Python DTO；
- LLM 无权产生最终 PASS，最终结果仍由 Icarus / Verilator / cocotb 给出。

### 4. 最多三次自动 Debug

当前链路会依次尝试三个排好序的 Hypothesis：

1. 生成当前假设的 Artifact；
2. 运行 targeted reverify；
3. 如果明确返回 `VERIFICATION_FAILED`，把当前假设标记为 `rejected`；
4. 自动选择下一个 `pending` 假设；
5. 最多执行三次。

第三次仍失败时，Run 进入：

```text
NEEDS_USER_REVIEW / blocked
```

以下情况不会自动重试，会立即等待用户介入：

- `TOOL_ERROR` 或未知复验状态；
- LLM 没有返回假设；
- Artifact 生成失败；
- Failure、Hypothesis 或 Artifact 图节点缺失；
- 状态机进入了不符合预期的状态。

每个 Hypothesis 会记录 `pending / selected / rejected / supported`、尝试次数
和拒绝原因；每个 Artifact 会记录对应 attempt 和 reverify 状态。

### 5. 配置

`jac.toml` 只加入了低随机度和有限重试：

```toml
[byllm.call_params]
temperature = 0.1
max_output_retries = 2
```

`.env.example` 中的 Key 保持为空，默认仍为 mock：

```bash
JACVERIFY_MOCK_LLM=1
JACVERIFY_LLM_BACKEND=firecrawl
FIRECRAWL_API_KEY=
JACVERIFY_FIRECRAWL_MODEL=spark-1-mini
JACVERIFY_FIRECRAWL_MAX_CREDITS=100
```

本机已经执行 `jac install byllm --no-save`。Jac 运行时缓存中已有
byLLM 0.6.19 和 LiteLLM 1.82.6；安装过程没有发起模型调用。

## 现在可以怎么运行

不配置 Key，运行稳定的本地演示：

```bash
cp .env.example .env
set -a
source .env
set +a
/Users/zhangdirui/.local/bin/jac test
```

Firecrawl live 实验配置：

```bash
JACVERIFY_MOCK_LLM=0
JACVERIFY_LLM_BACKEND=firecrawl
```

真实调用会把 FIFO 需求摘要、失败 expected/observed 和部分仿真输出发送
到 Firecrawl。

## Firecrawl 实测结果

2026-07-26 已完成一次 `mock EDA + live Firecrawl` 端到端运行：

- 两个 `spark-1-mini` Agent 任务都成功返回；
- 严格 JSON 输出成功转换成 JacVerify DTO；
- 七个 Walker 全部执行；
- 状态机最终到达 `DONE`；
- 固定候选 `fifo_fixed.sv` 的 mock reverify 为 `PASSED`。

但本次 Firecrawl 排名第一的根因是 full 检测错误导致覆盖；仓库中实际植入
的 bug 是 `write_ptr` 在 `DEPTH-1` 后错误回绕到 1。因此当前结果只能证明
Firecrawl API 接口和结构化输出链路可用，不能证明诊断准确。

另外，当前 reverify 使用固定的已审查候选，所以 reverify 通过并不意味着
第一名假设得到因果验证。后续必须把 RTL 片段提供给诊断调用，并让生成的
定向测试真正区分候选假设。

## 还缺什么

### 必须补齐后才能提高诊断可信度

1. 给诊断调用加入相关 RTL 片段，目前只有需求和仿真输出。
2. 让定向测试真正区分候选假设，不能只复验固定修复件。
3. 记录 Firecrawl job ID、model、credits 和调用时延。
4. 轮换此前已经公开的 Firecrawl Key；不要提交 `.env`。

### 产品链路仍未完成

1. 当前“生成 Artifact”只是生成方案说明，没有生成新的 cocotb 测试或 SVA 文件。
2. 当前 live Artifact 仍绑定到预先审查的 `fifo_fixed.sv`，没有自动生成 RTL patch。
3. 失败上下文目前是 FIFO 专用的简化需求摘要，还没有从任意设计文档自动抽取需求。
4. 尚未记录 token、费用、模型名和调用延迟。
5. targeted reverify 通过后，还应再跑完整 regression 才能进入 DONE。

## 建议的下一步

下一步优先把相关 RTL 片段放进失败上下文，并生成真正能区分 Hypothesis 的
cocotb 定向测试。之后再补 targeted PASS 后的完整 regression gate。
