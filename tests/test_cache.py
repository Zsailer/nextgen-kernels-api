"""Unit tests for KernelMessageCache.

Tests the message caching functionality including:
- Adding and retrieving messages by msg_id and cell_id
- LRU eviction when cache is full
- Message validation and error handling
"""
import json
import pytest

from nextgen_kernels_api.services.kernels.cache import (
    InvalidKeyException,
    KernelMessageCache,
    MissingKeyException,
)


@pytest.fixture
def cache():
    """Create a fresh KernelMessageCache instance with default maxsize for each test."""
    cache_instance = KernelMessageCache()
    yield cache_instance
    # Cleanup after test
    cache_instance.clear()


@pytest.fixture
def small_cache():
    """Create a fresh KernelMessageCache instance with small maxsize for testing eviction."""
    cache_instance = KernelMessageCache(maxsize=3)
    yield cache_instance
    # Cleanup after test
    cache_instance.clear()


def test_cache_initialization(cache):
    """Test that cache initializes with correct defaults."""
    assert len(cache) == 0
    assert cache.maxsize == 10000


def test_cache_add_message_with_msg_id(cache):
    """Test adding a message using __setitem__ with msg_id."""
    msg_data = {"msg_id": "test-123", "channel": "shell", "cell_id": "cell-1"}
    cache["test-123"] = msg_data

    assert "test-123" in cache
    assert len(cache) == 1
    assert cache["test-123"] == msg_data


def test_cache_add_message_using_add_method(cache):
    """Test adding a message using the add() method."""
    msg_data = {"msg_id": "test-456", "channel": "iopub", "cell_id": "cell-2"}
    cache.add(msg_data)

    assert "test-456" in cache
    assert cache["test-456"] == msg_data


def test_cache_get_by_msg_id(cache):
    """Test retrieving a message by msg_id using get()."""
    msg_data = {"msg_id": "test-789", "channel": "shell", "cell_id": "cell-3"}
    cache.add(msg_data)

    result = cache.get(msg_id="test-789")
    assert result == msg_data


def test_cache_get_by_cell_id(cache):
    """Test retrieving a message by cell_id using get()."""
    msg_data = {"msg_id": "test-abc", "channel": "shell", "cell_id": "cell-4"}
    cache.add(msg_data)

    result = cache.get(cell_id="cell-4")
    assert result == msg_data
    assert result["msg_id"] == "test-abc"


def test_cache_get_nonexistent_returns_none(cache):
    """Test that get() returns None for nonexistent keys."""
    assert cache.get(msg_id="nonexistent") is None
    assert cache.get(cell_id="nonexistent") is None


def test_cache_contains(cache):
    """Test the __contains__ method for membership checking."""
    msg_data = {"msg_id": "test-def", "channel": "shell", "cell_id": "cell-5"}
    cache.add(msg_data)

    assert "test-def" in cache
    assert "nonexistent" not in cache


def test_cache_delitem(cache):
    """Test removing a message using __delitem__."""
    msg_data = {"msg_id": "test-ghi", "channel": "shell", "cell_id": "cell-6"}
    cache.add(msg_data)

    assert "test-ghi" in cache
    del cache["test-ghi"]
    assert "test-ghi" not in cache
    assert cache.get(cell_id="cell-6") is None


def test_cache_remove_by_msg_id(cache):
    """Test removing a message by msg_id using remove()."""
    msg_data = {"msg_id": "test-jkl", "channel": "shell", "cell_id": "cell-7"}
    cache.add(msg_data)

    cache.remove(msg_id="test-jkl")
    assert "test-jkl" not in cache
    assert cache.get(cell_id="cell-7") is None


def test_cache_remove_by_cell_id(cache):
    """Test removing a message by cell_id using remove()."""
    msg_data = {"msg_id": "test-mno", "channel": "shell", "cell_id": "cell-8"}
    cache.add(msg_data)

    cache.remove(cell_id="cell-8")
    assert "test-mno" not in cache
    assert cache.get(cell_id="cell-8") is None


def test_cache_pop_by_msg_id(cache):
    """Test popping a message by msg_id."""
    msg_data = {"msg_id": "test-pqr", "channel": "shell", "cell_id": "cell-9"}
    cache.add(msg_data)

    result = cache.pop(msg_id="test-pqr")
    assert result == msg_data
    assert "test-pqr" not in cache


def test_cache_pop_by_cell_id(cache):
    """Test popping a message by cell_id."""
    msg_data = {"msg_id": "test-stu", "channel": "shell", "cell_id": "cell-10"}
    cache.add(msg_data)

    result = cache.pop(cell_id="cell-10")
    assert result == msg_data
    assert "test-stu" not in cache


def test_cache_pop_nonexistent_raises_keyerror(cache):
    """Test that pop() raises KeyError for nonexistent keys."""
    with pytest.raises(KeyError):
        cache.pop(msg_id="nonexistent")


def test_cache_clear(cache):
    """Test clearing all messages from cache."""
    cache.add({"msg_id": "test-1", "channel": "shell", "cell_id": "cell-1"})
    cache.add({"msg_id": "test-2", "channel": "shell", "cell_id": "cell-2"})
    cache.add({"msg_id": "test-3", "channel": "shell", "cell_id": "cell-3"})

    assert len(cache) == 3
    cache.clear()
    assert len(cache) == 0


def test_cache_iter(cache):
    """Test iterating over message IDs in the cache."""
    cache.add({"msg_id": "test-1", "channel": "shell", "cell_id": "cell-1"})
    cache.add({"msg_id": "test-2", "channel": "shell", "cell_id": "cell-2"})
    cache.add({"msg_id": "test-3", "channel": "shell", "cell_id": "cell-3"})

    msg_ids = list(cache)
    assert len(msg_ids) == 3
    assert "test-1" in msg_ids
    assert "test-2" in msg_ids
    assert "test-3" in msg_ids


def test_cache_missing_msg_id_raises_exception(cache):
    """Test that adding a message without msg_id raises KeyError."""
    msg_data = {"channel": "shell", "cell_id": "cell-1"}

    # The add() method tries to access data['msg_id'] directly, causing KeyError
    with pytest.raises(KeyError):
        cache.add(msg_data)


def test_cache_setitem_missing_msg_id_raises_exception(cache):
    """Test that __setitem__ with missing msg_id raises MissingKeyException."""
    msg_data = {"channel": "shell", "cell_id": "cell-1"}

    with pytest.raises(MissingKeyException, match="`msg_id` missing in message data"):
        cache["test-key"] = msg_data


def test_cache_missing_channel_raises_exception(cache):
    """Test that adding a message without channel raises MissingKeyException."""
    msg_data = {"msg_id": "test-123", "cell_id": "cell-1"}

    with pytest.raises(MissingKeyException, match="`channel` missing in message data"):
        cache.add(msg_data)


def test_cache_mismatched_key_raises_exception(cache):
    """Test that adding a message with mismatched key raises InvalidKeyException."""
    msg_data = {"msg_id": "test-456", "channel": "shell", "cell_id": "cell-1"}

    with pytest.raises(InvalidKeyException, match="Key must match `msg_id` in value"):
        cache["wrong-key"] = msg_data


def test_cache_lru_eviction(small_cache):
    """Test that LRU eviction removes oldest message when cache is full."""
    # Add 3 messages to fill the cache (maxsize=3)
    small_cache.add({"msg_id": "test-1", "channel": "shell", "cell_id": "cell-1"})
    small_cache.add({"msg_id": "test-2", "channel": "shell", "cell_id": "cell-2"})
    small_cache.add({"msg_id": "test-3", "channel": "shell", "cell_id": "cell-3"})

    assert len(small_cache) == 3
    assert "test-1" in small_cache

    # Add a 4th message, which should evict "test-1" (oldest)
    small_cache.add({"msg_id": "test-4", "channel": "shell", "cell_id": "cell-4"})

    assert len(small_cache) == 3
    assert "test-1" not in small_cache
    assert "test-2" in small_cache
    assert "test-3" in small_cache
    assert "test-4" in small_cache


def test_cache_lru_access_updates_order(small_cache):
    """Test that accessing a message updates its position in LRU order."""
    # Add 3 messages
    small_cache.add({"msg_id": "test-1", "channel": "shell", "cell_id": "cell-1"})
    small_cache.add({"msg_id": "test-2", "channel": "shell", "cell_id": "cell-2"})
    small_cache.add({"msg_id": "test-3", "channel": "shell", "cell_id": "cell-3"})

    # Access test-1, moving it to end (most recently used)
    _ = small_cache["test-1"]

    # Add a 4th message, which should evict "test-2" (now the oldest)
    small_cache.add({"msg_id": "test-4", "channel": "shell", "cell_id": "cell-4"})

    assert "test-1" in small_cache  # Still in cache (was accessed)
    assert "test-2" not in small_cache  # Evicted
    assert "test-3" in small_cache
    assert "test-4" in small_cache


def test_cache_cell_id_replacement(cache):
    """Test that adding a new message with same cell_id replaces the old one."""
    # Add first message with cell_id
    cache.add({"msg_id": "test-1", "channel": "shell", "cell_id": "cell-1"})
    assert "test-1" in cache

    # Add second message with same cell_id
    cache.add({"msg_id": "test-2", "channel": "shell", "cell_id": "cell-1"})

    # First message should be removed, second should be present
    assert "test-1" not in cache
    assert "test-2" in cache
    assert cache.get(cell_id="cell-1")["msg_id"] == "test-2"


def test_cache_messages_without_cell_id(cache):
    """Test that messages without cell_id are stored correctly."""
    # Add message without cell_id
    msg_data = {"msg_id": "test-1", "channel": "control", "cell_id": None}
    cache.add(msg_data)

    assert "test-1" in cache
    assert cache["test-1"] == msg_data


def test_cache_different_channels(cache):
    """Test caching messages from different channels."""
    cache.add({"msg_id": "shell-1", "channel": "shell", "cell_id": "cell-1"})
    cache.add({"msg_id": "iopub-1", "channel": "iopub", "cell_id": "cell-2"})
    cache.add({"msg_id": "stdin-1", "channel": "stdin", "cell_id": None})
    cache.add({"msg_id": "control-1", "channel": "control", "cell_id": None})

    assert len(cache) == 4
    assert cache["shell-1"]["channel"] == "shell"
    assert cache["iopub-1"]["channel"] == "iopub"
    assert cache["stdin-1"]["channel"] == "stdin"
    assert cache["control-1"]["channel"] == "control"


def test_cache_repr(cache):
    """Test that __repr__ returns valid JSON."""
    cache.add({"msg_id": "test-1", "channel": "shell", "cell_id": "cell-1"})
    cache.add({"msg_id": "test-2", "channel": "shell", "cell_id": "cell-2"})

    repr_str = repr(cache)
    # Should be valid JSON
    parsed = json.loads(repr_str)
    assert isinstance(parsed, dict)
    assert "test-1" in parsed
    assert "test-2" in parsed
