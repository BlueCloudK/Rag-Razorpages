using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace PresentationLayer.Pages.Admin;

[Authorize(Roles = AuthConstants.Admin)]
public class ActivityModel : PageModel
{
    private readonly IAuditLogService _auditLogService;

    public ActivityModel(IAuditLogService auditLogService)
    {
        _auditLogService = auditLogService;
    }

    public AuditDashboardDto Data { get; private set; } = new();

    public async Task OnGetAsync()
    {
        Data = new AuditDashboardDto
        {
            RecentLogs = await _auditLogService.GetRecentLogsAsync(),
            SubjectUsage = await _auditLogService.GetSubjectUsageAsync()
        };
    }
}
