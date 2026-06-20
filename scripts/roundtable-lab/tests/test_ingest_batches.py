from __future__ import annotations

import asyncio
import time
import unittest

from roundtable_lab.ingest import embed_in_batches


class FakeClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        await asyncio.sleep(0.05)
        return [[float(len(text))] for text in texts]


class IngestBatchTests(unittest.TestCase):
    def test_embed_in_batches_preserves_order_while_running_batches_concurrently(self) -> None:
        async def run() -> tuple[list[list[float]], float]:
            started = time.perf_counter()
            result = await embed_in_batches(FakeClient(), ["a", "bb", "ccc", "dddd"], 1)
            return result, time.perf_counter() - started

        result, elapsed = asyncio.run(run())

        self.assertEqual(result, [[1.0], [2.0], [3.0], [4.0]])
        self.assertLess(elapsed, 0.16)


if __name__ == "__main__":
    unittest.main()
