# WashRData

Home-Assistant-Integration, die Waschmaschine und Trockner über den Leistungssensor einer smarten
Steckdose überwacht. Sie erkennt Start, Pausen und Ende eines Zyklus, misst Dauer und Energie und
lernt aus den eigenen Zyklen, wie lange ein Programm ruhig sein kann, ohne fertig zu sein.

> **Status:** 0.1, Grundgerüst. Programmerkennung und Restzeit kommen in 0.2, siehe
> [Konzept und Roadmap](docs/KONZEPT.md).

> [!CAUTION]
> Waschmaschine und Trockner ziehen oft über 2000 W, stundenlang. Die Steckdose muss dafür
> ausgelegt sein (bei 230 V und 16 A sind das 3680 W). Unterdimensionierte Steckdosen können
> überhitzen.

## Funktionen

- Zyklus-Erkennung mit Hysterese und Startenergie: Standby und kurze Spitzen lösen nichts aus.
- Endverzögerung, die mitlernt: Einweichen und lange Pausen beenden den Zyklus nicht.
- Ein zu früh beendeter Zyklus wird fortgesetzt statt geteilt, und der Fehler wird gelernt.
- Knitterschutz beim Trockner als eigener Zustand, nicht als neuer Zyklus.
- Funktioniert mit Steckdosen, die nur Änderungen melden; übersteht Neustarts mitten im Programm.
- Nur lokal, keine Abhängigkeiten.

## Installation

**HACS:** dieses Repository als benutzerdefiniertes Repository (Typ *Integration*) hinzufügen,
WashRData installieren, Home Assistant neu starten.

**Manuell:** `custom_components/washrdata` nach `<config>/custom_components/` kopieren und neu starten.

Danach **Einstellungen > Geräte & Dienste > Integration hinzufügen > WashRData**: Name, Gerätetyp und
Leistungssensor wählen. Schwellen und Endverzögerung lassen sich in den Optionen anpassen, die
Standardwerte passen für die meisten Geräte.

## Entitäten

| Entität | Inhalt |
| :--- | :--- |
| `sensor.<name>_state` | `idle`, `starting`, `running`, `paused`, `finished`, `anti_crease` |
| `binary_sensor.<name>_running` | An während des ganzen Zyklus, auch in Pausen |
| `sensor.<name>_cycle_duration` / `_cycle_energy` | Aktueller Zyklus |
| `sensor.<name>_last_cycle_duration` / `_last_cycle_energy` | Letzter Zyklus (Details als Attribute) |
| `sensor.<name>_cycle_count` | Anzahl Zyklen |
| `sensor.<name>_total_energy` | Gesamtenergie, für das Energie-Dashboard |
| `sensor.<name>_end_delay` | Diagnose: gelernte Endverzögerung |

## Automationen

Events: `washrdata_cycle_started`, `washrdata_cycle_finished`, `washrdata_cycle_resumed`,
`washrdata_anti_crease_started`, `washrdata_anti_crease_ended`.

```yaml
triggers:
  - trigger: event
    event_type: washrdata_cycle_finished
    event_data:
      name: Waschmaschine
conditions:
  - condition: template
    value_template: "{{ not trigger.event.data.cycle.interrupted }}"
actions:
  - action: notify.mobile_app_handy
    data:
      message: >
        Waschmaschine fertig nach {{ trigger.event.data.cycle.duration_min | round }} min,
        {{ trigger.event.data.cycle.energy_kwh }} kWh.
```

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Aufbau und Regeln: [CLAUDE.md](CLAUDE.md). Konzept: [docs/KONZEPT.md](docs/KONZEPT.md).
