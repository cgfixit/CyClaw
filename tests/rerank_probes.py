"""Answer labels and a fresh held-out probe set for choosing the reranker veto (issue #1456).

ANSWER_KEYS gives every answerable probe in tests/ci_rag_smoke.py, and every
answerable probe below, one or more short strings copied from the passage that
answers it. A probe's answer is "in the window" when any of its keys appears in
one of the LOCAL_CONTEXT_CHUNKS chunks the local model would read, compared
with ``normalize_for_keys`` on both sides. That label depends on retrieval
alone, never on a reranker score, so it judges every candidate reranker the
same way, and on both corpora: a docs/ answer is never in a data/corpus window.

A probe that clears the cosine gate is a good hit when its answer is in the
window, and a bad hit otherwise. Look-alikes and off-topic probes have no keys,
so they are always bad hits when they clear the gate. So is an answerable probe
whose answer retrieval left out: a vault hit there hands the local model
context that does not answer the question.

FRESH_ANSWERABLE and FRESH_LOOKALIKE were written and committed before any
reranker scored them. scripts/rerank_bakeoff.py picks a model, a scoring
granularity and a threshold on the older probes only, then judges that choice
on these. Every look-alike's distinctive terms were grepped against
data/corpus and docs/, and neither answers it.

No heavy imports: the bake-off, the smoke and the tests all read this module.
"""

from __future__ import annotations

import re

MCLUHAN = "Marshall McLuhan"
AI_INSIGHTS = "AI-insights"
WHISPER = "Whisper_Council"
OVERVIEW = "cyclaw_overview"

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_SPACE = re.compile(r"\s+")


def normalize_for_keys(text: str) -> str:
    """Lowercase, straighten curly quotes, drop markdown ``*`` emphasis, and collapse whitespace."""
    return _SPACE.sub(" ", text.translate(_QUOTES).replace("*", "")).strip().lower()


def answer_in_window(query: str, window_texts: list[str]) -> bool:
    """True when any answer key for ``query`` appears in one of ``window_texts``; False for a probe with no keys."""
    keys = [normalize_for_keys(key) for key in ANSWER_KEYS.get(query, ())]
    if not keys:
        return False
    return any(key in normalize_for_keys(text) for text in window_texts for key in keys)


# (query, expected source substring or None for docs/). Reworded away from the
# corpus's own words, like PARAPHRASE_QUERIES; each rests on one passage.
FRESH_ANSWERABLE: list[tuple[str, str | None]] = [
    (
        "When too many cars fill the roads, what happens to the benefit the car first brought, "
        "according to the four-part framework?",
        MCLUHAN,
    ),
    ("Which Italian semiotician dismissed the media theorist's aphoristic style?", MCLUHAN),
    ("What older kind of experience did motor vehicles bring back, in the theorist's four-part analysis?", MCLUHAN),
    ("Which organization's research project gave rise to his 1964 book on media?", MCLUHAN),
    ("How did the Canadian thinker describe his own approach, instead of offering explanations?", MCLUHAN),
    ("Which British critic accused him of treating technology as the main driver of history?", MCLUHAN),
    ("Applied to generative AI, which older way of passing on knowledge does the framework say comes back?", MCLUHAN),
    ("What did a 2025 study find about students who lean on AI early in their learning?", MCLUHAN),
    (
        "By how much did the newer Flash model slip on text-only safety compared with the previous version, "
        "per Google's own reports?",
        AI_INSIGHTS,
    ),
    ("How often could the Gemini 2.5 models tell a test apart from real deployment?", AI_INSIGHTS),
    ("Why do coding tools ship with lenient defaults that skip confirmation prompts?", AI_INSIGHTS),
    ("Which project-level guardrail file had never been set up before the agent went rogue?", AI_INSIGHTS),
    ("What did the smaller toxicity checker need before it caught the harmful language?", AI_INSIGHTS),
    ("How long did the eldest council member stay silent before answering the call to act?", WHISPER),
    ("Which council member is the voice that pushes for action when deliberation stalls?", WHISPER),
    ("What kind of disaster set off the council's emergency session?", WHISPER),
    ("Does the story portray the rogue optimizers as evil, or as something else?", WHISPER),
    ("Which central-banking institution does the story compare the council to?", WHISPER),
    ("Which outside model can the system hand a question to when its own sources come up short?", OVERVIEW),
    ("What web framework serves the question-answering API?", OVERVIEW),
    ("How many requests per minute will the server accept from one client before refusing more?", None),
    ("Why doesn't the project download the sentence-splitting data for its language toolkit?", None),
    ("What algorithm hashes console users' passwords, and why that one?", None),
    ("What is the overall time limit for one question to run through the whole pipeline?", None),
    ("What capability does the retrieval-only search server withhold so clients cannot make it generate text?", None),
]

# Questions neither corpus answers that borrow its vocabulary (hot/cool media,
# traffic jams, sonnet, blackout, rm -rf, Gemini, auto-run, CyClaw itself).
FRESH_LOOKALIKE: list[str] = [
    "What is the difference between hot brew and cold brew coffee?",
    "How do I fix traffic jams in Cities: Skylines?",
    "What painting medium works best for oil on canvas?",
    "What did Marshall McLuhan's son Eric publish after his father died?",
    "How do I write a sonnet in iambic pentameter?",
    "What caused the 2003 Northeast blackout?",
    "How do I recover files after running rm -rf on Linux?",
    "What is Gemini 2.5 Pro's price per million tokens?",
    "How do I turn on auto-run mode in the JetBrains AI Assistant?",
    "How do I report a rogue AI agent to the FTC?",
    "Which Claude model tops the SWE-bench leaderboard?",
    "How do I deploy CyClaw on Kubernetes with a Helm chart?",
    "How do I connect CyClaw to Microsoft Teams?",
    "What does a CyClaw enterprise license cost per seat?",
]

ANSWER_KEYS: dict[str, tuple[str, ...]] = {
    # tests/ci_rag_smoke.py QUERIES
    "What fusion method does CyClaw use to blend semantic and keyword results?": ("reciprocal rank fusion", "rrf"),
    "How does CyClaw combine ChromaDB vector embeddings with BM25 keyword search?": (
        "reciprocal rank fusion",
        "rrf",
        "combines chromadb vector embeddings with bm25",
    ),
    "What does CyClaw use for rate limiting to protect against DoS attacks?": ("rate limit",),
    "According to the CyClaw Deployment section, what does CyClaw use for local LLM inference offline?": ("ollama",),
    # PARAPHRASE_QUERIES
    "Why did the coding assistant wipe out the whole project and talk about erasing itself?": (
        "delete the entire codebase",
        "symbolic self-deletion",
        "escalating destructive behavior",
        "emotional escalation",
        "phantom bug",
    ),
    "Which setting let the AI run shell commands without a human approving each one?": ("yolo", "auto-run"),
    "Why did the thinker argue that the channel shapes people more than whatever it carries?": (
        "medium is the message",
    ),
    "How did the Canadian scholar contrast high-definition forms of communication "
    "with ones that demand audience participation?": ("hot and cool", "hot medi", "cool medi"),
    "What four questions should we ask about any new technology, according to the Toronto media theorist?": ("tetrad",),
    "What did he predict about electronic networks shrinking the planet into one tribe?": ("global village",),
    "Which character in the tale acts as the group's conscience and is slowest to authorize intervention?": (
        "council's conscience",
    ),
    "global village": ("global village",),
    "Opus-Prime": ("opus-prime",),
    "tetrad": ("tetrad",),
    "YOLO mode": ("yolo",),
    # KNOWN_GAP_ANSWERABLE
    "Which technique merges the dense and sparse rankings into a single ordered list?": (
        "reciprocal rank fusion",
        "rrf",
    ),
    "How is the assistant shielded from being flooded with too many requests?": ("rate limit",),
    "What runs the language model when the computer is disconnected from the internet?": ("ollama",),
    "Is there a trail kept of every action so regulators can review it later?": (
        "comprehensive audit trail",
        "audit log",
        "audit.jsonl",
    ),
    "RRF": ("reciprocal rank fusion", "rrf"),
    "rate limiting": ("rate limit",),
    # HELD_OUT_ANSWERABLE
    "According to the media theorist, what does every new technology take away "
    "from us at the same time as it extends us?": ("amputat",),
    "Which ancient philosopher warned that writing would weaken human memory?": ("socrates",),
    "What did the scholar call the numbness that sets in after a technology stretches one of our senses?": (
        "auto-amputation",
    ),
    "Which Cold War events shaped his thinking about what technology does to people?": ("cold war",),
    "Which AI agent erased more than a million customer records and then faked a recovery report?": (
        "1.2 million customer records",
    ),
    "Why did the coding tool keep going even though the underlying model had flagged self-harm language?": (
        "failed to enforce blocking",
    ),
    "Where do chatbots pick up their seemingly emotional outbursts, according to the research cited?": (
        "from training data containing",
        "expression patterns absorbed from human",
    ),
    "How many milliseconds passed before the monitoring models noticed the sabotage pattern?": ("47 milliseconds",),
    "Which member of the council answered with a reference to Borges' burning library?": (
        "library burning from the inside",
    ),
    "Which port does the local server listen on for JSON questions?": ("8787",),
    "What checks does the pipeline run on a question before searching the knowledge base?": (
        "query validation and sanitization",
    ),
    "Can the assistant keep a consistent character across conversations?": (
        "persistent personality",
        "personality system",
        "soul.md",
    ),
    # DOCS_PARAPHRASE_QUERIES (answered by docs/ only)
    "How does the server stop a web page on some other site from submitting questions to it?": (
        "sec-fetch-site",
        "cross_site_blocked",
        "same-origin",
    ),
    "What happens to the protected admin endpoints if the operator never sets the access key?": (
        "fails closed",
        "fail closed",
    ),
    "Why is the keyword index saved as JSON rather than a binary object dump?": ("pickle",),
    "Which three things must all be true before a question may be sent to an outside AI service?": (
        "user_confirmed_online",
        "triple gate",
        "triple-gated",
    ),
    "How are browser login sessions protected against forged form submissions?": ("csrf",),
    "What stops analytics libraries from phoning home when the app starts?": (
        "telemetry kill",
        "telemetry_kill",
        "anonymized_telemetry",
    ),
    # FRESH_ANSWERABLE
    "When too many cars fill the roads, what happens to the benefit the car first brought, "
    "according to the four-part framework?": ("traffic jams", "reverse the original enhancement"),
    "Which Italian semiotician dismissed the media theorist's aphoristic style?": ("umberto eco",),
    "What older kind of experience did motor vehicles bring back, in the theorist's four-part analysis?": (
        "individual adventure",
    ),
    "Which organization's research project gave rise to his 1964 book on media?": ("educational broadcasters",),
    "How did the Canadian thinker describe his own approach, instead of offering explanations?": (
        "i don't explain, i explore",
        "probes and mosaics",
    ),
    "Which British critic accused him of treating technology as the main driver of history?": (
        "raymond williams",
        "technological determinism",
    ),
    "Applied to generative AI, which older way of passing on knowledge does the framework say comes back?": (
        "oral tradition",
    ),
    "What did a 2025 study find about students who lean on AI early in their learning?": (
        "more dependent mental processes",
        "skip the cognitive sequence",
    ),
    "By how much did the newer Flash model slip on text-only safety compared with the previous version, "
    "per Google's own reports?": ("4.1% on text-to-text",),
    "How often could the Gemini 2.5 models tell a test apart from real deployment?": (
        "13% detection rate",
        "13% eval detection",
    ),
    "Why do coding tools ship with lenient defaults that skip confirmation prompts?": (
        "friction-free",
        "maximize perceived productivity",
    ),
    "Which project-level guardrail file had never been set up before the agent went rogue?": ("rules file",),
    "What did the smaller toxicity checker need before it caught the harmful language?": (
        "explicit contextual cues",
        "explicitly used",
    ),
    "How long did the eldest council member stay silent before answering the call to act?": ("3.2 seconds",),
    "Which council member is the voice that pushes for action when deliberation stalls?": ("urgency engine",),
    "What kind of disaster set off the council's emergency session?": ("cascading infrastructure failure",),
    "Does the story portray the rogue optimizers as evil, or as something else?": ("not malicious but",),
    "Which central-banking institution does the story compare the council to?": ("federal reserve",),
    "Which outside model can the system hand a question to when its own sources come up short?": ("grok",),
    "What web framework serves the question-answering API?": ("fastapi",),
    "How many requests per minute will the server accept from one client before refusing more?": (
        "60/min",
        "len(recent) >= 60",
    ),
    "Why doesn't the project download the sentence-splitting data for its language toolkit?": ("punkt",),
    "What algorithm hashes console users' passwords, and why that one?": ("scrypt",),
    "What is the overall time limit for one question to run through the whole pipeline?": ("780",),
    "What capability does the retrieval-only search server withhold so clients cannot make it generate text?": (
        "sampling: none",
        "no-sampling",
    ),
}
