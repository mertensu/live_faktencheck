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
        "guests": "Test Sendung - Sprecher A interviewt Sprecher B",
        "speakers": [
            "Sprecher A",
            "Sprecher B"
        ],
        "show": "test",  # Zu welcher Show gehört diese Episode
        "episode_name": "Test Episode"
    },
    
    # Maischberger Episoden
    "maischberger-2025-09-19": {
        "name": "Maischberger",
        "description": "Sendung vom 19. September 2025",
        "guests": "Sandra Maischberger interviewt Gitta Connemann und Katharina Dröge. Sendung vom 19.September 2025",
        "speakers": [
            "Sandra Maischberger",
            "Gitta Connemann",
            "Katharina Dröge"
        ],
        "show": "maischberger",
        "episode_name": "19. September 2025 - Gitta Connemann & Katharina Dröge"
    },
    # Weitere Maischberger Episoden können hier hinzugefügt werden:
    # "maischberger-2025-10-15": {
    #     "name": "Maischberger",
    #     "description": "Sendung vom 15. Oktober 2025",
    #     "guests": "...",
    #     "speakers": [...],
    #     "show": "maischberger",
    #     "episode_name": "15. Oktober 2025 - ..."
    # },
    
    # Miosga Episoden
    "miosga-2025-10": {
        "name": "Miosga",
        "description": "Sendung vom Oktober 2025",
        "guests": "Caren Miosga interviewt Heidi Reichinnek. Sendung vom Oktober 2025",
        "speakers": [
            "Caren Miosga",
            "Heidi Reichinnek"
        ],
        "show": "miosga",
        "episode_name": "Oktober 2025 - Heidi Reichinnek"
    },
    # Weitere Miosga Episoden können hier hinzugefügt werden
}

# Standard-Sendung (für listener.py wenn keine spezifische Sendung gewählt wird)
# Wird verwendet wenn weder Kommandozeilen-Parameter noch Umgebungsvariable gesetzt sind
DEFAULT_SHOW = "test"  # Sollte mit der Route im Frontend übereinstimmen

def get_show_config(episode_key=None):
    """Gibt die Konfiguration für eine Episode zurück"""
    if episode_key is None:
        episode_key = DEFAULT_SHOW
    return SHOW_CONFIG.get(episode_key, SHOW_CONFIG[DEFAULT_SHOW])

def get_speakers(episode_key=None):
    """Gibt die Sprecher für eine Episode zurück"""
    config = get_show_config(episode_key)
    return config.get("speakers", [])

def get_guests(episode_key=None):
    """Gibt die Gäste-Beschreibung für eine Episode zurück"""
    config = get_show_config(episode_key)
    return config.get("guests", "")

def get_all_shows():
    """Gibt alle verfügbaren Shows zurück (z.B. ['maischberger', 'miosga', 'test'])"""
    shows = set()
    for episode_key, config in SHOW_CONFIG.items():
        show = config.get("show", episode_key.split("-")[0])  # Fallback: erster Teil des Keys
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
    # Sortiere nach Key (normalerweise chronologisch wenn Datum im Key)
    return sorted(episodes, key=lambda x: x["key"], reverse=True)  # Neueste zuerst

def get_all_episodes():
    """Gibt alle verfügbaren Episoden zurück"""
    return list(SHOW_CONFIG.keys())

