# Trivia Setup

Put a multiple-choice trivia question on your board, then reveal the answer on the next refresh. Questions come from the free [Open Trivia Database](https://opentdb.com/).

## Overview

**What it does:**
- Shows a question with four choices labelled A–D
- On the next refresh, shows the same question with the correct answer
- On the refresh after that, fetches a new question
- No API key required

**Prerequisites:**
- ✅ Internet connection (to reach opentdb.com)
- ✅ No API key needed

## Quick Setup

### 1. Enable the Plugin

**Option A: Web UI**
1. Go to **Integrations** and find "Trivia"
2. Toggle **Enable Trivia** to on
3. Click **Save Changes**

**Option B: Environment Variable**

Add to your `.env` file:
```bash
TRIVIA_ENABLED=true
```

### 2. Configure (optional)

Click **Configure** and adjust:

- **Difficulty** — `any` (default), `easy`, `medium` or `hard`
- **Category ID** — an OpenTDB category number from the table below, or `0` for any category
- **Refresh Interval** — how long each step stays on the board, and therefore how long players get to think. With the default `120`, a question shows for 2 minutes, the answer is revealed on the next refresh and shows for 2 minutes, then a new question appears

### 3. Use in Templates

The plugin works without a template (it has a built-in 6-line display). To build your own page:

```
{{trivia.question|wrap}}


A {{trivia.choice_a}}  B {{trivia.choice_b}}
C {{trivia.choice_c}}  D {{trivia.choice_d}}
{center}{{trivia.answer_letter}} {{trivia.answer}}
```

The last line stays blank until the answer phase.

## Category IDs

| ID | Category | ID | Category |
|----|----------|----|----------|
| 0 | Any (default) | 21 | Sports |
| 9 | General Knowledge | 22 | Geography |
| 10 | Entertainment: Books | 23 | History |
| 11 | Entertainment: Film | 24 | Politics |
| 12 | Entertainment: Music | 25 | Art |
| 13 | Entertainment: Musicals & Theatres | 26 | Celebrities |
| 14 | Entertainment: Television | 27 | Animals |
| 15 | Entertainment: Video Games | 28 | Vehicles |
| 16 | Entertainment: Board Games | 29 | Entertainment: Comics |
| 17 | Science & Nature | 30 | Science: Gadgets |
| 18 | Science: Computers | 31 | Entertainment: Japanese Anime & Manga |
| 19 | Science: Mathematics | 32 | Entertainment: Cartoon & Animations |
| 20 | Mythology | | |

The live list is at <https://opentdb.com/api_category.php>.

## Template Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{{trivia.question}}` | Question text | `What is the capital of Australia?` |
| `{{trivia.choice_a}}` … `{{trivia.choice_d}}` | The four shuffled choices | `Sydney` |
| `{{trivia.answer}}` | Correct answer (empty during the question phase) | `Canberra` |
| `{{trivia.answer_letter}}` | Letter of the correct choice (empty during the question phase) | `B` |
| `{{trivia.phase}}` | `question` or `answer` | `answer` |
| `{{trivia.is_revealed}}` | Whether the answer is showing | `true` |
| `{{trivia.category}}` | Category name | `Geography` |
| `{{trivia.difficulty}}` | `easy`, `medium` or `hard` | `easy` |

## Configuration Reference

| Setting | Type | Required | Default | Description |
|---------|------|----------|---------|-------------|
| `enabled` | boolean | No | `false` | Enable or disable trivia |
| `difficulty` | string | No | `any` | `any`, `easy`, `medium`, `hard` |
| `category` | integer | No | `0` | OpenTDB category id, `0` = any |
| `refresh_seconds` | integer | No | `120` | Seconds per phase, i.e. the think time before the answer is revealed (min 30, max 3600) |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRIVIA_ENABLED` | No | `false` | Enable trivia feature |

## Display Examples

**Question phase:**
```
WHAT IS THE CAPITAL
OF AUSTRALIA?
A SYDNEY   B CANBERRA
C PERTH    D MELBOURNE
```

**Answer phase (next refresh):**
```
WHAT IS THE CAPITAL
OF AUSTRALIA?
A SYDNEY   B CANBERRA
C PERTH    D MELBOURNE

ANSWER: B CANBERRA
```

Long choices are shown one per line and the question is shortened so everything fits.

## API Information

- **Endpoint:** `GET https://opentdb.com/api.php?amount=1&type=multiple&encode=url3986[&category=N][&difficulty=easy|medium|hard]`
- **Authentication:** None
- **Rate limit:** one request per 5 seconds per IP. The plugin calls the API at most once per refresh (never during the answer phase)
- **Response:** `response_code` 0 on success; anything else (e.g. 1 = no results for that category/difficulty, 5 = rate limited) marks the plugin unavailable until the next refresh

## Troubleshooting

### Nothing showing / "Not Available"

1. Check it is enabled: `grep TRIVIA_ENABLED .env`
2. Check logs: `docker-compose logs | grep -i trivia`
3. Check the API is reachable: `curl "https://opentdb.com/api.php?amount=1&type=multiple"`
4. If you set a **Category ID** with a **Difficulty**, some combinations have very few questions; try `any` difficulty or category `0`

### The answer never shows / shows too slowly

Each phase lasts one **Refresh Interval**. Lower it (minimum 30 seconds) for a faster cycle.

### Same question twice in a row

OpenTDB picks randomly; the plugin does not use session tokens, so occasional repeats are possible.

## Restart After Changes

```bash
docker-compose restart
docker-compose logs -f
```
