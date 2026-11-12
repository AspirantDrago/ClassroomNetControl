$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$callback = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CALLBACK__'))
$headers = @{ Authorization = 'Bearer __TOKEN__' }
$result = @{ stdout = ''; stderr = ''; exit_code = $null; timed_out = $false; stdout_truncated = $false; stderr_truncated = $false }
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$directory = [IO.Path]::GetFullPath((Join-Path $tempRoot ('cmnc-' + [Guid]::NewGuid().ToString('N'))))
$process = $null
try {
    Add-Type -TypeDefinition @'
using System.IO;
using System.Text;
using System.Threading.Tasks;
public class CmncCapturedOutput {
    public string Text;
    public bool Truncated;
    public static async Task<CmncCapturedOutput> Read(StreamReader reader) {
        var text = new StringBuilder();
        var buffer = new char[4096];
        bool truncated = false;
        int count;
        while ((count = await reader.ReadAsync(buffer, 0, buffer.Length).ConfigureAwait(false)) > 0) {
            int remaining = 65536 - text.Length;
            int take = System.Math.Min(count, remaining);
            if (take > 0) text.Append(buffer, 0, take);
            if (take < count) truncated = true;
        }
        if (text.Length > 0 && char.IsHighSurrogate(text[text.Length - 1])) { text.Length--; truncated = true; }
        return new CmncCapturedOutput {Text = text.ToString(), Truncated = truncated};
    }
}
'@
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $command = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('__COMMAND__'))
    $childScript = @'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$global:LASTEXITCODE = 0
try {
    & {
__USER_COMMAND__
    }
    if (-not $?) { exit 1 }
    exit $global:LASTEXITCODE
} catch {
    [Console]::Error.WriteLine(($_ | Out-String))
    exit 1
}
'@
    $childScript = $childScript.Replace('__USER_COMMAND__', $command)
    $scriptPath = Join-Path $directory 'command.ps1'
    [IO.File]::WriteAllText($scriptPath, $childScript, (New-Object Text.UTF8Encoding($true)))
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = Join-Path $PSHOME 'powershell.exe'
    $start.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $scriptPath + '"'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
    $start.StandardErrorEncoding = New-Object Text.UTF8Encoding($false)
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Could not start PowerShell' }
    $stdout = [CmncCapturedOutput]::Read($process.StandardOutput)
    $stderr = [CmncCapturedOutput]::Read($process.StandardError)
    if (-not $process.WaitForExit(__RUNTIME_MS__)) {
        $result.timed_out = $true
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F 2>&1 | Out-Null
        $process.WaitForExit(1000) | Out-Null
    } else {
        $result.exit_code = $process.ExitCode
    }
    if ($stdout.Wait(1000)) {
        $result.stdout = $stdout.Result.Text
        $result.stdout_truncated = $stdout.Result.Truncated
    } else { $result.stdout_truncated = $true }
    if ($stderr.Wait(1000)) {
        $result.stderr = $stderr.Result.Text
        $result.stderr_truncated = $stderr.Result.Truncated
    } else { $result.stderr_truncated = $true }
} catch {
    $result.stderr = ($_ | Out-String)
    if ($result.stderr.Length -gt 65536) { $result.stderr = $result.stderr.Substring(0,65536); $result.stderr_truncated = $true }
    $result.exit_code = 1
} finally {
    if ($process) { $process.Dispose() }
    try { if ($directory.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($directory).StartsWith("cmnc-") -and [IO.Directory]::Exists($directory)) { [IO.Directory]::Delete($directory, $true) } } catch {}
}
$json = $result | ConvertTo-Json -Compress
Invoke-WebRequest -Uri $callback -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) -UseBasicParsing -TimeoutSec 5 | Out-Null
