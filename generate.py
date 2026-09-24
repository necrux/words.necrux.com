#!/usr/bin/env python3

import argparse
import os
import re
import time
from pathlib import Path

import requests
import yaml
from jinja2 import Environment, FileSystemLoader
from urllib.parse import quote


BASE_DIR = Path(__file__).parent

GRADES_DIR = BASE_DIR / "grades"
CONFIG_DIR = BASE_DIR / "configs"
TEMPLATES_DIR = BASE_DIR / "templates"
SITE_DIR = BASE_DIR / "public"

GLOBAL_CONFIG_FILE = CONFIG_DIR / "display.yaml"

ASSETS_DIR = SITE_DIR / "assets"
CSS_DIR = ASSETS_DIR / "css"
JS_DIR = ASSETS_DIR / "js"

STYLE_CSS_OUTPUT = CSS_DIR / "style.css"
SITE_JS_OUTPUT = JS_DIR / "site.js"

MERRIAM_WEBSTER_API = (
    "https://www.dictionaryapi.com/api/v3/references/sd2/json"
)
MERRIAM_WEBSTER_AUDIO = (
    "https://media.merriam-webster.com/audio/prons/en/us/mp3/"
)
WIKTAPI_API = (
    "https://api.wiktapi.dev/v1/en/word"
)
QUICKPRONOUNCE_API = (
    "https://api.quickpronounce.site/v1/dictionary"
)

MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_yaml(path):
    """Load a YAML file and return its contents."""
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(path, data):
    """Save data to a YAML file."""
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            allow_unicode=True,
            sort_keys=False,
        )


def merge_config(global_config, grade_config):
    """
    Merge grade-specific configuration over the global configuration.

    Nested dictionaries are merged so a grade can override one setting
    without redefining the entire section.
    """
    merged = dict(global_config)

    for key, value in grade_config.items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = {
                **merged[key],
                **value,
            }
        else:
            merged[key] = value

    return merged


def load_grade_config(grade):
    """Load and merge global and grade-specific display configuration."""
    global_config = load_yaml(GLOBAL_CONFIG_FILE)

    grade_config_file = (
        GRADES_DIR / str(grade) / "display.yaml"
    )
    grade_config = load_yaml(grade_config_file)

    return merge_config(
        global_config,
        grade_config,
    )


def grade_has_tests(grade):
    words_dir = GRADES_DIR / str(grade) / "words"

    return any(
        words_dir.glob("test_*.yaml")
    ) or any(
        words_dir.glob("test_*.yml")
    )


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def get_merriam_webster_key():
    """Return the Merriam-Webster API key."""
    key = os.getenv("MW_API_KEY")

    if not key:
        raise RuntimeError(
            "MW_API_KEY environment variable is not set."
        )

    return key


def get_quickpronounce_key():
    """Return the QuickPronounce API key."""
    key = os.getenv("QP_API_KEY")

    if not key:
        raise RuntimeError(
            "QP_API_KEY environment variable is not set."
        )

    return key


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def request_json(url, params=None, headers=None):
    """Make a JSON request with retries."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()
            return response.json()

        except requests.RequestException as error:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Request failed after {MAX_RETRIES} attempts: "
                    f"{url}"
                ) from error

            time.sleep(RETRY_DELAY)

    return None


# ---------------------------------------------------------------------------
# QuickPronounce
# ---------------------------------------------------------------------------

def extract_quickpronounce_syllables(data):
    """Extract US syllable pronunciation from QuickPronounce."""
    if not isinstance(data, dict):
        return None

    response_data = data.get("data", {})

    if not isinstance(response_data, dict):
        return None

    syllables = response_data.get("syllables", {})

    if not isinstance(syllables, dict):
        return None

    us_syllables = syllables.get("us")

    if not isinstance(us_syllables, list):
        return None

    return us_syllables


def extract_quickpronounce_audio(data):
    """
    Extract QuickPronounce audio data.

    Audio is not currently fetched or stored, but this function
    remains available for future use.
    """
    pronunciation = data.get("pronunciation", {})

    return pronunciation.get("audio")


def lookup_quickpronounce(word, quickpronounce_key):
    """Look up pronunciation information using QuickPronounce."""
    data = request_json(
        f"{QUICKPRONOUNCE_API}/{quote(word)}",
        headers={
            "X-API-Key": quickpronounce_key,
        },
    )

    if not isinstance(data, dict):
        return {}

    syllables = extract_quickpronounce_syllables(data)

    if not syllables:
        return {}

    return {
        "pronunciation": syllables,
        "pronunciation_source": "quickpronounce",
    }


# ---------------------------------------------------------------------------
# Merriam-Webster
# ---------------------------------------------------------------------------

def extract_merriam_webster_definition(data):
    """Extract a definition from Merriam-Webster data."""
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        definitions = entry.get("shortdef")

        if definitions:
            return definitions[0]

    return None


def extract_merriam_webster_part_of_speech(data):
    """Extract part of speech from Merriam-Webster data."""
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        part_of_speech = entry.get("fl")

        if part_of_speech:
            return part_of_speech

    return None


def extract_merriam_webster_audio(data):
    """Extract the Merriam-Webster audio filename."""
    if not isinstance(data, list):
        return None

    for entry in data:
        if not isinstance(entry, dict):
            continue

        hwi = entry.get("hwi", {})
        pronunciations = hwi.get("prs", [])

        for pronunciation in pronunciations:
            sound = pronunciation.get("sound", {})
            audio = sound.get("audio")

            if audio:
                return audio

    return None


def lookup_merriam_webster(word, merriam_webster_key):
    """Look up definition, part of speech, and audio using MW."""
    data = request_json(
        f"{MERRIAM_WEBSTER_API}/{word}",
        params={
            "key": merriam_webster_key,
        },
    )

    if not isinstance(data, list):
        return {}

    definition = extract_merriam_webster_definition(data)
    part_of_speech = extract_merriam_webster_part_of_speech(data)
    audio = extract_merriam_webster_audio(data)

    result = {}

    if definition:
        result["definition"] = definition

    if part_of_speech:
        result["part_of_speech"] = part_of_speech

    if audio:
        if audio.startswith("bix"):
            subdirectory = "bix"
        elif audio.startswith("gg"):
            subdirectory = "gg"
        elif audio[0].isdigit() or audio[0] in "_-":
            subdirectory = "number"
        else:
            subdirectory = audio[0]

        result["audio"] = (
            f"{MERRIAM_WEBSTER_AUDIO}"
            f"{subdirectory}/{audio}.mp3"
        )
        result["audio_source"] = "merriam-webster"

    return result

    if not isinstance(data, list):
        return {}

    definition = extract_merriam_webster_definition(data)
    part_of_speech = extract_merriam_webster_part_of_speech(data)
    audio = extract_merriam_webster_audio(data)

    result = {}

    if definition:
        result["definition"] = definition

    if part_of_speech:
        result["part_of_speech"] = part_of_speech

    if audio:
        result["audio"] = (
            f"{MERRIAM_WEBSTER_AUDIO}{audio}.mp3"
        )
        result["audio_source"] = "merriam-webster"

    return result


# ---------------------------------------------------------------------------
# WiktAPI
# ---------------------------------------------------------------------------

def extract_wiktapi_definition(data):
    """Extract a definition from WiktAPI data."""
    if not isinstance(data, dict):
        return None

    definitions = data.get("definitions", [])

    for definition in definitions:
        if not isinstance(definition, dict):
            continue

        glosses = definition.get("glosses", [])

        if glosses:
            return glosses[0]

    return None


def extract_wiktapi_part_of_speech(data):
    """Extract part of speech from WiktAPI data."""
    if not isinstance(data, dict):
        return None

    definitions = data.get("definitions", [])

    for definition in definitions:
        if not isinstance(definition, dict):
            continue

        part_of_speech = definition.get("partOfSpeech")

        if part_of_speech:
            return part_of_speech

    return None


def extract_wiktapi_audio(data):
    """Extract audio from WiktAPI data."""
    if not isinstance(data, dict):
        return None

    audio = data.get("audio")

    if isinstance(audio, str):
        return audio

    return None


def lookup_wiktapi(word):
    """Look up fallback word information using WiktAPI."""
    data = request_json(
        f"{WIKTAPI_API}/{word}",
    )

    if not isinstance(data, dict):
        return {}

    definition = extract_wiktapi_definition(data)
    part_of_speech = extract_wiktapi_part_of_speech(data)
    audio = extract_wiktapi_audio(data)

    result = {}

    if definition:
        result["definition"] = definition

    if part_of_speech:
        result["part_of_speech"] = part_of_speech

    if audio:
        result["audio"] = audio
        result["audio_source"] = "wiktapi"

    return result


# ---------------------------------------------------------------------------
# Dictionary cache
# ---------------------------------------------------------------------------

def load_cache(cache_file):
    """Load the local dictionary cache."""
    return load_yaml(cache_file)


def save_cache(cache_file, cache):
    """Save the local dictionary cache."""
    save_yaml(cache_file, cache)


def cache_entry_complete(entry):
    """Return True when a cached word contains all required data."""
    required_fields = [
        "definition",
        "part_of_speech",
        "pronunciation",
        "pronunciation_source",
    ]

    if not all(field in entry for field in required_fields):
        return False

    return entry["pronunciation_source"] == "quickpronounce"


# ---------------------------------------------------------------------------
# Word enrichment
# ---------------------------------------------------------------------------

def lookup_word(
    word,
    merriam_webster_key,
    quickpronounce_key,
):
    """
    Look up all information for a word.

    Source priority:

    1. Merriam-Webster for definition/POS/audio
    2. WiktAPI for missing definition/POS/audio
    3. QuickPronounce for pronunciation
    """
    result = {
        "word": word,
    }

    merriam_webster = lookup_merriam_webster(
        word,
        merriam_webster_key,
    )

    result.update(merriam_webster)

    if (
        "definition" not in result
        or "part_of_speech" not in result
    ):
        wiktapi = lookup_wiktapi(word)

        if "definition" not in result:
            result["definition"] = wiktapi.get(
                "definition"
            )

        if "part_of_speech" not in result:
            result["part_of_speech"] = wiktapi.get(
                "part_of_speech"
            )

        if "audio" not in result and "audio" in wiktapi:
            result["audio"] = wiktapi["audio"]
            result["audio_source"] = wiktapi.get(
                "audio_source"
            )

    quickpronounce = lookup_quickpronounce(
        word,
        quickpronounce_key,
    )

    result["pronunciation"] = quickpronounce.get(
        "pronunciation"
    )
    result["pronunciation_source"] = "quickpronounce"

    return result


def enrich_word(
    word,
    cache,
    merriam_webster_key,
    quickpronounce_key,
):
    """Return cached or freshly looked-up word data."""
    if word in cache and cache_entry_complete(cache[word]):
        return cache[word]

    print(f"Looking up: {word}")

    result = lookup_word(
        word,
        merriam_webster_key,
        quickpronounce_key,
    )

    cache[word] = result

    return result


def enrich_words(
    words,
    cache,
    merriam_webster_key,
    quickpronounce_key,
):
    """Enrich a list of words."""
    enriched = []

    for word in words:
        enriched.append(
            enrich_word(
                word,
                cache,
                merriam_webster_key,
                quickpronounce_key,
            )
        )

    return enriched


# ---------------------------------------------------------------------------
# Test loading
# ---------------------------------------------------------------------------

def get_test_number(path):
    """Return the numeric test number from a test filename."""
    match = re.match(
        r"test_(\d+)\.(yaml|yml)$",
        path.name,
    )

    if not match:
        return None

    return int(match.group(1))


def load_tests(words_dir):
    """Load all spelling tests from a grade's words directory."""
    tests = []

    for path in sorted(words_dir.glob("test_*.yaml")):
        test_number = get_test_number(path)

        if test_number is None:
            continue

        data = load_yaml(path)
        data["number"] = test_number

        tests.append(data)

    for path in sorted(words_dir.glob("test_*.yml")):
        test_number = get_test_number(path)

        if test_number is None:
            continue

        if any(
            test["number"] == test_number
            for test in tests
        ):
            continue

        data = load_yaml(path)
        data["number"] = test_number

        tests.append(data)

    return sorted(
        tests,
        key=lambda test: test["number"],
    )


def prepare_test(
    test,
    cache,
    merriam_webster_key,
    quickpronounce_key,
):
    """Prepare a spelling test for template rendering."""
    words = test.get("words", [])
    challenge_words = test.get("challengeWords", [])

    test["enriched_words"] = enrich_words(
        words,
        cache,
        merriam_webster_key,
        quickpronounce_key,
    )

    test["enriched_challenge_words"] = enrich_words(
        challenge_words,
        cache,
        merriam_webster_key,
        quickpronounce_key,
    )

    return test


# ---------------------------------------------------------------------------
# Jinja
# ---------------------------------------------------------------------------

def create_environment():
    """Create the Jinja2 environment."""
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
    )

def render_assets(environment):
    """Render shared CSS and JavaScript assets."""
    display = load_yaml(GLOBAL_CONFIG_FILE)

    render_template(
        environment,
        "style.css.j2",
        STYLE_CSS_OUTPUT,
        {
            "display": display,
        },
    )

    render_template(
        environment,
        "site.js.j2",
        SITE_JS_OUTPUT,
        {
            "display": display,
        },
    )

# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def render_template(
    environment,
    template_name,
    output_path,
    context,
):
    """Render a Jinja template to a file."""
    template = environment.get_template(template_name)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    context = dict(context)

    context["asset_path"] = os.path.relpath(
        ASSETS_DIR,
        output_path.parent,
    )

    output_path.write_text(
        template.render(**context),
        encoding="utf-8",
    )


def prepare_asset_directories():
    """Create the shared CSS and JavaScript directories."""
    CSS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    JS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


# ---------------------------------------------------------------------------
# Root homepage
# ---------------------------------------------------------------------------

def render_homepage(environment):
    """
    Render the root grade-selection page.

    Only grades containing at least one spelling test are displayed.
    """
    display = load_yaml(GLOBAL_CONFIG_FILE)
    grades = []

    for grade in range(1, 6):
        if not grade_has_tests(grade):
            continue

        grade_dir = GRADES_DIR / str(grade)
        config_file = grade_dir / "display.yaml"

        grade_display = load_yaml(config_file)
        site = grade_display.get("site", {})

        title = site.get(
            "title",
            f"Grade {grade}",
        )

        grades.append(
            {
                "number": grade,
                "title": title,
                "url": f"grades/{grade}/index.html",
            }
        )

    render_template(
        environment,
        "grades.html.j2",
        SITE_DIR / "index.html",
        {
            "display": display,
            "grades": grades,
        },
    )


# ---------------------------------------------------------------------------
# Grade pages
# ---------------------------------------------------------------------------

def render_grade_homepage(
    environment,
    grade,
    display,
    tests,
):
    """Render the homepage for a specific grade."""
    render_template(
        environment,
        "index.html.j2",
        SITE_DIR
        / "grades"
        / str(grade)
        / "index.html",
        {
            "display": display,
            "grade": grade,
            "tests": tests,
        },
    )


def render_latest_test(
    environment,
    grade,
    display,
    test,
):
    """Render the latest words page."""
    render_template(
        environment,
        "test.html.j2",
        SITE_DIR
        / "grades"
        / str(grade)
        / "latest_words"
        / "index.html",
        {
            "display": display,
            "grade": grade,
            "test": test,
        },
    )


def render_practice_test(
    environment,
    grade,
    display,
    test,
):
    """Render the latest words practice page."""
    render_template(
        environment,
        "practice.html.j2",
        SITE_DIR
        / "grades"
        / str(grade)
        / "latest_words"
        / "practice.html",
        {
            "display": display,
            "grade": grade,
            "test": test,
        },
    )


def render_past_tests(
    environment,
    grade,
    display,
    tests,
):
    """Render all past test pages."""
    for test in tests:
        render_template(
            environment,
            "test.html.j2",
            SITE_DIR
            / "grades"
            / str(grade)
            / "past_words"
            / f"test_{test['number']}.html",
            {
                "display": display,
                "grade": grade,
                "test": test,
            },
        )


def render_past_index(
    environment,
    grade,
    display,
    tests,
):
    """Render the past words index."""
    past_tests = tests[:-1]

    render_template(
        environment,
        "list.html.j2",
        SITE_DIR
        / "grades"
        / str(grade)
        / "past_words"
        / "index.html",
        {
            "display": display,
            "grade": grade,
            "tests": past_tests,
        },
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def clean_grade_output(grade):
    """
    Remove generated HTML for one grade before rebuilding it.

    Assets are deliberately not removed because they are shared by
    every grade.
    """
    grade_output = (
        SITE_DIR
        / "grades"
        / str(grade)
    )

    if not grade_output.exists():
        return

    for path in sorted(
        grade_output.rglob("*"),
        reverse=True,
    ):
        if path.is_file() and path.suffix == ".html":
            path.unlink()


# ---------------------------------------------------------------------------
# Grade generation
# ---------------------------------------------------------------------------

def render_grade(
    environment,
    grade,
    merriam_webster_key,
    quickpronounce_key,
):
    """Build all pages for one grade."""
    grade_dir = GRADES_DIR / str(grade)
    words_dir = grade_dir / "words"
    cache_file = grade_dir / ".local_dictionary.yaml"

    if not grade_dir.exists():
        raise RuntimeError(
            f"Grade directory does not exist: {grade_dir}"
        )

    if not words_dir.exists():
        raise RuntimeError(
            f"Words directory does not exist: {words_dir}"
        )

    display = load_grade_config(grade)
    cache = load_cache(cache_file)

    tests = load_tests(words_dir)

    if not tests:
        raise RuntimeError(
            f"No spelling tests found in: {words_dir}"
        )

    print(f"Building grade {grade}...")

    for test in tests:
        prepare_test(
            test,
            cache,
            merriam_webster_key,
            quickpronounce_key,
        )

    save_cache(
        cache_file,
        cache,
    )

    clean_grade_output(grade)

    render_grade_homepage(
        environment,
        grade,
        display,
        tests,
    )

    latest_test = tests[-1]
    latest_test["is_latest"] = True

    render_latest_test(
        environment,
        grade,
        display,
        latest_test,
    )

    render_practice_test(
        environment,
        grade,
        display,
        latest_test,
    )

    render_past_tests(
        environment,
        grade,
        display,
        tests,
    )

    render_past_index(
        environment,
        grade,
        display,
        tests,
    )


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate the spelling words website.",
    )

    parser.add_argument(
        "-g",
        "--grade",
        type=int,
        choices=range(1, 6),
        required=True,
        help="Grade to generate (1-5).",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    merriam_webster_key = get_merriam_webster_key()
    quickpronounce_key = get_quickpronounce_key()

    environment = create_environment()

    prepare_asset_directories()
    render_assets(environment)

    render_homepage(environment)

    render_grade(
        environment,
        args.grade,
        merriam_webster_key,
        quickpronounce_key,
    )

    print(f"Generation complete for grade {args.grade}.")


if __name__ == "__main__":
    main()