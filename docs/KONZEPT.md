# WashRData: Konzept

Stand: Version 0.1.0 (Grundgerüst), Oktober 2026.

## Ziel

WashRData überwacht Waschmaschine und Trockner über den Leistungssensor einer smarten Steckdose in
Home Assistant. Es erkennt Start, Pausen und Ende eines Zyklus und misst Dauer und Energie. Später
kommen Programmerkennung, Restzeit, Kosten, Zusatzsensoren und Wartung dazu.

„Besser als das Vorbild“ heißt hier drei Dinge:

1. **Genauere Erkennung:** kein vorzeitiges Ende beim Einweichen, kein neuer Zyklus durch
   Knitterschutz, keine verlorenen Messwerte.
2. **Schlanke Architektur:** kleine, verständliche Module und eine Erkennung, die ohne Home Assistant
   testbar ist.
3. **Mehr Features:** Kosten und Tarife, Zusatzsensoren, Wartungsprognose, Wasserverbrauch.

## Ausgangslage: ha_washdata

[ha_washdata](https://github.com/3dg1luk43/ha_washdata) (Version 0.5.8, AGPL-3.0) ist ausgereift und
verbreitet. Es kann Zyklen erkennen, Programme zuordnen und die Restzeit schätzen. Es hat ein eigenes
Panel, einen Community-Store und 35 Sprachen.

| Thema | Beobachtung | Folgerung für WashRData |
| :--- | :--- | :--- |
| Umfang | ~60.000 Zeilen Python in der Integration; `manager.py` 9.500, `profile_store.py` 11.400, `cycle_detector.py` 6.000 Zeilen | Module klein halten (Richtwert 600 Zeilen); Erkennung als eigene Bibliothek |
| Einstellungen | Viele Tuning-Parameter (Off Delay, Min Off Gap, Start Energy ...), dazu eine Vorschlags-Engine, die sie nachjustiert | Wenige Einstellungen; die Schwellen, auf die es ankommt, aus den eigenen Zyklen lernen |
| Abhängigkeiten | `numpy` als Laufzeit-Abhängigkeit | Reines Python, solange es reicht |
| Häufige Issues | Knitterschutz (#68, #296, #343), Ende-Erkennung bei hängenden oder gleichbleibenden Messwerten (#101, #363), Fehler im HA-Log (#144, #245, #405), verlorene Profile (#57) | Knitterschutz als eigener Zustand; Tick und `state_reported`; robuste Persistenz; Tests gegen echtes HA |
| Tests | Viele Tests, laut eigener Doku ein Drittel mit `MagicMock` statt echtem HA; Fehler blieben deshalb monatelang unentdeckt | Engine-Tests ohne HA, Adapter-Tests immer gegen echtes HA |

Code aus ha_washdata wird nicht übernommen (AGPL). WashRData ist eine Neuentwicklung.

## Architektur

```
 Steckdose (sensor.*_power)
        │ state_changed / state_reported      Tick alle 30 s
        ▼                                          │
 ┌─────────────────── device.py (Adapter) ─────────┴──────────┐
 │ Einheit -> W, unavailable -> None, Zeitstempel ordnen       │
 │                    │                                        │
 │                    ▼                                        │
 │  ┌──────────── engine/ (ohne Home Assistant) ───────────┐  │
 │  │ CycleDetector: Zustandsautomat, Energie, Verlauf      │  │
 │  │ LearnedStats:  gelernte Endverzögerung                │  │
 │  └───────────────────────────────────────────────────────┘  │
 │                    │ Events                                  │
 │                    ▼                                        │
 │  HA-Events, Speicher (Store), Dispatcher -> Entitäten       │
 └─────────────────────────────────────────────────────────────┘
```

- **engine/** bekommt nur Paare aus Zeitstempel und Watt. Sie kennt weder Home Assistant noch Uhrzeit
  noch Einheiten, ist deterministisch und lässt sich Kurve für Kurve testen.
- **device.py** übersetzt zwischen Home Assistant und Engine, speichert den Zustand und feuert Events.
- **Entitäten** lesen nur vom Gerät, sie rechnen nichts selbst.

## Zustandsmodell

| Zustand | Bedeutung |
| :--- | :--- |
| `idle` | Nichts los (aus oder Standby) |
| `starting` | Aktivität erkannt, aber noch nicht genug Energie für einen Zyklus |
| `running` | Zyklus läuft, Leistung über der Stoppschwelle |
| `paused` | Zyklus läuft, aber gerade ruhig (Einweichen, Pause oder ein noch nicht bestätigtes Ende) |
| `finished` | Zyklus beendet. Kommt kurz danach anhaltend Leistung, wird er fortgesetzt |
| `anti_crease` | Knitterschutz: kurze Trommelbewegungen nach dem Ende, kein neuer Zyklus |

`binary_sensor.<name>_running` ist in `running` und `paused` an, also über den ganzen Zyklus.

## Erkennung

**Hysterese.** Ab der Startleistung gilt das Gerät als aktiv, unter der Stoppleistung als ruhig.
Dazwischen bleibt der vorige Zustand. Ein Display-Standby zwischen den Schwellen startet so nichts, und
eine kurze Schwankung im Lauf beendet nichts.

**Start über Energie.** Ein Zyklus beginnt erst, wenn die Aktivität genug Energie verbraucht hat
(Waschmaschine 2 Wh, Trockner 5 Wh). Kurze Spitzen fallen so heraus. Als Startzeit gilt der Beginn der
Aktivität, nicht der Moment der Bestätigung.

**Ende mit lernender Verzögerung.** Ein Zyklus endet, wenn das Gerät eine bestimmte Zeit ruhig ist.
Als Endzeit zählt der Beginn der Ruhe, nicht ihr Ablauf. Die Verzögerung ist ein Mindestwert
(Waschmaschine 5 min, Trockner 3 min). WashRData merkt sich die längste Pause der letzten 20 Zyklen und
setzt die Verzögerung auf das 1,25-Fache plus 1 min, höchstens bis zu einer Obergrenze (Waschmaschine
60 min, Trockner 20 min). Ein Programm mit 12 Minuten Einweichen bringt dem Gerät also bei, nicht nach
5 Minuten Ruhe das Ende auszurufen.

**Fortsetzen statt Teilen.** Kommt innerhalb des Fortsetzungsfensters (Waschmaschine 15 min, Trockner
10 min) nach einem Ende wieder anhaltend Leistung, wird der Zyklus wieder geöffnet (Event
`washrdata_cycle_resumed`), statt einen zweiten anzulegen. Die Lücke zählt als Pause und fließt ins
Lernen ein. Derselbe Fehler passiert beim nächsten Mal nicht wieder.

**Knitterschutz.** Nach dem Ende eines Trocknerzyklus gelten kurze Aktivitäten (höchstens 4 min) als
Knitterschutz. Sie werden gezählt, sind aber kein neuer Zyklus. Nach 15 Minuten ohne Bewegung (oder
spätestens 2 Stunden nach dem Ende) ist der Knitterschutz vorbei. Erst eine längere Aktivität startet
einen neuen Zyklus. Bei Waschmaschinen lässt sich das in den Optionen einschalten.

**Messwerte, die ausbleiben.** Viele Steckdosen melden nur Änderungen. Damit Zeitgrenzen trotzdem
greifen, bekommt die Engine alle 30 s einen Tick mit dem letzten Wert. Zusätzlich wertet der Adapter
`state_reported` aus, also Meldungen mit gleichem Wert. Ein Messwert, der wegen eines dazwischen
gelaufenen Ticks älter wirkt, wird auf den letzten Zeitpunkt gehoben statt verworfen.

**Ausfall.** Ist der Sensor `unavailable`, läuft die Zeit weiter, aber ohne Energie und ohne
Zustandswechsel. Erst nach 15 Minuten ohne Messwert endet ein laufender Zyklus, markiert als
unterbrochen. Lücken über 15 Minuten (etwa ein HA-Neustart) werden nicht hochgerechnet.

**Unterbrochen.** Ein beendeter Zyklus, der kürzer als die Mindestdauer ist (Waschmaschine 10 min,
Trockner 15 min), wird als `interrupted` markiert und nicht zum Lernen benutzt.

## Daten und Persistenz

Je Gerät speichert ein Home Assistant `Store` (`.storage/washrdata.<entry_id>`):

- den vollständigen Zustand der Engine, auch einen laufenden Zyklus. Ein Neustart oder Reload mitten
  im Programm setzt den Zyklus fort.
- die gelernten Werte,
- die letzten 50 Zyklen mit komprimiertem Leistungsverlauf. Er dient als Grundlage für die
  Programmerkennung in 0.2.

Gespeichert wird verzögert (30 s) und sofort am Zyklusende.

## Entitäten und Events (0.1)

| Entität | Inhalt |
| :--- | :--- |
| `sensor.<name>_state` | Zustand (siehe oben) |
| `binary_sensor.<name>_running` | An während des ganzen Zyklus |
| `sensor.<name>_cycle_duration` | Laufzeit des aktuellen Zyklus (min) |
| `sensor.<name>_cycle_energy` | Energie des aktuellen Zyklus (kWh) |
| `sensor.<name>_last_cycle_duration` | Dauer des letzten Zyklus, mit Details als Attribute |
| `sensor.<name>_last_cycle_energy` | Energie des letzten Zyklus (kWh) |
| `sensor.<name>_cycle_count` | Anzahl Zyklen |
| `sensor.<name>_total_energy` | Gesamtenergie (kWh), für das Energie-Dashboard |
| `sensor.<name>_end_delay` | Diagnose: aktuell wirksame, gelernte Endverzögerung |

Events: `washrdata_cycle_started`, `washrdata_cycle_finished`, `washrdata_cycle_resumed`,
`washrdata_anti_crease_started`, `washrdata_anti_crease_ended`. Jedes Event enthält `entry_id`,
`name`, `device_type` und eine Zusammenfassung des Zyklus (Start, Ende, Dauer, Energie,
Spitzenleistung, `interrupted`, `resumed`, `anti_crease_bursts`).

## Roadmap

| Version | Inhalt |
| :--- | :--- |
| **0.1 Grundgerüst** (dieser Stand) | Engine mit Zustandsautomat, lernender Endverzögerung, Fortsetzen und Knitterschutz; Integration mit Config- und Options-Flow, Sensoren, Events, Persistenz; Waschmaschine und Trockner |
| **0.2 Programme und Restzeit** | Zyklen benennen (Service, Select-Entität) und Profile daraus bilden; Programmerkennung über Merkmale (Dauer, Energie, Heizphasen) und Kurvenvergleich (DTW) auf einheitlich abgetasteten Kurven, ohne numpy; Restzeit und Fortschritt mit Unsicherheitsangabe; programmabhängiges Ende: kennt WashRData das Programm, kann der Zyklus nicht deutlich vor dem erwarteten Ende enden; Import alter Zyklen aus dem Recorder, damit man nicht bei null anfängt |
| **0.3 Zusatzsensoren und Benachrichtigungen** | Türkontakt (Ende bestätigen, Erinnerung „Wäsche noch drin“), Vibrationssensor (Pause oder Ende unterscheiden, Leistung allein reicht dafür nicht immer), Wasserzähler; Blueprints für Benachrichtigungen, Vorwarnung vor dem Ende |
| **0.4 Kosten und Tarife** | Kosten pro Zyklus mit fester oder dynamischer Preis-Entität (Tibber, Nordpool, EPEX); Empfehlung für die günstigste Startzeit: Programmprofil mal Preiskurve; Startzeit nach PV-Prognose (Forecast.Solar, Solcast) |
| **0.5 Wartung und Wasser** | Erinnerungen nach Zyklen, kWh oder Zeit (Flusensieb, Entkalken, Trommelreinigung); Verschleiß erkennen, wenn die Kurve eines Programms über Monate abweicht (z. B. längere Heizphase durch Kalk); Wasserverbrauch pro Zyklus: gemessen mit Wasserzähler oder aus dem Programmprofil geschätzt |
| **später** | Spülmaschine, generischer Gerätetyp, Lovelace-Karte, Diagnose-Export, weitere Sprachen |

## Qualität

- Engine-Tests auf simulierten Kurven: Normalzyklus, Spitzen, Hysterese, Einweichen, Fortsetzen und
  Lernen, Knitterschutz, Ausfall, Neustart, Persistenz, Steckdosen, die nur Änderungen melden.
- Integrationstests mit echtem Home Assistant über `pytest-homeassistant-custom-component`:
  Config-Flow, Options-Flow, ein Zyklus von der Steckdose bis zu Entität, Event und Reload.
- Ab 0.2: echte, aufgezeichnete Zyklen als Testkorpus und eine Messung der Erkennungsgenauigkeit
  (Leave-one-out), damit Verbesserungen belegbar sind.
- CI: Ruff, Tests, `hassfest`, HACS-Validierung.

## Offene Punkte

- Lizenz des Projekts festlegen (z. B. MIT oder Apache-2.0).
- Sammeln echter Leistungskurven der eigenen Geräte für den Testkorpus.
