"""Grimm claim: judge with the Finanzplan (BT-Drs. 21/601) among the hits — snippet only, then
with Extract passages from it."""
import json
import asyncio
from backend.services.fast_fact_checker import FastFactChecker
from backend.services.search import tavily_search, tavily_extract

run0 = json.loads(open("/work/grimm.jsonl").readline())
CLAIM = run0["reformulated"]
HEADER = ("Kontext der Sendung: Bundeshaushalt, Staatsfinanzen und Finanzplanung bis 2029\nSendedatum: —\n"
          f"Sprecher: Veronika Grimm\nBehauptung: {CLAIM}")
URL = "https://dserver.bundestag.de/btd/21/006/2100601.pdf"


async def main():
    c = FastFactChecker()
    found = (await tavily_search("Finanzplan des Bundes 2025 bis 2029", search_depth="basic")).get("results", [])
    doc = [h for h in found if "2100601" in (h.get("url") or "")]
    hits = doc + run0["hits"]
    print("Ausschnitt 21/601:", doc[0]["content"][:400] if doc else "—")
    v1 = await c._judge(HEADER, hits)
    print("\nMIT DOKUMENT (Ausschnitt):", v1["consistency"], "|", v1["evidence"])
    extra = await tavily_extract([URL], query=CLAIM)
    print("\nEXTRACT aus 21/601:", (extra.get(URL) or "—")[:1500])
    v2 = await c._judge(HEADER, hits, extra)
    print("\nMIT LESE-SCHRITT:", v2["consistency"], "|", v2["evidence"])
    extra2 = await tavily_extract([URL], query="Sozialausgaben Zinsausgaben Verteidigung 2029 Gesamtausgaben Mrd. €")
    print("\nEXTRACT (Suchbegriffe statt Behauptung):", (extra2.get(URL) or "—")[:1500])
    v3 = await c._judge(HEADER, hits, extra2)
    print("\nMIT LESE-SCHRITT (Suchbegriffe):", v3["consistency"], "|", v3["evidence"])

asyncio.run(main())
