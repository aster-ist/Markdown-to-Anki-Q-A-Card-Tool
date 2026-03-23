import json
import tempfile
import unittest
from pathlib import Path

import requests

import md_to_anki
from md_to_anki import ConfigurationError, MarkdownToAnki, RetryableAPIError
from setup_api_key import upsert_env_value


class MarkdownToAnkiTests(unittest.TestCase):
    def test_validate_config_raises_when_required_values_are_missing(self):
        converter = MarkdownToAnki(api_key="", base_url="")

        with self.assertRaises(ConfigurationError):
            converter.validate_config()

    def test_parse_markdown_splits_large_chunks(self):
        long_sentence = "算法" * 260

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "long.md"
            input_path.write_text(f"# 测试\n{long_sentence}", encoding="utf-8")

            converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
            chunks = converter.parse_markdown(str(input_path))

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))

    def test_parse_llm_cards_accepts_fenced_json(self):
        raw_result = """
```json
[
  {
    "front": "什么是算法？",
    "back": "算法是解决问题的一组明确步骤。",
    "extra": "",
    "tags": ["算法", "基础"]
  }
]
```
"""
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        cards = converter.parse_llm_cards(raw_result, source_file="sample.md")

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["source"], "sample.md")
        self.assertEqual(cards[0]["tags"], ["算法", "基础"])

    def test_parse_llm_cards_repairs_invalid_backslash_escape(self):
        raw_result = """
```json
[
  {
    "front": "为何 \\phi(p)=p-1？",
    "back": "因为 1 到 p-1 都与 p 互质。",
    "extra": "",
    "tags": ["数论"]
  }
]
```
"""
        raw_result = raw_result.replace("\\\\phi", "\\phi")

        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        cards = converter.parse_llm_cards(raw_result, source_file="sample.md")

        self.assertEqual(len(cards), 1)
        self.assertIn("\\phi", cards[0]["front"])

    def test_generate_cards_returns_empty_list_for_invalid_json(self):
        class StubConverter(MarkdownToAnki):
            def call_llm_api(self, prompt, max_tokens=2000):
                return "not-json"

        converter = StubConverter(api_key="dummy", base_url="https://example.com")
        cards = converter.generate_cards_from_text("测试内容", source_file="sample.md")

        self.assertEqual(cards, [])

    def test_extract_response_content_retries_when_only_reasoning_content_is_returned(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        result = {
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_content": "推理中",
                },
                "finish_reason": "length",
            }]
        }

        with self.assertRaises(RetryableAPIError) as context:
            converter._extract_response_content(result, "测试 prompt", max_tokens=100)

        self.assertEqual(context.exception.next_max_tokens, 512)

    def test_call_llm_api_retries_on_engine_overload(self):
        class DummyResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload
                self.text = str(payload)

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code} error")

        responses = [
            DummyResponse(429, {
                "error": {
                    "message": "The engine is currently overloaded, please try again later",
                    "type": "engine_overloaded_error",
                }
            }),
            DummyResponse(200, {
                "choices": [{
                    "message": {"content": "重试成功"},
                    "finish_reason": "stop",
                }]
            }),
        ]
        sleep_calls = []

        original_post = md_to_anki.requests.post
        original_sleep = md_to_anki.time.sleep

        try:
            md_to_anki.requests.post = lambda *args, **kwargs: responses.pop(0)
            md_to_anki.time.sleep = lambda seconds: sleep_calls.append(seconds)

            converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
            result = converter.call_llm_api("测试 prompt", max_tokens=100)
        finally:
            md_to_anki.requests.post = original_post
            md_to_anki.time.sleep = original_sleep

        self.assertEqual(result, "重试成功")
        self.assertEqual(sleep_calls, [converter.retry_backoff_seconds])

    def test_call_llm_api_retries_on_timeout(self):
        class DummyResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {
                    "choices": [{
                        "message": {"content": "超时后成功"},
                        "finish_reason": "stop",
                    }]
                }

            @staticmethod
            def raise_for_status():
                return None

        calls = []
        sleep_calls = []

        def fake_post(*args, **kwargs):
            calls.append("called")
            if len(calls) == 1:
                raise requests.Timeout("timeout")
            return DummyResponse()

        original_post = md_to_anki.requests.post
        original_sleep = md_to_anki.time.sleep

        try:
            md_to_anki.requests.post = fake_post
            md_to_anki.time.sleep = lambda seconds: sleep_calls.append(seconds)
            converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
            result = converter.call_llm_api("测试 prompt", max_tokens=100)
        finally:
            md_to_anki.requests.post = original_post
            md_to_anki.time.sleep = original_sleep

        self.assertEqual(result, "超时后成功")
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleep_calls, [converter.retry_backoff_seconds])

    def test_call_llm_api_retries_when_content_is_temporarily_empty(self):
        class DummyResponse:
            def __init__(self, payload):
                self.status_code = 200
                self._payload = payload
                self.text = str(payload)

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        responses = [
            DummyResponse({
                "choices": [{
                    "message": {"content": ""},
                    "finish_reason": "stop",
                }]
            }),
            DummyResponse({
                "choices": [{
                    "message": {"content": "最终内容"},
                    "finish_reason": "stop",
                }]
            }),
        ]
        sleep_calls = []

        original_post = md_to_anki.requests.post
        original_sleep = md_to_anki.time.sleep

        try:
            md_to_anki.requests.post = lambda *args, **kwargs: responses.pop(0)
            md_to_anki.time.sleep = lambda seconds: sleep_calls.append(seconds)

            converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
            result = converter.call_llm_api("测试 prompt", max_tokens=100)
        finally:
            md_to_anki.requests.post = original_post
            md_to_anki.time.sleep = original_sleep

        self.assertEqual(result, "最终内容")
        self.assertEqual(sleep_calls, [converter.retry_backoff_seconds])

    def test_export_to_apkg_creates_package(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        converter.create_deck("Test Deck")
        converter.add_cards_to_deck([{
            "front": "正面",
            "back": "背面",
            "extra": "",
            "source": "sample.md",
            "tags": ["测试"],
        }])

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "deck.apkg"
            success = converter.export_to_apkg(output_path)

            self.assertTrue(success)
            self.assertTrue(output_path.exists())

    def test_upsert_env_value_preserves_existing_settings(self):
        lines = [
            "LLM_BASE_URL=https://api.moonshot.cn",
            "LLM_TIMEOUT=120",
        ]

        updated_lines = upsert_env_value(lines, "LLM_API_KEY", "new-key")

        self.assertIn("LLM_API_KEY=new-key", updated_lines)
        self.assertIn("LLM_BASE_URL=https://api.moonshot.cn", updated_lines)
        self.assertIn("LLM_TIMEOUT=120", updated_lines)

    def test_record_failed_chunk_stores_summary_fields(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        converter.record_failed_chunk(
            index=3,
            total_chunks=10,
            chunk_text="这是一个失败块，用于测试失败清单记录。",
            source_file="sample.md",
            reason="未生成卡片",
        )

        self.assertEqual(len(converter.failed_chunks), 1)
        self.assertEqual(converter.failed_chunks[0]["index"], 3)
        self.assertEqual(converter.failed_chunks[0]["source_file"], "sample.md")
        self.assertEqual(converter.failed_chunks[0]["reason"], "未生成卡片")

    def test_write_failed_chunks_report_creates_markdown_file(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        converter.record_failed_chunk(
            index=1,
            total_chunks=2,
            chunk_text="# 标题\n失败内容",
            source_file="sample.md",
            reason="未生成卡片",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "cards.apkg"
            report_path = converter.write_failed_chunks_report(
                "sample.md",
                output_path,
                manifest_file="cards_manifest_sample.json",
            )

            self.assertIsNotNone(report_path)
            self.assertTrue(report_path.exists())
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("Failed Chunks Report", report_text)
            self.assertIn("Chunk 1/2", report_text)
            self.assertIn("失败内容", report_text)
            self.assertIn("Manifest file: cards_manifest_sample.json", report_text)
            self.assertIn("Retry command: python md_to_anki.py --retry-report", report_text)

    def test_write_and_load_cards_manifest(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        cards = [{
            "front": "问题",
            "back": "答案",
            "extra": "",
            "source": "sample.md",
            "tags": ["测试"],
        }]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "cards.apkg"
            manifest_path = converter.write_cards_manifest("sample.md", output_path, "Deck", cards)
            payload = converter.load_cards_manifest(manifest_path)

        self.assertEqual(payload["deck_name"], "Deck")
        self.assertEqual(payload["cards"][0]["front"], "问题")
        self.assertTrue(payload["run_id"])

    def test_manifest_and_failed_report_share_same_run_id(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        converter.record_failed_chunk(
            index=1,
            total_chunks=1,
            chunk_text="失败内容",
            source_file="sample.md",
            reason="未生成卡片",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "cards.apkg"
            manifest_path = converter.write_cards_manifest("sample.md", output_path, "Deck", [])
            report_path = converter.write_failed_chunks_report(
                "sample.md",
                output_path,
                manifest_file=manifest_path,
            )

        manifest_name = manifest_path.name
        report_name = report_path.name
        self.assertIn("_run_", manifest_name)
        self.assertIn("_run_", report_name)
        manifest_run_id = manifest_name.split("_run_", 1)[1].rsplit(".", 1)[0]
        report_run_id = report_name.split("_run_", 1)[1].rsplit(".", 1)[0]
        self.assertEqual(manifest_run_id, report_run_id)

    def test_load_failed_chunks_report_parses_entries(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "failed_chunks_sample.md"
            report_path.write_text(
                "# Failed Chunks Report\n\n"
                "## Chunk 2/5\n\n"
                "- Source file: sample.md\n"
                "- Reason: 未生成卡片\n"
                "- Preview: 示例预览\n\n"
                "```md\n"
                "## 标题\n失败块内容\n"
                "```\n",
                encoding="utf-8",
            )

            entries = converter.load_failed_chunks_report(report_path)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["index"], 2)
        self.assertEqual(entries[0]["total_chunks"], 5)
        self.assertEqual(entries[0]["source_file"], "sample.md")
        self.assertIn("失败块内容", entries[0]["chunk_text"])

    def test_process_failed_chunks_report_generates_retry_deck(self):
        class StubConverter(MarkdownToAnki):
            def __init__(self):
                super().__init__(api_key="dummy", base_url="https://example.com")

            def generate_cards_from_text(self, text, source_file=""):
                return [{
                    "front": f"Q: {source_file}",
                    "back": text,
                    "extra": "",
                    "source": source_file,
                    "tags": ["retry"],
                }]

        converter = StubConverter()

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "failed_chunks_sample.md"
            output_path = Path(temp_dir) / "retry.apkg"
            manifest_path = Path(temp_dir) / "cards_manifest_sample.json"
            manifest_path.write_text(
                json.dumps({
                    "input_file": "sample.md",
                    "output_file": "cards.apkg",
                    "deck_name": "sample",
                    "cards": [{
                        "front": "原始卡片",
                        "back": "原始答案",
                        "extra": "",
                        "source": "sample.md",
                        "tags": ["original"],
                    }],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            report_path.write_text(
                "# Failed Chunks Report\n\n"
                "- Input file: sample.md\n"
                "- Output file: cards.apkg\n"
                f"- Manifest file: {manifest_path}\n"
                "- Failed chunks: 1\n\n"
                "## Chunk 1/3\n\n"
                "- Source file: sample.md\n"
                "- Reason: 未生成卡片\n"
                "- Preview: 示例预览\n\n"
                "```md\n"
                "失败块内容\n"
                "```\n",
                encoding="utf-8",
            )

            success = converter.process_failed_chunks_report(report_path, output_path)

            self.assertTrue(success)
            self.assertTrue(output_path.exists())
            self.assertEqual(len(converter.failed_chunks), 0)
            self.assertEqual(len(converter.deck.notes), 2)

    def test_build_retry_output_path_uses_original_output_name(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        retry_output = converter.build_retry_output_path(
            "failed_chunks_demo.md",
            "D:/tmp/output.apkg",
        )

        self.assertEqual(Path(retry_output).name, "output_merged.apkg")

    def test_build_retry_command_uses_report_and_merged_output(self):
        converter = MarkdownToAnki(api_key="dummy", base_url="https://example.com")
        command = converter.build_retry_command(
            "D:/tmp/failed_chunks_output_run_20260323_192742.md",
            "D:/tmp/output.apkg",
        )

        self.assertIn('--retry-report "D:/tmp/failed_chunks_output_run_20260323_192742.md"', command)
        self.assertIn('"D:\\tmp\\output_merged.apkg"', command.replace("/", "\\"))


if __name__ == "__main__":
    unittest.main()
