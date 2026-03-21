# Markdown to Anki Q&A Card Tool

This is a Python command-line tool that converts Markdown notes into Anki `.apkg` packages. The current version uses a Moonshot-compatible Chat Completions API and generates Front/Back Q&A cards with bilingual support, tags, and optional extra notes.

## Features

- Read local Markdown files and split them by headings and chunk length
- Use an LLM to extract the most important knowledge points
- Generate Front/Back Q&A cards instead of Cloze cards
- Support `extra`, `source`, and `tags` fields
- Export directly to an importable `.apkg` file
- Provide clearer errors for missing config, invalid JSON, and missing fields

## Requirements

- Python 3.9+
- A virtual environment is recommended

## Installation

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env`, then fill in your real values:

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.moonshot.cn
LLM_MODEL=kimi-k2.5
LLM_TIMEOUT=120
```

If you only want to update the API key quickly, run:

```bash
python setup_api_key.py
```

The helper script updates `LLM_API_KEY`, preserves the existing `LLM_BASE_URL`, and adds the default Moonshot URL if it is missing.

## Usage

```bash
python md_to_anki.py <input.md> <output.apkg>
```

Example:

```bash
python md_to_anki.py test_sample.md output.apkg
```

What the script does:

1. Read the Markdown file
2. Split the content by headings and chunk size
3. Ask the LLM to return Q&A card JSON
4. Write the cards into an Anki deck
5. Export an `.apkg` package

## Project Files

- `md_to_anki.py`: main script
- `setup_api_key.py`: config helper
- `.env.example`: safe environment template
- `test_sample.md`: public sample Markdown file
- `tests/test_md_to_anki.py`: offline unit tests

## Testing

Offline tests:

```bash
python -m unittest discover -s tests -v
```

Live verification with your real LLM configuration:

```bash
python test_new_cards.py
```

## Troubleshooting

### Missing configuration

If you see `缺少必要配置`, your `.env` file is missing `LLM_API_KEY` or `LLM_BASE_URL`.

### JSON parsing errors

If the model does not return valid JSON, the script prints a truncated preview of the response so you can retry or adjust the prompt.

### No cards generated

Make sure the input content is specific enough, and run `python test_new_cards.py` first to verify the API connection.

## License

MIT License
