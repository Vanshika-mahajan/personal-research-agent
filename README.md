# Personal Research Agent

Researches hotels, hostels and cafés from the web, keeps every claim tied to a
source link, and writes the documents for the Vibers Connect research brief.
It runs on your own machine with a local Ollama model.

Every output is labelled so you can always tell research from opinion:

| Label | Meaning |
|---|---|
| **RESEARCHED** | backed by a source link (a web page, or a note you pasted in) |
| **IDEA** | a hypothesis drafted from the research. Not evidence |
| **YOUR VIEW** | left blank on purpose. The agent will not invent your opinion |

---

## One-time setup

```bash
cd ~/Documents/personal-research-agent
source .venv/bin/activate
pip install -r requirements.txt

ollama serve                 # leave running in another terminal
ollama pull llama3.2:3b

python -m app.main check     # confirms Ollama, web search and the output folder
```

## Everyday use

**Prefer clicking to typing?** Start the interface and use your browser:

```bash
python -m app.main ui          # opens http://127.0.0.1:8765
```

See [The interface](#the-interface) below. Everything in this section can also be
done from the command line.

You never need to list properties yourself. Give a **place**; the agent finds the
properties with the most review material and studies those.

```bash
# 1. See which properties it would study (no Ollama needed, ~35 searches)
python -m app.main discover "Manali"
python -m app.main discover "Goa" --stays 4 --cafes 3

# 2. Find them, research them, get ONE report (works for any place)
python -m app.main study "Goa" --stays 4 --cafes 3

# 3. The Vibers brief: both documents + the dashboard wireframe
python -m app.main brief vibers --place Manali
python -m app.main brief vibers --place Goa --part 1      # only Part 1
python -m app.main brief vibers --depth quick             # faster, shallower

# One specific property, or any research question
python -m app.main property "Cafe 1947" --place Manali --type cafe
python -m app.main ask "What do guests complain about at beach hostels in Goa?"

# Other
python -m app.main compare                        # top problems across saved properties
python -m app.main list                           # saved reports
```

`--no-fetch` (placed before the command) skips downloading pages and uses
search snippets only: `python -m app.main --no-fetch property "Cafe 1947" --type cafe`.

`--depth`: `quick` = 1 search round, `standard` = 2 (default), `deep` = 3.

## The interface

```bash
python -m app.main ui                     # opens your browser
python -m app.main ui --port 9000         # another port
python -m app.main ui --no-browser        # just print the address
```

It is a normal web page served from your own computer. It needs no extra packages and
nothing leaves your machine except the searches the agent already makes. Stop it with
`Ctrl+C` in the terminal.

| Tab | What you do there |
|---|---|
| **Study a place** | Type a town. **1 · Find properties** picks the hotels, hostels and cafés with the most reviews and history (no Ollama needed). Look at the cards: each shows its score, the sources it was seen on and why it qualified. **Remove** a card, or **Use this instead** on a "considered but not chosen" venue, to change the list. **2 · Research them** studies the list and writes one report. **Vibers brief** writes both brief documents and the dashboard wireframe from the same list. *More options* holds research depth, how many reviews / independent sources a venue must show, "Fill empty slots with weaker candidates" (flagged), "Search for properties again" and "Redo research even if saved". |
| **One property** | Research a single named hotel, hostel or café. |
| **Ask a question** | Any research question, answered from the web with source links. |
| **Add notes** | Paste Google Maps or Instagram reviews you copied by hand (blank line between notes). They are used as high-confidence evidence. |
| **Reports** | Read every report, download it as Markdown, and see which properties have been researched (⚠ means the research found little material). |

A job's progress shows in the drawer at the bottom of the page. **Stop** ends the job at
its next step. It cannot interrupt a model that is in the middle of answering, so allow
a short wait.

Things to know:

* One job runs at a time. Starting a second one is refused with a message.
* The page only answers requests from your own computer (`127.0.0.1`), so other devices
  on your network cannot use it. Do not forward the port to the internet; it has no login.
* Closing the browser tab does not stop a running job. Reopen the page and the job is
  still there.
* Jobs that use the model (**Research them**, **Vibers brief**, **One property**,
  **Ask a question**) need `ollama serve` running. The top-right chips tell you whether
  Ollama and web search are reachable; **Test** checks web search.

## Where things are saved (`research/`)

| Folder | Contents |
|---|---|
| `reports/` | finished Markdown reports |
| `reports/vibers/` | `part1_property_research.md`, `part2_qc_intelligence.md`, `part2_dashboard_wireframe.html`, `property_selection.md` |
| `reports/study_<place>.md` | the report from `study` |
| `selections/` | the properties chosen for each place (reused until `--rediscover`) |
| `properties/` | one JSON profile per property, **reused** so you never redo finished work |
| `topics/` | platform / tool / market research (Zostel, PriceLabs, ...) |
| `evidence/` | every evidence passage, finding and verification result |
| `raw/` | full page text of every source (git-ignored) |
| `manual/` | notes you pasted in |

If a long run is interrupted, run the same command again. Finished
properties are loaded from `properties/` and only the missing ones are researched.
`--refresh` forces a redo.

## How properties are chosen (discovery)

`discover` / `study` / `brief` search for candidates, then score each one by **how much
evidence exists to study** (out of 100):

| Part | Points | What counts |
|---|---|---|
| Reach | 30 | independent sites that mention it (10+ = full marks) |
| Review volume | 35 | reviews visible across platforms (5,000+ = full marks, log scale) |
| Rating | 20 | rating shrunk towards 4.0, so 5.0 from 3 reviews cannot win |
| History | 15 | years operating, when a "since 2014" style date was seen (12+ years = full) |

To qualify a venue needs a listing on a review/booking platform (or a visible rating/review
count), at least 3 independent sources, and 50+ reviews visible (or 5+ sources). Landmarks,
areas and articles' section titles are filtered out. If fewer venues qualify than you asked
for, you get fewer and a note saying why. The list is **never padded**; `--allow-thin`
fills the gaps with weaker, clearly flagged venues, and `--min-reviews` / `--min-sources`
change the bar.

The score says how much there is to study, **not** how good the place is.

* What it searches: "best hostels/hotels/cafes in <place>" articles, Tripadvisor, Booking.com,
  Hostelworld, Zomato, "oldest ... since" queries; then two searches per promising candidate.
* The numbers come only from search-result text. Google Maps and Instagram are unreadable
  to the agent, so their counts are usually missing: *not shown* means unseen, not zero.
* After researching, a property that turns out thin (fewer than 8 passages or 3 sources) is
  swapped for the next-best reserve. Every swap is listed in the report.
* The choice is saved in `research/selections/<place>.json`, so re-running studies the **same**
  properties and reuses their cached research. `--rediscover` searches again.
* The report of what was chosen and what was rejected (with reasons) is written to
  `research/reports/discovery_<place>.md`, and at the top of Part 1 of the brief.

Prefer to choose yourself? Pass a file: `python -m app.main brief vibers --properties mine.json`
(see `research/vibers_properties.json` for the format). It then skips discovery entirely.

## Google reviews and Instagram: add them by hand

Google Maps and Instagram need a login and render with JavaScript, so a
program cannot read them. The agent only sees search-engine snippets for
those channels, and every report has a **Channels reached** table saying so
(✅ full text, ⚠️ snippets only, ❌ nothing).

The honest fix is to read them yourself in your browser and paste them in:

```bash
python -m app.main note "Zostel Old Manali" "the heater in our dorm never worked" --platform "Google Maps"
python -m app.main note "Cafe 1947" --file cafe1947_reviews.txt --platform "Google Maps"   # blank line between reviews
python -m app.main note "Cafe 1947" "caption: weekly open-mic every Friday" --platform Instagram
```

Notes are treated as high-confidence evidence and appear in reports as
*your note*. The next `property` / `brief` run notices them automatically.
Then rebuild the documents without searching again:

```bash
python -m app.main brief vibers --render-only
```

## How the pipeline works

```
plan queries -> search -> read pages -> rank & filter passages
   -> LLM findings (in small batches) -> verify (LLM + wording check)
   -> quality check -> [more searching] -> insights -> report
```

* **Property mode** writes its own platform-targeted queries (Google, Tripadvisor,
  Booking.com / Hostelworld, Instagram, Reddit, offers and events); no LLM needed for planning.
* Passages about *other* venues (list articles mention many) are dropped.
* A finding is only **verified** if the LLM agrees **and** its wording overlaps the
  evidence it cites, so an invented finding cannot slip through.
* The report is assembled in code from verified findings, so its source links are real.
  The LLM only adds a short optional summary.
* "Most common problems" are counted by transparent keyword matching across
  properties (needs negative wording + a problem keyword, in at least 2 sources). The list is
  never padded to five.

## Settings (`.env`)

All optional. Defaults are in `app/config.py`.

```
OLLAMA_MODEL=llama3.2:3b      # try a larger model if findings look thin
OLLAMA_NUM_CTX=8192
OLLAMA_BASE_URL=http://localhost:11434
FETCH_PAGES=true
RESULTS_PER_QUERY=6
SEARCH_DELAY=1.5             # seconds between searches; raise it if DuckDuckGo keeps timing out
SEARCH_TIMEOUT=15            # seconds to wait for one search
SEARCH_RETRIES=2             # extra tries (with a growing pause) when a search times out
SEARCH_REGION=wt-wt          # worldwide; e.g. in-en to favour India
MAX_EVIDENCE=60
RESEARCH_DIR=research
```

## Tests

```bash
python -m pytest -q
```

Runs fully offline (fake LLM and fake web), including a test that starts the interface's real server.
Three more tests drive the page in a real browser; they need `pip install playwright` and
Google Chrome, and are skipped when either is missing. Tests that need a real Ollama server or
internet (`test_llm`, `test_graph::test_research_node`, ...) are skipped automatically
when those are not available.

## Honest limits

* A 3B model is small. It is good at following the grounding rules but
  can miss findings. If a report says "No finding passed verification", read the
  *Raw evidence* section and try a larger model.
* Search results come from DuckDuckGo and change over time, so a fresh `--rediscover` may
  choose differently. Discovery reads names and numbers out of snippets and article headings
  with fixed rules; it can miss a good venue whose listings don't show a rating or count.
  Check the "Considered but not chosen" table, and use `--properties` to force a venue in.
* **DuckDuckGo can time out or throttle you.** Each search waits up to `SEARCH_TIMEOUT`
  seconds and is retried after a pause. If a run still shows many `! search failed` lines:
  the list is flagged *unreliable* (a WARNING in the report and in the page), and a saved list
  from such a run is redone automatically next time. If 8 searches in a row fail, the run
  stops with advice instead of carrying on. Wait a few minutes, then run it again; raising
  `SEARCH_DELAY` to 3 and `SEARCH_TIMEOUT` to 25 in `.env` helps on a slow or busy connection.
* Everything the agent drafts as an **IDEA** is a hypothesis to test, not a result.

## Leftover files from earlier versions

These are not used by the pipeline (the real logic is in `app/graph/nodes.py`) but
are kept because older tests import them: `app/graph/evidence.py`, `insight.py`,
`insights.py`, `quality.py`, `app/llm/evidence_analyzer.py`, `followup_generator.py`.
`requirement.txt` (empty, no "s") can be deleted.
