import logging
import asyncio
import http
import json
import pickle

from functools import partial

from edb import errors
from edb.server.protocol import protocol
from edb.server.dbview import dbview


log = logging.getLogger(__name__)


class WasmRpcError(Exception):
    def __init__(self, info):
        super().__init__("Wasm request error")
        self.__dict__.update(info)


def handle_error(
    request: protocol.HttpRequest,
    response: protocol.HttpResponse,
    error: Exception,
):
    er_type = type(error)
    if not issubclass(er_type, errors.EdgeDBError):
        er_type = errors.InternalServerError

    # TODO(tailhook) figure out whether we want to expose error message here
    # for arbitrary errors
    response.body = json.dumps({
        'kind': 'error',
        'error': {
            'message': str(error),
            'type': er_type.__name__,
        }
    }).encode()
    response.content_type = b'application/json'
    response.status = http.HTTPStatus.INTERNAL_SERVER_ERROR
    response.close_connection = True


async def rpc_request(
    server,  # : server.Server,  # circular import
    request: str,
    params: dict,
) -> dict:
    req_data = pickle.dumps(dict(
        request=request,
        params=params,
    ), protocol=5)

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    transport, protocol = await loop.create_unix_connection(
        partial(asyncio.StreamReaderProtocol, reader),
        server.wasm_socket_path(),
    )
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    writer.write(req_data)
    writer.write_eof()
    resp_data = pickle.loads(await reader.read())
    match resp_data["response"]:
        case "success":
            return resp_data
        case "failure":
            log.error("Wasm request failed: %s", resp_data["error"])
            raise WasmRpcError(resp_data)


async def proxy_request(
    request: protocol.HttpRequest,
    response: protocol.HttpResponse,
    server  # : server.Server,  # circular import
) -> None:
    try:
        resp_data = await rpc_request(server, "http",
            dict(
                method=bytes(request.method),
                url=request.uri,
                headers=request.headers,
                body=request.body,
            )
        )
    except Exception as e:
        if not isinstance(e, WasmRpcError):
            log.exception("Error handing wasm RPC", exc_info=e)
        response.status = http.HTTPStatus.INTERNAL_SERVER_ERROR
        response.content_type = b"text/plain"
        response.body = b"500 Internal Server Error"
    else:
        response.status = http.HTTPStatus(resp_data['status'])
        headers = resp_data['headers']
        response.content_type = headers.pop('content-type', None)
        response.custom_headers = headers
        response.body = resp_data['body']


async def handle_request(
    request: protocol.HttpRequest,
    response: protocol.HttpResponse,
    db: dbview.Database,
    args: list[str],
    server  # : server.Server,  # circular import
) -> None:
    try:
        await proxy_request(request, response, server)
    except Exception as e:
        log.exception("Exception during wasm request: %s", e)
        # TODO(tailhook) figure out what we want to expose to users
        handle_error(request, response, e)