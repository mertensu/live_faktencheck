"""
Zentrale Konfiguration für Sendungsdetails und Sprecher

Jede spezifische Sendung (Episode) bekommt einen eigenen Eintrag.
Format: "show-name-date" oder "show-name-description"
Beispiel: "maischberger-2025-09-19" oder "maischberger-connemann-droege"
"""

# Sendungsdetails - Jede Episode ist ein eigener Eintrag
SHOW_CONFIG = {
    # Test
    "test": {
        "name": "Test",
        "description": "Test-Umgebung für Fact-Checks",
        "info": "Test Sendung - Sprecher A interviewt Sprecher B",
        "reference_links": [],  # Optional: URLs to reference documents (laws, press releases, etc.)
        "speakers": [
            "Sprecher A",
            "Sprecher B",
            "Autor"  # For article mode
        ],
        "show": "test",  # Zu welcher Show gehört diese Episode
        "episode_name": "Test Episode"
    },

    "bericht-aus-berlin-reiche-2026-03-01": {
        "name": "Bericht aus Berlin",
        "description": "Sendung vom 1.März 2026",
        "info": "Bericht aus Berlin: Matthias Deiß interviewt Katherina Reiche, Bundeswirtschaftsministerin (CDU). Sendung vom 1. März 2026",
        "speakers": [
            "Matthias Deiß",
            "Katherina Reiche"
        ],
        "reference_links": [
            "https://www.zdfheute.de/wirtschaft/heizungsgesetz-schwarz-rote-koalition-mieter-eigentuemer-waermeplanung-100.html"
        ],
        "show": " bericht-aus-berlin",
        "episode_name": "Interview mit Katherina Reiche"
    },

    # Maischberger Episoden
    "maischberger-2025-09-19": {
        "name": "Maischberger",
        "description": "Sendung vom 19. September 2025",
        "info": "Sandra Maischberger interviewt Gitta Connemann (CDU) und Katharina Dröge (B90/Grüne). Sendung vom 19.September 2025",
        "speakers": [
            "Sandra Maischberger",
            "Gitta Connemann",
            "Katharina Dröge"
        ],
        "show": "maischberger",
        "episode_name": "19. September 2025 - Gitta Connemann & Katharina Dröge"
    },

    # Maischberger Episoden
    "maischberger-2025-09-30": {
        "name": "Maischberger",
        "description": "Sendung vom 30. September 2025",
        "info": "Sandra Maischberger interviewt Philipp Amthor (CDU) und Ines Schwerdtner (Linke). Sendung vom 30.September 2025",
        "speakers": [
            "Sandra Maischberger",
            "Philipp Amthor",
            "Ines Schwerdtner"
        ],
        "show": "maischberger",
        "episode_name": "30. September 2025 - Philipp Amthor & Ines Schwerdtner"
    },

    "maischberger-2026-01-28": {
        "name": "Maischberger",
        "description": "Sendung vom 28. Januar 2026",
        "info": "Sandra Maischberger interviewt Gregor Gysi (Linke) und Philipp Amthor (CDU). Sendung vom 28.Januar 2026",
        "speakers": [
            "Sandra Maischberger",
            "Gregor Gysi",
            "Philipp Amthor"
        ],
        "show": "maischberger",
        "episode_name": "28. Januar 2026 - Gregor Gysi & Philipp Amthor"
    },

    # Miosga Episoden
    "miosga-2025-10": {
        "name": "Miosga",
        "description": "Sendung vom Oktober 2025",
        "info": "Caren Miosga interviewt Heidi Reichinnek (Linke). Sendung vom Oktober 2025",
        "speakers": [
            "Caren Miosga",
            "Heidi Reichinnek"
        ],
        "show": "miosga",
        "episode_name": "Oktober 2025 - Heidi Reichinnek"
    },

   
    # Markus Lanz Episoden
    "lanz-2026-02-06": {
        "name": "Markus Lanz",
        "description": "Sendung vom 6. Februar 2026",
        "info": "Markus Lanz diskutiert mit seinen Gästen über Regierung, Haushalt und Investitionen. Gäste: Veronika Grimm (Wirtschaftswissenschaftlerin, Mitglied im Sachverständigenrat), Dirk Wiese (SPD-Politiker, MdB), Wiebke Winter (CDU-Politikerin) und Daniel Friedrich Sturm (Journalist). Grimm warnt, dass der Bundeshaushalt 2029 durch Zinsrückzahlungen, Soziales und Verteidigung ausgeschöpft sei. Wiese bekräftigt, dass Reformen folgen werden. Sendung vom 6. Februar 2026.",
        "speakers": [
            "Markus Lanz",
            "Veronika Grimm",
            "Dirk Wiese",
            "Wiebke Winter",
            "Daniel Friedrich Sturm"
        ],
        "show": "lanz",
        "episode_name": "6. Februar 2026 - Grimm, Wiese, Winter & Sturm"
    },

    # Pinar Atalay Episoden
    "atalay-2026-02-09": {
        "name": "Pinar Atalay",
        "description": "Sendung vom 9. Februar 2026",
        "info": "Pinar Atalay diskutiert mit Heidi Reichinnek (Die Linke) und Philipp Amthor (CDU) über Wachstum vs. Umverteilung, Social-Media-Regeln und den Umgang mit der AfD.",
        "speakers": [
            "Pinar Atalay",
            "Heidi Reichinnek",
            "Philipp Amthor"
        ],
        "show": "atalay",
        "episode_name": "9. Februar 2026 - Heidi Reichinnek & Philipp Amthor",
        "publish": True
    },

    # Unter den Linden Episoden
    "unter-den-linden-2026-02-23": {
        "name": "Unter den Linden",
        "description": "Sendung vom 23. Februar 2026",
        "info": "Moderatorin Michaela Kolster diskutiert mit Andreas Audretsch (B'90/Grüne, stv. Vorsitzender Bundestagsfraktion) und Philipp Amthor (CDU, Parlamentarischer Staatssekretär beim Bundesminister für Digitales und Staatsmodernisierung). Thema: Der Staat ist überfordert – Bröckelnde Brücken, eine marode Bahn und langsame Digitalisierung – unsere Infrastruktur funktioniert vielerorts nicht. Gleichzeitig klafft im Bundeshaushalt bis 2029 eine Lücke von über 170 Milliarden Euro. Die SPD fordert Steuererhöhungen für Topverdienende. Die Union hingegen warnt vor einer Überlastung der Wirtschaft und fordert Steuersenkungen für Unternehmen und Bürger:innen für mehr Wachstum. Die Debatte um das Bürgergeld, Rente, Krankenversicherung und massive Investitionen in die Verteidigung. Sind wir diesen Herausforderungen gewachsen? Wie viel Staat kann sich Deutschland noch leisten?",
        "speakers": [
            "Michaela Kolster",
            "Andreas Audretsch",
            "Philipp Amthor"
        ],
        "show": "unter-den-linden",
        "episode_name": "23. Februar 2026 - Andreas Audretsch & Philipp Amthor"
    },

    "youtube-rieck-2026-01-17": {
        "name": "youtube",
        "description": "Sendung vom 17. Januar 2026",
        "info": "Video von Christian Rieck vom 17. Januar 2026. Er berichtet über die Erbschaftsteuerreform der SPD dargelegt im Konzeptpapier: https://spd-landesgruppe-ost.de/wp-content/uploads/2026/01/FairErben-Konzept-zur-Reform-der-Erbschaftsteuer-2.pdf",
        "speakers": [
            "Christian Rieck"
        ],
        "show": "youtube",
        "type": "youtube",
        "episode_name": "17. Januar 2026 - Christian Rieck"
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

def get_show_config(episode_key=None):
    """Gibt die Konfiguration für eine Episode zurück"""
    if episode_key is None:
        episode_key = DEFAULT_SHOW
    return SHOW_CONFIG.get(episode_key, SHOW_CONFIG[DEFAULT_SHOW])

def get_speakers(episode_key=None):
    """Gibt die Sprecher für eine Episode zurück"""
    config = get_show_config(episode_key)
    return config.get("speakers", [])

def get_info(episode_key=None):
    """Gibt die Kontext-Information für eine Episode zurück (Datum, Quelle, Teilnehmer etc.)"""
    config = get_show_config(episode_key)
    return config.get("info", "")

def get_reference_links(episode_key=None):
    """Gibt die optionalen Referenz-Links für eine Episode zurück (Gesetzentwürfe, Pressemitteilungen etc.)"""
    config = get_show_config(episode_key)
    return config.get("reference_links", [])

def get_all_shows():
    """Gibt alle verfügbaren Shows zurück (z.B. ['maischberger', 'miosga', 'test'])"""
    shows = set()
    for episode_key, config in SHOW_CONFIG.items():
        show = config.get("show", episode_key.split("-")[0])
        shows.add(show)
    return sorted(shows)

def get_episodes_for_show(show_key):
    """Gibt alle Episoden für eine Show zurück"""
    episodes = []
    for episode_key, config in SHOW_CONFIG.items():
        if config.get("show") == show_key:
            episodes.append({
                "key": episode_key,
                "name": config.get("episode_name", config.get("description", episode_key)),
                "description": config.get("description", ""),
                "show_name": config.get("name", show_key),
            })
    return sorted(episodes, key=lambda x: x["key"], reverse=True)

def get_all_episodes():
    """Gibt alle verfügbaren Episoden zurück"""
    return list(SHOW_CONFIG.keys())
