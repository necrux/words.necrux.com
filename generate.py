#!/usr/bin/env python3
from pathlib import Path
import os
import re
import time

import requests
import yaml
from jinja2 import Environment, FileSystemLoader


BASE_DIR = Path(__file__).parent
WORDS_DIR = BASE_DIR / "words"
CONFIG_DIR = BASE_DIR / "configs"
TEMPLATES_DIR = BASE_DIR / "templates"
SITE_DIR = BASE_DIR / "public"

CACHE_FILE = BASE_DIR / ".local_dictionary.yaml"

MERRIAM_WEBSTER_API = "https://www.dictionaryapi.com/api/v3/references/sd4/json"
MERRIAM_WEBSTER_AUDIO = (
    "https://media.merriam-webster.com/audio/prons/en/us/mp3/"
)

WIKTAPI_API = "https://api.wiktapi.dev/v1/en/word"

MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 10


def load_yaml(path):
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def save_yaml(path, data):
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=False,
            allow_unicode=True,
        )


def get_merriam_webster_key():
    key = os.environ.get("MW_API_KEY")

    if not key:
        raise RuntimeError(
            "MW_API_KEY environment variable is not set."
        )

    return key


def load_cache():
    if not CACHE_FILE.exists():
        return {}

    return load_yaml(CACHE_FILE) or {}


def save_cache(cache):
    save_yaml(CACHE_FILE, cache)


def request_json(url, params=None):
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
                f"Request failed (attempt {attempt}/{MAX_RETRIES}): "
                f"{url}: {exc}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


def extract_merriam_webster_definition(data):
    if not data or not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        shortdefs = entry.get("shortdef")

        if shortdefs:
            return shortdefs[0]

    return None


def extract_merriam_webster_part_of_speech(data):
    if not data or not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        part_of_speech = entry.get("fl")

        if part_of_speech:
            return part_of_speech

    return None


def extract_merriam_webster_pronunciation(data):
    if not data or not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        hwi = entry.get("hwi", {})

        for pronunciation in hwi.get("prs", []):
            mw = pronunciation.get("mw")

            if mw:
                return mw

    return None


def build_merriam_webster_audio_url(audio):
    if not audio:
        return None

    if audio.startswith("bix"):
        subdirectory = "bix"
    elif audio.startswith("gg"):
        subdirectory = "gg"
    elif audio[0].isdigit() or not audio[0].isalpha():
        subdirectory = "number"
    else:
        subdirectory = audio[0]

    return f"{MERRIAM_WEBSTER_AUDIO}{subdirectory}/{audio}.mp3"


def extract_merriam_webster_audio(data):
    if not data or not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        hwi = entry.get("hwi", {})

        for pronunciation in hwi.get("prs", []):
            sound = pronunciation.get("sound", {})
            audio = sound.get("audio")

            if audio:
                return build_merriam_webster_audio_url(audio)

    return None


def lookup_merriam_webster(word, api_key):
    url = f"{MERRIAM_WEBSTER_API}/{word}"

    data = request_json(
        url,
        params={"key": api_key},
    )

    if not data:
        return {}

    return {
        "definition": extract_merriam_webster_definition(data),
        "part_of_speech": extract_merriam_webster_part_of_speech(data),
        "pronunciation": extract_merriam_webster_pronunciation(data),
        "audio": extract_merriam_webster_audio(data),
    }


def extract_wiktapi_definition(data):
    if not data:
        return None

    for entry in data.get("entries", []):
        for sense in entry.get("senses", []):
            glosses = sense.get("glosses", [])

            if glosses:
                return glosses[0]

    return None


def extract_wiktapi_part_of_speech(data):
    if not data:
        return None

    for entry in data.get("entries", []):
        part_of_speech = entry.get("pos")

        if part_of_speech:
            return part_of_speech

    return None


def extract_wiktapi_audio(data):
    if not data:
        return None

    fallback_audio = None

    for entry in data.get("entries", []):
        for sound in entry.get("sounds", []):
            mp3_url = sound.get("mp3_url")

            if sound.get("tags") and "US" in sound["tags"] and mp3_url:
                return mp3_url

            if mp3_url and not fallback_audio:
                fallback_audio = mp3_url

            ogg_url = sound.get("ogg_url")

            if ogg_url and not fallback_audio:
                fallback_audio = ogg_url

    return fallback_audio


def lookup_wiktapi(word):
    url = f"{WIKTAPI_API}/{word}"

    data = request_json(
        url,
        params={"lang": "en"},
    )

    if not data:
        return {}

    return {
        "definition": extract_wiktapi_definition(data),
        "part_of_speech": extract_wiktapi_part_of_speech(data),
        "audio": extract_wiktapi_audio(data),
    }


def cache_entry_complete(entry):
    required_fields = (
        "word",
        "definition",
        "definition_source",
        "part_of_speech",
        "part_of_speech_source",
        "pronunciation",
        "pronunciation_source",
        "audio",
        "audio_source",
    )

    return all(field in entry for field in required_fields)


def lookup_word(word, api_key):
    merriam_webster = lookup_merriam_webster(
        word,
        api_key,
    )

    wiktapi = lookup_wiktapi(word)

    definition = merriam_webster.get("definition")

    if definition:
        definition_source = "merriam-webster"
    else:
        definition = wiktapi.get("definition")
        definition_source = "wiktapi" if definition else None

    part_of_speech = merriam_webster.get("part_of_speech")

    if part_of_speech:
        part_of_speech_source = "merriam-webster"
    else:
        part_of_speech = wiktapi.get("part_of_speech")
        part_of_speech_source = (
            "wiktapi" if part_of_speech else None
        )

    pronunciation = merriam_webster.get("pronunciation")

    if pronunciation:
        pronunciation_source = "merriam-webster"
    else:
        pronunciation_source = None

    audio = merriam_webster.get("audio")

    if audio:
        audio_source = "merriam-webster"
    else:
        audio = wiktapi.get("audio")
        audio_source = "wiktapi" if audio else None

    if not any(
        (
            definition,
            part_of_speech,
            pronunciation,
            audio,
        )
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


def enrich_word(word, cache, api_key):
    cache_key = word.lower()

    cached = cache.get(cache_key)

    if cached and cache_entry_complete(cached):
        return cached

    print(f"Looking up: {word}")

    result = lookup_word(
        word,
        api_key,
    )

    if result:
        cache[cache_key] = result
        return result

    if cached:
        print(f"Using existing cached data for: {word}")
        return cached

    print(f"Unable to retrieve data for: {word}")

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


def enrich_words(words, cache, api_key):
    enriched = []

    for word in words:
        enriched.append(
            enrich_word(
                word,
                cache,
                api_key,
            )
        )

    return enriched


def get_test_number(path):
    match = re.search(r"test_(\d+)\.yaml$", path.name)

    if not match:
        raise ValueError(
            f"Unable to determine test number from {path.name}"
        )

    return int(match.group(1))


def load_tests():
    test_files = list(WORDS_DIR.glob("test_*.yaml"))
    test_files.extend(WORDS_DIR.glob("test_*.yml"))

    test_files.sort(key=get_test_number)

    tests = []

    for path in test_files:
        data = load_yaml(path)

        tests.append(
            {
                "number": get_test_number(path),
                "source": path.name,
                **data,
            }
        )

    return tests


def prepare_test(test, cache, api_key, is_latest=False):
    prepared = dict(test)

    prepared["is_latest"] = is_latest
    prepared["title"] = f"Test {test['number']}"

    prepared["words"] = enrich_words(
        test.get("words", []),
        cache,
        api_key,
    )

    prepared["challengeWords"] = enrich_words(
        test.get("challengeWords", []),
        cache,
        api_key,
    )

    return prepared


def clean_generated_html():
    if not SITE_DIR.exists():
        return

    for path in SITE_DIR.rglob("*.html"):
        path.unlink()


def create_environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
    )


def render_template(environment, template_name, output_path, **context):
    template = environment.get_template(template_name)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        template.render(**context),
        encoding="utf-8",
    )


def render_homepage(environment, display, latest_test):
    render_template(
        environment,
        "index.html.j2",
        SITE_DIR / "index.html",
        display=display,
        test=latest_test,
        latest_url="latest/index.html",
        historic_url="historic/index.html",
    )


def render_latest_test(environment, display, latest_test):
    render_template(
        environment,
        "test.html.j2",
        SITE_DIR / "latest" / "index.html",
        display=display,
        test=latest_test,
    )


def render_practice_test(environment, display, latest_test):
    render_template(
        environment,
        "practice.html.j2",
        SITE_DIR / "latest" / "practice.html",
        display=display,
        test=latest_test,
    )


def render_historic_tests(environment, display, tests):
    historic_dir = SITE_DIR / "historic"

    for test in tests:
        render_template(
            environment,
            "test.html.j2",
            historic_dir / f"test_{test['number']}.html",
            display=display,
            test=test,
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


def main():
    api_key = get_merriam_webster_key()

    display = load_yaml(
        CONFIG_DIR / "display.yaml"
    )

    tests = load_tests()

    if not tests:
        raise RuntimeError(
            "No spelling tests were found."
        )

    cache = load_cache()

    latest_test_number = max(
        test["number"]
        for test in tests
    )

    prepared_tests = []

    for test in tests:
        is_latest = test["number"] == latest_test_number

        prepared_tests.append(
            prepare_test(
                test,
                cache,
                api_key,
                is_latest=is_latest,
            )
        )

    latest_test = next(
        test
        for test in prepared_tests
        if test["is_latest"]
    )

    save_cache(cache)

    clean_generated_html()

    environment = create_environment()

    render_homepage(
        environment,
        display,
        latest_test,
    )

    render_latest_test(
        environment,
        display,
        latest_test,
    )

    render_practice_test(
        environment,
        display,
        latest_test,
    )

    historic_tests = [
        test
        for test in prepared_tests
        if not test["is_latest"]
    ]

    render_historic_tests(
        environment,
        display,
        historic_tests,
    )

    render_historic_index(
        environment,
        display,
        historic_tests,
    )

    print("Generation complete.")


if __name__ == "__main__":
    main()
