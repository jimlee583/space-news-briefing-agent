# space-news-briefing-agent

A scheduled Python agent that, every weekday morning:

1. Ingests intelligence from one or more **sources** (news today; launch
   schedules now; FCC filings / SAM.gov / SDA announcements next).
2. Normalizes everything into a common `IntelligenceEvent` shape.
3. Deduplicates and persists the day's events to a JSONL store.
4. Summarizes them with an LLM into a structured, grounded briefing.
5. Generates an executive-friendly **PowerPoint deck** (`.pptx`).
6. Emails the deck to a distribution list.

The system is designed to be small, easy to extend, and easy to run either
locally or on GitHub Actions.

---

## Table of contents

- [Architecture](#architecture)
- [Quick start (local)](#quick-start-local)
- [Configuration](#configuration)
- [Intelligence sources](#intelligence-sources)
  - [News (NewsAPI by default)](#news-newsapi-by-default)
  - [Upcoming launches (Launch Library 2)](#upcoming-launches-launch-library-2)
  - [Events JSONL store](#events-jsonl-store)
- [Adding or removing tracked companies](#adding-or-removing-tracked-companies)
- [Running on GitHub Actions](#running-on-github-actions)
- [Manually triggering the workflow](#manually-triggering-the-workflow)
- [Adding new sources](#adding-new-sources)
- [Project layout](#project-layout)
- [Development](#development)

---

## Architecture

```
                ┌──────────────────────────────────────┐
   topics.yaml ─▶ sources/news.py  (NewsAPI / RSS / …)  ┐
                │                                        │
   LL2 API ────▶ sources/launches.py                     │
                │                                        ▼
                │                 core/normalize.py  ──▶  IntelligenceEvent[]
                │                                        │
                │                 core/dedupe.py     ──▶  IntelligenceEvent[]
                │                                        │
                │                 core/storage.py    ──▶  output/events.jsonl
                │                                        │
                │                                        ▼
                │                 summarizer.py     ──▶  Briefing (LLM)
                │                                        │
                ▼                                        ▼
                main.py / pipeline.py        deck.py (.pptx)  ──▶  email_sender.py
```

The pipeline shape is::

    source-specific ingestion
      → normalized intelligence events
      → dedupe / persist
      → summarize
      → PowerPoint deck
      → email

Glue lives in `main.py` (re-exported as `pipeline.py` for backwards
compatibility); the CLI in `cli.py` just parses args, loads config, and
calls it.

---

## Quick start (local)

Prerequisites:

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`brew install uv` or `pipx install uv`)

```bash
git clone <this-repo> space-news-briefing-agent
cd space-news-briefing-agent

# Create the virtualenv and install dependencies
uv sync

# Configure secrets
cp .env.example .env
# edit .env: set OPENAI_API_KEY, NEWS_API_KEY, SMTP_*, EMAIL_TO

# Dry run: build the deck without sending email
uv run space-news-briefing --skip-email

# Full run
uv run space-news-briefing
```

The generated deck lands in `output/space_defense_news_briefing_YYYY-MM-DD.pptx`.
Normalized events for the run are appended to `output/events.jsonl` (path
configurable via `EVENTS_STORE_PATH`).

You can also invoke it as a module:

```bash
uv run python -m space_news_briefing_agent --skip-email
```

### Test with the launch source disabled

```bash
ENABLE_LAUNCH_SOURCE=false uv run space-news-briefing --skip-email
```

### Test with the news source disabled

```bash
ENABLE_NEWS_SOURCE=false uv run space-news-briefing --skip-email
```

If both sources are disabled the pipeline still runs and emits a
"No major updates found" deck rather than crashing.

---

## Configuration

All configuration is via environment variables (loaded from `.env` if
present). See `.env.example` for the full list. The most important ones:

| Variable                   | Purpose                                                    | Default              |
| -------------------------- | ---------------------------------------------------------- | -------------------- |
| `OPENAI_API_KEY`           | Auth for the LLM call                                      | _required_           |
| `OPENAI_MODEL`             | Model name                                                 | `gpt-4o-mini`        |
| `NEWS_PROVIDER`            | Which news backend to use                                  | `newsapi`            |
| `NEWS_API_KEY`             | Auth for NewsAPI                                           | _required for NewsAPI_ |
| `SMTP_HOST` / `SMTP_PORT`  | SMTP server                                                | `smtp.gmail.com:587` |
| `SMTP_USERNAME` / `_PASSWORD` | SMTP credentials                                        | _required for email_ |
| `EMAIL_FROM`               | Optional explicit `From:`                                  | falls back to `SMTP_USERNAME` |
| `EMAIL_TO`                 | Comma-separated recipient list                             | _required for email_ |
| `LOOKBACK_HOURS`           | How far back to search news                                | `36`                 |
| `MAX_ARTICLES_PER_TOPIC`   | Per-topic cap (overridable per topic in `topics.yaml`)     | `8`                  |
| `OUTPUT_DIR`               | Where the deck is written                                  | `output`             |
| `TOPICS_FILE`              | Path to topics config                                      | `topics.yaml`        |
| `LOG_LEVEL`                | `DEBUG` / `INFO` / `WARNING` / `ERROR`                     | `INFO`               |
| `ENABLE_NEWS_SOURCE`       | Master switch for news ingestion                           | `true`               |
| `ENABLE_LAUNCH_SOURCE`     | Master switch for launch ingestion                         | `true`               |
| `LAUNCH_API_BASE_URL`      | Override Launch Library 2 base URL                         | LL2 public           |
| `LAUNCH_LOOKAHEAD_DAYS`    | Look-ahead window for upcoming launches                    | `30`                 |
| `INCLUDE_ALL_LAUNCHES`     | If `true`, keep every upcoming launch (not just tracked)   | `false`              |
| `EVENTS_STORE_PATH`        | JSONL store for normalized events                          | `output/events.jsonl`|

CLI flags (`--date`, `--topics`, `--output-dir`, `--skip-email`,
`--log-level`) override env vars for ad-hoc runs.

---

## Intelligence sources

Each source lives under `src/space_news_briefing_agent/sources/` and exposes
a single `fetch_*_events(cfg) -> list[IntelligenceEvent]` entry point. The
orchestrator (`main.py`) treats sources as independent and fault-tolerant:
**if one source fails, the rest of the pipeline still runs.**

### News (NewsAPI by default)

Implementation: `sources/news.py` (wraps `news/newsapi.py`).

- Reads tracked companies from `topics.yaml`.
- Calls each query against NewsAPI's `/v2/everything`.
- Normalizes the resulting articles into `NewsArticleEvent` records via
  `core/normalize.py`.
- Tags entities (K2 Space, Boeing, Lockheed Martin, …) and content tags
  (launch, satellite, constellation, missile warning, …) using simple
  keyword matching.

Disable with `ENABLE_NEWS_SOURCE=false`.

### Upcoming launches (Launch Library 2)

Implementation: `sources/launches.py`.

- Default provider: The Space Devs **Launch Library 2** (free public
  endpoint at `https://ll.thespacedevs.com/2.2.0`).
- Override the base URL via `LAUNCH_API_BASE_URL` (e.g. to use the dev
  mirror or a paid plan).
- Pulls upcoming launches inside `LAUNCH_LOOKAHEAD_DAYS` (default 30).
- By default keeps only launches whose provider / payload / customer
  matches a tracked entity (Rocket Lab, SpaceX with tracked payloads, SDA,
  Space Force, NASA, Lockheed Martin, Northrop Grumman, Boeing, York
  Space, K2 Space). Set `INCLUDE_ALL_LAUNCHES=true` to keep everything.
- Falls back to a small bundled mock if the API is unreachable so the
  daily run never breaks because of a flaky upstream — see TODO note in
  `sources/launches.py`.

Disable with `ENABLE_LAUNCH_SOURCE=false`.

### Events JSONL store

Every run appends the day's deduped events to `output/events.jsonl`
(configurable via `EVENTS_STORE_PATH`). Each line is a single
`IntelligenceEvent` (or subclass) serialized via Pydantic. The file is
git-friendly, easy to grep, and trivially loadable with `core/storage.py`:

```python
from space_news_briefing_agent.core.storage import load_events
events = load_events("output/events.jsonl")
```

If you only want the most recent run, rotate / truncate this file from cron
or `gh actions`.

---

## Adding or removing tracked companies

The full topic list lives in `topics.yaml` at the repo root — **no code
changes needed** to add or remove companies.

Each topic supports:

```yaml
- name: Some New Company           # required, used as slide section title
  queries:                         # required, at least one query
    - '"Some New Company"'         # quote inner phrases for exact match
    - 'Some New Company satellite'
  enabled: true                    # optional, defaults to true
  max_articles: 6                  # optional, overrides MAX_ARTICLES_PER_TOPIC
```

To **temporarily mute** a topic without losing its config, set
`enabled: false`. To **track a different YAML file** for a one-off run,
pass `--topics path/to/other.yaml` or set `TOPICS_FILE`.

---

## Running on GitHub Actions

The workflow at `.github/workflows/daily-briefing.yml` runs the briefing on
a weekday cron and uploads the deck as a build artifact.

Configure these in your repository:

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret           | Notes                                                      |
| ---------------- | ---------------------------------------------------------- |
| `OPENAI_API_KEY` | Your OpenAI key                                            |
| `NEWS_API_KEY`   | Your NewsAPI key                                           |
| `SMTP_USERNAME`  | SMTP login (e.g. Gmail address)                            |
| `SMTP_PASSWORD`  | SMTP password / app password                               |
| `EMAIL_FROM`     | (Optional) explicit From: address                          |
| `EMAIL_TO`       | Comma-separated recipient list                             |

**Variables** (Settings → Secrets and variables → Actions → Variables) —
all optional, all have defaults:

| Variable                 | Default              |
| ------------------------ | -------------------- |
| `OPENAI_MODEL`           | `gpt-4o-mini`        |
| `NEWS_PROVIDER`          | `newsapi`            |
| `SMTP_HOST`              | `smtp.gmail.com`     |
| `SMTP_PORT`              | `587`                |
| `LOOKBACK_HOURS`         | `36`                 |
| `MAX_ARTICLES_PER_TOPIC` | `8`                  |
| `ENABLE_NEWS_SOURCE`     | `true`               |
| `ENABLE_LAUNCH_SOURCE`   | `true`               |
| `LAUNCH_API_BASE_URL`    | LL2 public           |
| `LAUNCH_LOOKAHEAD_DAYS`  | `30`                 |
| `INCLUDE_ALL_LAUNCHES`   | `false`              |

The workflow uses `uv` for fast, reproducible installs.

---

## Manually triggering the workflow

The workflow is registered with `workflow_dispatch`, so you can run it on
demand from the GitHub UI:

1. Go to **Actions → Daily Space & Defense-Space Briefing**.
2. Click **Run workflow**.
3. Choose the branch and (optionally) flip `skip_email` to `true` for a dry
   run that still uploads the deck artifact.

From the CLI:

```bash
gh workflow run daily-briefing.yml
gh workflow run daily-briefing.yml -f skip_email=true
```

---

## Adding new sources

The repo is structured to make new intelligence sources cheap to add. Good
candidates next:

- **FCC filings** — public ECFS API, watch for satellite licensing /
  earth-station applications from tracked operators.
- **SAM.gov solicitations** — public opportunities feed; filter for
  Space Force / SDA / NRO / SSC NAICS codes.
- **SDA / Space Force announcements** — RSS or scraped press pages.

Recipe:

1. Create `src/space_news_briefing_agent/sources/<name>.py`. Expose
   `fetch_<name>_events(cfg) -> list[IntelligenceEvent]`. Translate the
   provider's wire format into `IntelligenceEvent` (or a new subclass)
   using `core/normalize.py` helpers. Catch provider errors and return
   `[]` on failure — sources MUST NOT crash the daily pipeline.
2. (Optional) Add provider-specific config in `config.py` and an
   `ENABLE_<NAME>_SOURCE` flag.
3. Wire it into `main.py` next to the existing `fetch_news_events` /
   `fetch_launch_events` calls, behind its feature flag.
4. (Optional) Add a new subclass to `core/models.py` if the source has
   fields the existing types don't model.
5. Add tests in `tests/`.

The summarizer, deck, emailer, and storage layer require no changes for
new sources as long as they emit `IntelligenceEvent` instances.

---

## Project layout

```
.
├── .env.example
├── .github/workflows/daily-briefing.yml
├── pyproject.toml
├── topics.yaml                      # ← edit this to track different companies
├── README.md
├── src/space_news_briefing_agent/
│   ├── __init__.py
│   ├── __main__.py                  # python -m space_news_briefing_agent
│   ├── cli.py                       # argparse entry point
│   ├── config.py                    # env-var configuration
│   ├── topics.py                    # topics.yaml loader
│   ├── models.py                    # Briefing / NewsItem / CompanyBrief / Article
│   ├── core/                        # source-agnostic data layer
│   │   ├── models.py                # IntelligenceEvent + subclasses, BriefingInput
│   │   ├── normalize.py             # raw → IntelligenceEvent + entity/tag tagging
│   │   ├── dedupe.py                # URL & title-based dedupe
│   │   └── storage.py               # JSONL load/save/append
│   ├── sources/                     # one module per intelligence source
│   │   ├── news.py                  # wraps news/newsapi.py + normalize
│   │   └── launches.py              # The Space Devs Launch Library 2 (+ mock)
│   ├── news/                        # news-provider abstraction (legacy, used by sources/news.py)
│   │   ├── base.py                  # NewsProvider protocol
│   │   ├── newsapi.py               # NewsAPI implementation
│   │   ├── registry.py              # provider factory registry
│   │   └── collector.py             # per-topic aggregation + dedup
│   ├── summarizer.py                # OpenAI structured-output summarization
│   ├── deck.py                      # python-pptx deck generator
│   ├── email_sender.py              # SMTP email with .pptx attachment
│   ├── main.py                      # orchestrator: sources → summarize → deck → email
│   ├── pipeline.py                  # backwards-compatible alias for main.py
│   └── logging_setup.py
└── tests/
```

---

## Development

```bash
uv sync --extra dev

# Lint
uv run ruff check .
uv run ruff format --check .

# Type-check
uv run mypy src

# Tests
uv run pytest
```
