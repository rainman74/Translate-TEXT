# Translate-TEXT

Fully local text translator — English ↔ German via Ollama/mistral-nemo. No cloud, no API key.

---

## Features

- **Bidirectional**: English → German and German → English
- **Drag & drop**: Drop one or more `.txt` files onto `translatetxt.cmd`
- **Two-pass translation**: Pass 1 translates, Pass 2 reviews and corrects — same model, different prompt
- **Context-aware**: Each chunk includes the 5 previous translations for consistent terminology and style
- **Smart chunking**: Splits on sentence boundaries, never across paragraphs. Abbreviations (Mr., Dr., z.B., etc.) are protected from false splits.
- **Deterministic post-processing**: Regex-based grammar fixes for systematic LLM errors (neuter gender, fake compounds, missing commas, duplicate words)
- **Ollama auto-install**: Downloads and installs Ollama if not present
- **Full GPU offloading**: Configured for flash attention, quantized KV cache, and maximum GPU layers

---

## How it works

1. **Sentence splitting** — Input text is split into sentences, respecting abbreviations and ellipsis
2. **Chunking** — Sentences are grouped into pairs (2 per chunk), paragraph boundaries preserved
3. **Pass 1: Translate** — Each chunk is sent to mistral-nemo with a translation system prompt and up to 5 previous translations as context
4. **Pass 2: Review** — The draft translation is reviewed by the same model with a proofreading prompt, using the original text as reference
5. **Post-processing** — Deterministic regex fixes for known LLM error patterns (German gender, invented compounds, missing commas, meta-output stripping)
6. **Output** — Translated text is written with paragraph structure preserved

---

## Usage

### Drag & drop
Drop `.txt` files onto `translatetxt.cmd` and select the translation direction.

### Command line
```
translatetxt.cmd "D:\Text.EN.txt"
translatetxt.cmd "D:\File1.txt" "D:\File2.txt" "D:\File3.txt"
```

### Output naming
- `Document.EN.txt` → `Document.DE.txt`
- `Document.DE.txt` → `Document.EN.txt`
- `Document.txt` → `Document.DE.txt` (or `.EN.txt`)

---

## Files

| File | Description |
|------|-------------|
| `translatetxt.cmd` | Windows batch wrapper — direction selection, Ollama setup, batch loop |
| `translate_txt.py` | Translation engine — chunking, two-pass translation, post-processing |

---

## Requirements

- **Windows 10/11 x64**
- **Python 3.8+** with `requests` module (auto-installed if missing)
- **Ollama** (auto-installed if missing)
- **GPU**: mistral-nemo (12B) requires ~8 GB VRAM for full GPU offloading

---

## Configuration

Settings in `translatetxt.cmd`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_FLASH_ATTENTION` | `1` | Enable flash attention for lower memory usage |
| `OLLAMA_KV_CACHE_TYPE` | `q4_0` | Quantized KV cache to fit model in GPU memory |
| `OLLAMA_NUM_PARALLEL` | `1` | Sequential processing for best quality |
| `OLLAMA_NUM_THREADS` | `8` | CPU threads (fallback if no GPU) |

Settings in `translate_txt.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL` | `mistral-nemo` | Ollama model for translation |
| `num_ctx` | `4096` | Context window size |
| `temperature` | `0.05` | Low temperature for deterministic output |
| `top_p` | `0.7` | Nucleus sampling threshold |
| `repeat_penalty` | `1.1` | Penalizes repetitive output |
| `num_predict` | `768` | Max tokens per response |
| `sentences_per_chunk` | `2` | Sentences grouped per translation chunk |

---

## Best practices

- **Model choice**: `mistral-nemo` (12B) offers the best quality-to-size ratio for translation tasks. Smaller models produce significantly worse grammar and vocabulary.
- **GPU memory**: Ensure at least 8 GB VRAM is available. The wrapper sets `OLLAMA_KV_CACHE_TYPE=q4_0` and `OLLAMA_FLASH_ATTENTION=1` to minimize memory usage.
- **Text preparation**: Clean input text produces better translations. Remove unnecessary line breaks within paragraphs — the chunker relies on double newlines (`\n\n`) for paragraph boundaries.
- **Context blocks**: 5 context blocks provide the most consistent terminology and style across the entire document.
- **Temperature**: Keep at `0.05` for reliable, reproducible translations. Only increase if the model produces repetitive or stuck output.
- **Post-processing**: The built-in German grammar fixes handle common LLM errors automatically. For domain-specific terminology, consider adding regex patterns to `_fix_german()` in `translate_txt.py`.
