# Trivia Plugin

Multiple-choice trivia from the [Open Trivia Database](https://opentdb.com/). Shows a question with four choices, then reveals the answer on the next refresh.

**→ [Setup Guide](./docs/SETUP.md)** - Configuration instructions

## Overview

The Trivia plugin fetches one multiple-choice question from OpenTDB and runs a two-phase cycle driven by the refresh interval:

1. **Question phase** – the question and choices A–D are shown; `answer` / `answer_letter` are empty.
2. **Answer phase** (next refresh) – the same question and choices, with the correct answer revealed. No HTTP call is made.
3. The refresh after that fetches a fresh question.

Default display (no template needed):

```
WHAT IS THE CAPITAL
OF AUSTRALIA?
A SYDNEY   B CANBERRA
C PERTH    D MELBOURNE

ANSWER: B CANBERRA
```

## Template Variables

```
{{trivia.question}}       # The question text
{{trivia.choice_a}}       # Choice A
{{trivia.choice_b}}       # Choice B
{{trivia.choice_c}}       # Choice C
{{trivia.choice_d}}       # Choice D
{{trivia.answer}}         # Correct answer text ("" while the question is open)
{{trivia.answer_letter}}  # A-D of the correct choice ("" while the question is open)
{{trivia.phase}}          # "question" or "answer"
{{trivia.is_revealed}}    # true/false
{{trivia.category}}       # e.g. "Geography"
{{trivia.difficulty}}     # easy / medium / hard
```

## Example Templates

### Question with choices (Recommended)

```
{{trivia.question|wrap}}


A {{trivia.choice_a}}  B {{trivia.choice_b}}
C {{trivia.choice_c}}  D {{trivia.choice_d}}
{center}{{trivia.answer_letter}} {{trivia.answer}}
```

The last line is blank during the question phase and shows e.g. `B CANBERRA` once revealed.

### One choice per line

```
{{trivia.question|wrap}}
A {{trivia.choice_a}}
B {{trivia.choice_b}}
C {{trivia.choice_c}}
D {{trivia.choice_d}}
```

## Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| enabled | boolean | false | Enable/disable the plugin |
| difficulty | enum | any | `any`, `easy`, `medium` or `hard` |
| category | integer | 0 | OpenTDB category id, 0 = any (see [SETUP.md](./docs/SETUP.md)) |
| refresh_seconds | integer | 120 | Seconds per step of the question → answer → new question cycle (min 30). This is the think time: the answer is revealed one refresh after the question |

## API

This plugin uses the free [Open Trivia Database API](https://opentdb.com/api_config.php). No API key is required. OpenTDB asks for at most one request every 5 seconds per IP; the plugin makes at most one request per refresh (and none during the answer phase), so the 30 s minimum refresh keeps it well inside that limit. Session tokens (which prevent repeat questions) are not used.

Questions are requested with `encode=url3986` and decoded with `urllib.parse.unquote`, so HTML entities never reach the board.

## Development

```bash
pip install -r requirements-dev.txt
# see .github/workflows/ci.yml for the plugin directory layout the tests expect
pytest tests/ -v --cov=.
```

## Author

FiestaBoard Team
