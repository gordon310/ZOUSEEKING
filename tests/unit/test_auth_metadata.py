from backend.app.auth_metadata import audience_from_user_metadata


def test_signup_metadata_audience_is_allowlisted():
    assert audience_from_user_metadata({"audience": "b"}) == "b"
    assert audience_from_user_metadata({"audience": "invalid"}) == "c"
    assert audience_from_user_metadata({}) == "c"
