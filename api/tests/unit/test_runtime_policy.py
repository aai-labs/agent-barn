from api.domains.agents.runtime_policy import build_chat_commands_policy_md

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
