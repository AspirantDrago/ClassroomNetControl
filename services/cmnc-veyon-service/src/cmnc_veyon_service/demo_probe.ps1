$ErrorActionPreference = 'Stop'
$ok = $false
$client = New-Object System.Net.Sockets.TcpClient
function Read-Exact([int]$length) {
    $data = New-Object byte[] $length
    $offset = 0
    while ($offset -lt $length) {
        $n = $stream.Read($data, $offset, $length - $offset)
        if ($n -le 0) { throw 'Disconnected' }
        $offset += $n
    }
    return ,$data
}
function Write-Bytes([byte[]]$data) { $stream.Write($data, 0, $data.Length) }
function Read-U32 {
    [byte[]]$bytes = Read-Exact 4
    [Array]::Reverse($bytes)
    return [BitConverter]::ToUInt32($bytes, 0)
}
function Write-U32([uint32]$value) {
    [byte[]]$bytes = [BitConverter]::GetBytes($value)
    [Array]::Reverse($bytes)
    Write-Bytes $bytes
}
try {
    $connect = $client.ConnectAsync('__SOURCE_HOST__', 11400)
    if (-not $connect.Wait(3000)) { throw 'Connect timeout' }
    $stream = $client.GetStream()
    $stream.ReadTimeout = 3000
    $stream.WriteTimeout = 3000
    if ([Text.Encoding]::ASCII.GetString((Read-Exact 12)) -ne "RFB 003.008`n") { throw 'Not Veyon RFB' }
    Write-Bytes ([Text.Encoding]::ASCII.GetBytes("RFB 003.008`n"))
    [byte[]]$security = Read-Exact 2
    if ($security[0] -ne 1 -or $security[1] -ne 40) { throw 'Not token-authenticated Veyon' }
    Write-Bytes ([byte[]]@(40))
    if ((Read-U32) -ne 18) { throw 'Invalid auth methods' }
    [byte[]]$methods = Read-Exact 18
    [byte[]]$int5 = @(0,0,0,2,0,0,0,0,5)
    [byte[]]$int1 = @(0,0,0,2,0,0,0,0,1)
    if ([Convert]::ToBase64String($methods) -ne [Convert]::ToBase64String([byte[]]($int1 + $int5))) { throw 'Wrong auth method' }
    Write-U32 18
    Write-Bytes ([byte[]]($int5 + @(0,0,0,10,0,0,0,0,0)))
    if ((Read-U32) -ne 0) { throw 'Invalid acknowledgement' }
    [byte[]]$token = [Text.Encoding]::ASCII.GetBytes('__SOURCE_TOKEN__')
    Write-U32 (9 + $token.Length)
    Write-Bytes ([byte[]]@(0,0,0,12,0))
    Write-U32 $token.Length
    Write-Bytes $token
    if ((Read-U32) -ne 0) { throw 'Authentication failed' }
    Write-Bytes ([byte[]]@(1))
    [byte[]]$init = Read-Exact 24
    $width = 256 * [int]$init[0] + [int]$init[1]
    $height = 256 * [int]$init[2] + [int]$init[3]
    if ($width -lt 1 -or $height -lt 1 -or $width -gt 8192 -or $height -gt 8192) { throw 'No screen available' }
    $ok = $true
} catch { $ok = $false } finally { $client.Close() }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $url = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CALLBACK_B64__'))
    $headers = @{Authorization='Bearer __PROBE_TOKEN__'}
    $body = @{reachable=$ok} | ConvertTo-Json -Compress
    $null = Invoke-WebRequest -Uri $url -Method POST -Headers $headers -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 5
} catch { }
