from echolingua.audio.cache import tts_cache_key
from echolingua.providers.tts.base import TTSRequest


def test_cache_key_changes_with_voice() -> None:
    a = tts_cache_key("fake", TTSRequest(text="Bonjour", voice="a", language="fr"))
    b = tts_cache_key("fake", TTSRequest(text="Bonjour", voice="b", language="fr"))
    assert a != b
    assert len(a) == 64
