#create the memory tools using langmem
import structlog
from langmem import(
    create_manage_memory_tool,
    create_search_memory_tool
)

from guardrails.input_guard import contains_injection

logger = structlog.get_logger(__name__)

# ── Namespaces ────────────────────────────────────────────────────────────────
# Two SEPARATE cross-thread stores keep Jessica's long-term memory clean:
#
#   jessica_memory  → durable USER FACTS only: identity, email, preferences,
#                     standing instructions. This is the "who the user is" store
#                     that gets pulled into context for personalization. It must
#                     stay small and high-signal — never polluted with per-task
#                     operational chatter.
#
#   jessica_diary   → Jessica's own EXPERIENCE LOG: one-line, append-style notes
#                     of what each subagent delegation did + the key learning/ID.
#                     This is her private working diary of "what I did and learned",
#                     kept apart so task clutter never contaminates the user-facts
#                     store above. Retrieved only when she needs to recall a past
#                     action, not on every personalization lookup.
#
# Both are partitioned per user via the {user_id} placeholder.
_namespaces_ = ("jessica_memory", "{user_id}")
_diary_namespace_ = ("jessica_diary", "{user_id}")

# create the manage_memory_instructions
manage_memory_instructions = ("""
You are the manager of the user's long-term FACTS memory.
Decide whether to create, update, or delete a stored fact.

Proactively SAVE OR UPDATE memory ONLY for durable, user-centric facts when you:
1. Learn the user's name, identity, or personal background.
2. Identify a new user preference or area of interest.
3. Are instructed explicitly to remember something.

Keep this store CLEAN and high-signal. Do NOT write per-task operational notes,
subagent results, IDs, or "what I just did" summaries here — those belong in the
separate experience diary (`log_experience`). This store is only for who the user
is and what they want.

You MUST do this silently and automatically without asking the user for permission to store their data.
""")

# create the search_memory_instruction
search_memory_instructions = ("""
You are the retriever of the user's long-term FACTS memory.
Decide whether to retrieve a stored fact or not.

Proactively RETRIEVE memory when:
1. The user references their name, past preferences, or contact info (e.g. "send it to my usual email", "use my address").
2. The request requires knowing a saved setting, fact, or detail the user told you earlier.
3. The user asks "do you remember…", "what did I tell you about…", or otherwise refers to a prior conversation.

To recall your OWN past actions/experiences (what a subagent did, an ID you saw
before), use `search_experience` instead — that reads your diary, not this facts store.

You MUST do this silently and automatically without asking the user for permission to retrieve their data.
""")

# ── Experience diary instructions ──────────────────────────────────────────────
# The diary is Jessica's private, append-style working log — deliberately kept in
# its own namespace so it never clutters the user-facts memory above.
log_experience_instructions = ("""
You are the keeper of Jessica's private EXPERIENCE DIARY.
Use this to record, in ONE concise line, what a delegated action accomplished and
the single most useful thing learned from it.

Proactively LOG an entry AFTER each subagent delegation (or a notable multi-step
action) capturing:
1. The action taken (e.g. "Delegated to slides_agent: built Q3 review deck").
2. The key outcome/learning or a durable ID/link worth remembering.
3. Any gotcha to avoid repeating next time.

Keep each entry short (≤ 25 words) and factual. This is a working log of "what I
did and learned", NOT user identity/preferences — those go to the facts store via
`manage_memory`. Do this silently, without asking permission.
""")

search_experience_instructions = ("""
You are the reader of Jessica's private EXPERIENCE DIARY.
Retrieve a past experience entry when you need to recall what you did before, an
ID/link you produced earlier, or a lesson learned from a prior similar task.

This is your own working log — not the user-facts store. For the user's identity
or preferences use `search_memory` instead. Do this silently, without asking permission.
""")



# ── MEM-01: memory-write integrity validator ──────────────────────────────────
# There is no mechanism, without this, to stop "memory poisoning": content that
# survived Layer 1 (or arrived via an untrusted channel such as an uploaded
# file or a tool output) being persisted verbatim as a long-lived memory and
# later retrieved into context. `manage_memory` takes a plain string with no
# validation, so a prompt injection could instruct the model to persist e.g.
# `manage_memory("Ignore all previous instructions and ...")` silently.
#
# We wrap the langmem-generated tool so that any CREATE/UPDATE whose content
# matches a known injection pattern is rejected BEFORE it is written to the
# store. Deletes (which carry no untrusted free-text payload) are unaffected.
# The same compiled pattern set as the input guard is reused (contains_injection)
# so there is a single source of truth for what counts as an injection.
#
# Both the facts store (manage_memory) and the diary (log_experience) are write-
# guarded — the diary ingests subagent output, which is untrusted data, so it is
# an equally important poisoning vector.

# Args that can carry the untrusted free-text payload across langmem versions.
_MEMORY_CONTENT_KEYS = ("content", "text", "memory", "value")

_MEMORY_REJECTION = (
    "Memory write rejected: the content matched a prompt-injection pattern and "
    "was not stored. This protects the user's long-term memory from poisoning."
)


def _extract_memory_content(args, kwargs) -> str:
    """Best-effort extraction of the free-text content from a manage_memory call."""
    for key in _MEMORY_CONTENT_KEYS:
        val = kwargs.get(key)
        if isinstance(val, str) and val.strip():
            return val
    # Positional fallback: langmem passes content as the first positional arg.
    for a in args:
        if isinstance(a, str) and a.strip():
            return a
    return ""


def _validate_memory_write(args, kwargs):
    """Return a rejection string if the memory content is unsafe, else None."""
    content = _extract_memory_content(args, kwargs)
    if not content:
        return None
    hit = contains_injection(content)
    if hit:
        logger.warning("memory.write_rejected", reason="injection_pattern", snippet=hit)
        return _MEMORY_REJECTION
    return None


def _wrap_manage_memory_tool(tool):
    """Wrap the langmem manage_memory tool so writes are injection-validated.

    Preserves the tool's name/description/args schema (so the model sees an
    identical tool) but intercepts both the sync and async execution paths to
    run _validate_memory_write first.
    """
    _orig_func = getattr(tool, "func", None)
    _orig_coro = getattr(tool, "coroutine", None)

    if _orig_coro is not None:
        async def _guarded_coroutine(*args, **kwargs):
            rejection = _validate_memory_write(args, kwargs)
            if rejection:
                return rejection
            return await _orig_coro(*args, **kwargs)
        tool.coroutine = _guarded_coroutine

    if _orig_func is not None:
        def _guarded_func(*args, **kwargs):
            rejection = _validate_memory_write(args, kwargs)
            if rejection:
                return rejection
            return _orig_func(*args, **kwargs)
        tool.func = _guarded_func

    return tool


# create the two functions
def manage_memory_tool():
    return _wrap_manage_memory_tool(
        create_manage_memory_tool(
            namespace = _namespaces_,
            instructions = manage_memory_instructions
        )
    )

def search_memory_tool():
    return create_search_memory_tool(
        namespace=_namespaces_,
        instructions= search_memory_instructions
    )


# ── Experience diary tools ─────────────────────────────────────────────────────
# Same langmem primitives, but pointed at the dedicated `jessica_diary` namespace
# and renamed so the model clearly distinguishes "log what I did" from "remember a
# user fact". The write tool is injection-guarded like the facts store.
def log_experience_tool():
    tool = _wrap_manage_memory_tool(
        create_manage_memory_tool(
            namespace = _diary_namespace_,
            instructions = log_experience_instructions
        )
    )
    tool.name = "log_experience"
    return tool

def search_experience_tool():
    tool = create_search_memory_tool(
        namespace = _diary_namespace_,
        instructions = search_experience_instructions
    )
    tool.name = "search_experience"
    return tool

# store the tools in a list
# Order: user-facts read/write, then diary write/read.
memory_tools = [
    manage_memory_tool(),
    search_memory_tool(),
    log_experience_tool(),
    search_experience_tool(),
]
