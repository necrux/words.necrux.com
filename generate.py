#!/usr/bin/env python3

from pathlib import Path
import re
import time

import requests
import yaml
from jinja2 import Environment, FileSystemLoader


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent

CONFIG_DIR = ROOT / "configs"
TEMPLATES_DIR = ROOT / "templates"
WORDS_DIR = ROOT / "words"

SITE_DIR = ROOT / "site"
CACHE_FILE = ROOT / ".local_dictionary.yaml"

DISPLAY_CONFIG = CONFIG_DIR / "display.yaml"


# ---------------------------------------------------------------------------
# Dictionary API
# ---------------------------------------------------------------------------

WIKTAPI_API = "https://api.wiktapi.dev/v1/en/word/{}"
WIKTAPI_PRONUNCIATION_API = (
    "https://api.wiktapi.dev/v1/en/word/{}/pronunciations"
)

MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 10


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def load_yaml(path):
    """Load a YAML file and return its contents."""
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(data, path):
    """Save data as YAML."""
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=True,
            allow_unicode=True,
        )


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------

def test_number(path):
    """Return the numeric test number from test_N.yaml."""
    match = re.fullmatch(r"test_(\d+)\.ya?ml", path.name)

    if not match:
        raise ValueError(f"Invalid test filename: {path.name}")

    return int(match.group(1))


def get_test_files():
    """Return spelling test files sorted numerically."""
    files = list(WORDS_DIR.glob("test_*.yaml"))
    files.extend(WORDS_DIR.glob("test_*.yml"))

    return sorted(files, key=test_number)


# ---------------------------------------------------------------------------
# Dictionary cache
# ---------------------------------------------------------------------------

def load_cache():
    """Load the local dictionary cache."""
    if not CACHE_FILE.exists():
        return {}

    return load_yaml(CACHE_FILE)


def save_cache(cache):
    """Save the local dictionary cache."""
    save_yaml(cache, CACHE_FILE)


def cache_entry_complete(entry):
    """
    Determine whether a cached dictionary entry contains the data currently
    required by the site.

    Pronunciation is intentionally excluded because it is not currently
    retrieved or displayed.
    """
    if not isinstance(entry, dict):
        return False

    required_fields = (
        "word",
        "definition",
        "part_of_speech",
        "audio",
    )

    return all(field in entry for field in required_fields)


# ---------------------------------------------------------------------------
# Dictionary API
# ---------------------------------------------------------------------------

def request_json(url):
    """
    Request JSON from an API endpoint with retries.

    Returns None if all attempts fail.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params={"lang": "en"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            print(
                f"Dictionary request failed "
                f"(attempt {attempt}/{MAX_RETRIES}): {exc}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def extract_definition(entry):
    """Return the first available gloss from a dictionary entry."""
    for sense in entry.get("senses", []):
        glosses = sense.get("glosses", [])

        if glosses:
            return glosses[0]

    return None


def extract_audio(entry):
    """
    Return the preferred US MP3 pronunciation URL.

    WiktApi sound entries may contain IPA, audio filenames, OGG URLs,
    and MP3 URLs. Prefer an explicitly US-tagged MP3.
    """
    sounds = entry.get("sounds", [])

    # Prefer an explicitly US-tagged MP3.
    for sound in sounds:
        tags = {tag.lower() for tag in sound.get("tags", [])}

        if "us" in tags:
            mp3_url = sound.get("mp3_url")

            if mp3_url:
                return mp3_url

    # Fall back to any available MP3.
    for sound in sounds:
        mp3_url = sound.get("mp3_url")

        if mp3_url:
            return mp3_url

    # Finally fall back to an OGG URL if no MP3 exists.
    for sound in sounds:
        ogg_url = sound.get("ogg_url")

        if ogg_url:
            return ogg_url

    return None


def lookup_part_of_speech(word):
    """
    Retrieve part of speech using WiktApi's pronunciation endpoint.

    The full word endpoint does not consistently include `pos` in its
    returned entry data, while the pronunciation endpoint does.
    """
    url = WIKTAPI_PRONUNCIATION_API.format(word)

    data = request_json(url)

    if not data:
        return None

    pronunciations = data.get("pronunciations", [])

    for pronunciation in pronunciations:
        if pronunciation.get("lang_code") == "en":
            pos = pronunciation.get("pos")

            if pos:
                return pos

    return None


def lookup_word(word):
    """
    Retrieve dictionary data for a word.

    Pronunciation is intentionally left blank for now. Audio is still
    extracted and cached for use by the generated site.
    """
    url = WIKTAPI_API.format(word)

    data = request_json(url)

    if not data:
        return None

    entries = data.get("entries", [])

    if not entries:
        return None

    entry = entries[0]

    definition = extract_definition(entry)
    part_of_speech = entry.get("pos")

    if not part_of_speech:
        part_of_speech = lookup_part_of_speech(word)

    audio = extract_audio(entry)

    return {
        "word": word,
        "definition": definition,
        "part_of_speech": part_of_speech,
        "pronunciation": None,
        "audio": audio,
    }


def enrich_word(word, cache):
    """
    Return dictionary data for a word.

    Existing complete cache entries are authoritative. Failed API lookups
    are not cached.
    """
    cache_key = word.lower()

    cached = cache.get(cache_key)

    if cache_entry_complete(cached):
        return cached

    print(f"Looking up: {word}")

    result = lookup_word(word)

    if result is None:
        print(f"  Unable to retrieve dictionary data for: {word}")

        # Do not overwrite an existing cache entry with a failed lookup.
        if cached:
            return cached

        return {
            "word": word,
            "definition": None,
            "part_of_speech": None,
            "pronunciation": None,
            "audio": None,
        }

    cache[cache_key] = result

    return result


# ---------------------------------------------------------------------------
# Test enrichment
# ---------------------------------------------------------------------------

def enrich_test(test_data, cache):
    """Enrich all words in a spelling test."""
    enriched = dict(test_data)

    enriched["words"] = [
        enrich_word(word, cache)
        for word in test_data.get("words", [])
    ]

    enriched["challengeWords"] = [
        enrich_word(word, cache)
        for word in test_data.get("challengeWords", [])
    ]

    return enriched


# ---------------------------------------------------------------------------
# Jinja2
# ---------------------------------------------------------------------------

def create_environment():
    """Create the Jinja2 template environment."""
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
    )


# ---------------------------------------------------------------------------
# Site cleanup
# ---------------------------------------------------------------------------

def clean_site():
    """
    Remove generated HTML from site/.

    The repository-root index.html is intentionally not touched.
    """
    if not SITE_DIR.exists():
        return

    for html_file in SITE_DIR.rglob("*.html"):
        html_file.unlink()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_template(environment, template_name, output_path, **context):
    """Render a Jinja2 template to an output file."""
    template = environment.get_template(template_name)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    rendered = template.render(**context)

    output_path.write_text(
        rendered,
        encoding="utf-8",
    )


def render_homepage(environment, display):
    """Render the repository-root homepage."""
    render_template(
        environment,
        "index.html.j2",
        ROOT / "index.html",
        display=display,
        latest_url="site/latest/index.html",
        historic_url="site/historic/index.html",
    )


def render_historic_index(environment, display, tests):
    """Render the historic tests index."""
    render_template(
        environment,
        "list.html.j2",
        SITE_DIR / "historic" / "index.html",
        display=display,
        title="Historic Words",
        tests=tests,
    )


def render_test(environment, display, test, latest):
    """Render an individual spelling test."""
    if latest:
        output_path = SITE_DIR / "latest" / "index.html"
    else:
        output_path = (
            SITE_DIR
            / "historic"
            / f"test_{test['number']}.html"
        )

    render_template(
        environment,
        "test.html.j2",
        output_path,
        display=display,
        test=test,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    display = load_yaml(DISPLAY_CONFIG)
    cache = load_cache()

    test_files = get_test_files()

    if not test_files:
        raise RuntimeError("No spelling test files found.")

    environment = create_environment()

    clean_site()

    tests = []

    for path in test_files:
        number = test_number(path)
        source = load_yaml(path)

        enriched = enrich_test(source, cache)

        enriched["number"] = number
        enriched["title"] = f"Test {number}"

        tests.append(enriched)

    # Save dictionary data after all enrichment has completed.
    save_cache(cache)

    latest = tests[-1]

    render_homepage(
        environment,
        display,
    )

    render_test(
        environment,
        display,
        latest,
        latest=True,
    )

    for test in tests[:-1]:
        render_test(
            environment,
            display,
            test,
            latest=False,
        )

    render_historic_index(
        environment,
        display,
        list(reversed(tests[:-1])),
    )

    print("Site generation complete.")


if __name__ == "__main__":
    main()
