from echolingua.providers.selector import ProviderSelectionPolicy, ProviderSelector
from echolingua.providers.tts.fake import FakeTTSProvider


def test_priority_selection() -> None:
    slow = FakeTTSProvider(name="slow", priority=50)
    fast = FakeTTSProvider(name="fast", priority=1)
    ordered = ProviderSelector([slow, fast], ProviderSelectionPolicy(strategy="priority")).ordered()
    assert [provider.metadata.name for provider in ordered] == ["fast", "slow"]


def test_explicit_without_fallback() -> None:
    a = FakeTTSProvider(name="a", priority=1)
    b = FakeTTSProvider(name="b", priority=2)
    policy = ProviderSelectionPolicy(strategy="explicit", explicit_provider="b", allow_fallback_on_error=False)
    assert [p.metadata.name for p in ProviderSelector([a, b], policy).ordered()] == ["b"]


def test_random_selection_preserves_all_providers() -> None:
    a = FakeTTSProvider(name="a", priority=1)
    b = FakeTTSProvider(name="b", priority=2)
    ordered = ProviderSelector([a, b], ProviderSelectionPolicy(strategy="random")).ordered()
    assert sorted(provider.metadata.name for provider in ordered) == ["a", "b"]


def test_step_provider_overrides_policy() -> None:
    a = FakeTTSProvider(name="a", priority=1)
    b = FakeTTSProvider(name="b", priority=2)
    policy = ProviderSelectionPolicy(strategy="priority", allow_fallback_on_error=False)
    ordered = ProviderSelector([a, b], policy).ordered("b")
    assert [provider.metadata.name for provider in ordered] == ["b"]


def test_default_provider_promotes_primary_in_priority_mode() -> None:
    a = FakeTTSProvider(name="a", priority=1)
    b = FakeTTSProvider(name="b", priority=50)
    policy = ProviderSelectionPolicy(strategy="priority", default_provider="b", allow_fallback_on_error=True)
    ordered = ProviderSelector([a, b], policy).ordered()
    assert [provider.metadata.name for provider in ordered] == ["b", "a"]
