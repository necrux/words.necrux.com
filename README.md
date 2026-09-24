# Huebner Spelling Words

This is a simple, easy-to-use website for our kids, maintained by Wes Henderson.

## Adding New Words

New spelling tests are added by creating a new file in:

`grade/#/words/test_#.yaml`

The file should follow the same format as the other test files in that directory. Replace `#` with the next test number.

## Definitions & Pronunciations

Definitions, pronunciations, and other word information are automatically looked up when the website is built.

The website uses several data sources:

* **Merriam-Webster** _(elementary dictionary)_: Primary source for reliable, trusted definitions, and parts of speech.
* **WiktAPI**: Backup source for definitions and other word information when Merriam-Webster does not provide it.
* **QuickPronounce**: Provides easy-to-read, kid-friendly pronunciations broken into syllables, making words easier for children to sound out.

The website is automatically updated when new spelling tests are added.
