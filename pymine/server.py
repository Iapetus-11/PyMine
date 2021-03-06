import asyncio
import aiohttp
import random
import socket
import struct
import sys
import os

sys.path.append(os.getcwd())

import pymine.api as pymine_api

from pymine.types.buffer import Buffer
from pymine.types.stream import Stream

from pymine.data.packet_map import PACKET_MAP
from pymine.data.states import STATES

from pymine.util.logging import task_exception_handler
from pymine.util.encryption import gen_rsa_keys
from pymine.util.share import share, logger

share["rsa"]["private"], share["rsa"]["public"] = gen_rsa_keys()
states = share["states"]
logger.debug_ = share["conf"]["debug"]


async def close_con(stream):  # Close a connection to a client
    await stream.drain()

    stream.close()
    await stream.wait_closed()

    try:
        del states[stream.remote]
    except BaseException:
        pass

    logger.debug(f"Disconnected nicely from {stream.remote[0]}:{stream.remote[1]}.")
    return False, stream


share["close_con"] = close_con


# Handle / respond to packets, this is a loop
async def handle_packet(stream: Stream):
    packet_length = 0

    # Basically an implementation of Buffer.unpack_varint()
    # except designed to read directly from a a StreamReader
    # and also to handle legacy server list ping packets
    for i in range(5):
        try:
            read = await asyncio.wait_for(stream.read(1), 5)
        except asyncio.TimeoutError:
            logger.debug("Closing due to timeout on read...")
            return False, stream

        if read == b"":
            logger.debug("Closing due to invalid read....")
            return False, stream

        if i == 0 and read == b"\xFE":
            logger.warn("Legacy ping attempted, legacy ping is not supported.")
            return False, stream

        b = struct.unpack("B", read)[0]
        packet_length |= (b & 0x7F) << 7 * i

        if not b & 0x80:
            break

    if packet_length & (1 << 31):
        packet_length -= 1 << 32

    buf = Buffer(await stream.read(packet_length))

    state = STATES.encode(states.get(stream.remote, 0))
    packet = buf.unpack_packet(state, PACKET_MAP)

    logger.debug(f"IN : state:{state:<11} | id:0x{packet.id:02X} | packet:{type(packet).__name__}")

    for handler in pymine_api.packet.PACKET_HANDLERS[state][packet.id]:
        resp_value = await handler(stream, packet)

        try:
            continue_, stream = resp_value
        except (
            ValueError,
            TypeError,
        ):
            logger.warn(f"Invalid return from packet handler: {handler.__module__}.{handler.__qualname__}")
            continue

        if not continue_:
            return False, stream

    return continue_, stream


async def handle_con(reader, writer):  # Handle a connection from a client
    stream = Stream(reader, writer)
    logger.debug(f"Connection received from {stream.remote[0]}:{stream.remote[1]}.")

    continue_ = True

    while continue_:
        try:
            continue_, stream = await handle_packet(stream)
        except BaseException as e:
            logger.error(logger.f_traceback(e))
            break

    await close_con(stream)


async def start():  # Actually start the server
    addr = share["conf"]["server_ip"]
    port = share["conf"]["server_port"]

    if addr is None:
        addr = socket.gethostbyname(socket.gethostname())

    server = share["server"] = await asyncio.start_server(handle_con, host=addr, port=port)
    share["ses"] = aiohttp.ClientSession()

    await pymine_api.init()

    try:
        async with server:
            if random.randint(0, 999) == 1:  # shhhhh
                logger.info(f"PPMine 69.420 started on port {addr}:{port}!")
            else:
                logger.info(f'PyMine {float(share["server_version"])} started on {addr}:{port}!')

            for handler in pymine_api.server.SERVER_READY_HANDLERS:
                asyncio.create_task(handler())

            await server.serve_forever()
    except (
        asyncio.CancelledError,
        KeyboardInterrupt,
    ):
        pass


async def stop():  # Stop the server properly
    logger.info("Closing server...")

    share["server"].close()

    # wait for the server to be closed, stop the api, and stop the aiohttp.ClientSession
    await asyncio.gather(share["server"].wait_closed(), pymine_api.stop(), share["ses"].close())

    logger.info("Server closed.")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(task_exception_handler)

    try:
        loop.run_until_complete(start())
    except BaseException as e:
        logger.critical(logger.f_traceback(e))

    try:
        loop.run_until_complete(stop())
    except BaseException as e:
        logger.critical(logger.f_traceback(e))

    loop.stop()
    loop.close()
