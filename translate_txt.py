import sys
import os
import re
import subprocess
import requests
import time
from difflib import SequenceMatcher

OLLAMA_API = "http://127.0.0.1:11434"
MODEL      = "mistral-nemo"

LANGUAGES = {
    "en2de": ("English", "German"),
    "de2en": ("German", "English"),
}

# Common abbreviations that should NOT trigger a sentence split
ABBREVIATIONS_EN = [
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "St.", "vs.",
    "etc.", "e.g.", "i.e.", "Inc.", "Ltd.", "Corp.", "No.", "Vol.",
    "Fig.", "Rev.", "Gen.", "Sgt.", "Capt.", "Lt.", "Col.", "Maj.",
    "approx.", "dept.", "est.", "govt.", "Jan.", "Feb.", "Mar.",
    "Apr.", "Jun.", "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec.",
]
ABBREVIATIONS_DE = [
    "Dr.", "Prof.", "Hr.", "Fr.", "Nr.", "Str.", "ca.", "z.B.",
    "d.h.", "u.a.", "v.a.", "bzgl.", "bzw.", "evtl.", "ggf.",
    "inkl.", "usw.", "etc.", "Abs.", "Abt.", "Bd.", "Jh.",
]

PLACEHOLDER = "\x00"

# ---------------------------------------------------------------------------
#  Ollama Setup
# ---------------------------------------------------------------------------

def _server_running():
    try:
        requests.get(f"{OLLAMA_API}/api/tags", timeout=2)
        return True
    except:
        return False

def _start_server():
    print("  Starting Ollama server ...", flush=True)
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["ollama", "serve"], **kwargs)
    for _ in range(20):
        time.sleep(1)
        if _server_running():
            return True
    print("  [ERROR] Ollama server did not respond in time.")
    return False

def _preload_model():
    try:
        requests.post(f"{OLLAMA_API}/api/generate", json={
            "model": MODEL, "prompt": "", "keep_alive": 0
        }, timeout=10)
    except:
        pass
    print(f"  Preloading [{MODEL}] ...", flush=True)
    print()
    try:
        requests.post(f"{OLLAMA_API}/api/generate", json={
            "model": MODEL,
            "prompt": "",
            "stream": False,
            "keep_alive": "999h",
            "options": {
                "num_ctx": 4096,
                "num_gpu": 99,
            }
        }, timeout=60)
    except:
        pass

def stop_ollama():
    try:
        subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

def setup_ollama():
    if _server_running():
        print("  Restarting Ollama to apply GPU memory settings ...", flush=True)
        stop_ollama()
        time.sleep(3)
    if not _start_server():
        sys.exit(1)
    _preload_model()
    result = subprocess.run(["ollama", "ps"], capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    print(flush=True)

# ---------------------------------------------------------------------------
#  Sentence Splitting
# ---------------------------------------------------------------------------

def _protect_abbreviations(text, direction):
    """Replace periods in abbreviations with a placeholder to prevent false splits."""
    abbrs = ABBREVIATIONS_DE + ABBREVIATIONS_EN if direction == "de2en" \
            else ABBREVIATIONS_EN + ABBREVIATIONS_DE
    for abbr in sorted(abbrs, key=len, reverse=True):
        text = text.replace(abbr, abbr.replace(".", PLACEHOLDER))
    text = text.replace("...", PLACEHOLDER * 3)
    return text

def _restore_abbreviations(text):
    return text.replace(PLACEHOLDER, ".")

def split_sentences(text, direction="en2de"):
    """Split text into sentences, respecting abbreviations and ellipsis."""
    protected = _protect_abbreviations(text, direction)
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z\u00C0-\u00DC"\'\u201E\u201C\u00AB(])', protected)
    return [_restore_abbreviations(p).strip() for p in parts if p.strip()]

# ---------------------------------------------------------------------------
#  Chunking — group sentences into blocks, respect paragraph boundaries
# ---------------------------------------------------------------------------

def build_chunks(text, direction="en2de", sentences_per_chunk=2):
    """Split text into translation chunks, never crossing paragraph boundaries."""
    paragraphs = re.split(r'\n\s*\n', text.strip())
    chunks = []
    para_indices = []

    for pi, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        sentences = split_sentences(para, direction)
        for i in range(0, len(sentences), sentences_per_chunk):
            chunk = " ".join(sentences[i:i + sentences_per_chunk])
            chunks.append(chunk)
            para_indices.append(pi)

    return chunks, para_indices

# ---------------------------------------------------------------------------
#  Post-processing: glossary + deterministic grammar fixes
# ---------------------------------------------------------------------------

def _postprocess(text, direction="en2de"):
    """Clean up LLM translation artifacts, apply glossary and grammar fixes."""
    # --- Strip LLM meta-output (review notes, explanations, headers) ---
    # The review pass sometimes outputs its working notes after the translation.
    # Cut everything from the first meta-marker onward.
    for marker in ['\nCorrected ', '\nChanges made', '\nChanges:', '\nNotes:',
                   '\nExplanation:', '\nRevision:', '\nKorrektur:', '\nÄnderungen:']:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    # Strip wrapping quotes
    if len(text) > 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    # Remove stray typographic quotes
    for ch in ['\u201e', '\u201c', '\u201d']:
        text = text.replace(ch, '')
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    # Apply target-language grammar fixes
    if direction == "en2de":
        text = _fix_german(text)
    return text.strip()


# ---------------------------------------------------------------------------
#  German grammar fixes — generic, rule-based, no content-specific patterns
# ---------------------------------------------------------------------------

# Neuter nouns where LLMs frequently produce "eine" instead of "ein"
_NEUTER_NOUNS = [
    'Stück', 'Mädchen', 'Kind', 'Haus', 'Ende', 'Mal', 'Buch', 'Bild',
    'Fest', 'Tier', 'Spiel', 'Ziel', 'Stück', 'Beispiel', 'Problem',
    'Ergebnis', 'Zeichen', 'System', 'Thema', 'Jahr', 'Land', 'Wort',
    'Auto', 'Geld', 'Recht', 'Teil', 'Mittel', 'Paar', 'Gebäude',
    'Unternehmen', 'Ereignis', 'Verhältnis', 'Verfahren', 'Element',
]

# Substantivized adjectives: genitive/dative plural requires -n ending
_SUBST_ADJECTIVES = [
    'Brave', 'Unartige', 'Gute', 'Böse', 'Kleine', 'Große', 'Alte',
    'Junge', 'Kranke', 'Gesunde', 'Arme', 'Reiche', 'Fremde',
    'Bekannte', 'Verwandte', 'Angestellte', 'Beamte', 'Jugendliche',
    'Erwachsene', 'Deutsche', 'Angehörige', 'Abgeordnete', 'Verletzte',
    'Verstorbene', 'Verdächtige', 'Angeklagte', 'Vorsitzende',
]

# Colors for detecting fake compound adjectives (color + clothing suffix)
_COLORS_DE = ['rot', 'blau', 'grün', 'schwarz', 'weiß', 'gelb',
              'braun', 'grau', 'gold', 'silber', 'lila', 'rosa', 'orange']

# Clothing stems used to detect invented color-clothing compounds
_CLOTHING_STEMS = ['jacke', 'jacken', 'mantel', 'mäntel', 'hemd', 'hemden',
                   'hose', 'hosen', 'kittel', 'weste', 'westen', 'rock',
                   'kleid', 'anzug', 'coat', 'jacket', 'cape']

# Subordinate conjunctions that require a preceding comma in German
_SUBORD_CONJ = ['dass', 'weil', 'obwohl', 'wenn', 'obgleich', 'sodass',
                'sobald', 'solange', 'nachdem', 'bevor', 'damit',
                'indem', 'sofern', 'falls', 'seitdem', 'ehe']

# German months for date-preposition fix
_MONTHS_DE = ('Januar|Februar|März|April|Mai|Juni|Juli|'
              'August|September|Oktober|November|Dezember')


def _fix_german(text):
    """Deterministic German grammar fixes — generic, rule-based."""

    # --- Neuter gender: "eine {Neutrum}" → "ein {Neutrum}" ---
    for noun in _NEUTER_NOUNS:
        text = re.sub(rf'\beine\b(\s+{re.escape(noun)})\b', rf'ein\1', text)
        text = re.sub(rf'\bEine\b(\s+{re.escape(noun)})\b', rf'Ein\1', text)

    # --- Substantivized adjectives: "der Brave" → "der Braven" (gen/dat plural) ---
    for adj in _SUBST_ADJECTIVES:
        text = re.sub(rf'\bder {re.escape(adj)}\b', f'der {adj}n', text)

    # --- Fake color-clothing compounds → "color gekleidet" ---
    for color in _COLORS_DE:
        for stem in _CLOTHING_STEMS:
            text = re.sub(rf'\b{color}{stem}\w+', f'{color} gekleidet',
                          text, flags=re.IGNORECASE)

    # --- Wrong preposition for dates: "auf dem/den X. Monat" → "am X. Monat" ---
    text = re.sub(rf'auf de[mn] (\d+\.\s*(?:{_MONTHS_DE}))', r'am \1', text)

    # --- Missing comma before subordinate conjunctions ---
    for conj in _SUBORD_CONJ:
        text = re.sub(rf'(\w) ({conj})\b', rf'\1, \2', text)
    text = re.sub(r',\s*,', ',', text)  # fix double commas

    # --- LLM stutter: "dass dass" → "dass" ---
    text = re.sub(r'\b(dass|und|oder|aber|auch|noch|schon|dann|denn)\s+\1\b',
                  r'\1', text, flags=re.IGNORECASE)

    # --- Double period (but preserve ellipsis) ---
    text = re.sub(r'\.\.(?!\.)', '.', text)

    return text


# ---------------------------------------------------------------------------
#  Translation engine
# ---------------------------------------------------------------------------

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

SYSTEM_TRANSLATE = (
    "You are a professional {src}-to-{tgt} translator.\n"
    "- Produce natural, fluent {tgt} with correct grammar, gender, and case.\n"
    "- Use natural {tgt} sentence structure (e.g., V2 in German, SVO in English).\n"
    "  Do not mirror the syntax of {src}.\n"
    "- Restructure passive constructions naturally. In German, use impersonal forms\n"
    "  ('Es wird erzählt, dass …', 'Man sagt, …') instead of literal passives\n"
    "  where the subject cannot logically be the patient of the verb.\n"
    "- Use exclusively established {tgt} vocabulary. Never invent compound words.\n"
    "  If unsure, use a descriptive phrase instead.\n"
    "- Translate ALL terms completely. No {src} expressions may remain.\n"
    "- Localize cultural references, proper nouns (where customary), and idioms\n"
    "  to their functional equivalents in {tgt}.\n"
    "- Preserve punctuation, parentheses, and dashes exactly.\n"
    "- Output ONLY the translation. No notes, explanations, headings, or labels."
)

SYSTEM_REVIEW = (
    "You are a {tgt} translation proofreader.\n"
    "Correct the draft translation based on the original. You may restructure freely.\n\n"
    "- Terminological consistency: replace ALL remaining {src} terms with {tgt} equivalents.\n"
    "  This includes names, titles, and cultural references (e.g., Santa Claus → Weihnachtsmann).\n"
    "  No {src} words or phrases may remain in the output.\n"
    "- Grammatical precision: fix gender agreement, case errors, and verb conjugation.\n"
    "  Ensure every proper noun and title has its required article.\n"
    "- Vocabulary: replace invented compound words with real {tgt} words or descriptive phrases.\n"
    "- Idiomatic correctness: replace word-for-word translations with natural {tgt} phrasing.\n"
    "  Fix unnatural passive constructions (e.g., 'X wird erzählt' → 'Man erzählt, dass X' or\n"
    "  'Es wird erzählt, dass X').\n"
    "- Structural integrity: do not add or omit information. Match the original precisely.\n"
    "- Do not add headings, labels, or section titles not present in the original.\n"
    "- CRITICAL: Output ONLY the corrected {tgt} text.\n"
    "  Do NOT output change notes, explanations, or 'Corrected' sections.\n"
    "  Do NOT describe what you changed. Just output the final text."
)

def _call_chat(system_prompt, user_msg, temperature=0.05):
    """Send a chat request to Ollama and return the response text."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "options": {
            "think": False,
            "num_ctx": 4096,
            "num_gpu": 99,
            "temperature": temperature,
            "num_predict": 768,
            "repeat_penalty": 1.1,
            "top_p": 0.7,
        }
    }
    response = requests.post(f"{OLLAMA_API}/api/chat", json=payload, timeout=120)
    return response.json().get("message", {}).get("content", "").strip()

def translate_chunk(text, src_lang, tgt_lang, direction="en2de",
                    context_blocks=None, ctx=3, force_variety=False):
    """Translate a single chunk via two passes: translate + review."""
    if not text.strip():
        return text

    # --- Pass 1: Translate ---
    system = SYSTEM_TRANSLATE.format(src=src_lang, tgt=tgt_lang)

    user_msg = ""
    if context_blocks and ctx > 0:
        user_msg += "Previous translations for reference:\n"
        for src, tgt in context_blocks[-ctx:]:
            user_msg += f"  {src} → {tgt}\n"
        user_msg += "\n"
    user_msg += f"Translate:\n{text}"

    try:
        temp = 0.15 if force_variety else 0.05
        draft = _call_chat(system, user_msg, temperature=temp)
        draft = _postprocess(draft, direction)
        if not draft:
            return text

        # --- Pass 2: Review & correct ---
        review_system = SYSTEM_REVIEW.format(src=src_lang, tgt=tgt_lang)
        review_msg = f"Original ({src_lang}):\n{text}\n\nTranslation ({tgt_lang}):\n{draft}"
        corrected = _call_chat(review_system, review_msg, temperature=0.0)
        corrected = _postprocess(corrected, direction)

        return corrected if corrected else draft
    except Exception as e:
        print(f"\n  [WARNING] Translation failed: {e}", flush=True)
        return text

# ---------------------------------------------------------------------------
#  Main processing
# ---------------------------------------------------------------------------

def process_text(input_file, output_file, ctx=3, direction="en2de"):
    start_timer = time.time()
    src_lang, tgt_lang = LANGUAGES[direction]

    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    chunks, para_indices = build_chunks(content, direction)
    total_chunks = len(chunks)

    if total_chunks == 0:
        print("  [WARNING] No text found in input file.", flush=True)
        return

    translated_chunks = []
    context_blocks = []

    try:
        for i, chunk in enumerate(chunks):
            print(f"\r  Chunk {i + 1} of {total_chunks} — translating + reviewing ...  ", end="", flush=True)

            translation = translate_chunk(chunk, src_lang, tgt_lang, direction,
                                          context_blocks, ctx)

            # Similarity guard: retry with slight temperature if output too similar to previous
            if translated_chunks and similarity(translation, translated_chunks[-1]) > 0.8:
                translation = translate_chunk(chunk, src_lang, tgt_lang, direction,
                                              context_blocks, ctx, force_variety=True)

            translated_chunks.append(translation)
            context_blocks.append((chunk, translation))

    except KeyboardInterrupt:
        print(f"\n\n  [CANCELLED] {len(translated_chunks)} of {total_chunks} chunks translated.", flush=True)
        if translated_chunks:
            base, ext = os.path.splitext(output_file)
            partial_file = f"{base}.partial{ext}"
            _write_output(partial_file, translated_chunks, para_indices)
            print(f"  Partial translation saved to:\n  {partial_file}", flush=True)
        else:
            print("  Nothing to save.", flush=True)
        stop_ollama()
        print()
        sys.exit(0)

    _write_output(output_file, translated_chunks, para_indices)

    end_timer = time.time()
    duration = end_timer - start_timer
    hours, rem = divmod(duration, 3600)
    minutes, seconds = divmod(rem, 60)
    print(f"\n\n  Translation finished in: {int(hours)}:{int(minutes):02}:{seconds:06.3f}\n")


def _write_output(path, translated_chunks, para_indices):
    """Write translated chunks to file, re-inserting paragraph breaks."""
    with open(path, "w", encoding="utf-8") as f:
        prev_para = None
        for i, chunk in enumerate(translated_chunks):
            if prev_para is not None and para_indices[i] != prev_para:
                f.write("\n\n")
            elif prev_para is not None:
                f.write(" ")
            f.write(chunk)
            prev_para = para_indices[i]
        f.write("\n")


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        os.system("")  # Enable ANSI on Windows
        sys.stdout.write("\033[92m")
        sys.stdout.flush()

        ctx = int(sys.argv[3]) if len(sys.argv) >= 4 else 3
        direction = sys.argv[4] if len(sys.argv) >= 5 else "en2de"

        if direction not in LANGUAGES:
            print(f"  [ERROR] Unknown direction '{direction}'. Use 'en2de' or 'de2en'.")
            sys.exit(1)

        setup_ollama()
        process_text(sys.argv[1], sys.argv[2], ctx, direction)
        stop_ollama()
