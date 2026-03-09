"""
Zentrale Konfiguration für Sendungsdetails und Sprecher

Jede spezifische Sendung (Episode) bekommt einen eigenen Eintrag.
Format: "show-name-date" oder "show-name-description"
Beispiel: "maischberger-2025-09-19"

Felder pro Episode:
  show            - Show-Schlüssel (muss in SHOWS enthalten sein)
  date            - Sendedatum (z.B. "19. September 2025")
  guests          - Gäste im Format "Name (Rolle/Partei)", Moderator zuerst
  context         - Optionaler Themen-Hintergrund für LLM
  reference_links - Optionale Referenz-URLs (Gesetzentwürfe, Pressemitteilungen etc.)
  publish         - True = in Produktion sichtbar (Standard: False)
  type            - "show" oder "youtube" (Standard: "show")
"""

import re

# Anzeigename je Show-Schlüssel
SHOWS = {
    "maischberger": "Maischberger",
    "lanz": "Markus Lanz",
    "miosga": "Miosga",
    "unter-den-linden": "Unter den Linden",
    "bericht-aus-berlin": "Bericht aus Berlin",
    "atalay": "Pinar Atalay",
    "youtube": "YouTube",
    "test": "Test",
}

# Sendungsdetails - Jede Episode ist ein eigener Eintrag
SHOW_CONFIG = {
    "test": {
        "show": "test",
        "date": "",
        "guests": ["Sprecher A", "Sprecher B", "Autor"],
        "reference_links": [],
        "type": "show",
    },

    "bericht-aus-berlin-reiche-2026-03-01": {
        "show": "bericht-aus-berlin",
        "date": "1. März 2026",
        "guests": [
            "Matthias Deiß (Moderator)",
            "Katherina Reiche (Bundeswirtschaftsministerin, CDU)",
        ],
        "reference_links": [
            "https://www.zdfheute.de/wirtschaft/heizungsgesetz-schwarz-rote-koalition-mieter-eigentuemer-waermeplanung-100.html"
        ],
        "type": "show",
    },

    "maischberger-2025-09-19": {
        "show": "maischberger",
        "date": "19. September 2025",
        "guests": [
            "Sandra Maischberger (Moderatorin)",
            "Gitta Connemann (CDU)",
            "Katharina Dröge (B90/Grüne)",
        ],
        "type": "show",
    },

    "maischberger-2025-09-30": {
        "show": "maischberger",
        "date": "30. September 2025",
        "guests": [
            "Sandra Maischberger (Moderatorin)",
            "Philipp Amthor (CDU)",
            "Ines Schwerdtner (Linke)",
        ],
        "type": "show",
    },

    "maischberger-2026-01-28": {
        "show": "maischberger",
        "date": "28. Januar 2026",
        "guests": [
            "Sandra Maischberger (Moderatorin)",
            "Gregor Gysi (Linke)",
            "Philipp Amthor (CDU)",
        ],
        "type": "show",
    },

    "miosga-2025-10": {
        "show": "miosga",
        "date": "Oktober 2025",
        "guests": [
            "Caren Miosga (Moderatorin)",
            "Heidi Reichinnek (Linke)",
        ],
        "type": "show",
    },

    "lanz-2026-02-06": {
        "show": "lanz",
        "date": "6. Februar 2026",
        "guests": [
            "Markus Lanz (Moderator)",
            "Veronika Grimm (Wirtschaftswissenschaftlerin, Mitglied im Sachverständigenrat)",
            "Dirk Wiese (SPD-Politiker, MdB)",
            "Wiebke Winter (CDU-Politikerin)",
            "Daniel Friedrich Sturm (Journalist)",
        ],
        "context": "Grimm warnt, dass der Bundeshaushalt 2029 durch Zinsrückzahlungen, Soziales und Verteidigung ausgeschöpft sei. Wiese bekräftigt, dass Reformen folgen werden.",
        "type": "show",
    },

    "atalay-2026-02-09": {
        "show": "atalay",
        "date": "9. Februar 2026",
        "guests": [
            "Pinar Atalay (Moderatorin)",
            "Heidi Reichinnek (Die Linke)",
            "Philipp Amthor (CDU)",
        ],
        "context": "Thema: Wachstum vs. Umverteilung, Social-Media-Regeln und Umgang mit der AfD.",
        "publish": True,
        "type": "show",
    },

    "unter-den-linden-2026-02-23": {
        "show": "unter-den-linden",
        "date": "23. Februar 2026",
        "guests": [
            "Michaela Kolster (Moderatorin)",
            "Andreas Audretsch (B90/Grüne, stv. Vorsitzender Bundestagsfraktion)",
            "Philipp Amthor (CDU, Parlamentarischer Staatssekretär beim Bundesminister für Digitales und Staatsmodernisierung)",
        ],
        "context": "Der Staat ist überfordert – Bröckelnde Brücken, eine marode Bahn und langsame Digitalisierung. Im Bundeshaushalt bis 2029 klafft eine Lücke von über 170 Milliarden Euro. SPD fordert Steuererhöhungen für Topverdienende, Union warnt vor Überlastung der Wirtschaft.",
        "type": "show",
    },

    "youtube-rieck-2026-01-17": {
        "show": "youtube",
        "date": "17. Januar 2026",
        "guests": [
            "Christian Rieck",
        ],
        "context": "Video über die Erbschaftsteuerreform der SPD, dargelegt im SPD-Konzeptpapier.",
        "reference_links": [
            "https://spd-landesgruppe-ost.de/wp-content/uploads/2026/01/FairErben-Konzept-zur-Reform-der-Erbschaftsteuer-2.pdf"
        ],
        "type": "youtube",
    },
}

# Allow start_dev.sh to override the "test" entry with a real episode's config.
# Written by start_dev.sh when called with a real episode key; ignored otherwise.
import json as _json  # noqa: E402
import os as _os  # noqa: E402
_override_path = _os.path.join(_os.path.dirname(__file__), ".test_override.json")
if _os.path.exists(_override_path):
    with open(_override_path) as _f:
        SHOW_CONFIG["test"] = _json.load(_f)

# Standard-Sendung (für listener.py wenn keine spezifische Sendung gewählt wird)
DEFAULT_SHOW = "test"


# --- Helpers ---

def _guest_name(guest: str) -> str:
    """Extract name from 'Name (Role)' format."""
    return re.sub(r'\s*\([^)]*\)\s*$', '', guest).strip()

def _is_moderator(guest: str) -> bool:
    return bool(re.search(r'\(Moderator', guest, re.IGNORECASE))


# --- Public API ---

def get_show_name(show_key: str) -> str:
    """Returns the display name for a show key."""
    return SHOWS.get(show_key, show_key.replace('-', ' ').capitalize())

def get_show_config(episode_key=None):
    """Gibt die Konfiguration für eine Episode zurück"""
    if episode_key is None:
        episode_key = DEFAULT_SHOW
    return SHOW_CONFIG.get(episode_key, SHOW_CONFIG[DEFAULT_SHOW])

def get_speakers(episode_key=None) -> list:
    """Gibt die Sprecher-Namen für eine Episode zurück (ohne Rollen-Klammern)"""
    config = get_show_config(episode_key)
    return [_guest_name(g) for g in config.get("guests", [])]

def get_info(episode_key=None) -> str:
    """Gibt den LLM-Kontext für eine Episode zurück (Name, Gäste, Datum, Thema)"""
    config = get_show_config(episode_key)
    show_key = config.get("show", episode_key or DEFAULT_SHOW)
    show_name = get_show_name(show_key)
    date = config.get("date", "")
    guests = config.get("guests", [])
    context = config.get("context", "")

    parts = []
    if guests:
        parts.append(f"{show_name}: {', '.join(guests)}.")
    else:
        parts.append(f"{show_name}.")
    if date:
        parts.append(f"Sendung vom {date}.")
    if context:
        parts.append(context)

    return " ".join(parts)

def get_episode_name(episode_key=None) -> str:
    """Gibt den Anzeigenamen einer Episode zurück (Datum + Gäste ohne Moderator)"""
    config = get_show_config(episode_key)
    date = config.get("date", "")
    guests = config.get("guests", [])
    non_mod_names = [_guest_name(g) for g in guests if not _is_moderator(g)]

    if date and non_mod_names:
        return f"{date} - {' & '.join(non_mod_names)}"
    if date:
        return date
    return episode_key or DEFAULT_SHOW

def get_reference_links(episode_key=None) -> list:
    """Gibt die optionalen Referenz-Links für eine Episode zurück"""
    config = get_show_config(episode_key)
    return config.get("reference_links", [])

def get_all_shows() -> list:
    """Gibt alle Show-Schlüssel zurück, die in SHOW_CONFIG vorkommen"""
    shows = set()
    for config in SHOW_CONFIG.values():
        show_key = config.get("show")
        if show_key:
            shows.add(show_key)
    return sorted(shows)

def get_episodes_for_show(show_key: str) -> list:
    """Gibt alle Episoden für eine Show zurück"""
    episodes = []
    for episode_key, config in SHOW_CONFIG.items():
        if config.get("show") == show_key:
            episodes.append({
                "key": episode_key,
                "name": get_episode_name(episode_key),
                "description": f"Sendung vom {config['date']}" if config.get("date") else "",
                "show_name": get_show_name(show_key),
            })
    return sorted(episodes, key=lambda x: x["key"], reverse=True)

def get_all_episodes() -> list:
    """Gibt alle verfügbaren Episode-Schlüssel zurück"""
    return list(SHOW_CONFIG.keys())
