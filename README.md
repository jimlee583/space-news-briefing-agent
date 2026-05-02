# space-news-briefing-agent

A scheduled Python agent that, every weekday morning:

1. Searches current news for a configurable list of space and defense-space
   companies (K2 Space, Boeing Space, Lockheed Martin Space, York Space
   Systems, Rocket Lab, Northrop Grumman Space, …).
2. Deduplicates and normalizes the articles.
3. Summarizes them with an LLM into a structured, grounded briefing.
4. Generates an executive-friendly **PowerPoint deck** (`.pptx`).
5. Emails the deck to a distribution list.

The system is designed to be small, easy to extend, and easy to run either
locally or on GitHub Actions.

---

## Table of contents

- [Architecture](#architecture)
- [Quick start (local)](#quick-start-local)
- [Configuration](#configuration)
- [Adding or removing tracked companies](#adding-or-removing-tracked-companies)
- [Running on GitHub Actions](#running-on-github-actions)
- [Manually triggering the workflow](#manually-triggering-the-workflow)
- [Changing the schedule](#changing-the-schedule)
- [Swapping out the news provider](#swapping-out-the-news-provider)
- [Project layout](#project-layout)
- [Development](#development)

---

## Architecture

```
                    ┌─────────────────┐
   topics.yaml ───▶ │   topics.py     │
                    └────────┬────────┘
                             │
                             ▼
   NewsAPI / RSS / …  ◀── news/collector.py ── news/registry.py
                             │
                             ▼
                    ┌─────────────────┐
                    │  summarizer.py  │  ── OpenAI structured output ──▶  Briefing
                    └────────┬────────┘
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
         deck.py (.pptx)           email_sender.py (SMTP)
```

All glue lives in `pipeline.py`; the CLI in `cli.py` just parses args, loads
config, and calls it.

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

You can also invoke it as a module:

```bash
uv run python -m space_news_briefing_agent --skip-email
```

---

## Configuration

All configuration is via environment variables (loaded from `.env` if present).
See `.env.example` for the full list. The most important ones:

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
| `LOOKBACK_HOURS`           | How far back to search                                     | `36`                 |
| `MAX_ARTICLES_PER_TOPIC`   | Per-topic cap (overridable per topic in `topics.yaml`)     | `8`                  |
| `OUTPUT_DIR`               | Where the deck is written                                  | `output`             |
| `TOPICS_FILE`              | Path to topics config                                      | `topics.yaml`        |
| `LOG_LEVEL`                | `DEBUG` / `INFO` / `WARNING` / `ERROR`                     | `INFO`               |

CLI flags (`--date`, `--topics`, `--output-dir`, `--skip-email`, `--log-level`)
override env vars for ad-hoc runs.

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

To **temporarily mute** a topic without losing its config, set `enabled: false`.
To **track a different YAML file** for a one-off run, pass `--topics
path/to/other.yaml` or set `TOPICS_FILE`.

After editing `topics.yaml`, do a dry run to confirm:

```bash
uv run space-news-briefing --skip-email
```

The logs will show which topics were loaded and how many articles each one
returned.

---

## Running on GitHub Actions

The workflow at `.github/workflows/daily-briefing.yml` runs the briefing on a
weekday cron and uploads the deck as a build artifact.

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

## Changing the schedule

Edit the `cron:` line in `.github/workflows/daily-briefing.yml`:

```yaml
on:
  schedule:
    - cron: "30 11 * * 1-5"   # 11:30 UTC, Mon-Fri
```

GitHub Actions cron is **always UTC**. Examples:

| Local time             | UTC cron               |
| ---------------------- | ---------------------- |
| 07:30 ET (DST)         | `30 11 * * 1-5`        |
| 06:00 PT (standard)    | `0 14 * * 1-5`         |
| 09:00 CET              | `0 8 * * 1-5`          |

Note: GitHub Actions cron triggers can be delayed by several minutes during
peak load, so don't pick a schedule that has to be exact.

---

## Swapping out the news provider

The news layer is intentionally tiny so you can replace NewsAPI later
(SerpAPI, Bing Search, Google Custom Search, an RSS feed, etc.).

To add a new provider:

1. Create `src/space_news_briefing_agent/news/<provider>.py` with a class that
   implements the `NewsProvider` protocol from
   `src/space_news_briefing_agent/news/base.py`:

   ```python
   class MyProvider:
       name = "myprovider"

       def __init__(self, api_key: str) -> None: ...

       def search(self, query, *, since, max_results) -> list[Article]: ...
   ```

   The contract: return a list of `Article` objects with `topic_name=""`
   (the collector fills it in), set `query` to the exact string used, and
   raise `NewsProviderError` on auth/quota/network failures.

2. Register it in `src/space_news_briefing_agent/news/registry.py`:

   ```python
   from .myprovider import MyProvider

   def _build_myprovider(cfg: NewsConfig) -> NewsProvider:
       return MyProvider(api_key=cfg.api_key or "")

   _FACTORIES["myprovider"] = _build_myprovider
   ```

3. Set `NEWS_PROVIDER=myprovider` in `.env` (and as a GitHub Actions variable).

The rest of the pipeline (collector, summarizer, deck, email) is provider-agnostic.

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
│   ├── models.py                    # Pydantic: Article, NewsItem, CompanyBrief, Briefing
│   ├── news/
│   │   ├── __init__.py
│   │   ├── base.py                  # NewsProvider protocol
│   │   ├── newsapi.py               # NewsAPI implementation
│   │   ├── registry.py              # provider factory registry
│   │   └── collector.py             # per-topic aggregation + dedup
│   ├── summarizer.py                # OpenAI structured-output summarization
│   ├── deck.py                      # python-pptx deck generator
│   ├── email_sender.py              # SMTP email with .pptx attachment
│   ├── pipeline.py                  # collect → summarize → render → email
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
