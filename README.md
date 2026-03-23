# Markdown 转 Anki 问答卡片工具

这是一个 Python 命令行工具，用于把 Markdown 笔记转换成可导入 Anki 的 `.apkg` 包。当前版本使用 Moonshot 兼容的 Chat Completions 接口，生成 Front/Back 问答卡片，支持双语内容、标签和补充说明。

## 功能特性

- 读取本地 Markdown 文件并按标题/长度分块
- 调用 LLM 自动提取核心知识点
- 生成 Front/Back 问答卡片，而不是 Cloze 填空卡片
- 支持 `extra` 补充说明、`source` 来源、`tags` 标签
- 导出为可直接导入 Anki 的 `.apkg` 文件
- 对缺失配置、非法 JSON 和字段缺失提供更清晰的错误提示

## 环境要求

- Python 3.9+
- 建议使用虚拟环境

## 安装

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env`，然后填写你的真实配置：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.moonshot.cn
LLM_MODEL=kimi-k2.5
LLM_TIMEOUT=120
```

如果只想快速更新 API Key，可以运行：

```bash
python setup_api_key.py
```

这个脚本会更新 `LLM_API_KEY`，同时保留已有的 `LLM_BASE_URL`，如果没有则补上 Moonshot 默认地址。

## 用法

```bash
python md_to_anki.py <input.md> <output.apkg>
```

示例：

```bash
python md_to_anki.py test_sample.md output.apkg
```

执行流程：

1. 读取 Markdown 文件
2. 按标题与长度切分文本块
3. 调用 LLM 生成问答卡片 JSON
4. 将卡片写入 Anki 牌组
5. 导出 `.apkg` 文件

如果上一次运行生成了 `failed_chunks_*.md` 报告，可以只补跑失败块：

```bash
python md_to_anki.py --retry-report failed_chunks_output_20260323_120000.md retry_output.apkg
```

也可以不传输出路径，脚本会自动基于原输出名生成一个合并包，例如 `output_merged.apkg`：

```bash
python md_to_anki.py --retry-report failed_chunks_output_20260323_120000.md
```

补跑时会自动读取同批次生成的 `cards_manifest_*.json`，把“原先成功的卡片 + 这次补跑成功的卡片”一起重新打包成新的 `.apkg`，这样你不需要手动合并主包和补跑包。

每次生成失败块报告时，终端和报告文件顶部还会直接给出一条可复制执行的补跑命令，例如：

```bash
python md_to_anki.py --retry-report "failed_chunks_output_run_20260323_192742.md" "output_merged.apkg"
```

实际使用时，优先直接复制报告里的 `Retry command` 那一行即可。

## 项目文件

- `md_to_anki.py`: 主脚本
- `setup_api_key.py`: 配置辅助脚本
- `.env.example`: 安全的环境变量模板
- `test_sample.md`: 可公开使用的样例 Markdown
- `tests/test_md_to_anki.py`: 离线测试

## 测试

离线测试：

```bash
python -m unittest discover -s tests -v
```

在线验证（会调用你的真实 LLM 配置）：

```bash
python test_new_cards.py
```

## 常见问题

### 缺少配置

如果看到 `缺少必要配置`，说明 `.env` 中缺少 `LLM_API_KEY` 或 `LLM_BASE_URL`。

### JSON 解析失败

如果模型没有返回合法 JSON，脚本会打印截断后的响应内容，便于你调整 prompt 或重试。

### 没有生成卡片

确认输入内容足够具体，并先用 `python test_new_cards.py` 验证 API 是否可用。

## GitHub 发布建议

如果你准备发布到 GitHub：

- 不要提交 `.env`
- 不要提交 `venv/`
- 不要提交 `.apkg` 产物
- 不要提交个人笔记、会话记忆和真实 API Key

## 许可证

MIT License
