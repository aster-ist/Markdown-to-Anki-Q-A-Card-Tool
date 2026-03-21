import tempfile
import unittest
from pathlib import Path

from md_to_anki import ConfigurationError, MarkdownToAnki
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

    def test_generate_cards_returns_empty_list_for_invalid_json(self):
        class StubConverter(MarkdownToAnki):
            def call_llm_api(self, prompt, max_tokens=2000):
                return "not-json"

        converter = StubConverter(api_key="dummy", base_url="https://example.com")
        cards = converter.generate_cards_from_text("测试内容", source_file="sample.md")

        self.assertEqual(cards, [])

    def test_extract_response_content_retries_when_only_reasoning_content_is_returned(self):
        class RetryConverter(MarkdownToAnki):
            def __init__(self):
                super().__init__(api_key="dummy", base_url="https://example.com")
                self.retry_tokens = []

            def call_llm_api(self, prompt, max_tokens=2000):
                self.retry_tokens.append(max_tokens)
                return "最终答案"

        converter = RetryConverter()
        result = {
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_content": "推理中",
                },
                "finish_reason": "length",
            }]
        }

        content = converter._extract_response_content(result, "测试 prompt", max_tokens=100)

        self.assertEqual(content, "最终答案")
        self.assertEqual(converter.retry_tokens, [512])

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


if __name__ == "__main__":
    unittest.main()
