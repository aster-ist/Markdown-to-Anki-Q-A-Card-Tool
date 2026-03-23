# Markdown to Anki Q&A Card Tool
[中文文档](README_cn.md)
This is a Python command-line tool that converts Markdown notes into an Anki `.apkg` package. The current version uses a Moonshot-compatible Chat Completions API to generate Front/Back Q&A cards and supports bilingual content, tags, and extra notes.

## Features

- Read local Markdown files and chunk by headings/length
- Call an LLM to automatically extract core knowledge points
- Generate Front/Back Q&A cards (not Cloze deletion cards)
- Support `extra` notes, `source`, and `tags`
- Export as an `.apkg` file that can be imported directly into Anki
- Clearer error messages for missing configuration, invalid JSON, and missing fields

## Requirements

- Python 3.9+
- Virtual environment recommended

## Installation

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env`, then fill in your real settings:

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.moonshot.cn
LLM_MODEL=kimi-k2.5
LLM_TIMEOUT=120
```

If you only want to quickly update the API key, run:

```bash
python setup_api_key.py
```

This script updates `LLM_API_KEY`, preserves the existing `LLM_BASE_URL`, and adds the Moonshot default address if it is missing.

## Usage

```bash
python md_to_anki.py <input.md> <output.apkg>
```

Example:

```bash
python md_to_anki.py test_sample.md output.apkg
```

Execution flow:

1. Read the Markdown file
2. Split text into chunks by headings and length
3. Call the LLM to generate Q&A card JSON
4. Write cards into the Anki deck
5. Export the `.apkg` file

If the previous run generated a `failed_chunks_*.md` report, you can rerun only the failed chunks:

```bash
python md_to_anki.py --retry-report failed_chunks_output_20260323_120000.md retry_output.apkg
```

You can also omit the output path; the script will automatically create a merged package based on the original output name, e.g., `output_merged.apkg`:

```bash
python md_to_anki.py --retry-report failed_chunks_output_20260323_120000.md
```

During retry, it automatically reads the `cards_manifest_*.json` generated in the same batch and repacks “previously successful cards + cards that succeed in this retry” into a new `.apkg`. This way, you don’t need to manually merge the main package and the retry package.

Each time a failed-chunks report is generated, the terminal and the top of the report file provide a copyable retry command, for example:

```bash
python md_to_anki.py --retry-report "failed_chunks_output_run_20260323_192742.md" "output_merged.apkg"
```

In practice, it’s best to copy the `Retry command` line directly from the report.

## Project Files

- `md_to_anki.py`: Main script
- `setup_api_key.py`: Configuration helper script
- `.env.example`: Safe environment variable template
- `test_sample.md`: Public sample Markdown
- `tests/test_md_to_anki.py`: Offline tests

## Tests

Offline tests:

```bash
python -m unittest discover -s tests -v
```

Online validation (uses your real LLM configuration):

```bash
python test_new_cards.py
```

## FAQ

### Missing configuration

If you see `Missing required configuration`, it means `.env` is missing `LLM_API_KEY` or `LLM_BASE_URL`.

### JSON parsing failure

If the model does not return valid JSON, the script prints a truncated response to help you adjust the prompt or retry.

### No cards generated

Ensure the input content is specific enough and first verify the API is available with `python test_new_cards.py`.

## License

MIT License
