import pytest

from backend.app.routes.intake import cleanup_expired_sessions


class FakeRepository:
    async def expire_sessions(self, limit):
        assert limit == 100
        return ["session-id/file-a.pdf", "session-id/file-b.png"]


class FakeStorage:
    def __init__(self):
        self.deleted = []

    def delete_private_file(self, path):
        self.deleted.append(path)


@pytest.mark.asyncio
async def test_cleanup_deletes_only_paths_returned_by_expiry_pass():
    storage = FakeStorage()

    await cleanup_expired_sessions(FakeRepository(), storage)

    assert storage.deleted == ["session-id/file-a.pdf", "session-id/file-b.png"]
