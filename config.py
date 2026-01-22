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
        "speakers": [
            "Sprecher A",
            "Sprecher B",
            "Autor"  # For article mode
        ],
        "show": "test",  # Zu welcher Show gehört diese Episode
        "episode_name": "Test Episode"
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

   
    "youtube-rieck-2026-01-17": {
        "name": "youtube",
        "description": "Sendung vom 17. Januar 2026",
        "info": "Youtube-Video von Christian Rieck vom 17. Januar 2026. Er berichtet über die Erbschaftsteuerreform der SPD dargelegt im Konzeptpapier: https://spd-landesgruppe-ost.de/wp-content/uploads/2026/01/FairErben-Konzept-zur-Reform-der-Erbschaftsteuer-2.pdf",
        "speakers": [
            "Christian Rieck"
        ],
        "show": "youtube",
        "episode_name": "17. Januar 2026 - Christian Rieck"
    },


}

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

def get_all_shows():
    """Gibt alle verfügbaren Shows zurück (z.B. ['maischberger', 'miosga', 'test'])"""
    shows = set()
    for episode_key, config in SHOW_CONFIG.items():
        show = config.get("show", episode_key.split("-")[0])
        shows.add(show)
    return sorted(list(shows))

def get_episodes_for_show(show_key):
    """Gibt alle Episoden für eine Show zurück"""
    episodes = []
    for episode_key, config in SHOW_CONFIG.items():
        if config.get("show") == show_key:
            episodes.append({
                "key": episode_key,
                "name": config.get("episode_name", config.get("description", episode_key)),
                "description": config.get("description", ""),
                "config": config
            })
    return sorted(episodes, key=lambda x: x["key"], reverse=True)

def get_all_episodes():
    """Gibt alle verfügbaren Episoden zurück"""
    return list(SHOW_CONFIG.keys())
