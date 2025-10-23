# Message Type Filtering for Kernel Client Listeners

This document describes the message type filtering feature for kernel client listeners.

## Overview

The kernel client now supports filtering messages by message type and channel when adding listeners. This allows you to create focused listeners that only receive specific types of messages, reducing unnecessary processing and improving performance.

## API

### `add_listener(callback, msg_types=None, exclude_msg_types=None)`

Add a listener to be called when messages are received.

**Parameters:**

- `callback` (Callable[[str, list[bytes]], None]): Function that takes (channel_name, msg_bytes) as arguments
- `msg_types` (Optional[List[Tuple[str, str]]]): Optional list of (msg_type, channel) tuples to include. If provided, only messages matching these filters will be sent to the listener.
- `exclude_msg_types` (Optional[List[Tuple[str, str]]]): Optional list of (msg_type, channel) tuples to exclude. If provided, messages matching these filters will NOT be sent to the listener.

**Raises:**
- `ValueError`: If both `msg_types` and `exclude_msg_types` are provided

**Notes:**
- If both `msg_types` and `exclude_msg_types` are provided, a ValueError is raised
- If neither is provided, all messages are sent (default behavior)
- Message types and channels are case-sensitive

## Usage Examples

### Example 1: Listen to only iopub status messages

```python
def my_status_listener(channel_name, msg):
    print(f"Status message received on {channel_name}")

client.add_listener(
    my_status_listener,
    msg_types=[("status", "iopub")]
)
```

### Example 2: Listen to all messages except iopub status messages

```python
def my_no_status_listener(channel_name, msg):
    print(f"Non-status message received on {channel_name}")

client.add_listener(
    my_no_status_listener,
    exclude_msg_types=[("status", "iopub")]
)
```

### Example 3: Listen to all messages (default behavior)

```python
def my_all_listener(channel_name, msg):
    print(f"Message received on {channel_name}")

client.add_listener(my_all_listener)
```

### Example 4: Listen to multiple specific message types

```python
def my_multi_listener(channel_name, msg):
    print(f"Specific message received on {channel_name}")

client.add_listener(
    my_multi_listener,
    msg_types=[
        ("status", "iopub"),
        ("execute_reply", "shell"),
        ("stream", "iopub"),
        ("error", "iopub")
    ]
)
```

### Example 5: Monitor only execution-related messages

```python
def execution_monitor(channel_name, msg):
    # Process execution-related messages
    pass

client.add_listener(
    execution_monitor,
    msg_types=[
        ("execute_input", "iopub"),
        ("execute_result", "iopub"),
        ("execute_reply", "shell"),
        ("error", "iopub")
    ]
)
```

## Common Message Types

Here are some commonly used message types for filtering:

### IOPub Channel
- `("status", "iopub")` - Kernel execution state (idle/busy/starting)
- `("stream", "iopub")` - stdout/stderr output
- `("display_data", "iopub")` - Rich display outputs
- `("execute_input", "iopub")` - Echo of code being executed
- `("execute_result", "iopub")` - Execution results
- `("error", "iopub")` - Exception/error information

### Shell Channel
- `("execute_reply", "shell")` - Reply to execute request
- `("kernel_info_reply", "shell")` - Kernel information
- `("complete_reply", "shell")` - Tab completion results
- `("inspect_reply", "shell")` - Object introspection results

### Stdin Channel
- `("input_request", "stdin")` - Kernel requests user input

### Control Channel
- `("shutdown_reply", "control")` - Kernel shutdown confirmation

## Implementation Details

### Internal Data Structure

Listeners are stored in a dictionary mapping callback functions to filter configurations:

```python
self._listeners = {
    callback1: {
        'msg_types': {("status", "iopub"), ("stream", "iopub")},
        'exclude_msg_types': None
    },
    callback2: {
        'msg_types': None,
        'exclude_msg_types': {("status", "iopub")}
    },
    callback3: {
        'msg_types': None,
        'exclude_msg_types': None
    }
}
```

### Filtering Logic

The `_should_route_to_listener` method determines whether a message should be routed to a listener:

1. **Inclusion filter** (`msg_types` is specified): Only messages matching the specified (msg_type, channel) tuples are routed
2. **Exclusion filter** (`exclude_msg_types` is specified): All messages EXCEPT those matching the specified tuples are routed
3. **No filter**: All messages are routed (default behavior)

### Performance

- Message type extraction happens once per message, not per listener
- Filtering uses set lookups for O(1) performance
- Only listeners that match the filter receive the message

## Migration Guide

### Before (all listeners receive all messages)

```python
def my_listener(channel_name, msg):
    # Need to manually filter messages
    header = session.unpack(msg[0])
    msg_type = header.get('msg_type')

    if msg_type == 'status' and channel_name == 'iopub':
        # Handle status message
        pass

client.add_listener(my_listener)
```

### After (filtering built-in)

```python
def my_listener(channel_name, msg):
    # No need to manually filter - only status messages arrive
    pass

client.add_listener(
    my_listener,
    msg_types=[("status", "iopub")]
)
```

## Testing

See `test_filtering_simple.py` for comprehensive tests of the filtering functionality.

To run tests:
```bash
python test_filtering_simple.py
```

## Future Enhancements

Potential future improvements:
- Wildcard support: `("*", "iopub")` to match all message types on a channel
- Pattern matching: `("execute_*", "shell")` to match execute_request, execute_reply, etc.
- Message content filtering: Filter based on message content, not just type
- Priority-based routing: Route messages to higher-priority listeners first
