<p align="center">
  <h1 align="center">CrimsonForge</h1>
  <p align="center">
    Crimson Desert Modding Studio
    <br />
    <em>Unpack, translate, patch fonts, and repack game archives — all in one tool.</em>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.5.0-blue" alt="Version 1.5.0">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/PySide6-Qt6-41cd52?logo=qt&logoColor=white" alt="PySide6">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

## What is CrimsonForge?

CrimsonForge is a desktop application for modding **Crimson Desert** by Pearl Abyss. It reads encrypted game archives (PAZ/PAMT/PAPGT), lets you translate 172,000+ localization strings with AI or manually, modify fonts for any language, and write everything back with valid checksums so the game runs normally.

Built for translators, modders, and localization teams. Works on Windows and macOS.

---

## Features

### Archive Explorer
- Browse **1.4 million+ game files** across all package groups with instant filtering
- Preview images, audio, video, and text files directly from PAZ archives — no extraction needed
- Built-in syntax-highlighted editor for CSS, HTML, XML, JSON, and paloc files
- Extract files with automatic **ChaCha20 decryption** and **LZ4 decompression**
- Keyboard navigation with live preview (arrow keys, not just mouse)

### Translation Workspace
- Load any of the game's languages as source, translate into **70+ world languages**
- **172,000+ entries** parsed from paloc files (both numeric IDs and symbolic keys like `questdialog_*`, `textdialog_*`)
- **AI-powered batch translation** with 8 providers — supports every model each provider offers
- **Enterprise AI prompt** with 10 strict rules: preserves `{...}` placeholders, HTML tags, template variables, proper nouns, and gaming terminology
- **Glossary manager** for consistent translation of character names, places, and factions — injected into every AI request
- Auto-categorization: Dialogue, Quests, Items, Skills, Knowledge, Factions, Mounts, Documents
- Auto-lock untranslatable entries (empty text, developer placeholders)
- Enterprise search: wildcards (`key:quest*`), boolean filters (`locked:yes`, `empty:yes`, `{*}`), field queries
- Session recovery: autosave every 30s, full state restoration on relaunch
- Game update detection: auto-merges new/changed/removed strings, preserves translations
- Status bar with real-time progress, badge counts, token/cost tracking

### Ship to App (Mod Distribution)
- Generate **ZIP + BAT** packages for end-user distribution
- install.bat auto-discovers Steam, copies pre-patched files — one click install
- uninstall.bat uses Steam Verify Integrity to restore originals
- Built-in **font donor system**: select a donor font, auto-adds missing glyphs for the target language
- Pre-patched game files with full checksum chain (PAZ + PAMT + PAPGT)
- End user needs nothing installed — just extract ZIP and run BAT

### Font Builder
- Extract game fonts from PAZ archives
- Analyze glyph coverage for any target language (Latin, Arabic, CJK, Hangul, Thai, Cyrillic...)
- Add missing glyphs from a donor font (e.g., Noto Sans) — only characters needed for the selected language
- GSUB/GPOS merge with missing-glyph filtering — no crashes on complex fonts
- Handles CJK fonts with large coordinates (Korean, Chinese, Japanese)
- Preview fonts with sample text in the target script
- Patch modified fonts directly back into the game

### Patch to Game
- One-click pipeline: build paloc, compress, encrypt, write to PAZ, update PAMT + PAPGT checksums
- Automatic backup before every patch
- Verification after repack
- Game version detection from `meta/0.paver` (e.g., v1.01.02)
- Game ready to play immediately

### Repack Engine
- Scan modified files and repack into game archives
- Full checksum chain: PAZ CRC → PAMT CRC → PAPGT CRC
- Native DLL checksum computation (754x faster than pure Python)
- Supports LZ4 compression and ChaCha20 encryption
- Preserve original file timestamps

---

## AI Translation Providers

CrimsonForge connects to any model offered by these providers. Configure your API key, click **Load Models** to fetch the full list, and pick any model:

| Provider | What You Need |
|----------|---------------|
| **OpenAI** | API key from [platform.openai.com](https://platform.openai.com) |
| **Anthropic** | API key from [console.anthropic.com](https://console.anthropic.com) |
| **Google Gemini** | API key from [aistudio.google.com](https://aistudio.google.com) |
| **DeepSeek** | API key from [platform.deepseek.com](https://platform.deepseek.com) |
| **Mistral** | API key from [console.mistral.ai](https://console.mistral.ai) |
| **Cohere** | API key from [dashboard.cohere.com](https://dashboard.cohere.com) |
| **Ollama** | Install [Ollama](https://ollama.com) locally — no API key needed |
| **vLLM / Custom** | Self-hosted — configure your base URL |

Models update automatically from each provider's API. No hardcoded model names — new models appear in the dropdown as providers release them.

---

## Supported Game Archives

| Format | Description |
|--------|-------------|
| **PAPGT** | Root package group index with CRC chain |
| **PAMT** | Per-group metadata table mapping files to PAZ offsets |
| **PAZ** | Encrypted (ChaCha20) and compressed (LZ4) data archives |
| **PALOC** | Localization string files (length-prefixed UTF-8 key-value pairs) |
| **PAVER** | Game version file (3 x uint16: major.minor.patch) |

---

## Installation

### Requirements
- Python 3.12 or newer
- Crimson Desert installed via Steam

### Setup
```bash
git clone https://github.com/hzeemr/crimsonforge.git
cd crimsonforge
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
python main.py
```

### Build Standalone Executable (Optional)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name CrimsonForge main.py
```

---

## Quick Start

1. **Launch** — CrimsonForge auto-discovers your Crimson Desert installation
2. **Explorer** — browse game files, preview images/audio/video, extract what you need
3. **Translate** — load a language, translate with AI or manually, patch to game
4. **Font Builder** — add missing glyphs for your target language, patch font
5. **Ship to App** — generate a ZIP for end users (install.bat + uninstall.bat)
6. **Settings** — configure AI providers, prompts, batch settings

---

## Translation Workflow

```
Load game language
        |
  172K+ entries parsed
        |
  Auto-categorized (Dialogue, Quests, Items, ...)
        |
  AI translate / manual edit / import JSON
        |
  Glossary enforced for consistent proper nouns
        |
  Review → Approve
        |
  Patch to Game  or  Ship to App (ZIP+BAT)
        |
  Game ready to play
```

---

## Project Structure

```
crimsonforge/
  main.py                 Entry point
  version.py              Version and changelog
  requirements.txt        Python dependencies
  ai/                     AI provider integrations (8 providers)
    default_prompt.py       Enterprise translation prompt
    prompt_manager.py       Prompt template system with glossary injection
  core/                   Game archive parsers and engines
    paloc_parser.py         Localization file parser (172K+ entries)
    pamt_parser.py          Package metadata parser
    papgt_manager.py        Root index manager
    crypto_engine.py        ChaCha20 decryption/encryption
    compression_engine.py   LZ4 compression
    checksum_engine.py      PaChecksum with native DLL acceleration
    repack_engine.py        Archive repacking pipeline
    font_builder.py         Font glyph manipulation with GSUB/GPOS merge
    vfs_manager.py          Virtual file system (1.4M+ files)
  translation/            Translation state, batch processing, usage index
  ui/                     PySide6 GUI (7 tabs, dark/light themes, tooltips)
  utils/                  Config, logging, platform utilities
  data/                   Language definitions, default settings
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

CrimsonForge is not affiliated with Pearl Abyss. Crimson Desert is a trademark of Pearl Abyss.
