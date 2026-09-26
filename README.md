# Zendure Regelung

Eigenständige Nulleinspeise-Regelung für Geräte, die über die Zendure-Integration
(`zendure_ha`, FireSon) in Home Assistant eingebunden sind.

Die Zendure-Integration bleibt installiert und liefert weiterhin alle Messwerte und die
Verbindung zu den Geräten. Die Regelung selbst – wie viel welches Gerät wann lädt oder
entlädt – übernimmt diese Integration.

## Installation

1. Den Ordner `custom_components/zendure_control` nach `/config/custom_components/` kopieren.
2. Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **Zendure Regelung**.
   - **Netzleistungs-Sensor:** z. B. `sensor.ecotracker_power` (positiv = Bezug, negativ = Einspeisung, W oder kW).
   - **Befehlsweg:** `Automatisch` lassen (siehe unten).
4. In der Zendure-Integration beim **Zendure Manager** den Betriebsmodus auf **Aus** stellen.
5. In Zendure Regelung den Schalter **Regelung aktiv** einschalten.

### Warum „Aus“ und nicht „Manuell“?

Im Modus „Manuell“ rechnet der Zendure Manager bei jeder Änderung des Netzsensors weiter
und schickt die eingestellte manuelle Leistung an die Geräte. Beide Regelungen würden sich
dann gegenseitig überschreiben. Im Modus „Aus“ sendet der Manager nach dem Umschalten
einmalig „Aus“ an alle Geräte und danach keine Befehle mehr.

Zendure Regelung prüft das: Steht der Manager nicht auf „Aus“, pausiert die Regelung,
der Sensor **Blockiert durch Zendure Manager** geht an und es erscheint eine Benachrichtigung.

## Befehlswege

| Befehlsweg | Wie | Wann |
|---|---|---|
| Automatisch | Treiber, sonst Entitäten | Standard |
| Zendure-Integration intern | Ruft die Lade-/Entlade-Funktionen der geladenen Zendure-Integration direkt auf. Das sind dieselben Befehle, die der Zendure Manager selbst sendet (Hyper: `deviceAutomation`, SolarFlow: Grenzwerte mit `smartMode`). | schnell, schreibt nicht in den Gerätespeicher |
| Nur Entitäten | Schreibt `AC-Betriebsmodus`, `AC-Ausgangsgrenze` und `AC-Eingangsgrenze` der Zendure-Geräte. | Notlösung, falls der interne Weg nach einem Update der Zendure-Integration nicht mehr passt |

**Achtung beim Weg „Nur Entitäten“:** Die Zendure-Integration schreibt diese Werte ohne
`smartMode`. Je nach Firmware landen sie dann im Flash-Speicher des Geräts. Die Regelung
schreibt deshalb auf diesem Weg höchstens alle 5 s und nur bei Änderungen ab 10 W. Für den
Dauerbetrieb ist der interne Weg vorzuziehen.

Welcher Weg pro Gerät verwendet wird, steht im Attribut `steuerung` des Sensors
**Letzte Entscheidung**.

## Entitäten

| Entität | Bedeutung |
|---|---|
| Regelung aktiv | Ein/Aus. Beim Ausschalten werden alle Geräte auf 0 W gesetzt. |
| Modus | Nulleinspeisung, Nur entladen, Nur laden (PV-Überschuss) |
| Ziel-Netzleistung | Worauf geregelt wird. +10 bis +20 W vermeidet Einspeisung bei Lastabfall. |
| Sollleistung gesamt | Leistung, die alle Geräte zusammen liefern sollen (negativ = laden) |
| Netzleistung | Verwendeter Wert des Netzsensors, Attribut `alter_s` |
| Letzte Entscheidung | Klartext, z. B. `Entladen 194W: Hyper Garage 40W (Übergabe), SF 800 Pro 154W (entlädt)` |
| *Gerät* angefordert | Letzter Befehl an das Gerät |
| *Gerät* Status | entlädt, lädt, Übergabe, Bypass, folgt nicht, aus, leer, voll, offline. Attribute: Soll, Ist, SOC, Solar |
| *Gerät* folgt Befehl nicht | Gerät liefert 15 s nach einem Befehl mehr als 30 W bzw. 20 % daneben |
| Netzsensor veraltet | Netzsensor meldet seit über 30 s nichts: Regelung pausiert, nach 120 s alle Geräte auf 0 W |
| Blockiert durch Zendure Manager | Zendure Manager steht nicht auf „Aus“ |

## Wie geregelt wird

- **Auslöser:** jede Änderung des Netzsensors, höchstens alle 3 s. Zusätzlich spätestens alle
  10 s, auch wenn der Netzsensor denselben Wert meldet (Home Assistant meldet unveränderte
  Werte sonst nicht). Ein veralteter Netzwert wird nie verwendet.
- **Sollleistung:** Netzleistung − Ziel + aktuelle AC-Leistung aller Geräte.
- **Totband:** Liegt die Netzleistung weniger als 10 W neben dem Ziel, bleibt alles, wie es ist.
- **Entladen:**
  - Volle Geräte mit PV zuerst, sonst würde ihre PV abgeregelt. Danach nach Ladestand.
  - Weitere Geräte kommen dazu, wenn die aktiven zu 80 % ausgelastet sind.
  - Übergabe: Können die übrigen Geräte den Bedarf 60 s lang mit halber Last decken, wird
    das schwächste Gerät schrittweise heruntergefahren (halbe Leistung pro Schritt). Die
    anderen übernehmen jeweils sofort die Differenz.
- **Laden (nur aus Überschuss):** Erst nach 20 s stabiler Einspeisung über 50 W, das Gerät
  mit dem niedrigsten Ladestand zuerst.
- **Geräte im Bypass** und **Geräte, die nicht folgen**, werden mit ihrer tatsächlichen
  Leistung eingerechnet. Die anderen Geräte gleichen aus, bei Bypass-Einspeisung notfalls
  durch AC-Laden.

Alle Schwellwerte stehen in `const.py`.

## Tests

```bash
pip install pytest-homeassistant-custom-component
pytest
```

`tests/test_regulator.py` prüft den Regelalgorithmus ohne Home Assistant,
`tests/test_integration.py` Erkennung, Befehlswege, Blockade und Einstellungen in Home Assistant.

## Zurück zur Zendure-Regelung

Schalter **Regelung aktiv** ausschalten (alle Geräte gehen auf 0 W) und beim Zendure Manager
wieder „Smarte Leistungsregelung“ wählen.
