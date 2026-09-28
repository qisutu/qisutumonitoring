"""The status of a device comes only from explicitly configured checks."""
PRIORITY = {'up': 0, 'pending': 1, 'warning': 2, 'unknown': 3,
            'stale': 4, 'error': 5, 'down': 6, 'critical': 7}
LABELS = {'up': 'OK', 'pending': 'Ausstehend', 'warning': 'Warnung',
          'unknown': 'Keine Messwerte', 'stale': 'Überfällig', 'error': 'Prüffehler',
          'down': 'Prüfung fehlgeschlagen', 'critical': 'Kritisch', 'paused': 'Pausiert', 'blocked': 'Abhängigkeit ausgefallen', 'unlicensed': 'Nicht freigeschaltet'}


def effective(check, now):
    if check.get('device_license_blocked'):
        return 'unlicensed'
    if not check['enabled'] or check.get('device_enabled') == 0:
        return 'paused'
    if check.get('device_blocked'):
        return 'blocked'
    if check['last_checked'] and now-check['last_checked'] > max(60, check['interval']+check['timeout']+30):
        return 'stale'
    return check['status']


def check_label(check, status):
    if status == 'unknown' and 'metrics' in check:
        return 'Messwerte unvollständig'
    if check.get('type') == 'ping' and status in ('warning', 'down'):
        return 'Keine Ping-Antwort'
    if status == 'down':
        return {'tcp': 'TCP-Verbindung fehlgeschlagen', 'http': 'HTTP-Prüfung fehlgeschlagen'}.get(check.get('type'), 'Ressourcenabfrage fehlgeschlagen')
    if status == 'critical' and 'metrics' in check and not check.get('kind'):
        return 'Ressourcen kritisch'
    return LABELS.get(status, status)


def summarize(devices, services, resources, now, integrations=None):
    grouped = {}
    for check in services + resources + (integrations or []):
        check['effective_status'] = effective(check, now)
        check['status_label'] = check_label(check, check['effective_status'])
        grouped.setdefault(check['device_id'], []).append(check)
    for device in devices:
        checks = grouped.get(device['id'], [])
        active = [check for check in checks if check['enabled']]
        device['checks_total'] = len(checks)
        device['checks_active'] = len(active) if device['enabled'] and not device.get('license_blocked') else 0
        device['last_checked'] = max((check['last_checked'] or 0 for check in active), default=0) or None
        device['message'] = ''
        if device.get('license_blocked'):
            status,label='unlicensed','Nicht freigeschaltet'
            device['message']='Gerätebegrenzung: Dieses Gerät wird nicht geprüft. Unter „Freischaltung“ die Geräteauswahl ändern oder den Vertrag verlängern.'
        elif not device['enabled']:
            status, label = 'paused', 'Gerät pausiert'
        elif device.get('blocked'):
            status, label = 'blocked', 'Durch Abhängigkeit ausgesetzt'
            device['message'] = device['block_reason']
        elif not checks:
            status, label = 'unmonitored', 'Noch keine Prüfung eingerichtet'
        elif not active:
            status, label = 'paused', 'Alle Prüfungen pausiert'
        else:
            cause = max(active, key=lambda check: PRIORITY.get(check['effective_status'], 0))
            status, label = cause['effective_status'], cause['status_label']
            if status not in ('up', 'pending'):
                device['message'] = (cause.get('name') or 'Ressourcen') + ': ' + cause['message']
        device['status'], device['status_label'] = status, label
