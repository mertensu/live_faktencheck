"""Whitelisted domains for Tavily fact-checking searches."""

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
    ],
}

# Flat list for backward compatibility
TRUSTED_DOMAINS = [
    domain
    for domains in TRUSTED_DOMAINS_BY_CATEGORY.values()
    for domain in domains
]
