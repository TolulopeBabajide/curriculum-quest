# Curriculum Quest 🛡️📚

**Microsoft Agents League — Battle #2: Reasoning Agents (Challenge B, Role-Play Game System)**

A multi-agent **real-life community simulation** that teaches the **Nigerian NERDC JSS1 Basic
Science** curriculum. The learner lives a day in **Oke-Ola**, an everyday (fictional) Nigerian
community — home and compound, market, stream, farm, health post, kitchen, and the night sky. Each
real situation (a blocked market gutter, the firewood the family cooks with, the stream they fetch
from) teaches a science topic and is **localized to the learner's own real environment**. A cast of
AI characters — a Storyteller, Teacher Adaeze, a helpful neighbour, and a friend, Tunde — narrates,
teaches, and sets practical challenges, grounding every fact and question in the curriculum via
**Microsoft Foundry IQ** with inline citations. Science becomes something the learner can see, touch,
and do the same day.

> Built with the **Microsoft Agent Framework** (local) + **Microsoft Foundry IQ** (grounding layer).

---

## 🧠 Why this is a *reasoning* system (not a quiz bot)

The "dice roll" of a normal RPG is replaced by a **knowledge check + verifier** loop:

1. **Storyteller** sets a real-life scene, localized to the learner's environment, and picks the topic.
2. **Mentor (Teacher Adaeze)** retrieves cited curriculum content from Foundry IQ and teaches it with a real local example.
3. **Neighbour (Examiner)** sets a *grounded, cited, practical* challenge from that same content.
4. The learner answers — about their own surroundings.
5. **Verifier step** checks the answer against the cited source (Critic/Verifier reasoning pattern).
6. **Storyteller** narrates the real outcome (cleaner stream, healthier home), updates state — then loops.

This is genuine multi-agent, multi-step reasoning: planning, role-specialisation, grounded retrieval,
and verification — the exact patterns the track rewards.

---

## 🗺️ Curriculum → Community mapping (JSS1 Basic Science)

| NERDC Theme | Community place | Real-life topics |
|-------------|-----------------|------------------|
| Theme 1 — Learning About Our Environment | **Home, market, stream, farm, health post** | Family Health · Environmental Pollution · Living & Non-Living Things |
| Theme 2 — You and Energy | **Kitchen & compound** | Energy (firewood/kerosene/gas/solar) · Renewable & Non-Renewable · Forces (carrying water) |
| Theme 3 — Science and Development | **The night sky** | Gravitation & weightlessness · The Earth in space |

Every example is **localized to the learner's real environment** (asked at onboarding, stored in
campaign state). Swappable to any of the 48 NERDC subject/grade files — see `scripts/seed_foundry_iq.py`.

---

## 🧩 Agents

| Agent | In-story role | Real job | Tools |
|-------|---------------|----------|-------|
| **Game Master** (the Storyteller) | Narrator + orchestrator | Onboards the learner, localizes scenes, runs the challenge loop, updates state, narrates | character agents (as tools), dice, state, Foundry IQ |
| **Mentor** (Teacher Adaeze) | Science teacher | Teaches a topic from *cited* curriculum content with a real local example | Foundry IQ (curriculum KB), state |
| **Examiner** (a neighbour: Mama Nkechi / Baba Sule / Nurse Bisi) | Community elder/worker | Sets + verifies a *cited, practical* real-life challenge | Foundry IQ (curriculum KB), state |
| **Companion** (Tunde) | The learner's friend | Encourages, adapts to struggle, reacts | state |

---

## 📊 Data & Responsible AI

- **The community frame is 100% original synthetic data** — Oke-Ola, its places, and its people in `worldpack/` are invented for this project (a *representative* Nigerian community, not a real town).
- **Learner personalization uses only what the learner volunteers** at runtime — a first name and a few details about their surroundings (home type, cooking/lighting source, nearby market/farm/stream). **Providing a name is optional**; the game plays fine without one, and no address or other identifier is requested.
- **Where that data goes (be clear-eyed):** like any LLM application, the learner's messages and the details they share are **sent to Azure OpenAI (`gpt-5-mini`) on each turn** to generate the characters' responses — so this input *does leave the device* and is processed by a third party (Microsoft Azure) under its terms. It is **stored only locally** (gitignored `state/`; per-session files are deleted on disconnect), **never committed** to this repo, and not written to application logs.
- **Curriculum content is public NERDC educational material** (not PII, not customer data, not proprietary) used as the grounded knowledge source, with **citations back to curriculum objectives**.
- No student data, PII, or credentials are committed anywhere in this repo.
- Learners are told they are interacting with AI. Answers are checked against cited sources before progress is granted (human-in-the-loop: the learner *is* the human).
- **For real classroom/child use** (beyond this demo): verifiable parental/teacher consent (COPPA-school path; Nigeria NDPA guardian consent), input minimization, and a data-retention statement would be required first — tracked in the backlog (GRC-04/05/06).

---

## 🚀 Quick start

```bash
# 1. Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your Foundry + Foundry IQ values
az login                    # DefaultAzureCredential

# 2. Seed Foundry IQ (one time) — indexes worldpack + curriculum, creates the knowledge base
python scripts/seed_foundry_iq.py

# 3. Play
python -m src.game_loop
```

See `BUILD-PLAN.md` for the full 24-hour build plan, architecture, and demo script.

---

## ⚠️ Preview SDK note

Microsoft Agent Framework and Foundry IQ are in preview; APIs shift. If an import or call signature
differs from what's here, run `pip show agent-framework` and check the
[Agent Framework docs](https://learn.microsoft.com/agent-framework/). The Foundry IQ wiring is isolated
in `src/tools/lore.py` so you only fix it in one place.

---

## 📄 License

Copyright © 2026 Tolulope Babajide.

Source-available under the **PolyForm Noncommercial License 1.0.0** — see [`LICENSE`](LICENSE).
You may use, study, share, and modify this project **for any noncommercial purpose** (including
personal, research, and educational use). **Commercial use is not permitted** without a separate
license from the author.

> Note: a noncommercial restriction means this is *source-available*, not OSI "open source"
> (the OSI definition forbids field-of-use limits). For commercial licensing, contact the author.
>
> Third-party components retain their own licenses — the NERDC curriculum is public educational
> material used under citation, and the agent harness under `.claude/`, `scripts/`, `docs/` was
> adapted from the agentic-team-template (see its upstream terms).
