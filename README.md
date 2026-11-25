# Local PII Scrubber for LLM Prompts

A free, open-source Python tool that removes personal information from a prompt on your own computer before you send it to a chatbot. It accompanies the recommendation report *Addressing Large-Language Model Privacy Leaks* (Anerie Patel, University of Waterloo, November 2026).

The tool replaces detected details with numbered placeholders such as `[NAME_1]`, keeps a local map of the originals, and can restore them in the chatbot's reply. The text is processed locally and nothing is sent anywhere by the scrubber itself.

> **This is a first layer of protection, not a guarantee.** It misses some names, cannot detect sensitive topics (for example health or drug use), and cannot stop traits such as age, gender or country from being inferred from the text that remains. Always read the cleaned prompt before you send it.

## What it detects

| Category | Placeholder | How it is found |
|---|---|---|
| Email addresses | `[EMAIL_n]` | Pattern matching |
| IP addresses (IPv4 and IPv6) | `[IP_n]` | Pattern matching with validity check; ignores version numbers such as `firmware 1.2.3.4`; skips loopback, public DNS and example addresses |
| API keys and secrets | `[API_KEY_n]` | Known key formats (OpenAI, Anthropic, Stripe, AWS, GitHub, Slack, Google, SendGrid, JWT), `key = value` context, and an entropy check for random-looking strings |
| Person names | `[NAME_n]` | Context rules plus a named-entity-recognition (NER) model |
| Locations | `[LOCATION_n]` | Context rules plus the NER model |

## How it works

The scrubber borrows the idea of separating detection from replacement from [Microsoft Presidio](https://microsoft.github.io/presidio/) but is built for one person at a command line, not for a development team. Detection runs in four layers:

1. **Patterns:** regular expressions for emails, IP addresses and API keys with known prefixes.
2. **Context rules:** greetings ("Dear Wei Zhang,"), self-introductions in several languages, titles ("Dr. Smith"), `key = value` pairs, CSV and SQL columns, file paths, chat-log speaker labels, and a high-entropy check that only fires when nearby words suggest a secret.
3. **NER model:** `dslim/bert-base-NER` from Hugging Face tags names and places, and the output is cleaned up (fragments such as "luwas" are expanded to the whole word "Oluwaseun").
4. **Propagation:** once a name is found, every other mention of it is masked.

When detections overlap, the lower-numbered layer wins, then the longer span. Each distinct value gets one placeholder, reused wherever it appears.

## Installation

```bash
git clone https://github.com/anerie-anerie/comm.git
cd comm
pip install transformers torch   # only needed for names and locations
```

- Requires Python 3 (version tested: **[fill in]**).
- The standard library is enough for the regex-and-rules mode (`--no-ner`).
- The NER model is downloaded from Hugging Face the first time it is used (a few hundred megabytes) and cached afterwards. After that, scrubbing runs on your machine.

## Usage

Command line:

```bash
python3 scrubber.py "Hi, I'm Anerie Patel (anerie@uwaterloo.ca) from Waterloo"
echo "some text" | python3 scrubber.py
python3 scrubber.py --show-map "text"   # also print the placeholder map
python3 scrubber.py --no-ner "text"     # patterns and rules only (fast)
```

Example (regex and rules only):

```text
$ python3 scrubber.py --no-ner "Email me at sam.lee@example.com from 203.0.113.42"
Email me at [EMAIL_1] from [IP_1]
```

With the NER model on, names and places are replaced too (for example `[NAME_1]`, `[LOCATION_1]`). Exact detections depend on the model.

Python:

```python
from scrubber import scrub, restore

clean, mapping = scrub("Hi, I'm Anerie Patel from Waterloo")
# send `clean` to the chatbot, then:
original_reply = restore(chatbot_reply, mapping)
```

`restore` only works if the chatbot repeats the placeholders exactly. **Keep `mapping` on your own computer: it contains the original personal information.**

### Optional settings (environment variables)

```bash
SCRUBBER_NER_MODELS="dslim/bert-base-NER,Davlan/xlm-roberta-base-ner-hrl"  # multilingual option
SCRUBBER_CASEFIX=1   # extra NER pass for lowercase names
```

Both options were built but not evaluated in the report.

## Evaluation

Real prompts would expose real people, so all test data are synthetic, generated with the [Faker](https://faker.readthedocs.io/) library.

- **Preliminary benchmark:** 100 prompts, 237 labelled details.
- **Hard benchmark:** 300 prompts, 727 labelled details from 45 templates with personal information and 32 without (server logs, configuration files, chats, emails, translation requests). It includes 30 international names, lowercase names, IPv6 addresses, 11 API-key formats, and look-alikes such as git hashes and version numbers. Public figures and places in general-knowledge questions count as non-personal.
- **New-values test:** the same 300 templates with new random values, run after the fixes. Because it reuses the templates, it likely overstates real-world performance.

Presidio was run with default settings as the comparison.

| Test | Tool | Recall | Precision | F1 | Time per prompt |
|---|---|---|---|---|---|
| Hard benchmark | Scrubber, first version | 77.7% | 90.5% | 0.836 | 88.3 ms |
| Hard benchmark | Presidio | 80.3% | 88.4% | 0.842 | 15.6 ms |
| New values, same templates | Scrubber, final version | 95.7% | 96.1% | 0.959 | 62.4 ms |
| New values, same templates | Presidio | 81.0% | 88.9% | 0.848 | 8.7 ms |

Presidio has no default API-key recognizer and found none; the scrubber found 88.9% in the first version and 100% in the final one. Full per-category tables are in the report's Appendix A.

### Error analysis (first version)

- **Pattern-only baseline:** patterns alone found 49.8% of details on the preliminary test, because they cannot recognize names.
- **Missed IP addresses (37):** 18 were followed by a full stop, 10 were IPv6 (unsupported at the time) and 5 followed the word "version."
- **False alarms:** 12 hashes, identifiers or encoded strings mistaken for secrets; 13 non-personal addresses such as `127.0.0.1`.
- **Names:** the model often returned fragments ("luwas" for Oluwaseun, "oh" for Rohan), labelled "Santiago Gutiérrez" as a place, and missed lowercase names and names inside configuration files, SQL or file paths.

### Known weak spots (final version)

- Lowercase full names in ordinary sentences: 5 of 10 found.
- Lowercase place names: 0 of 5 found.
- IP addresses written directly after the word "version" are skipped by design.
- 26 of the 28 false alarms were public figures or places in general-knowledge questions.
- Fairness across languages is unproven: international names were found as often as English ones (96.6% versus 95.3%), but the sample was 30 names, all in Latin script.

## Limitations

- Benchmarks are synthetic, and only five categories are covered.
- Sensitive topics and inference are out of scope.
- The default NER model is trained mainly on English text.
- Restoring originals requires the chatbot to repeat placeholders exactly.

## Repository contents

- `scrubber.py`: the final version of the scrubber.
- First version of the scrubber: **[filename]**
- Benchmark generators (Faker): **[filename(s)]**
- Evaluation script: **[filename]**
