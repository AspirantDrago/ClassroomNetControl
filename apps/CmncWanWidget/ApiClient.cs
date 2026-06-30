using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace CmncWanWidget;

public sealed class ApiClient
{
    private readonly AppConfig _config;
    private readonly HttpClient _http;
    private string? _token;

    public ApiClient(AppConfig config)
    {
        _config = config;

        _http = new HttpClient
        {
            BaseAddress = new Uri(_config.ApiBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(10)
        };
    }

    public async Task EnsureAuthAsync()
    {
        if (!_config.UseLoginPassword)
            return;

        if (!string.IsNullOrWhiteSpace(_token))
            return;

        var payload = JsonSerializer.Serialize(new
        {
            username = _config.Username,
            password = _config.Password
        });

        using var content = new StringContent(payload, Encoding.UTF8, "application/json");
        using var response = await _http.PostAsync(NormalizePath(_config.AuthLoginPath), content);

        await EnsureSuccessAsync(response);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);

        _token =
            JsonHelpers.GetString(doc.RootElement, "access_token", "token", "jwt");

        if (string.IsNullOrWhiteSpace(_token))
            throw new InvalidOperationException("API не вернул access_token/token/jwt.");

        _http.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", _token);
    }

    public async Task<ClassroomInfo?> GetFirstClassroomAsync()
    {
        await EnsureAuthAsync();

        Console.WriteLine(NormalizePath(_config.ClassroomsPath));
        using var response = await _http.GetAsync(NormalizePath(_config.ClassroomsPath));
        await EnsureSuccessAsync(response);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);

        var items = JsonHelpers.ExtractArray(doc.RootElement, "items", "classrooms", "data");

        var first = items.FirstOrDefault();

        if (first.ValueKind == JsonValueKind.Undefined)
            return null;

        return new ClassroomInfo
        {
            Id = JsonHelpers.GetString(first, "id", "classroom_id", "classroomId"),
            Name = JsonHelpers.GetString(first, "name", "title", "display_name", "displayName")
        };
    }

    public async Task<IReadOnlyList<DeviceInfo>> GetDevicesAsync(string classroomId)
    {
        await EnsureAuthAsync();

        var path = _config.DevicesPath.Replace("{classroomId}", Uri.EscapeDataString(classroomId));

        using var response = await _http.GetAsync(NormalizePath(path));
        await EnsureSuccessAsync(response);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);

        var items = JsonHelpers.ExtractArray(doc.RootElement, "items", "devices", "data");

        return items.Select(x =>
        {
            var staticIp = JsonHelpers.GetString(x, "static_ip", "staticIp");

            return new DeviceInfo
            {
                Id = JsonHelpers.GetString(x, "id", "device_id", "deviceId"),
                Name = JsonHelpers.GetString(
                    x,
                    "inventory_name",
                    "inventoryName",
                    "name",
                    "host_name",
                    "hostname",
                    "display_name",
                    "displayName"
                ),

                IsStatic = !string.IsNullOrWhiteSpace(staticIp),

                IsProtectedFromBlocking = JsonHelpers.GetBool(
                    x,
                    false,
                    "wan_protected",
                    "wanProtected",
                    "is_protected_from_blocking",
                    "isProtectedFromBlocking",
                    "is_block_protected",
                    "isBlockProtected",
                    "block_protected",
                    "blockProtected",
                    "wan_block_protected",
                    "wanBlockProtected"
                ),

                WanEnabled = JsonHelpers.GetBool(
                    x,
                    true,
                    "wan_allowed",
                    "wanAllowed",
                    "wan_enabled",
                    "wanEnabled",
                    "internet_enabled",
                    "internetEnabled",
                    "has_wan_access",
                    "hasWanAccess"
                )
            };
        }).ToList();
    }

    public async Task BlockWanAsync(string classroomId)
    {
        await EnsureAuthAsync();

        var path = _config.WanBlockPath.Replace("{classroomId}", Uri.EscapeDataString(classroomId));

        using var response = await _http.PostAsync(NormalizePath(path), new StringContent("", Encoding.UTF8, "application/json"));
        await EnsureSuccessAsync(response);
    }

    public async Task UnblockWanAsync(string classroomId)
    {
        await EnsureAuthAsync();

        var path = _config.WanUnblockPath.Replace("{classroomId}", Uri.EscapeDataString(classroomId));

        using var response = await _http.PostAsync(NormalizePath(path), new StringContent("", Encoding.UTF8, "application/json"));
        await EnsureSuccessAsync(response);
    }

    private static string NormalizePath(string path)
    {
        return path.TrimStart('/');
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage response)
    {
        if (response.IsSuccessStatusCode)
            return;

        var body = await response.Content.ReadAsStringAsync();

        throw new HttpRequestException(
            $"HTTP {(int)response.StatusCode} {response.ReasonPhrase}: {body}"
        );
    }
}