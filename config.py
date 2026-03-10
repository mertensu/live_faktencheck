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
from dataclasses import dataclass, field

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


def _guest_name(guest: str) -> str:
    """Extract name from 'Name (Role)' format."""
    return re.sub(r'\s*\([^)]*\)\s*$', '', guest).strip()

def _is_moderator(guest: str) -> bool:
    return bool(re.search(r'\(Moderator', guest, re.IGNORECASE))


@dataclass
class Episode:
    key: str
    show: str
    date: str
    guests: list[str]
    context: str = ""
    reference_links: list[str] = field(default_factory=list)
    type: str = "show"
    publish: bool = False

    @property
    def speakers(self) -> list[str]:
        """Guest names without role annotations."""
        return [_guest_name(g) for g in self.guests]

    @property
    def episode_name(self) -> str:
        """e.g. '28. Januar 2026 - Gysi & Amthor'"""
        non_mod_names = [_guest_name(g) for g in self.guests if not _is_moderator(g)]
        if self.date and non_mod_names:
            return f"{self.date} - {' & '.join(non_mod_names)}"
        if self.date:
            return self.date
        return self.key

    @property
    def info(self) -> str:
        """Formatted LLM context string."""
        show_name = SHOWS.get(self.show, self.show.replace('-', ' ').capitalize())
        parts = []
        if self.guests:
            parts.append(f"{show_name}: {', '.join(self.guests)}.")
        else:
            parts.append(f"{show_name}.")
        if self.date:
            parts.append(f"Sendung vom {self.date}.")
        if self.context:
            parts.append(self.context)
        return " ".join(parts)


# Sendungsdetails - Jede Episode ist ein eigener Eintrag
EPISODES: dict[str, Episode] = {
    "bericht-aus-berlin-reiche-2026-03-01": Episode(
        key="bericht-aus-berlin-reiche-2026-03-01",
        show="bericht-aus-berlin",
        date="1. März 2026",
        guests=[
            "Matthias Deiß (Moderator)",
            "Katherina Reiche (Bundeswirtschaftsministerin, CDU)",
        ],
        reference_links=[
            "https://www.zdfheute.de/wirtschaft/heizungsgesetz-schwarz-rote-koalition-mieter-eigentuemer-waermeplanung-100.html"
        ],
    ),

    "maischberger-2025-09-19": Episode(
        key="maischberger-2025-09-19",
        show="maischberger",
        date="19. September 2025",
        guests=[
            "Sandra Maischberger (Moderatorin)",
            "Gitta Connemann (CDU)",
            "Katharina Dröge (B90/Grüne)",
        ],
    ),

    "maischberger-2025-09-30": Episode(
        key="maischberger-2025-09-30",
        show="maischberger",
        date="30. September 2025",
        guests=[
            "Sandra Maischberger (Moderatorin)",
            "Philipp Amthor (CDU)",
            "Ines Schwerdtner (Linke)",
        ],
    ),

    "maischberger-2026-01-28": Episode(
        key="maischberger-2026-01-28",
        show="maischberger",
        date="28. Januar 2026",
        guests=[
            "Sandra Maischberger (Moderatorin)",
            "Gregor Gysi (Linke)",
            "Philipp Amthor (CDU)",
        ],
    ),

    "miosga-2025-10": Episode(
        key="miosga-2025-10",
        show="miosga",
        date="Oktober 2025",
        guests=[
            "Caren Miosga (Moderatorin)",
            "Heidi Reichinnek (Linke)",
        ],
    ),

    "lanz-2026-02-06": Episode(
        key="lanz-2026-02-06",
        show="lanz",
        date="6. Februar 2026",
        guests=[
            "Markus Lanz (Moderator)",
            "Veronika Grimm (Wirtschaftswissenschaftlerin, Mitglied im Sachverständigenrat)",
            "Dirk Wiese (SPD-Politiker, MdB)",
            "Wiebke Winter (CDU-Politikerin)",
            "Daniel Friedrich Sturm (Journalist)",
        ],
        context="Grimm warnt, dass der Bundeshaushalt 2029 durch Zinsrückzahlungen, Soziales und Verteidigung ausgeschöpft sei. Wiese bekräftigt, dass Reformen folgen werden.",
    ),

    "atalay-2026-02-09": Episode(
        key="atalay-2026-02-09",
        show="atalay",
        date="9. Februar 2026",
        guests=[
            "Pinar Atalay (Moderatorin)",
            "Heidi Reichinnek (Die Linke)",
            "Philipp Amthor (CDU)",
        ],
        context="Thema: Wachstum vs. Umverteilung, Social-Media-Regeln und Umgang mit der AfD.",
        publish=True,
    ),

    "unter-den-linden-2026-02-23": Episode(
        key="unter-den-linden-2026-02-23",
        show="unter-den-linden",
        date="23. Februar 2026",
        guests=[
            "Michaela Kolster (Moderatorin)",
            "Andreas Audretsch (B90/Grüne, stv. Vorsitzender Bundestagsfraktion)",
            "Philipp Amthor (CDU, Parlamentarischer Staatssekretär beim Bundesminister für Digitales und Staatsmodernisierung)",
        ],
        context="Der Staat ist überfordert – Bröckelnde Brücken, eine marode Bahn und langsame Digitalisierung. Im Bundeshaushalt bis 2029 klafft eine Lücke von über 170 Milliarden Euro. SPD fordert Steuererhöhungen für Topverdienende, Union warnt vor Überlastung der Wirtschaft.",
    ),

    "youtube-rieck-2026-01-17": Episode(
        key="youtube-rieck-2026-01-17",
        show="youtube",
        date="17. Januar 2026",
        guests=[
            "Christian Rieck",
        ],
        context="Video über die Erbschaftsteuerreform der SPD, dargelegt im SPD-Konzeptpapier.",
        reference_links=[
            "https://spd-landesgruppe-ost.de/wp-content/uploads/2026/01/FairErben-Konzept-zur-Reform-der-Erbschaftsteuer-2.pdf"
        ],
        type="youtube",
    ),
}


# --- Module-level helpers ---

def get_show_name(show_key: str) -> str:
    """Returns the display name for a show key."""
    return SHOWS.get(show_key, show_key.replace('-', ' ').capitalize())

def get_episodes_for_show(show_key: str) -> list[dict]:
    """Returns all episodes for a show as dicts."""
    episodes = [
        {
            "key": ep.key,
            "name": ep.episode_name,
            "description": f"Sendung vom {ep.date}" if ep.date else "",
            "show_name": get_show_name(show_key),
        }
        for ep in EPISODES.values()
        if ep.show == show_key
    ]
    return sorted(episodes, key=lambda x: x["key"], reverse=True)
