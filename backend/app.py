from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import json
import requests

app = Flask(__name__)
CORS(app)  # Erlaubt Cross-Origin Requests vom Frontend

# In-Memory Storage für die Fakten-Check Daten
# In Produktion sollte man eine Datenbank verwenden
fact_checks = []
pending_claims_blocks = []  # Speichert die Vorab-Listen von Claims

@app.route('/api/fact-checks', methods=['GET'])
def get_fact_checks():
    """Gibt alle Fakten-Checks zurück, gruppiert nach Sprecher"""
    return jsonify(fact_checks)

@app.route('/api/fact-checks', methods=['POST'])
def receive_fact_check():
    """Empfängt neue Fakten-Check Daten von N8N"""
    try:
        # Debug: Zeige was ankommt
        raw_data = request.get_json()
        print(f"\n📥 Empfangene Daten von N8N:")
        print(f"   Content-Type: {request.content_type}")
        print(f"   Raw JSON: {json.dumps(raw_data, indent=2, ensure_ascii=False)}")
        
        # N8N sendet manchmal die Daten in einem 'body' Objekt oder direkt
        data = raw_data
        if isinstance(raw_data, dict) and 'body' in raw_data:
            # Wenn N8N die Daten in 'body' packt
            if isinstance(raw_data['body'], str):
                try:
                    data = json.loads(raw_data['body'])
                except:
                    data = raw_data
            else:
                data = raw_data['body']
        
        # Auch 'json' als Wrapper prüfen (manche N8N Konfigurationen)
        if isinstance(data, dict) and 'json' in data:
            data = data['json']
        
        # Prüfe ob es verified_claims von N8N ist (Phase 2: Verifizierte Claims zurück)
        # Format: { verified_claims: [{ claim_data: [{ output: { speaker, original_claim, verdict, evidence, sources } }] }] }
        if isinstance(data, dict) and 'verified_claims' in data:
            print("📋 Erkenne verified_claims von N8N - verarbeite Fact-Check Ergebnisse...")
            return handle_verified_claims(data)
        
        # Prüfe ob es eine Liste von Claims zur Überprüfung ist (Admin-Modus / Phase 1)
        # Format: { block_id, timestamp, claims_count, claims: [...] }
        if isinstance(data, dict) and 'claims' in data and isinstance(data.get('claims'), list):
            # Es ist eine Vorab-Liste von Claims
            print("📋 Erkenne Vorab-Liste von Claims - leite an pending_claims weiter...")
            return handle_pending_claims(data)
        
        # Sonst: Einzelner Fact-Check
        # Extrahiere die Felder (unterstütze verschiedene Feldnamen)
        # Unterstütze sowohl deutsche als auch englische Keys
        sprecher = data.get("sprecher") or data.get("Sprecher") or data.get("speaker") or ""
        behauptung = data.get("behauptung") or data.get("Behauptung") or data.get("claim") or data.get("original_claim") or ""
        urteil = data.get("urteil") or data.get("Urteil") or data.get("verdict") or ""
        begruendung = data.get("evidence") or data.get("begruendung") or data.get("Begründung") or data.get("Begruendung") or data.get("begründung") or data.get("reasoning") or ""
        quellen = data.get("quellen") or data.get("Quellen") or data.get("sources") or []
        
        # Wenn quellen ein String ist, in Liste umwandeln
        if isinstance(quellen, str):
            # Prüfe ob es ein JSON-String ist (z.B. '["url1", "url2"]')
            if quellen.strip().startswith('[') or quellen.strip().startswith('"'):
                try:
                    quellen = json.loads(quellen)
                except:
                    # Falls Parsing fehlschlägt, als einzelnes Element behandeln
                    quellen = [quellen] if quellen else []
            else:
                quellen = [quellen] if quellen else []
        
        fact_check = {
            "id": len(fact_checks) + 1,
            "sprecher": sprecher,
            "behauptung": behauptung,
            "urteil": urteil,
            "begruendung": begruendung,
            "quellen": quellen if isinstance(quellen, list) else [],
            "timestamp": datetime.now().isoformat()
        }
        
        fact_checks.append(fact_check)
        print(f"✅ Neuer Fakten-Check gespeichert:")
        print(f"   ID: {fact_check['id']}")
        print(f"   Sprecher: {fact_check['sprecher']}")
        print(f"   Behauptung: {fact_check['behauptung'][:60]}...")
        print(f"   Urteil: {fact_check['urteil']}\n")
        
        return jsonify({"status": "success", "id": fact_check["id"]}), 201
        
    except Exception as e:
        print(f"❌ Fehler beim Empfangen: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400

def handle_verified_claims(data):
    """Behandelt verified_claims von N8N mit Fact-Check Ergebnissen (Phase 2)"""
    try:
        verified_claims_list = data.get("verified_claims", [])
        processed_count = 0
        
        # Iteriere über alle verified_claims Gruppen
        for verified_group in verified_claims_list:
            claim_data_list = verified_group.get("claim_data", [])
            
            # Iteriere über alle Claims in der Gruppe
            for claim_item in claim_data_list:
                output = claim_item.get("output", {})
                
                # Extrahiere die Felder
                sprecher = output.get("speaker", "")
                behauptung = output.get("original_claim", "")
                urteil = output.get("verdict", "")
                begruendung = output.get("evidence", "")
                quellen = output.get("sources", [])
                
                # Erstelle Fact-Check Eintrag
                fact_check = {
                    "id": len(fact_checks) + 1,
                    "sprecher": sprecher,
                    "behauptung": behauptung,
                    "urteil": urteil,
                    "begruendung": begruendung,
                    "quellen": quellen if isinstance(quellen, list) else [],
                    "timestamp": datetime.now().isoformat()
                }
                
                fact_checks.append(fact_check)
                processed_count += 1
                
                print(f"✅ Fact-Check gespeichert:")
                print(f"   ID: {fact_check['id']}")
                print(f"   Sprecher: {fact_check['sprecher']}")
                print(f"   Behauptung: {fact_check['behauptung'][:60]}...")
                print(f"   Urteil: {fact_check['urteil']}")
        
        print(f"\n✅ {processed_count} Fact-Checks aus verified_claims verarbeitet\n")
        return jsonify({"status": "success", "processed_count": processed_count}), 201
        
    except Exception as e:
        print(f"❌ Fehler beim Verarbeiten der verified_claims: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400

def handle_pending_claims(data):
    """Behandelt Vorab-Listen von Claims"""
    try:
        block_id = data.get("block_id") or f"block_{int(datetime.now().timestamp() * 1000)}"
        timestamp = data.get("timestamp") or datetime.now().isoformat()
        claims = data.get("claims", [])
        
        pending_block = {
            "block_id": block_id,
            "timestamp": timestamp,
            "claims_count": len(claims),
            "claims": claims,
            "status": "pending"
        }
        
        pending_claims_blocks.append(pending_block)
        print(f"✅ Vorab-Liste gespeichert: {block_id} mit {len(claims)} Claims")
        
        return jsonify({"status": "success", "block_id": block_id, "claims_count": len(claims), "type": "pending_claims"}), 201
    except Exception as e:
        print(f"❌ Fehler beim Verarbeiten der Vorab-Liste: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/pending-claims', methods=['POST'])
def receive_pending_claims():
    """Empfängt Vorab-Liste von Claims von N8N zur Überprüfung"""
    try:
        raw_data = request.get_json()
        print(f"\n📋 Empfange Vorab-Liste von Claims:")
        print(f"   Raw JSON: {json.dumps(raw_data, indent=2, ensure_ascii=False)}")
        
        # N8N sendet manchmal die Daten in einem 'body' Objekt oder direkt
        data = raw_data
        if isinstance(raw_data, dict) and 'body' in raw_data:
            if isinstance(raw_data['body'], str):
                try:
                    data = json.loads(raw_data['body'])
                except:
                    data = raw_data
            else:
                data = raw_data['body']
        
        if isinstance(data, dict) and 'json' in data:
            data = data['json']
        
        # Erwartetes Format: { block_id, timestamp, claims_count, claims: [{name, claim, ...}] }
        block_id = data.get("block_id") or f"block_{int(datetime.now().timestamp() * 1000)}"
        timestamp = data.get("timestamp") or datetime.now().isoformat()
        claims = data.get("claims", [])
        
        pending_block = {
            "block_id": block_id,
            "timestamp": timestamp,
            "claims_count": len(claims),
            "claims": claims,
            "status": "pending"
        }
        
        pending_claims_blocks.append(pending_block)
        print(f"✅ Vorab-Liste gespeichert: {block_id} mit {len(claims)} Claims")
        
        return jsonify({"status": "success", "block_id": block_id, "claims_count": len(claims)}), 201
        
    except Exception as e:
        print(f"❌ Fehler beim Empfangen der Vorab-Liste: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/pending-claims', methods=['GET'])
def get_pending_claims():
    """Gibt alle pending Claims zurück"""
    # Sortiere nach Timestamp (neueste zuerst)
    sorted_blocks = sorted(pending_claims_blocks, key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(sorted_blocks)

@app.route('/api/approve-claims', methods=['POST'])
def approve_claims():
    """Sendet ausgewählte Claims zurück an N8N für weitere Analyse"""
    try:
        data = request.get_json()
        selected_claims = data.get("claims", [])
        block_id = data.get("block_id")
        n8n_webhook_url = data.get("n8n_webhook_url", "http://localhost:5678/webhook/verified-claims")
        
        if not selected_claims:
            return jsonify({"status": "error", "message": "Keine Claims ausgewählt"}), 400
        
        print(f"\n✅ Sende {len(selected_claims)} ausgewählte Claims an N8N...")
        print(f"   Block ID: {block_id}")
        print(f"   N8N Webhook: {n8n_webhook_url}")
        
        # Sende ausgewählte Claims an N8N zur Verifizierung
        # Format: Nur name und claim für jeden Claim (NOCH NICHT verifiziert!)
        claims_to_verify = []
        for claim in selected_claims:
            claims_to_verify.append({
                "name": claim.get("name", ""),
                "claim": claim.get("claim", "")
            })
        
        import requests
        response = requests.post(
            n8n_webhook_url,
            json={
                "block_id": block_id,
                "claims": claims_to_verify,
                "timestamp": datetime.now().isoformat()
            },
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            # Block bleibt pending, damit weitere Claims gesendet werden können
            print(f"✅ Claims erfolgreich an N8N gesendet")
            return jsonify({"status": "success", "sent_count": len(selected_claims)}), 200
        else:
            print(f"❌ N8N antwortete mit Status {response.status_code}: {response.text}")
            return jsonify({"status": "error", "message": f"N8N Error: {response.status_code}"}), 500
            
    except Exception as e:
        print(f"❌ Fehler beim Senden an N8N: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/health', methods=['GET'])
def health():
    """Health Check Endpoint"""
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    print("🚀 Backend startet auf http://0.0.0.0:5000")
    print("📡 Webhook-Endpoint: http://localhost:5000/api/fact-checks (POST)")
    print("📡 Für N8N in Docker: http://host.docker.internal:5000/api/fact-checks")
    print("📡 Für N8N lokal: http://localhost:5000/api/fact-checks")
    app.run(debug=True, host='0.0.0.0', port=5000)

