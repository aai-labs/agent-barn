from api.domains.agents.runtime_policy import build_chat_commands_policy_md, build_role_scope_policy_md

# --- build_chat_commands_policy_md --------------------------------------------


def test_chat_commands_policy_md_is_always_emitted():
    # Unlike the integrations block, this policy has no precondition — an agent
    # with zero integrations still greets people and still must not advertise
    # commands it neither owns nor receives.
    md = build_chat_commands_policy_md()
    assert md.strip() != ""
    assert "## Chat Commands" in md


def test_chat_commands_policy_md_forbids_advertising_commands():
    md = build_chat_commands_policy_md()
    assert "/help" in md
    # The greeting is where this actually leaks, so it must be called out.
    assert "greeting" in md.lower()


def test_chat_commands_policy_md_is_runtime_neutral():
    # The same block ships to Hermes and OpenClaw agents; naming one runtime
    # would be wrong for the other.
    md = build_chat_commands_policy_md()
    assert "Hermes" not in md
    assert "OpenClaw" not in md


def test_chat_commands_policy_md_does_not_mention_profiles():
    # Guards the "no integrations configured" contract: AGENTS.md must stay free
    # of any `--profile` mapping when no secrets are set.
    assert "--profile" not in build_chat_commands_policy_md()


# --- build_role_scope_policy_md -----------------------------------------------


def test_role_scope_policy_md_is_always_emitted():
    # Like the chat-commands block, this has no precondition — an agent can be
    # coaxed out of its lane whether or not it has any integration configured.
    md = build_role_scope_policy_md()
    assert md.strip() != ""
    assert "## Role Scope" in md


def test_role_scope_policy_md_instructs_decline_and_redirect():
    # A single-purpose agent generated ASCII art on request. The block has to say
    # what to do instead, not merely that the request is unrelated.
    md = build_role_scope_policy_md().lower()
    assert "out of scope" in md
    assert "decline" in md


def test_role_scope_policy_md_closes_the_coaxing_paths():
    # The reported bug was plain compliance, but "you can clearly do it" and
    # "just a small one" are the follow-ups that reopen it.
    md = build_role_scope_policy_md().lower()
    assert "able to" in md
    assert "persistence" in md


def test_role_scope_policy_md_names_no_specific_role():
    # The block ships to every agent and defers to whatever Role/SOUL the agent
    # was given, so a broad template (general-purpose) stays broad and a narrow
    # one stays narrow. Naming any concrete role here would break that.
    md = build_role_scope_policy_md()
    for role_word in ("Documentation", "Confluence", "Jira", "Scrum", "Code Review", "Email"):
        assert role_word not in md


def test_role_scope_policy_md_is_runtime_neutral():
    # The same block ships to Hermes and OpenClaw agents; naming one runtime
    # would be wrong for the other.
    md = build_role_scope_policy_md()
    assert "Hermes" not in md
    assert "OpenClaw" not in md


def test_role_scope_policy_md_does_not_mention_profiles():
    # Same "no integrations configured" contract the chat-commands block guards.
    assert "--profile" not in build_role_scope_policy_md()
