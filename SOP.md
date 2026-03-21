# 发布版 SOP

## 安装

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

把 `.env.example` 复制为 `.env`，然后填写真实配置：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.moonshot.cn
LLM_MODEL=kimi-k2.5
LLM_TIMEOUT=120
```

## 使用

```powershell
python md_to_anki.py test_sample.md output.apkg
```

## 验证

```powershell
python -m unittest discover -s tests -v
```
