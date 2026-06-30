"""_aiter_in_thread cooperative cancellation (offline, no LLM).

The SSE path drives a blocking token generator in a worker thread via `core._aiter_in_thread`. When
the consumer goes away (client disconnects → the async generator is closed), the worker must STOP
pulling tokens instead of draining the whole stream into a dead queue. This pins that: after the
consumer reads one item and closes, the producer observes the stop (closes the underlying generator)
and does not drain the (otherwise unbounded) source.
"""

from __future__ import annotations

import asyncio
import threading

from apps.agent import core


def test_aiter_in_thread_stops_producer_on_consumer_close():
    pulled: list[int] = []
    gen_closed = threading.Event()      # set by the source's finally → cooperative stop propagated
    release = threading.Event()         # gates the source after each yield, so we control timing

    def source():
        i = 0
        try:
            while True:                 # unbounded: a correct consumer-close must stop this
                pulled.append(i)
                yield f"tok{i}"
                i += 1
                release.wait(timeout=2)  # block until the test releases the next iteration
        finally:
            gen_closed.set()

    async def drive():
        agen = core._aiter_in_thread(lambda: source())
        first = await agen.__anext__()  # consume one token
        await agen.aclose()             # consumer disconnects → finally sets the stop flag
        release.set()                   # let the producer take its next step; it should see stop + bail
        return first

    first = asyncio.run(drive())
    assert first == "tok0"
    assert gen_closed.wait(timeout=2)   # the producer closed the source (didn't leak it running)
    assert len(pulled) <= 3             # stopped cooperatively — did NOT drain the unbounded source


def test_aiter_in_thread_yields_all_then_done():
    # the normal path still delivers every item in order and terminates
    async def drive():
        out = []
        async for x in core._aiter_in_thread(lambda: iter(["a", "b", "c"])):
            out.append(x)
        return out
    assert asyncio.run(drive()) == ["a", "b", "c"]


def test_aiter_in_thread_reraises_producer_exception():
    def boom():
        yield "a"
        raise RuntimeError("stream broke")

    async def drive():
        out = []
        async for x in core._aiter_in_thread(lambda: boom()):
            out.append(x)
        return out

    try:
        asyncio.run(drive())
        assert False, "expected the producer error to surface on the consumer"
    except RuntimeError as e:
        assert "stream broke" in str(e)
