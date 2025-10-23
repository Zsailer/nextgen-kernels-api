# Configuring WebSocket Message Filtering

The `KernelClientWebsocketConnection` class supports configurable message filtering via Jupyter Server's configuration system. This allows you to control which kernel messages are sent to WebSocket clients.

## Configuration Traits

### `msg_types`

List of `(msg_type, channel)` tuples to include. Only messages matching these pairs will be sent to the websocket.

- **Type**: List of tuples
- **Default**: `None` (all messages)
- **Config**: `c.KernelClientWebsocketConnection.msg_types`

### `exclude_msg_types`

List of `(msg_type, channel)` tuples to exclude. Messages matching these pairs will NOT be sent to the websocket.

- **Type**: List of tuples
- **Default**: `None` (no exclusions)
- **Config**: `c.KernelClientWebsocketConnection.exclude_msg_types`

**Note**: Cannot be used together with `msg_types`. If both are specified, `msg_types` takes precedence.

## Configuration Examples

### Example 1: Listen to only execution-related messages

Create a `jupyter_server_config.py` file:

```python
# Only send execution-related messages to websockets
c.KernelClientWebsocketConnection.msg_types = [
    ("execute_input", "iopub"),
    ("execute_result", "iopub"),
    ("execute_reply", "shell"),
    ("stream", "iopub"),
    ("error", "iopub"),
]
```

### Example 2: Exclude status messages

```python
# Send all messages except status messages on iopub
c.KernelClientWebsocketConnection.exclude_msg_types = [
    ("status", "iopub"),
]
```

### Example 3: Listen to only iopub messages

```python
# Only send messages from the iopub channel
c.KernelClientWebsocketConnection.msg_types = [
    ("status", "iopub"),
    ("stream", "iopub"),
    ("display_data", "iopub"),
    ("execute_input", "iopub"),
    ("execute_result", "iopub"),
    ("error", "iopub"),
    ("clear_output", "iopub"),
]
```

### Example 4: Production environment - minimal messages

```python
# For production, only send essential output messages
c.KernelClientWebsocketConnection.msg_types = [
    ("stream", "iopub"),           # stdout/stderr
    ("display_data", "iopub"),     # rich outputs
    ("execute_result", "iopub"),   # execution results
    ("error", "iopub"),            # errors
    ("execute_reply", "shell"),    # execution completion
]
```

## Using Command-Line Configuration

You can also configure filtering via command-line when starting Jupyter Server:

```bash
# Exclude status messages
jupyter server \
  --KernelClientWebsocketConnection.exclude_msg_types="[('status', 'iopub')]"

# Only send execution results
jupyter server \
  --KernelClientWebsocketConnection.msg_types="[('execute_result', 'iopub'), ('stream', 'iopub')]"
```

## Environment Variables

Set via environment variable (use JSON format):

```bash
export JUPYTER_KERNEL_CLIENT_WEBSOCKET_CONNECTION_MSG_TYPES='[["stream", "iopub"], ["error", "iopub"]]'
jupyter server
```

## Configuration File Locations

Jupyter Server looks for configuration files in these locations (in order):

1. Current directory: `./jupyter_server_config.py`
2. User config directory: `~/.jupyter/jupyter_server_config.py`
3. System config directory: `/etc/jupyter/jupyter_server_config.py`

## Default Behavior

If neither `msg_types` nor `exclude_msg_types` is configured (both are `None`), all kernel messages are sent to the websocket. This maintains backward compatibility with existing setups.

## Use Cases

### Development vs Production

**Development** (default - all messages):
```python
# No configuration needed - all messages are sent
```

**Production** (minimal messages for performance):
```python
c.KernelClientWebsocketConnection.msg_types = [
    ("stream", "iopub"),
    ("display_data", "iopub"),
    ("execute_result", "iopub"),
    ("error", "iopub"),
]
```

### Debugging

**Exclude noisy messages during debugging**:
```python
c.KernelClientWebsocketConnection.exclude_msg_types = [
    ("status", "iopub"),  # Frequent status updates
]
```

### Custom Frontends

**Frontend only needs outputs, not execution metadata**:
```python
c.KernelClientWebsocketConnection.msg_types = [
    ("stream", "iopub"),
    ("display_data", "iopub"),
    ("execute_result", "iopub"),
    ("error", "iopub"),
]
```

## Common Message Type Reference

See [message_filtering.md](message_filtering.md#common-message-types) for a complete list of message types by channel.

## Troubleshooting

### Messages not appearing in frontend

Check if your `msg_types` filter includes all necessary message types. For example, to see cell outputs, you need:
- `("stream", "iopub")` for stdout/stderr
- `("display_data", "iopub")` for rich outputs
- `("execute_result", "iopub")` for return values
- `("error", "iopub")` for errors

### Configuration not taking effect

1. Verify config file location is correct
2. Check for typos in trait names
3. Ensure tuples are formatted correctly: `[("msg_type", "channel")]`
4. Restart Jupyter Server after configuration changes
5. Check server logs for configuration errors
