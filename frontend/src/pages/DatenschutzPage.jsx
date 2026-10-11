// Datenschutzerklärung. Mirrors what the code and the production config actually do —
// change it together with any new provider, stored field or retention rule.
const PROCESSING_STEPS = [
  {
    step: 'Prüfwürdige Sätze erkennen',
    service: 'Modell „Clef“ von Sference, betrieben im Europäischen Wirtschaftsraum; Grenzfälle beurteilt Google Gemini über Vertex AI in der EU. Beides aufgerufen über den EU-Router von Requesty.',
    data: 'jeder transkribierte Satz mit Sprecherkennung',
  },
  {
    step: 'Behauptung präzise formulieren',
    service: 'Sprachmodell von OpenAI, betrieben bei Microsoft Azure in der EU, aufgerufen über Requesty',
    data: 'Satz mit Umfeld, Name der sprechenden Person, Sendungskontext',
  },
  {
    step: 'Behauptung bewerten',
    service: 'Google Gemini über Vertex AI in der EU, aufgerufen über Requesty',
    data: 'Behauptung, Name der sprechenden Person, Suchergebnisse',
  },
  {
    step: 'Ersatz bei Störungen',
    service: 'Claude von Anthropic, betrieben bei Amazon Web Services (Bedrock) oder Google (Vertex AI) in der EU, aufgerufen über Requesty',
    data: 'wie im ausgefallenen Schritt',
  },
  {
    step: 'Belege suchen',
    service: 'Suchdienst Tavily (USA)',
    data: 'Suchanfragen, die aus der Behauptung formuliert werden',
  },
]

const BROWSER_STORAGE = [
  { key: 'fc_access_code', content: 'Ihr Zugangscode', purpose: 'damit Sie den Code nicht bei jedem Besuch neu eingeben müssen' },
  { key: 'fc_sidebar_collapsed', content: 'ob die Seitenleiste eingeklappt ist', purpose: 'Ihre Ansichtseinstellung' },
]

export function DatenschutzPage() {
  return (
    <div className="about-page">
      <div className="about-content legal-content">
        <h1>Datenschutzerklärung</h1>

        <h2>1. Verantwortlicher</h2>
        <p>Verantwortlich für die Datenverarbeitung auf live-faktencheck.de ist:</p>
        <p>
          Ulf Mertens<br />
          c/o Postflex #PFX-006-869<br />
          Emsdettener Str. 10<br />
          48268 Greven<br />
          E-Mail: <a href="mailto:info@live-faktencheck.de">info@live-faktencheck.de</a>
        </p>

        <h2>2. Überblick</h2>
        <p>
          Live Faktencheck transkribiert Gespräche aus Talkshows in Echtzeit und prüft darin geäußerte
          Tatsachenbehauptungen automatisch mit Hilfe von Künstlicher Intelligenz. Wer die Seite nur ansieht,
          gibt außer technisch notwendigen Verbindungsdaten keine personenbezogenen Daten an uns.
        </p>
        <p>Personenbezogene Daten fallen in drei Fällen an:</p>
        <ul>
          <li><strong>Besuch der Website:</strong> Verbindungsdaten wie die IP-Adresse (Abschnitt 3).</li>
          <li><strong>Nutzung mit Zugangscode:</strong> Ihre E-Mail-Anfrage, Ihr Zugangscode und Ihre Sitzungen (Abschnitt 4).</li>
          <li>
            <strong>Live-Faktencheck:</strong> das Audio der geprüften Sendung, das daraus entstehende Transkript
            sowie die geprüften Aussagen mit dem Namen der sprechenden Person (Abschnitte 5 bis 7).
          </li>
        </ul>
        <p>Wir setzen keine Tracking- oder Analyse-Werkzeuge ein und erstellen keine Nutzerprofile.</p>

        <h2>3. Hosting und Bereitstellung der Website</h2>
        <p>
          <strong>Website (Frontend):</strong> Die Seite wird über Cloudflare ausgeliefert (Cloudflare, Inc.,
          101 Townsend St, San Francisco, CA 94107, USA). Beim Aufruf verarbeitet Cloudflare Ihre IP-Adresse, Datum
          und Uhrzeit, die aufgerufene Adresse sowie Browser- und Gerätetyp, um die Seite auszuliefern und vor
          Angriffen zu schützen.
        </p>
        <p>
          <strong>Server (Backend):</strong> Die Anwendung läuft auf einem Server der Hostinger International Ltd.
          (61 Lordou Vironos Street, 6023 Larnaca, Zypern) in einem Rechenzentrum in Frankfurt am Main. Der Server
          ist nur über einen Cloudflare-Tunnel erreichbar; Cloudflare leitet die Anfragen weiter und sieht dabei
          ebenfalls Ihre IP-Adresse.
        </p>
        <p>
          <strong>Server-Protokolle:</strong> Der Server schreibt technische Protokolle zur Fehlersuche, etwa
          Zeitpunkt, Sitzungskennung, Sprechername und Prüfergebnis. Gesprächsinhalte wie transkribierte Sätze oder
          geprüfte Aussagen enthalten sie nicht. Die Protokolle sind auf 50 MB begrenzt; ältere Einträge werden
          laufend überschrieben.
        </p>
        <p>
          <strong>Keine Inhalte von Drittanbietern:</strong> Schriftarten und Stylesheets liefern wir selbst aus.
          Ihr Browser lädt beim Besuch keine Inhalte von Google Fonts, CDNs oder anderen Drittanbietern.
        </p>
        <p>
          <strong>Rechtsgrundlage:</strong> Art. 6 Abs. 1 lit. f DSGVO. Unser berechtigtes Interesse ist eine
          sichere, stabile und schnelle Auslieferung der Website.
        </p>

        <h2>4. Early Access und Zugangscodes</h2>
        <p>
          <strong>Anfrage per E-Mail:</strong> Während der Testphase vergeben wir Zugangscodes auf Anfrage an
          info@live-faktencheck.de. Wir verarbeiten Ihre E-Mail-Adresse, Ihren Namen und den Inhalt Ihrer
          Nachricht, um die Anfrage zu beantworten. Die E-Mails liegen bei unserem E-Mail-Anbieter STRATO GmbH,
          Otto-Ostrowski-Straße 7, 10249 Berlin, mit Rechenzentren in Deutschland. Wir löschen die Korrespondenz,
          wenn sie nicht mehr benötigt wird, spätestens 12 Monate nach Ende der Testphase.
        </p>
        <p>
          <strong>Zugangscode:</strong> Zu jedem Code speichern wir eine Bezeichnung (in der Regel Ihren Namen),
          das Erstellungsdatum, ob der Code aktiv ist, und wie viele Sekunden Live-Audio Sie bereits genutzt haben.
          Das brauchen wir, um den Zugang zu prüfen und das Nutzungskontingent (derzeit 5 Minuten) einzuhalten. Wir
          speichern den Code, solange er aktiv ist, und löschen ihn auf Ihren Wunsch.
        </p>
        <p>
          <strong>Rechtsgrundlage:</strong> Art. 6 Abs. 1 lit. b DSGVO (Bereitstellung des angefragten Zugangs)
          und Art. 6 Abs. 1 lit. f DSGVO (Schutz vor Missbrauch, Kostenkontrolle).
        </p>

        <h2>5. Live-Audio, Transkription und Sprecherzuordnung</h2>
        <p>
          <strong>Was passiert:</strong> Wenn Sie einen Live-Faktencheck starten, greift die Seite mit Ihrer
          Erlaubnis auf ein Mikrofon Ihres Geräts zu. Das Audio wird laufend an unseren Server und von dort an den
          Transkriptionsdienst AssemblyAI, Inc. (USA) gesendet, der es über seinen EU-Endpunkt in Text umwandelt und
          verschiedene Stimmen unterscheidet. AssemblyAI nutzt die Daten nicht zum Training seiner Modelle.
          Gesprochene Inhalte können personenbezogene Daten sein, insbesondere Aussagen von Gästen der Sendung und
          deren Namen.
        </p>
        <p>
          <strong>Was wir speichern:</strong> Das Audio speichern wir nicht. Das Transkript hält der Server nur
          während der laufenden Sitzung im Arbeitsspeicher; dauerhaft gespeichert werden nur die geprüften Aussagen
          (Abschnitt 7). Zur Sitzung speichern wir die Angaben, die Sie im Assistenten machen: Titel, Datum, Gäste
          mit Partei oder Funktion und den Kontext der Sendung.
        </p>
        <p>
          <strong>Sprecherzuordnung:</strong> Wir verwenden keine Stimmprofile und keine biometrische Erkennung.
          Der Transkriptionsdienst vergibt neutrale Kennungen („Sprecher A“, „Sprecher B“); den Namen ordnet die
          bedienende Person per Klick zu. Ohne Zuordnung bleibt die Aussage als „Unklar“ markiert.
        </p>
        <p>
          <strong>Ihre Verantwortung:</strong> Nutzen Sie das Werkzeug nur für öffentlich ausgestrahlte Sendungen
          oder Gespräche, bei denen alle Beteiligten einverstanden sind. Die Aufnahme des nichtöffentlich
          gesprochenen Wortes ohne Einwilligung ist nach § 201 StGB strafbar.
        </p>
        <p>
          <strong>Rechtsgrundlage:</strong> Art. 6 Abs. 1 lit. f DSGVO. Unser berechtigtes Interesse ist die
          öffentliche Einordnung politischer Aussagen in Fernsehsendungen. Soweit Aussagen politische Meinungen
          erkennen lassen (Art. 9 Abs. 1 DSGVO), stützen wir uns zusätzlich auf Art. 9 Abs. 2 lit. e DSGVO: Die
          Gäste haben diese Aussagen in einer öffentlich ausgestrahlten Sendung offensichtlich selbst öffentlich
          gemacht. Soweit die Faktenprüfung journalistischen Zwecken dient, können zusätzlich die Regeln zum
          Medienprivileg gelten (Art. 85 DSGVO in Verbindung mit dem jeweiligen Landesrecht).
        </p>

        <h2>6. Faktenprüfung mit KI-Modellen und Websuche</h2>
        <p>
          Die Prüfung läuft vollautomatisch in mehreren Schritten. Dabei gehen Ausschnitte des Transkripts, Namen der
          Sprechenden und der Sendungskontext an folgende Dienste:
        </p>
        <div className="legal-table-wrap">
          <table className="legal-table">
            <thead>
              <tr><th>Schritt</th><th>Dienst</th><th>Daten</th></tr>
            </thead>
            <tbody>
              {PROCESSING_STEPS.map(row => (
                <tr key={row.step}><td>{row.step}</td><td>{row.service}</td><td>{row.data}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Die Sprachmodelle verarbeiten die Daten nur, um die jeweilige Anfrage zu beantworten. Tavily speichert
          unsere Suchanfragen nicht und nutzt sie nicht zur Verbesserung seiner Dienste.
        </p>
        <p>
          Die Websuche ist auf eine Liste vertrauenswürdiger Quellen beschränkt (siehe
          Seite <a href="/trusted-domains">„Quellen“</a>). Die Ergebnisse werden nicht für Entscheidungen über
          Personen im Sinne von Art. 22 DSGVO verwendet; sie bewerten Aussagen, nicht Menschen.
        </p>
        <p><strong>Rechtsgrundlage:</strong> Art. 6 Abs. 1 lit. f DSGVO, wie in Abschnitt 5.</p>

        <h2>7. Gespeicherte Faktenchecks, Teilen-Links und Speicherdauer</h2>
        <p>
          <strong>Was gespeichert wird:</strong> Zu jedem Faktencheck speichern wir die geprüfte Aussage (meist nah
          am Wortlaut), den Namen der sprechenden Person, die Bewertung mit Begründung, die Quellen und den
          Zeitpunkt. Die Sitzung ist dem Zugangscode zugeordnet, mit dem sie angelegt wurde.
        </p>
        <p>
          <strong>Wer sie sieht:</strong> Wer den Teilen-Link einer Sitzung kennt, kann deren Faktenchecks ohne
          Anmeldung lesen. Ausgewählte Sitzungen veröffentlichen wir auf der Seite „Beispiele“.
        </p>
        <p>
          <strong>Löschen:</strong> Sie können eigene Sitzungen und einzelne Faktenchecks jederzeit unter „Mein
          Bereich“ dauerhaft löschen. Ansonsten bleiben sie gespeichert, bis Sie sie löschen oder uns um Löschung
          bitten; veröffentlichte Beispiele bis auf Widerruf.
        </p>
        <p>
          <strong>Sicherungskopien:</strong> Die Datenbank wird laufend verschlüsselt in Cloudflare R2 gesichert.
          Sicherungen werden nach 30 Tagen gelöscht; gelöschte Einträge verschwinden damit spätestens 30 Tage nach
          der Löschung auch aus den Sicherungen.
        </p>

        <h2>8. Speicher im Browser</h2>
        <p>
          Wir setzen keine Cookies. Im lokalen Speicher Ihres Browsers (localStorage) legen wir nur zwei Einträge ab:
        </p>
        <div className="legal-table-wrap">
          <table className="legal-table">
            <thead>
              <tr><th>Eintrag</th><th>Inhalt</th><th>Zweck</th></tr>
            </thead>
            <tbody>
              {BROWSER_STORAGE.map(row => (
                <tr key={row.key}><td><code>{row.key}</code></td><td>{row.content}</td><td>{row.purpose}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Die Einträge bleiben auf Ihrem Gerät, bis Sie sie in den Browser-Einstellungen löschen. Rechtsgrundlage
          ist § 25 Abs. 2 Nr. 2 TDDDG, da die Speicherung für den von Ihnen gewünschten Dienst unbedingt erforderlich
          ist, und für die weitere Verarbeitung Art. 6 Abs. 1 lit. b DSGVO.
        </p>

        <h2>9. Empfänger und Übermittlung in Drittländer</h2>
        <p>
          Wir geben personenbezogene Daten nur an die oben genannten Dienstleister weiter, die sie in unserem Auftrag
          verarbeiten (Art. 28 DSGVO). Eine Ausnahme ist die Suchmaschine Tavily: Sie verarbeitet unsere
          Suchanfragen als eigenständig Verantwortliche nach ihrer eigenen Datenschutzerklärung. Wir senden ihr nur
          aus der Behauptung formulierte Suchbegriffe, keine Audio- oder Transkriptdaten. Wir verkaufen keine Daten
          und geben sie nicht zu Werbezwecken weiter.
        </p>
        <p>
          Die Transkription läuft über den EU-Endpunkt von AssemblyAI; Audio und Transkript werden dort in der EU
          verarbeitet. Die Sprachmodelle rufen wir über den EU-Router von Requesty auf. Cloudflare, AssemblyAI,
          Tavily, Google, OpenAI und Anthropic sind US-Unternehmen oder gehören zu US-Konzernen; ein Zugriff aus den
          USA ist daher nicht ausgeschlossen. Eine Übermittlung in die USA stützen wir auf den Angemessenheitsbeschluss
          der EU-Kommission zum EU-US Data Privacy Framework (Art. 45 DSGVO), soweit der Anbieter dort zertifiziert
          ist, sonst auf EU-Standardvertragsklauseln (Art. 46 Abs. 2 lit. c DSGVO).
        </p>

        <h2>10. Ihre Rechte</h2>
        <p>
          Sie haben das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), Löschung (Art. 17),
          Einschränkung der Verarbeitung (Art. 18) und, soweit die Verarbeitung auf Art. 6 Abs. 1 lit. b DSGVO
          beruht, Datenübertragbarkeit (Art. 20). Eine Nachricht an
          info@live-faktencheck.de genügt.
        </p>
        <p>
          <strong>Widerspruchsrecht (Art. 21 DSGVO):</strong> Soweit wir Daten auf Grundlage berechtigter Interessen
          verarbeiten, können Sie aus Gründen, die sich aus Ihrer besonderen Situation ergeben, jederzeit
          widersprechen. Das gilt auch für Personen, deren Aussagen in einer Sendung geprüft wurden.
        </p>
        <p>
          <strong>Beschwerderecht:</strong> Sie können sich bei einer Datenschutz-Aufsichtsbehörde beschweren
          (Art. 77 DSGVO), insbesondere bei der Behörde an Ihrem Wohnort, Ihrem Arbeitsplatz oder dem Ort des
          mutmaßlichen Verstoßes.
        </p>
        <p className="legal-asof">Stand: 11. Oktober 2026</p>
      </div>
    </div>
  )
}
