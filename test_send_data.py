#!/usr/bin/env python3
"""
Test-Script zum Senden von Beispieldaten an das Backend
Simuliert, was N8N senden würde
"""

import requests
import json
import time

BACKEND_URL = "http://localhost:5000/api/fact-checks"

# Beispieldaten
test_data = [
    {
        "sprecher": "Sandra Maischberger",
        "behauptung": "Die Arbeitslosenquote ist auf einem historischen Tiefstand.",
        "urteil": "Wahr",
        "begruendung": "Laut Statistischem Bundesamt liegt die Arbeitslosenquote aktuell bei 3,2%, was tatsächlich ein historischer Tiefstand ist.",
        "quellen": [
            "https://www.destatis.de/DE/Themen/Arbeit/Arbeitsmarkt/arbeitslose.html",
            "https://www.bundesagentur.de/statistik"
        ]
    },
    {
        "sprecher": "Gitta Connemann",
        "behauptung": "Die Steuerreform wird allen Bürgern zugutekommen.",
        "urteil": "Teilweise wahr",
        "begruendung": "Während die Steuerreform tatsächlich vielen Bürgern Steuerentlastungen bringt, profitieren insbesondere höhere Einkommen stärker. Geringverdiener sehen nur minimale Verbesserungen.",
        "quellen": [
            "https://www.bundesfinanzministerium.de/steuerreform",
            "https://www.ifo.de/steueranalyse"
        ]
    },
    {
        "sprecher": "Katharina Dröge",
        "behauptung": "Deutschland hat seine Klimaziele für 2024 erreicht.",
        "urteil": "Falsch",
        "begruendung": "Deutschland hat die selbstgesteckten Klimaziele für 2024 verfehlt. Die CO2-Emissionen lagen 5% über dem Zielwert.",
        "quellen": [
            "https://www.umweltbundesamt.de/klimaziele",
            "https://www.bmuv.de/klimaschutzbericht"
        ]
    },
    {
        "sprecher": "Sandra Maischberger",
        "behauptung": "Die Inflation liegt aktuell bei 2,5%.",
        "urteil": "Wahr",
        "begruendung": "Das Statistische Bundesamt hat für den letzten Monat eine Inflationsrate von 2,5% gemeldet.",
        "quellen": [
            "https://www.destatis.de/DE/Themen/Wirtschaft/Preise/inflation.html"
        ]
    },
    {
        "sprecher": "Gitta Connemann",
        "behauptung": "Die Digitalisierung der Verwaltung ist vollständig abgeschlossen.",
        "urteil": "Falsch",
        "begruendung": "Die Digitalisierung der Verwaltung ist noch nicht abgeschlossen. Viele Prozesse laufen noch analog, und das Onlinezugangsgesetz (OZG) ist noch nicht vollständig umgesetzt.",
        "quellen": [
            "https://www.bmi.bund.de/digitalisierung",
            "https://www.verwaltung-innovativ.de"
        ]
    }
]

def send_fact_check(data):
    """Sendet einen Fakten-Check an das Backend"""
    try:
        response = requests.post(
            BACKEND_URL,
            json=data,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 201:
            print(f"✅ Gesendet: {data['sprecher']} - {data['behauptung'][:50]}...")
            return True
        else:
            print(f"❌ Fehler {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Fehler beim Senden: {e}")
        return False

def main():
    print("🧪 Test-Script zum Senden von Beispieldaten")
    print(f"📡 Backend: {BACKEND_URL}\n")
    
    # Prüfe ob Backend erreichbar ist
    try:
        response = requests.get("http://localhost:5000/api/health")
        if response.status_code != 200:
            print("⚠️  Backend scheint nicht zu laufen. Bitte starte es mit: uv run python backend/app.py")
            return
    except Exception as e:
        print(f"⚠️  Backend nicht erreichbar: {e}")
        print("💡 Bitte starte das Backend mit: uv run python backend/app.py")
        return
    
    print("📤 Sende Beispieldaten...\n")
    
    # Sende alle Beispieldaten mit kurzer Pause dazwischen
    for i, data in enumerate(test_data, 1):
        print(f"[{i}/{len(test_data)}] ", end="")
        send_fact_check(data)
        if i < len(test_data):
            time.sleep(1)  # 1 Sekunde Pause zwischen den Requests
    
    print(f"\n✅ {len(test_data)} Beispieldaten gesendet!")
    print("💡 Öffne http://localhost:3000 im Browser, um das Dashboard zu sehen.")

if __name__ == "__main__":
    main()

