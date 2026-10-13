"""Brza provjera iz terminala: radi li svaki izvor i što pronalazi.

    .venv\Scripts\python check.py "nox at10 genius 18k 2024"
"""
import asyncio
import sys
import time

from core import engine


async def main(q: str) -> None:
    t0 = time.time()
    async for src, offers, err in engine.stream(q, use_cache=False):
        status = f"GREŠKA {err}" if err else f"{len(offers):3} ponuda"
        print(f"{time.time() - t0:5.1f}s  {src.label:16} {status}")
    offers, ref = await engine.search_all(q)
    print(f"\nuobičajena cijena: {ref} €   ukupno ponuda: {len(offers)}\n")
    for o in offers[:15]:
        flag = "🔥" if o.is_deal else "  "
        print(f"{flag} {o.total:8.2f} €  {o.source_name:15} {o.condition:4}  {o.title[:60]}")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "bullpadel vertex 04"))
