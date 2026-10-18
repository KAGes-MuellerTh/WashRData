# CLAUDE.md

Hinweise für Claude Code in diesem Repository.

## Erst genau nachfragen, dann umsetzen

Der Projektverantwortliche hat ausdrücklich darum gebeten, daran erinnert zu werden, genauer zu sagen, was er umsetzen will.

- Ist eine Anfrage knapp oder mehrdeutig (Beispiele aus der Vergangenheit: „pull main“, „an die Vorgaben von PUMA anpassen“, „das Menü passt nicht“), vor der Umsetzung kurz nachfragen: Was genau soll sich ändern, auf welchen Seiten, wie soll das Ergebnis aussehen?
- Dabei freundlich darauf hinweisen: „Zur Erinnerung: Du wolltest, dass ich dich bitte, genauer zu beschreiben, was du vorhast.“
- Wenn möglich konkrete Auswahlmöglichkeiten anbieten, statt offen zu fragen.
- Bei klaren, eindeutigen Aufträgen nicht unnötig nachfragen, sondern umsetzen.

## Projekt

WashRData ist eine Home-Assistant-Custom-Integration. Sie erkennt anhand des Leistungssensors einer
smarten Steckdose die Zyklen von Waschmaschine und Trockner. Konzept, Architektur und Roadmap stehen
in [docs/KONZEPT.md](docs/KONZEPT.md); dieses Dokument ist die Referenz, bei Änderungen am Verhalten
mitpflegen.

Vorbild ist [ha_washdata](https://github.com/3dg1luk43/ha_washdata). Das Projekt steht unter AGPL-3.0:
**keinen Code daraus übernehmen**. Ideen und Anforderungen ja, Code nein.

## Aufbau

```
custom_components/washrdata/
  engine/            Erkennung, ohne jede Home-Assistant-Abhängigkeit
    model.py         Zustände, Konfiguration, Presets je Gerätetyp, CycleRecord
    detector.py      Zustandsautomat (update/tick), Persistenz (to_dict/from_dict)
    learning.py      Aus eigenen Zyklen gelernte Schwellen
    matching.py      Programmerkennung: Resampling, inkrementelles Open-End-DTW, Konfidenz
    tracker.py       Detector + Programme + Zyklus-Historie + Matcher eines Geräts
  device.py          Adapter: Sensor-Events und Ticks -> Tracker, Events, Speicher
  services.py        Dienste (label_cycle, create/rename/delete_program)
  diagnostics.py     Diagnose-Download mit allen Kurven
  sensor.py, binary_sensor.py, select.py, entity.py, config_flow.py, const.py
  strings.json, translations/{en,de}.json
tools/
  viewer.html        Kurven-Viewer für Diagnose-Dateien (eigenständige Seite, auch als Artifact veröffentlicht)
tests/
  engine/            reine Engine-Tests auf simulierten Leistungskurven (sim.py)
  integration/       Tests mit echtem Home Assistant (pytest-homeassistant-custom-component)
```

## Regeln

- `engine/` importiert nie `homeassistant`. Die Engine-Tests importieren sie als `engine`
  (siehe `pythonpath` in `pyproject.toml`) und laufen ohne Home Assistant.
- Code, Kommentare und Bezeichner auf Englisch; Dokumentation und UI-Texte auf Deutsch und Englisch.
- Jeder neue UI-Text kommt in `strings.json`, `translations/en.json` und `translations/de.json`.
- Kein Modul über ca. 600 Zeilen: lieber aufteilen. Keine Laufzeit-Abhängigkeiten (kein numpy),
  solange es ohne geht.
- Fehlerberichte kommen meist als Diagnose-Datei (`tracker.cycles[].trace`). Ein gemeldeter
  Erkennungsfehler wird zuerst als Test mit dieser Kurve nachgestellt, dann behoben.
- Verhaltensänderungen an der Erkennung brauchen einen Test mit einer Leistungskurve, die den Fall
  zeigt. Der Adapter (`device.py`) wird über `tests/integration/` gegen ein echtes HA getestet,
  nicht mit `MagicMock`.

## Befehle

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                    # alle Tests
.venv/bin/pytest tests/engine       # nur Engine, ohne Home Assistant
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
