#!/usr/bin/env python3

from pathlib import Path
import os
import re
import time

import requests
import yaml
from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parent

CONFIG_DIR = ROOT / "configs"
TEMPLATES_DIR = ROOT / "templates"
WORDS_DIR = ROOT / "words"

SITE_DIR = ROOT / "site"
CACHE_FILE = ROOT / ".local_dictionary.yaml"

DISPLAY_CONFIG = CONFIG_DIR / "display.yaml"


MERRIAM_WEBSTER_API = (
    "https://www.dictionaryapi.com/api/v3/references/sd2/json/{}"
)

MERRIAM_WEBSTER_AUDIO = (
    "https://media.merriam-webster.com/audio/prons/"
    "en/us/mp3/{}/{}.mp3"
)

WIKTAPI_API = "https://api.wiktapi.dev/v1/en/word/{}"

MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 10


def load_yaml(path):
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(data, path):
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=True,
            allow_unicode=True,
        )


def test_number(path):
    match = re.fullmatch(r"test_(\d+)\.ya?ml", path.name)

    if not match:
        raise ValueError(f"Invalid test filename: {path.name}")

    return int(match.group(1))


def get_test_files():
    files = list(WORDS_DIR.glob("test_*.yaml"))
    files.extend(WORDS_DIR.glob("test_*.yml"))

    return sorted(files, key=test_number)


def load_cache():
    if not CACHE_FILE.exists():
        return {}

    return load_yaml(CACHE_FILE)


def save_cache(cache):
    save_yaml(cache, CACHE_FILE)


def cache_entry_complete(entry):
    """
    Determine whether a cached dictionary entry contains all data
    currently required by the site.

    The pronunciation_source field was added with the written
    pronunciation support. Its presence also causes older cache
    entries to be refreshed automatically.
    """
    if not isinstance(entry, dict):
        return False

    required_fields = (
        "word",
        "definition",
        "definition_source",
        "part_of_speech",
        "part_of_speech_source",
        "audio",
        "audio_source",
        "pronunciation",
        "pronunciation_source",
    )

    return all(field in entry for field in required_fields)


def request_json(url, params=None):
    """
    Request JSON from an API endpoint with retries.

    Returns None if all attempts fail.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            return response.json()

        except requests.RequestException as exc:
            print(
                f"  Request failed "
                f"(attempt {attempt}/{MAX_RETRIES}): {exc}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def get_merriam_webster_key():
    key = os.environ.get("MW_API_KEY")

    if not key:
        raise RuntimeError(
            "MW_API_KEY environment variable is not set."
        )

    return key


def extract_merriam_webster_definition(data):
    """
    Extract the first concise definition from a Merriam-Webster
    Elementary Dictionary response.

    A successful lookup returns entry dictionaries.

    A failed lookup may return spelling suggestions as strings.
    Those are intentionally ignored.
    """
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        short_definitions = entry.get("shortdef", [])

        if short_definitions:
            return short_definitions[0]

    return None


def extract_merriam_webster_part_of_speech(data):
    """
    Extract the part of speech from the first usable Merriam-Webster
    dictionary entry.
    """
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        part_of_speech = entry.get("fl")

        if part_of_speech:
            return part_of_speech

    return None


def extract_merriam_webster_pronunciation(data):
    """
    Extract Merriam-Webster's written pronunciation notation.

    The 'mw' field contains Merriam-Webster's pronunciation
    notation intended to show how the word is pronounced.

    This is not IPA.
    """
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        headword_info = entry.get("hwi", {})

        for pronunciation in headword_info.get("prs", []):
            value = pronunciation.get("mw")

            if value:
                return value

    return None


def extract_merriam_webster_audio(data):
    """
    Extract the first Merriam-Webster audio filename.

    Merriam-Webster audio URLs are constructed from the filename
    returned in hwi.prs[].sound.audio.
    """
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        headword_info = entry.get("hwi", {})

        for pronunciation in headword_info.get("prs", []):
            sound = pronunciation.get("sound", {})
            audio = sound.get("audio")

            if audio:
                return audio

    return None


def merriam_webster_audio_url(audio):
    """
    Construct a Merriam-Webster MP3 URL from an audio filename.

    Merriam-Webster uses special subdirectories for audio filenames
    beginning with 'bix', 'gg', or a number/punctuation character.
    Otherwise the first character is used as the subdirectory.
    """
    if not audio:
        return None

    if audio.startswith("bix"):
        subdirectory = "bix"
    elif audio.startswith("gg"):
        subdirectory = "gg"
    elif not audio[0].isalnum() or audio[0].isdigit():
        subdirectory = "number"
    else:
        subdirectory = audio[0].lower()

    return MERRIAM_WEBSTER_AUDIO.format(
        subdirectory,
        audio,
    )


def lookup_merriam_webster(word):
    """
    Retrieve dictionary data from Merriam-Webster's Elementary
    Dictionary.

    Merriam-Webster provides the preferred source for:
        - definition
        - part of speech
        - written pronunciation
        - audio
    """
    api_key = get_merriam_webster_key()

    url = MERRIAM_WEBSTER_API.format(word)

    data = request_json(
        url,
        params={"key": api_key},
    )

    if not data:
        return None

    definition = extract_merriam_webster_definition(data)
    part_of_speech = extract_merriam_webster_part_of_speech(data)
    pronunciation = extract_merriam_webster_pronunciation(data)

    audio_filename = extract_merriam_webster_audio(data)
    audio = merriam_webster_audio_url(audio_filename)

    return {
        "definition": definition,
        "part_of_speech": part_of_speech,
        "pronunciation": pronunciation,
        "audio": audio,
    }


def extract_wiktapi_definition(entry):
    """
    Return the first available definition from a WiktApi entry.
    """
    for sense in entry.get("senses", []):
        glosses = sense.get("glosses", [])

        if glosses:
            return glosses[0]

    return None


def extract_wiktapi_audio(data):
    """
    Return the preferred US MP3 pronunciation URL from WiktApi.

    Preference order:
        1. US-tagged MP3
        2. Any MP3
        3. Any OGG
    """
    if not isinstance(data, dict):
        return None

    entries = data.get("entries", [])

    for entry in entries:
        sounds = entry.get("sounds", [])

        for sound in sounds:
            tags = {
                tag.lower()
                for tag in sound.get("tags", [])
            }

            if "us" in tags:
                mp3_url = sound.get("mp3_url")

                if mp3_url:
                    return mp3_url

    for entry in entries:
        sounds = entry.get("sounds", [])

        for sound in sounds:
            mp3_url = sound.get("mp3_url")

            if mp3_url:
                return mp3_url

    for entry in entries:
        sounds = entry.get("sounds", [])

        for sound in sounds:
            ogg_url = sound.get("ogg_url")

            if ogg_url:
                return ogg_url

    return None


def lookup_wiktapi(word):
    """
    Retrieve dictionary information from WiktApi.

    WiktApi is used as the fallback source for definition,
    part of speech, and audio.

    Written pronunciation is intentionally not retrieved from
    WiktApi because its pronunciation data is not the
    kid-friendly pronunciation notation used by Merriam-Webster.
    """
    url = WIKTAPI_API.format(word)

    data = request_json(
        url,
        params={"lang": "en"},
    )

    if not data:
        return None

    entries = data.get("entries", [])

    if not entries:
        return None

    entry = entries[0]

    return {
        "definition": extract_wiktapi_definition(entry),
        "part_of_speech": entry.get("pos"),
        "audio": extract_wiktapi_audio(data),
    }


def lookup_word(word):
    """
    Retrieve dictionary data using Merriam-Webster as the preferred
    source and WiktApi as the fallback.

    Field hierarchy:

        definition      MW → WiktApi → None
        part of speech  MW → WiktApi → None
        pronunciation   MW → None
        audio           MW → WiktApi → None

    Pronunciation is intentionally limited to Merriam-Webster's
    written pronunciation notation.
    """
    merriam_webster = lookup_merriam_webster(word)
    wiktapi = lookup_wiktapi(word)

    if merriam_webster:
        definition = merriam_webster["definition"]

        if definition:
            definition_source = "merriam-webster"
        elif wiktapi and wiktapi["definition"]:
            definition = wiktapi["definition"]
            definition_source = "wiktapi"
        else:
            definition_source = None

        part_of_speech = merriam_webster["part_of_speech"]

        if part_of_speech:
            part_of_speech_source = "merriam-webster"
        elif wiktapi and wiktapi["part_of_speech"]:
            part_of_speech = wiktapi["part_of_speech"]
            part_of_speech_source = "wiktapi"
        else:
            part_of_speech_source = None

        pronunciation = merriam_webster["pronunciation"]

        if pronunciation:
            pronunciation_source = "merriam-webster"
        else:
            pronunciation_source = None

        audio = merriam_webster["audio"]

        if audio:
            audio_source = "merriam-webster"
        elif wiktapi and wiktapi["audio"]:
            audio = wiktapi["audio"]
            audio_source = "wiktapi"
        else:
            audio_source = None

    elif wiktapi:
        print(
            "  Merriam-Webster unavailable; "
            "using WiktApi where necessary."
        )

        definition = wiktapi["definition"]
        definition_source = (
            "wiktapi"
            if definition
            else None
        )

        part_of_speech = wiktapi["part_of_speech"]
        part_of_speech_source = (
            "wiktapi"
            if part_of_speech
            else None
        )

        pronunciation = None
        pronunciation_source = None

        audio = wiktapi["audio"]
        audio_source = (
            "wiktapi"
            if audio
            else None
        )

    else:
        return None

    if (
        not definition
        and not part_of_speech
        and not pronunciation
        and not audio
    ):
        return None

    return {
        "word": word,
        "definition": definition,
        "definition_source": definition_source,
        "part_of_speech": part_of_speech,
        "part_of_speech_source": part_of_speech_source,
        "pronunciation": pronunciation,
        "pronunciation_source": pronunciation_source,
        "audio": audio,
        "audio_source": audio_source,
    }


def enrich_word(word, cache):
    """
    Return dictionary data for a word.

    Existing complete cache entries are authoritative.

    Failed API lookups are not cached as successful entries.
    """
    cache_key = word.lower()

    cached = cache.get(cache_key)

    if cache_entry_complete(cached):
        return cached

    print(f"Looking up: {word}")

    result = lookup_word(word)

    if result is None:
        print(
            f"  Unable to retrieve dictionary data for: {word}"
        )

        if cached:
            return cached

        return {
            "word": word,
            "definition": None,
            "definition_source": None,
            "part_of_speech": None,
            "part_of_speech_source": None,
            "pronunciation": None,
            "pronunciation_source": None,
            "audio": None,
            "audio_source": None,
        }

    cache[cache_key] = result

    return result


def enrich_test(test_data, cache):
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


def create_environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
    )


def clean_site():
    """
    Remove generated HTML from site/.

    The repository-root index.html is intentionally not touched.
    """
    if not SITE_DIR.exists():
        return

    for html_file in SITE_DIR.rglob("*.html"):
        html_file.unlink()


def render_template(
    environment,
    template_name,
    output_path,
    **context,
):
    template = environment.get_template(template_name)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    rendered = template.render(**context)

    output_path.write_text(
        rendered,
        encoding="utf-8",
    )


def render_homepage(environment, display):
    render_template(
        environment,
        "index.html.j2",
        ROOT / "index.html",
        display=display,
        latest_url="site/latest/index.html",
        historic_url="site/historic/index.html",
    )


def render_historic_index(environment, display, tests):
    render_template(
        environment,
        "list.html.j2",
        SITE_DIR / "historic" / "index.html",
        display=display,
        title="Historic Words",
        tests=tests,
    )


def render_test(environment, display, test, latest):
    if latest:
        output_path = (
            SITE_DIR
            / "latest"
            / "index.html"
        )
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


def main():
    display = load_yaml(DISPLAY_CONFIG)
    cache = load_cache()

    test_files = get_test_files()

    if not test_files:
        raise RuntimeError(
            "No spelling test files found."
        )

    get_merriam_webster_key()

    environment = create_environment()

    clean_site()

    tests = []

    for path in test_files:
        number = test_number(path)
        source = load_yaml(path)

        enriched = enrich_test(
            source,
            cache,
        )

        enriched["number"] = number
        enriched["title"] = f"Test {number}"

        tests.append(enriched)

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