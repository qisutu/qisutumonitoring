"""Individual ATA and NVMe SMART values; never infer health from missing data."""
from .extended import metric
from .integration_common import numeric


def smart_values(name, data):
    result = []
    def add(label, value, unit='', warn=None, critical=None):
        number = numeric(value)
        if number is not None:
            result.append(metric('smart', name, label, number, unit, warn=warn, critical=critical))
    add('Temperatur', (data.get('temperature') or {}).get('current'), '°C', 55, 65)
    add('Betriebsstunden', (data.get('power_on_time') or {}).get('hours'), 'h')
    add('Einschaltvorgänge', data.get('power_cycle_count'), 'gesamt')
    nvme = data.get('nvme_smart_health_information_log') or {}
    for key, label, unit, warn, crit in (
        ('percentage_used', 'NVMe-Verschleiß', '%', 80, 95),
        ('available_spare', 'NVMe-Reservespeicher', '%', None, None),
        ('media_errors', 'Nicht korrigierbare Medienfehler', 'gesamt', 1, None),
        ('num_err_log_entries', 'NVMe-Fehlerprotokolleinträge', 'gesamt', None, None),
        ('unsafe_shutdowns', 'Unsichere Abschaltungen', 'gesamt', None, None),
        ('critical_warning', 'NVMe-Warnbits', '', 1, None),
        ('data_units_read', 'NVMe-Dateneinheiten gelesen', '512000 B', None, None),
        ('data_units_written', 'NVMe-Dateneinheiten geschrieben', '512000 B', None, None),
    ):
        add(label, nvme.get(key), unit, warn, crit)
    known = {
        5: ('Neu zugewiesene Sektoren', 1),
        9: ('Betriebsstunden', None),
        187: ('Gemeldete nicht korrigierbare Fehler', 1),
        197: ('Ausstehende Sektoren', 1),
        198: ('Nicht korrigierbare Sektoren', 1),
        199: ('Schnittstellen-CRC-Fehler', 1),
    }
    present = {m['channel'] for m in result}
    for attribute in (data.get('ata_smart_attributes') or {}).get('table', []):
        ident = attribute.get('id')
        if ident in known:
            label, warn = known[ident]
            if label not in present:
                add(label, (attribute.get('raw') or {}).get('value'), 'h' if ident == 9 else 'gesamt', warn)
        # Normalized values are vendor-defined. Preserve the exact attribute
        # name and unit rather than pretending every raw integer means wear.
        label = 'ATA ' + str(ident) + ' · ' + str(attribute.get('name', ''))
        add(label + ' · normiert', attribute.get('value'))
    if not result:
        result.append(metric('smart', name, 'SMART-Einzelwerte', None, '', 'unknown',
                             'Das Laufwerk liefert keine auswertbaren SMART-Einzelwerte.'))
    return result
