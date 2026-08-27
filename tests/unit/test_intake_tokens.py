from backend.app.intake.tokens import hash_session_token, new_session_token, verify_session_token


def test_session_token_is_random_and_only_hash_is_compared():
    first = new_session_token()
    second = new_session_token()

    assert first.raw != second.raw
    assert len(first.digest) == 64
    assert first.digest == hash_session_token(first.raw)
    assert verify_session_token(first.raw, first.digest)
    assert not verify_session_token(second.raw, first.digest)
