import html
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import genanki
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://api.moonshot.cn"
DEFAULT_MODEL = "kimi-k2.5"
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_RETRY_BACKOFF_SECONDS = 3.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 0.8
MAX_CHUNK_SIZE = 500
MAX_ERROR_PREVIEW = 200
MAX_CHUNK_PREVIEW = 160


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is missing."""


class RetryableAPIError(RuntimeError):
    """Raised when an API response should be retried."""

    def __init__(self, message, next_max_tokens=None):
        super().__init__(message)
        self.next_max_tokens = next_max_tokens


# 初始化 Anki 模型 - 带标签、Extra 和 Source 的增强版
my_model = genanki.Model(
    1607392321,
    "Enhanced Front-Back Model with Tags",
    fields=[
        {"name": "Front"},
        {"name": "Back"},
        {"name": "Extra"},
        {"name": "Source"},
    ],
    templates=[{
        "name": "Card 1",
        "qfmt": """
            <div class="front">{{Front}}</div>
            {{#Source}}
            <div class="source">来源: {{Source}}</div>
            {{/Source}}
        """,
        "afmt": """
            {{FrontSide}}
            <hr id="answer">
            <div class="back">{{Back}}</div>
            {{#Extra}}
            <hr class="extra-divider">
            <div class="extra">
                <div class="extra-title">补充说明</div>
                {{Extra}}
            </div>
            {{/Extra}}
        """,
    }],
    css="""
    .card {
        font-family: "Microsoft YaHei", Arial, sans-serif;
        font-size: 18px;
        text-align: left;
        color: #2c3e50;
        background-color: white;
        padding: 20px;
        line-height: 1.6;
    }
    .front {
        font-weight: bold;
        font-size: 20px;
        margin-bottom: 15px;
        color: #34495e;
    }
    .back {
        margin-top: 10px;
    }
    .source {
        font-size: 14px;
        color: #7f8c8d;
        margin-top: 10px;
        font-style: italic;
    }
    .extra {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        margin-top: 10px;
    }
    .extra-title {
        font-weight: bold;
        color: #3498db;
        margin-bottom: 8px;
        font-size: 16px;
    }
    .extra-divider {
        border: none;
        border-top: 1px dashed #bdc3c7;
        margin: 15px 0;
    }
    hr#answer {
        border: none;
        border-top: 2px solid #3498db;
        margin: 15px 0;
    }
    """,
)


class MarkdownToAnki:
    def __init__(self, api_key=None, base_url=None, model=None, timeout=None):
        self.api_key = self._resolve_setting(api_key, "LLM_API_KEY")
        self.base_url = self._resolve_setting(base_url, "LLM_BASE_URL")
        self.model = self._resolve_setting(model, "LLM_MODEL", DEFAULT_MODEL)
        self.timeout = self._parse_timeout(timeout or os.getenv("LLM_TIMEOUT"))
        self.max_attempts = self._parse_attempts(os.getenv("LLM_MAX_ATTEMPTS"))
        self.retry_backoff_seconds = self._parse_float(
            os.getenv("LLM_RETRY_BACKOFF_SECONDS"),
            DEFAULT_RETRY_BACKOFF_SECONDS,
        )
        self.request_interval_seconds = self._parse_float(
            os.getenv("LLM_REQUEST_INTERVAL_SECONDS"),
            DEFAULT_REQUEST_INTERVAL_SECONDS,
        )
        self.deck = None
        self.failed_chunks = []
        self.current_run_id = None

    @staticmethod
    def _resolve_setting(explicit_value, env_name, default=""):
        if explicit_value is not None:
            return str(explicit_value).strip()

        return str(os.getenv(env_name) or default).strip()

    @staticmethod
    def _parse_timeout(timeout_value):
        if timeout_value in (None, ""):
            return DEFAULT_TIMEOUT

        try:
            parsed_timeout = int(timeout_value)
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT

        return parsed_timeout if parsed_timeout > 0 else DEFAULT_TIMEOUT

    @staticmethod
    def _parse_attempts(attempt_value):
        if attempt_value in (None, ""):
            return DEFAULT_MAX_ATTEMPTS

        try:
            parsed_attempts = int(attempt_value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_ATTEMPTS

        return parsed_attempts if parsed_attempts > 0 else DEFAULT_MAX_ATTEMPTS

    @staticmethod
    def _parse_float(value, default):
        if value in (None, ""):
            return default

        try:
            parsed_value = float(value)
        except (TypeError, ValueError):
            return default

        return parsed_value if parsed_value >= 0 else default

    def validate_config(self):
        missing = []

        if not self.api_key:
            missing.append("LLM_API_KEY")
        if not self.base_url:
            missing.append("LLM_BASE_URL")

        if missing:
            fields = ", ".join(missing)
            raise ConfigurationError(
                f"缺少必要配置: {fields}。请先创建 .env 文件，或参考 .env.example 填写。"
            )

        return True

    @staticmethod
    def _clean_llm_response(result):
        cleaned = result.strip().replace("\r\n", "\n")

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        first_bracket = cleaned.find("[")
        last_bracket = cleaned.rfind("]")
        if first_bracket != -1 and last_bracket != -1 and first_bracket < last_bracket:
            cleaned = cleaned[first_bracket:last_bracket + 1]

        return cleaned.strip()

    @staticmethod
    def _repair_common_json_issues(cleaned_result):
        repaired = cleaned_result

        # Repair LaTeX-like backslashes such as \phi that are illegal in JSON strings.
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", repaired)

        # Remove trailing commas before closing braces/brackets.
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)

        return repaired

    @staticmethod
    def _normalize_tags(tags):
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list):
            return []

        normalized_tags = []
        for tag in tags:
            if not isinstance(tag, str):
                continue
            normalized = tag.strip()
            if normalized:
                normalized_tags.append(normalized)

        return normalized_tags

    def parse_llm_cards(self, raw_result, source_file=""):
        cleaned_result = self._clean_llm_response(raw_result)
        try:
            cards = json.loads(cleaned_result)
        except json.JSONDecodeError:
            cards = json.loads(self._repair_common_json_issues(cleaned_result))

        if not isinstance(cards, list):
            raise ValueError("LLM 返回必须是 JSON 数组。")

        normalized_cards = []
        for index, card in enumerate(cards, start=1):
            if not isinstance(card, dict):
                raise ValueError(f"第 {index} 张卡片不是 JSON 对象。")

            front = card.get("front")
            back = card.get("back")

            if not isinstance(front, str) or not front.strip():
                raise ValueError(f"第 {index} 张卡片缺少有效的 front 字段。")
            if not isinstance(back, str) or not back.strip():
                raise ValueError(f"第 {index} 张卡片缺少有效的 back 字段。")

            extra = card.get("extra", "")
            if extra is None:
                extra = ""
            elif not isinstance(extra, str):
                extra = str(extra)

            normalized_cards.append({
                "front": front.strip(),
                "back": back.strip(),
                "extra": extra.strip(),
                "source": card.get("source", source_file) or source_file,
                "tags": self._normalize_tags(card.get("tags", [])),
            })

        return normalized_cards

    def _extract_error_details(self, response):
        try:
            payload = response.json()
        except ValueError:
            return None, None

        error = payload.get("error")
        if not isinstance(error, dict):
            return None, None

        return error.get("type"), error.get("message")

    def _should_retry_response(self, response):
        error_type, error_message = self._extract_error_details(response)

        if response.status_code == 429:
            return True, error_type, error_message
        if response.status_code >= 500:
            return True, error_type, error_message
        if error_type in {"engine_overloaded_error", "rate_limit_exceeded"}:
            return True, error_type, error_message

        return False, error_type, error_message

    def _sleep_before_retry(self, attempt, reason):
        delay_seconds = self.retry_backoff_seconds * attempt
        print(f"[DEBUG] {reason}，{delay_seconds:.1f} 秒后重试...")
        time.sleep(delay_seconds)

    def call_llm_api(self, prompt, max_tokens=2000):
        """调用 LLM API 生成内容"""
        try:
            self.validate_config()
            url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            current_max_tokens = max_tokens

            for attempt in range(1, self.max_attempts + 1):
                data = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是一个专业的 Anki 卡片制作助手，擅长从学习材料中"
                                "提取关键知识点并生成高质量的问答卡片。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": current_max_tokens,
                    "temperature": 1,
                }

                print(f"[DEBUG] 请求 URL: {url}")
                print(f"[DEBUG] 使用模型: {data['model']}")
                try:
                    response = requests.post(url, headers=headers, json=data, timeout=self.timeout)
                except (requests.Timeout, requests.ConnectionError) as exc:
                    if attempt < self.max_attempts:
                        self._sleep_before_retry(attempt, f"网络超时或连接失败（{exc.__class__.__name__}）")
                        continue
                    raise

                print(f"[DEBUG] 响应状态码: {response.status_code}")
                if response.status_code != 200:
                    print(f"[DEBUG] 响应内容: {response.text[:500]}")

                should_retry, error_type, error_message = self._should_retry_response(response)
                if should_retry and attempt < self.max_attempts:
                    retry_reason = error_type or error_message or f"HTTP {response.status_code}"
                    self._sleep_before_retry(attempt, f"接口繁忙或限流（{retry_reason}）")
                    continue

                response.raise_for_status()

                try:
                    result = response.json()
                except ValueError as exc:
                    raise ValueError("API 返回的不是合法 JSON。") from exc

                try:
                    return self._extract_response_content(result, prompt, max_tokens=current_max_tokens)
                except RetryableAPIError as exc:
                    if attempt >= self.max_attempts:
                        raise ValueError(str(exc)) from exc

                    if exc.next_max_tokens:
                        current_max_tokens = exc.next_max_tokens

                    self._sleep_before_retry(attempt, str(exc))

            raise ValueError("超过最大重试次数，API 仍未返回可用内容。")
        except (ConfigurationError, ValueError, requests.RequestException) as exc:
            print(f"API 调用错误: {exc}")
            return None
        except Exception as exc:
            print(f"API 调用错误: {exc}")
            return None

    def _extract_response_content(self, result, prompt, max_tokens):
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("API 返回中缺少 choices 数据。")

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content")

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_value = item.get("text", "")
                    if text_value:
                        text_parts.append(text_value)
            content = "".join(text_parts)

        if isinstance(content, str) and content.strip():
            return content.strip()

        reasoning_content = message.get("reasoning_content")
        finish_reason = choice.get("finish_reason")

        if reasoning_content and finish_reason == "length":
            retry_max_tokens = min(max(max_tokens * 2, 512), 4000)
            if retry_max_tokens > max_tokens:
                raise RetryableAPIError(
                    "响应只有 reasoning_content，自动提高 max_tokens 重试一次",
                    next_max_tokens=retry_max_tokens,
                )

        raise RetryableAPIError("API 返回内容为空。")

    @staticmethod
    def _split_large_chunk(chunk):
        if len(chunk) <= MAX_CHUNK_SIZE:
            return [chunk.strip()]

        sentences = re.split(r"(?<=[。！？.!?\n])", chunk)
        split_chunks = []
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > MAX_CHUNK_SIZE:
                if current:
                    split_chunks.append(current.strip())
                    current = ""

                for start in range(0, len(sentence), MAX_CHUNK_SIZE):
                    split_chunks.append(sentence[start:start + MAX_CHUNK_SIZE].strip())
                continue

            if len(current) + len(sentence) <= MAX_CHUNK_SIZE:
                current += sentence
            else:
                if current:
                    split_chunks.append(current.strip())
                current = sentence

        if current:
            split_chunks.append(current.strip())

        return [item for item in split_chunks if item]

    def parse_markdown(self, file_path):
        """读取 Markdown 文件并按段落/标题分块"""
        with open(file_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        # 按标题分割；如果没有标题，则整体作为一个块处理。
        chunks = re.split(r"(?=^#{1,6}\s)", content, flags=re.MULTILINE)
        chunks = [chunk.strip() for chunk in chunks if chunk.strip()]

        final_chunks = []
        for chunk in chunks:
            final_chunks.extend(self._split_large_chunk(chunk))

        return final_chunks

    def generate_cards_from_text(self, text, source_file=""):
        """使用 LLM API 从文本生成增强版卡片（带标签、Extra、Source）"""
        prompt = f"""
请从以下学习材料中生成 Anki 卡片。每张卡片包含：front（问题）、back（答案）、extra（补充说明）、tags（标签数组）。

**严格限制：每个文本块最多生成 2-3 张卡片，只提取最核心的知识点。**

要求：
1. **极度精简**：只提取最核心、最重要的知识点，宁缺毋滥
2. 优先选择：关键概念定义、核心原理、必须掌握的内容
3. 跳过：过于简单的内容、重复的信息、细枝末节、示例性内容
4. 问题要具体明确，答案要简洁（控制在 100 字以内）
5. **重要：如果原文是中英双语，请保持双语格式**
   - front（问题）：中文问题 + 英文问题（换行分隔）
   - back（答案）：中文答案 + 英文答案（换行分隔）
6. 如果原文只有单语，则生成单语卡片
7. **extra 字段尽量留空**，只在必要时添加简短补充（不超过 50 字）

**新增字段说明：**
- **extra**（补充说明）：尽量留空，只在必要时添加简短补充
- **tags**（标签数组）：2-3 个标签即可，如 ["算法", "数据结构"]

返回 JSON 格式：
[
  {{
    "front": "问题",
    "back": "答案",
    "extra": "",
    "tags": ["标签1", "标签2"]
  }}
]

学习材料：
{text}

请直接返回 JSON 数组，不要有其他说明文字。记住：最多 2-3 张卡片，答案简洁，extra 尽量留空。
"""

        result = self.call_llm_api(prompt, max_tokens=4000)
        if not result:
            return []

        try:
            return self.parse_llm_cards(result, source_file=source_file)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"JSON 解析错误: {exc}")
            print(f"API 返回内容: {result[:MAX_ERROR_PREVIEW]}...")

        repair_prompt = (
            prompt
            + "\n\n上一次输出不是合法 JSON。请重新输出严格合法的 JSON 数组，"
              "不要使用 Markdown 代码块，不要输出省略号，不要截断，"
              "如需写数学符号请避免使用未转义反斜杠。"
        )
        repaired_result = self.call_llm_api(repair_prompt, max_tokens=4000)
        if not repaired_result:
            return []

        try:
            return self.parse_llm_cards(repaired_result, source_file=source_file)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"JSON 二次解析错误: {exc}")
            print(f"API 返回内容: {repaired_result[:MAX_ERROR_PREVIEW]}...")
            return []

    @staticmethod
    def _make_chunk_preview(text):
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= MAX_CHUNK_PREVIEW:
            return normalized
        return normalized[:MAX_CHUNK_PREVIEW].rstrip() + "..."

    def _ensure_run_id(self):
        if not self.current_run_id:
            self.current_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.current_run_id

    def record_failed_chunk(self, index, total_chunks, chunk_text, source_file, reason):
        self.failed_chunks.append({
            "index": index,
            "total_chunks": total_chunks,
            "source_file": source_file,
            "reason": reason,
            "preview": self._make_chunk_preview(chunk_text),
            "chunk_text": chunk_text.strip(),
        })

    def print_failed_chunks_summary(self):
        if not self.failed_chunks:
            print("失败块清单：无")
            return

        print(f"失败块清单：共 {len(self.failed_chunks)} 个")
        for item in self.failed_chunks:
            print(
                f"  - 块 {item['index']}/{item['total_chunks']} | "
                f"来源: {item['source_file']} | 原因: {item['reason']}"
            )
            print(f"    预览: {item['preview']}")

    def write_cards_manifest(self, input_file, output_file, deck_name, cards):
        output_path = Path(output_file)
        run_id = self._ensure_run_id()
        manifest_name = f"cards_manifest_{output_path.stem}_run_{run_id}.json"
        manifest_path = output_path.parent / manifest_name

        payload = {
            "input_file": str(input_file),
            "output_file": str(output_file),
            "deck_name": deck_name,
            "run_id": run_id,
            "cards": cards,
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"成功卡片清单已保存到: {manifest_path}")
        return manifest_path

    def load_cards_manifest(self, manifest_file):
        manifest_path = Path(manifest_file)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        cards = payload.get("cards")
        if not isinstance(cards, list):
            raise ValueError(f"成功卡片清单格式无效: {manifest_file}")
        return payload

    def write_failed_chunks_report(self, input_file, output_file, manifest_file=None):
        if not self.failed_chunks:
            return None

        output_path = Path(output_file)
        run_id = self._ensure_run_id()
        report_name = f"failed_chunks_{output_path.stem}_run_{run_id}.md"
        report_path = output_path.parent / report_name
        retry_command = self.build_retry_command(report_path, output_file)

        lines = [
            "# Failed Chunks Report",
            "",
            f"- Input file: {input_file}",
            f"- Output file: {output_file}",
            f"- Manifest file: {manifest_file or ''}",
            f"- Retry command: {retry_command}",
            f"- Failed chunks: {len(self.failed_chunks)}",
            "",
        ]

        for item in self.failed_chunks:
            lines.extend([
                f"## Chunk {item['index']}/{item['total_chunks']}",
                "",
                f"- Source file: {item['source_file']}",
                f"- Reason: {item['reason']}",
                f"- Preview: {item['preview']}",
                "",
                "```md",
                item["chunk_text"],
                "```",
                "",
            ])

        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"失败块报告已保存到: {report_path}")
        print(f"补跑命令: {retry_command}")
        return report_path

    def load_failed_chunks_report_metadata(self, report_file):
        content = Path(report_file).read_text(encoding="utf-8")
        metadata = {}
        for key in ("Input file", "Output file", "Manifest file", "Failed chunks"):
            match = re.search(rf"- {re.escape(key)}: (.*)", content)
            metadata[key] = match.group(1).strip() if match else ""
        return metadata

    def load_failed_chunks_report(self, report_file):
        report_path = Path(report_file)
        content = report_path.read_text(encoding="utf-8")

        pattern = re.compile(
            r"## Chunk (\d+)/(\d+)\n"
            r"(?:\n)?- Source file: (?P<source>[^\n]+)\n"
            r"- Reason: (?P<reason>[^\n]+)\n"
            r"- Preview: (?P<preview>[^\n]*)\n"
            r"\n```md\n(?P<chunk>.*?)\n```",
            re.DOTALL,
        )

        entries = []
        for match in pattern.finditer(content):
            entries.append({
                "index": int(match.group(1)),
                "total_chunks": int(match.group(2)),
                "source_file": match.group("source").strip(),
                "reason": match.group("reason").strip(),
                "preview": match.group("preview").strip(),
                "chunk_text": match.group("chunk").strip(),
            })

        if not entries:
            raise ValueError(f"未能从失败块报告中解析出任何块: {report_file}")

        return entries

    def build_retry_output_path(self, report_file, original_output_file):
        if original_output_file:
            original_path = Path(original_output_file)
            return original_path.with_name(f"{original_path.stem}_merged.apkg")

        report_path = Path(report_file)
        return report_path.with_name(f"{report_path.stem}_merged.apkg")

    def build_retry_command(self, report_file, original_output_file):
        retry_output_path = self.build_retry_output_path(report_file, original_output_file)
        return (
            f'python md_to_anki.py --retry-report "{report_file}" '
            f'"{retry_output_path}"'
        )

    def process_failed_chunks_report(self, report_file, output_file=None):
        self.validate_config()
        self.failed_chunks = []
        self.current_run_id = None

        metadata = self.load_failed_chunks_report_metadata(report_file)
        entries = self.load_failed_chunks_report(report_file)
        original_output_file = metadata.get("Output file", "")
        manifest_file = metadata.get("Manifest file", "")

        if output_file is None:
            output_file = self.build_retry_output_path(report_file, original_output_file)

        print(f"读取失败块报告: {report_file}")
        print(f"待补跑块数: {len(entries)}")

        deck_name = f"{Path(report_file).stem}_retry"
        base_cards = []
        if manifest_file:
            manifest = self.load_cards_manifest(manifest_file)
            deck_name = manifest.get("deck_name") or deck_name
            base_cards = manifest.get("cards", [])
            print(f"读取成功卡片清单: {manifest_file}")
            print(f"原始成功卡片数: {len(base_cards)}")
        self.create_deck(deck_name)

        all_cards = list(base_cards)
        for retry_index, entry in enumerate(entries, start=1):
            print(
                f"补跑失败块 {retry_index}/{len(entries)} "
                f"(原块 {entry['index']}/{entry['total_chunks']})..."
            )
            cards = self.generate_cards_from_text(
                entry["chunk_text"],
                source_file=entry["source_file"],
            )
            all_cards.extend(cards)
            print(f"  生成 {len(cards)} 张卡片")

            if not cards:
                self.record_failed_chunk(
                    index=entry["index"],
                    total_chunks=entry["total_chunks"],
                    chunk_text=entry["chunk_text"],
                    source_file=entry["source_file"],
                    reason="补跑后仍未生成卡片",
                )

            if retry_index < len(entries) and self.request_interval_seconds > 0:
                time.sleep(self.request_interval_seconds)

        print(f"补跑总共生成 {len(all_cards)} 张卡片")
        self.print_failed_chunks_summary()
        manifest_path = self.write_cards_manifest(report_file, output_file, deck_name, all_cards)
        self.write_failed_chunks_report(report_file, output_file, manifest_file=manifest_path)
        self.add_cards_to_deck(all_cards)
        return self.export_to_apkg(output_file)

    def create_deck(self, deck_name="My Deck"):
        """创建 Anki 牌组"""
        self.deck = genanki.Deck(2023010101, deck_name)

    def add_cards_to_deck(self, cards):
        """将卡片添加到牌组（支持标签）"""
        if not self.deck:
            self.create_deck()

        for card in cards:
            tags = [tag.replace(" ", "_") for tag in self._normalize_tags(card.get("tags", []))]

            note = genanki.Note(
                model=my_model,
                fields=[
                    html.escape(card["front"]),
                    html.escape(card["back"]),
                    html.escape(card.get("extra", "")),
                    html.escape(str(card.get("source", ""))),
                ],
                tags=tags,
            )
            self.deck.add_note(note)

    def export_to_apkg(self, output_path):
        """导出为 .apkg 文件"""
        if not self.deck:
            print("错误：牌组为空")
            return False

        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            genanki.Package(self.deck).write_to_file(str(output_path))
            print(f"成功导出到: {output_path}")
            return True
        except Exception as exc:
            print(f"导出错误: {exc}")
            return False

    def process(self, input_file, output_file):
        """完整处理流程"""
        self.validate_config()
        self.failed_chunks = []
        self.current_run_id = None

        print(f"读取文件: {input_file}")
        chunks = self.parse_markdown(input_file)
        print(f"分块完成，共 {len(chunks)} 个块")

        self.create_deck(Path(input_file).stem)

        all_cards = []
        for index, chunk in enumerate(chunks, start=1):
            print(f"处理块 {index}/{len(chunks)}...")
            cards = self.generate_cards_from_text(chunk, source_file=Path(input_file).name)
            all_cards.extend(cards)
            print(f"  生成 {len(cards)} 张卡片")
            if not cards:
                self.record_failed_chunk(
                    index=index,
                    total_chunks=len(chunks),
                    chunk_text=chunk,
                    source_file=Path(input_file).name,
                    reason="未生成卡片",
                )
            if index < len(chunks) and self.request_interval_seconds > 0:
                time.sleep(self.request_interval_seconds)

        print(f"总共生成 {len(all_cards)} 张卡片")
        self.print_failed_chunks_summary()
        manifest_path = self.write_cards_manifest(input_file, output_file, Path(input_file).stem, all_cards)
        self.write_failed_chunks_report(input_file, output_file, manifest_file=manifest_path)
        self.add_cards_to_deck(all_cards)
        return self.export_to_apkg(output_file)


def build_parser():
    parser = argparse.ArgumentParser(
        description="将 Markdown 笔记或失败块报告转换为 Anki 卡片包。"
    )
    parser.add_argument("input", nargs="?", help="输入 Markdown 文件路径")
    parser.add_argument("output", nargs="?", help="输出 apkg 文件路径")
    parser.add_argument(
        "--retry-report",
        dest="retry_report",
        help="失败块报告路径。提供后将只补跑报告中的失败块。",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.retry_report and not args.input:
        parser.error("必须提供输入 Markdown 文件，或使用 --retry-report 指定失败块报告。")

    if args.retry_report and args.input:
        parser.error("使用 --retry-report 时不需要再提供 input 参数。")

    if not args.retry_report and not args.output:
        parser.error("普通模式下必须提供 output 参数。")

    input_file = args.input
    output_file = args.output

    if input_file and not os.path.exists(input_file):
        print(f"错误：文件不存在 {input_file}")
        sys.exit(1)

    if args.retry_report and not os.path.exists(args.retry_report):
        print(f"错误：失败块报告不存在 {args.retry_report}")
        sys.exit(1)

    try:
        converter = MarkdownToAnki()
        if args.retry_report:
            success = converter.process_failed_chunks_report(args.retry_report, output_file)
        else:
            success = converter.process(input_file, output_file)
    except ConfigurationError as exc:
        print(f"配置错误: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"运行错误: {exc}")
        sys.exit(1)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
