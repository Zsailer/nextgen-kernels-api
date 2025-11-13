"""Tests for message ID encoding and decoding utilities."""

import pytest
from nextgen_kernels_api.services.kernels.message_utils import (
    parse_msg_id,
    encode_channel_in_message_dict,
    encode_cell_id_in_message,
    strip_encoding_from_message,
)
from jupyter_client.session import Session


# Test parse_msg_id function

def test_parse_msg_id_with_channel_and_cell():
    """Parse message ID with both channel and cell ID."""
    channel, cell_id, base = parse_msg_id("shell:abc123_456_0#cell-xyz")
    assert channel == "shell"
    assert cell_id == "cell-xyz"
    assert base == "abc123_456_0"


def test_parse_msg_id_with_channel_only():
    """Parse message ID with channel but no cell ID."""
    channel, cell_id, base = parse_msg_id("control:abc123_456_1")
    assert channel == "control"
    assert cell_id is None
    assert base == "abc123_456_1"


def test_parse_msg_id_with_cell_only():
    """Parse message ID with cell ID but no channel (shouldn't happen but handle gracefully)."""
    channel, cell_id, base = parse_msg_id("abc123_456_2#cell-abc")
    assert channel is None
    assert cell_id == "cell-abc"
    assert base == "abc123_456_2"


def test_parse_msg_id_legacy_format():
    """Parse legacy message ID without any encoding."""
    channel, cell_id, base = parse_msg_id("abc123_456_3")
    assert channel is None
    assert cell_id is None
    assert base == "abc123_456_3"


def test_parse_msg_id_empty_raises():
    """Parsing empty message ID should raise an error."""
    from nextgen_kernels_api.services.kernels.message_utils import InvalidMsgIdFormatError

    with pytest.raises(InvalidMsgIdFormatError):
        parse_msg_id("")


# Test encode_channel_in_message_dict function

def test_encode_channel_in_message_dict():
    """Encode channel name into message dict's header."""
    msg = {
        "header": {"msg_id": "abc123_456_0"},
        "parent_header": {},
        "metadata": {},
        "content": {}
    }

    result = encode_channel_in_message_dict(msg, "shell")
    assert result["header"]["msg_id"] == "shell:abc123_456_0"


def test_encode_channel_in_message_dict_already_encoded():
    """Don't double-encode if channel already present."""
    msg = {
        "header": {"msg_id": "shell:abc123_456_0"},
        "parent_header": {},
        "metadata": {},
        "content": {}
    }

    result = encode_channel_in_message_dict(msg, "shell")
    assert result["header"]["msg_id"] == "shell:abc123_456_0"


def test_encode_channel_in_message_dict_missing_header():
    """Handle message dict without header gracefully."""
    msg = {"content": {}}
    result = encode_channel_in_message_dict(msg, "shell")
    # Should return message unchanged
    assert result == msg


# Test encode_cell_id_in_message function

def test_encode_cell_id_in_message():
    """Encode cell ID into message header."""
    session = Session()

    # Create a message with a header
    header = {"msg_id": "abc123_456_0", "msg_type": "execute_request"}
    msg_list = [
        session.pack(header),
        session.pack({}),  # parent_header
        session.pack({}),  # metadata
        session.pack({}),  # content
    ]

    result = encode_cell_id_in_message(msg_list, "cell-xyz")

    # Unpack and verify
    result_header = session.unpack(result[0])
    assert result_header["msg_id"] == "abc123_456_0#cell-xyz"


def test_encode_cell_id_already_present():
    """Don't double-encode if cell ID already in msg_id."""
    session = Session()

    header = {"msg_id": "abc123#cell-existing", "msg_type": "execute_request"}
    msg_list = [
        session.pack(header),
        session.pack({}),
        session.pack({}),
        session.pack({}),
    ]

    result = encode_cell_id_in_message(msg_list, "cell-new")

    # Should not change since # already present
    result_header = session.unpack(result[0])
    assert result_header["msg_id"] == "abc123#cell-existing"


# Test strip_encoding_from_message function

def test_strip_encoding_from_message():
    """Strip channel and cell ID from message IDs."""
    session = Session()

    header = {"msg_id": "shell:abc123_456_0#cell-xyz", "msg_type": "status"}
    parent_header = {"msg_id": "shell:abc123_456_0#cell-xyz"}

    msg_list = [
        session.pack(header),
        session.pack(parent_header),
        session.pack({}),  # metadata
        session.pack({}),  # content
    ]

    result = strip_encoding_from_message(msg_list)

    # Verify both header and parent_header are stripped
    result_header = session.unpack(result[0])
    result_parent = session.unpack(result[1])

    assert result_header["msg_id"] == "abc123_456_0"
    assert result_parent["msg_id"] == "abc123_456_0"


def test_strip_encoding_from_message_legacy_format():
    """Stripping encoding from legacy format should work fine."""
    session = Session()

    header = {"msg_id": "abc123_456_0", "msg_type": "status"}
    parent_header = {"msg_id": "abc123_456_0"}

    msg_list = [
        session.pack(header),
        session.pack(parent_header),
        session.pack({}),
        session.pack({}),
    ]

    result = strip_encoding_from_message(msg_list)

    result_header = session.unpack(result[0])
    result_parent = session.unpack(result[1])

    # Should remain unchanged
    assert result_header["msg_id"] == "abc123_456_0"
    assert result_parent["msg_id"] == "abc123_456_0"


def test_strip_encoding_malformed_message():
    """Handle malformed messages gracefully."""
    msg_list = [b"invalid"]

    # Should return original message if decoding fails
    result = strip_encoding_from_message(msg_list)
    assert result == msg_list
