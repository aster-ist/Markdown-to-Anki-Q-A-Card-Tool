from pathlib import Path

DEFAULT_BASE_URL = "https://api.moonshot.cn"
ENV_PATH = Path(".env")


def read_env_lines():
    if not ENV_PATH.exists():
        return []

    return ENV_PATH.read_text(encoding="utf-8").splitlines()


def upsert_env_value(lines, key, value):
    updated_lines = []
    found = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            current_key = line.split("=", 1)[0].strip()
            if current_key == key:
                updated_lines.append(f"{key}={value}")
                found = True
                continue

        updated_lines.append(line)

    if not found:
        updated_lines.append(f"{key}={value}")

    return updated_lines


def main():
    api_key = input("请输入你的 Moonshot API Key: ").strip()

    if not api_key:
        print("✗ API Key 为空，请重试")
        return

    lines = read_env_lines()
    lines = upsert_env_value(lines, "LLM_API_KEY", api_key)

    has_base_url = any(
        line.strip().startswith("LLM_BASE_URL=")
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    )
    if not has_base_url:
        lines = upsert_env_value(lines, "LLM_BASE_URL", DEFAULT_BASE_URL)

    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print("✓ API Key 已保存到 .env 文件")
    print(f"✓ 已保留或补充 LLM_BASE_URL（默认 {DEFAULT_BASE_URL}）")


if __name__ == "__main__":
    main()
