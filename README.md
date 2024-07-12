# A Next-generation Kernels API for Jupyter Server

A new Jupyter Server Kernel's API that attempt to solve many known issues in the current server.

- Improvements made:
    - tracks kernel lifecycle state and execution state server-side.
    - uses a single kernel client (thus, single set of ZMQ channels) to communicate with the kernel. No need to open ZMQ sockets outside of this client.
    - uses a completely native asyncio approach to poll messages from the kernel, dropping the tornado IOLoop and ZMQStream logic.
    - simplifies the websocket connection logic
        - removes all nudging logic in the websocket handler, since the kernel manager owns this now.
        - the WS handle registers itself as a listener on the kernel client
        - the websocket can connect, even if the kernel is busy. (I think) this eliminates the necessity for "pending" 

## Try it out

Not available on PyPI yet, so clone and install a dev version:
```console
pip install -e .
```
Then run JupyterLab using the config file in the root of this repo.
```
jupyter lab --config jupyter_config.py
```

The REST API is NOT enabled by default. If you want to tryout the REST API, enable the extension before starting Jupyter server:
```
jupyter server extension enable nextgen_kernels_api
```