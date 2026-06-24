namespace CmncWanWidget;

public sealed class AppConfig
{
    public string ApiBaseUrl { get; set; } = "";
    public bool UseLoginPassword { get; set; }
    public string Username { get; set; } = "";
    public string Password { get; set; } = "";

    public int RefreshSeconds { get; set; } = 10;

    public string AuthLoginPath { get; set; } = "/api/auth/login";
    public string ClassroomsPath { get; set; } = "/api/admin/classrooms";
    public string DevicesPath { get; set; } = "/api/admin/devices?classroom_id={classroomId}";

    public string WanBlockPath { get; set; } = "/api/admin/classrooms/{classroomId}/wan/block";
    public string WanUnblockPath { get; set; } = "/api/admin/classrooms/{classroomId}/wan/unblock";
}

public sealed class ClassroomInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
}

public sealed class DeviceInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public bool IsStatic { get; set; }
    public bool IsProtectedFromBlocking { get; set; }
    public bool WanEnabled { get; set; }
}

public enum WanWidgetState
{
    NoAccess,
    AllWanEnabled,
    AllBlockableStaticWanDisabled,
    Mixed
}
