"""Whitelisted domains for Tavily fact-checking searches."""

from urllib.parse import urlparse


TRUSTED_DOMAINS_BY_CATEGORY = {
    "Behörden & Offizielle Statistiken": [
        "destatis.de",
        "bundesnetzagentur.de",
        "umweltbundesamt.de",
        "bundesfinanzministerium.de",
        "bundesumweltministerium.de",
        "bundesgesundheitsministerium.de",
        "auswaertiges-amt.de",
        "bmvg.de",
        "bmas.de",
        "bundeswirtschaftsministerium.de",
        "bundeshaushalt.de",
        "bundesbank.de",
        "bundestag.de",
        "bdh-industrie.de",
        "publikationen-bundesregierung.de",
        "bmds.bund.de",
        "gesetze-im-internet.de",
        "arbeitsagentur.de",
        "rki.de",
        "bamf.de",
        "kba.de",
        "bundesregierung.de",
        "bmi.bund.de",
        "bmwsb.bund.de",
        "bundesrechnungshof.de",
        "bundeswahlleiterin.de",
        "bundesverfassungsgericht.de",
        "sachverstaendigenrat-wirtschaft.de",
        "bpb.de",
    ],
    "Länder: Statistische Ämter": [
        "statistikportal.de",
        "regionalstatistik.de",
        "statistik-berlin-brandenburg.de",
        "statistik-bw.de",
        "statistik.bayern.de",
        "statistik-nord.de",
        "statistik.hessen.de",
        "it.nrw",
        "statistik.niedersachsen.de",
        "statistik.rlp.de",
        "statistik.sachsen.de",
        "statistik.sachsen-anhalt.de",
        "statistik.thueringen.de",
        "laiv-mv.de",
        "statistik.saarland.de",
        "statistik.bremen.de",
        "wahlen-berlin.de",
    ],
    "Länder: Regierungen & Parlamente": [
        "berlin.de",
        "hamburg.de",
        "bayern.de",
        "baden-wuerttemberg.de",
        "land.nrw",
        "hessen.de",
        "niedersachsen.de",
        "sachsen.de",
        "sachsen-anhalt.de",
        "thueringen.de",
        "brandenburg.de",
        "regierung-mv.de",
        "rlp.de",
        "saarland.de",
        "schleswig-holstein.de",
        "bremen.de",
        "parlament-berlin.de",
        "buergerschaft-hh.de",
        "bayern.landtag.de",
        "landtag-bw.de",
        "landtag.nrw.de",
        "hessischer-landtag.de",
        "landtag-niedersachsen.de",
        "landtag.sachsen.de",
        "landtag.sachsen-anhalt.de",
        "thueringer-landtag.de",
        "landtag.brandenburg.de",
        "landtag-mv.de",
        "landtag.rlp.de",
        "landtag-saar.de",
        "landtag.ltsh.de",
        "bremische-buergerschaft.de",
    ],
    "Parteien": [
        "spd.de",
        "cdu.de",
        "csu.de",
        "fdp.de",
        "gruene.de",
        "die-linke.de",
        "afd.de",
    ],
    "Forschungsinstitute": [
        "diw.de",
        "ifo.de",
        "iwkoeln.de",
        "zew.de",
        "iab.de",
        "fraunhofer.de",
        "pik-potsdam.de",
        "wupperinst.org",
        "ewi.uni-koeln.de",
        "iwh-halle.de",
        "ifw-kiel.de",
        "rwi-essen.de",
    ],
    "Think Tanks & Stiftungen": [
        "boeckler.de",
        "swp-berlin.org",
        "agora-energiewende.de",
        "globalenergymonitor.org",
        "oeko.de",
        "steuerzahler.de",
        "portal-sozialpolitik.de",
        "oecd.org",
        "bertelsmann-stiftung.de",
    ],
    "Faktenchecks": [
        "correctiv.org",
    ],
    "EU-Quellen": [
        "ec.europa.eu",
        "ec.europa.eu/eurostat"
    ],
    "Qualitätsjournalismus": [
        "faz.net",
        "handelsblatt.com",
        "sueddeutsche.de",
        "zeit.de",
        "spiegel.de",
        "tagesschau.de",
    ],
}

# Flat list for backward compatibility
TRUSTED_DOMAINS = [
    domain
    for domains in TRUSTED_DOMAINS_BY_CATEGORY.values()
    for domain in domains
]


# Source tiers for ranking search hits (lower = more authoritative). Primary data first,
# press only as a fallback; party sites are statements, not evidence, so they come last.
# State sources get their own label below research: most claims are about the Bund, and
# ranked as "amtlich" a state ministry page beat the press on federal questions.
SOURCE_TIERS = {
    "Behörden & Offizielle Statistiken": (0, "amtlich"),
    "EU-Quellen": (0, "amtlich"),
    "Forschungsinstitute": (1, "Forschung"),
    "Think Tanks & Stiftungen": (1, "Forschung"),
    "Faktenchecks": (1, "Forschung"),
    "Länder: Statistische Ämter": (2, "Land"),
    "Länder: Regierungen & Parlamente": (2, "Land"),
    "Qualitätsjournalismus": (3, "Presse"),
    "Parteien": (4, "Partei"),
}
_UNKNOWN_TIER = (3, "Sonstige")


def source_tier(url: str) -> tuple[int, str]:
    """(rank, label) of a URL's trusted-domain category; unknown hosts rank with the press."""
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    for category, domains in TRUSTED_DOMAINS_BY_CATEGORY.items():
        for d in domains:
            d_host = d.split("/")[0]
            if host == d_host or host.endswith("." + d_host):
                return SOURCE_TIERS.get(category, _UNKNOWN_TIER)
    return _UNKNOWN_TIER
