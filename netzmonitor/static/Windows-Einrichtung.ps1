# Qisutu Monitoring 1.0.1 - einmalige Einrichtung auf dem Windows-Ziel.
# Windows PowerShell 5.1, als Administrator. Kein Agent, keine geplante Aufgabe.
# Beispiel: .\Windows-Einrichtung.ps1 -MonitorAddress 192.168.1.20 -UserName SERVER\monitoring
# Das Benutzerkonto muss bereits existieren. Fuer Hyper-V zusaetzlich -HyperV.
#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$MonitorAddress,
    [Parameter(Mandatory=$true)][string]$UserName,
    [switch]$HyperV,
    [string]$CertificateThumbprint
)
$ErrorActionPreference = 'Stop'
$monitorIP = $null
if (-not [System.Net.IPAddress]::TryParse($MonitorAddress, [ref]$monitorIP)) {
    throw 'MonitorAddress muss die konkrete IPv4- oder IPv6-Adresse des Monitoring-Servers sein.'
}
if ($monitorIP.Equals([System.Net.IPAddress]::Any) -or $monitorIP.Equals([System.Net.IPAddress]::IPv6Any)) {
    throw 'Eine konkrete Monitor-Adresse verwenden.'
}
$account = New-Object System.Security.Principal.NTAccount($UserName)
$sid = $account.Translate([System.Security.Principal.SecurityIdentifier])
$qualifiedName = $sid.Translate([System.Security.Principal.NTAccount]).Value
$namespaces = @('root\cimv2')
if ($HyperV) { $namespaces += 'root\virtualization\v2' }
if (-not (Get-Command Get-LocalGroup -ErrorAction SilentlyContinue)) { throw 'Lokale Gruppen fehlen. Auf Domaenencontrollern Zugang manuell durch die Administration einrichten.' }
$null = Get-LocalGroup -SID 'S-1-5-32-580'
$null = Get-LocalGroup -SID 'S-1-5-32-573'
# Vorab pruefen, damit eine fehlende Hyper-V-Rolle keine halbe Einrichtung erzeugt.
foreach ($namespace in $namespaces) {
    $null = Get-WmiObject -Namespace $namespace -Class __SystemSecurity
}
if ($CertificateThumbprint) {
    $certificate = Get-Item ('Cert:\LocalMachine\My\' + $CertificateThumbprint.Replace(' ',''))
    if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date)) { throw 'Serverzertifikat ungueltig oder ohne privaten Schluessel.' }
}
Import-Module Microsoft.WSMan.Management
Set-Service WinRM -StartupType Automatic
Start-Service WinRM
$existing = @(Get-ChildItem WSMan:\localhost\Listener | Where-Object { $_.Keys -contains 'Transport=HTTPS' })
if ($existing.Count -gt 1) { throw 'Mehrere HTTPS-Listener vorhanden. Bitte einen eindeutigen HTTPS-Zugang auf Port 5986 manuell auswaehlen.' }
if ($existing.Count -eq 1) {
    $listenerPath = $existing[0].PSPath
    $currentThumbprint = (Get-Item ($listenerPath + '\CertificateThumbprint')).Value
    $currentPort = [int](Get-Item ($listenerPath + '\Port')).Value
    if ($currentPort -ne 5986) { throw "Vorhandener HTTPS-Listener verwendet Port $currentPort. Diesen Port in Qisutu Monitoring eintragen und die Firewall manuell freigeben." }
    if ($CertificateThumbprint -and $certificate.Thumbprint -ne $currentThumbprint) { throw 'Bestehender Listener hat ein anderes Zertifikat; keine automatische Ersetzung.' }
    $certificate = Get-Item ('Cert:\LocalMachine\My\' + $currentThumbprint)
    if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date)) { throw 'Zertifikat des bestehenden Listeners muss erneuert werden.' }
} else {
    if (-not $CertificateThumbprint) {
        $dnsNames = @($env:COMPUTERNAME)
        try { $fqdn = [System.Net.Dns]::GetHostEntry($env:COMPUTERNAME).HostName; if ($fqdn -ne $env:COMPUTERNAME) { $dnsNames += $fqdn } } catch {}
        $certificate = New-SelfSignedCertificate -DnsName $dnsNames -CertStoreLocation Cert:\LocalMachine\My -FriendlyName 'Qisutu Monitoring WinRM HTTPS' -NotAfter (Get-Date).AddYears(2)
    }
    $null = New-Item WSMan:\localhost\Listener -Address * -Transport HTTPS -CertificateThumbprint $certificate.Thumbprint -Force
}
# Basic nur innerhalb von TLS; keine Klartextfreigabe und keine TrustedHosts-Aenderung.
Set-Item WSMan:\localhost\Service\AllowUnencrypted -Value $false
Set-Item WSMan:\localhost\Service\Auth\Basic -Value $true
function Add-ReadGroup([string]$GroupSID) {
    $group = Get-LocalGroup -SID $GroupSID
    if (-not (Get-LocalGroupMember -Group $group.Name | Where-Object { $_.SID -eq $sid })) {
        Add-LocalGroupMember -Group $group.Name -Member $qualifiedName
    }
}
# Sprachunabhaengig: Remote Management Users und Event Log Readers.
Add-ReadGroup 'S-1-5-32-580'
Add-ReadGroup 'S-1-5-32-573'
foreach ($namespace in $namespaces) {
    $security = Get-WmiObject -Namespace $namespace -Class __SystemSecurity
    $result = $security.GetSecurityDescriptor()
    if ($result.ReturnValue -ne 0) { throw "WMI-Rechte in $namespace nicht lesbar: $($result.ReturnValue)" }
    $descriptor = $result.Descriptor
    $already = @($descriptor.DACL | Where-Object { $_.Trustee.SIDString -eq $sid.Value -and $_.AceType -eq 0 -and ($_.AccessMask -band 33) -eq 33 })
    if ($already.Count -eq 0) {
        $trustee = ([WmiClass]'Win32_Trustee').CreateInstance()
        $sidBytes = New-Object byte[] $sid.BinaryLength
        $sid.GetBinaryForm($sidBytes,0)
        $trustee.SID = $sidBytes
        $trustee.SIDString = $sid.Value
        $ace = ([WmiClass]'Win32_ACE').CreateInstance()
        $ace.AccessMask = 33 # WBEM_ENABLE (1) und WBEM_REMOTE_ACCESS (32), keine Schreib-/Methodenrechte.
        $ace.AceFlags = 0
        $ace.AceType = 0
        $ace.Trustee = $trustee
        $descriptor.DACL = @($descriptor.DACL) + @($ace)
        $updated = $security.SetSecurityDescriptor($descriptor)
        if ($updated.ReturnValue -ne 0) { throw "WMI-Rechte in $namespace nicht gesetzt: $($updated.ReturnValue)" }
    }
}
$ruleName = 'Netzmonitor-WinRM-HTTPS'
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Any
    Get-NetFirewallRule -Name $ruleName | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $monitorIP.IPAddressToString
} else {
    $null = New-NetFirewallRule -Name $ruleName -DisplayName 'Qisutu Monitoring WinRM HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5986 -RemoteAddress $monitorIP.IPAddressToString -Profile Any
}
$hash = [System.Security.Cryptography.SHA256]::Create()
try { $fingerprint = ([System.BitConverter]::ToString($hash.ComputeHash($certificate.RawData))).Replace('-','').ToLowerInvariant() } finally { $hash.Dispose() }
Write-Host ''
Write-Host 'Qisutu-Monitoring-Zugang vorbereitet.'
Write-Host "Benutzer: $qualifiedName"
Write-Host 'Port: 5986 (HTTPS)'
Write-Host "Zertifikat gueltig bis: $($certificate.NotAfter)"
Write-Host "SHA-256: $fingerprint"
Write-Host 'Diesen Fingerabdruck in Qisutu Monitoring vergleichen und bestaetigen, dann Verbindung pruefen.'
Write-Host 'Bestehende Firewallregeln und Gruppenrichtlinien bleiben wirksam. Domaenencontroller: Gruppen-/WMI-Rechte durch die Administration einrichten.'
