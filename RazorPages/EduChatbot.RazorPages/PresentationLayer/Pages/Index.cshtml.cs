using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages;

[Authorize]
public class IndexModel : PageModel
{
    private readonly ISubjectService _subjectService;
    private readonly IAuditLogService _auditLogService;
    private readonly ICurrentUserService _currentUser;
    private readonly IOrganizationService _organizationService;

    public IndexModel(
        ISubjectService subjectService,
        IAuditLogService auditLogService,
        ICurrentUserService currentUser,
        IOrganizationService organizationService)
    {
        _subjectService = subjectService;
        _auditLogService = auditLogService;
        _currentUser = currentUser;
        _organizationService = organizationService;
    }

    public IList<SubjectDto> Subjects { get; private set; } = new List<SubjectDto>();
    public Dictionary<int, SubjectUsageDto> SubjectUsage { get; private set; } = new();
    public OrganizationDashboardDto Dashboard { get; private set; } = new();
    public SubscriptionStatusDto? Subscription => Dashboard.Subscription;
    public string DisplayName { get; private set; } = "User";
    public string Email { get; private set; } = string.Empty;
    public string PrimaryRole { get; private set; } = "User";
    public bool IsAdmin { get; private set; }
    public bool IsLecturer { get; private set; }
    public bool IsStudent { get; private set; }
    public bool CanCreateSubject => Dashboard.CanCreateSubject;

    [BindProperty]
    public SubjectInput Input { get; set; } = new();

    public async Task OnGetAsync()
    {
        var user = await _currentUser.GetCurrentUserAsync();
        IsAdmin = await _currentUser.IsInRoleAsync(AuthConstants.Admin);
        IsLecturer = await _currentUser.IsInRoleAsync(AuthConstants.Lecturer);
        IsStudent = await _currentUser.IsInRoleAsync(AuthConstants.Student);
        DisplayName = string.IsNullOrWhiteSpace(user?.FullName) ? user?.Email ?? "User" : user.FullName;
        Email = user?.Email ?? string.Empty;
        PrimaryRole = IsAdmin ? AuthConstants.Admin : IsLecturer ? AuthConstants.Lecturer : IsStudent ? AuthConstants.Student : "User";

        Dashboard = await _organizationService.GetDashboardAsync();
        var fallbackSubjects = await _subjectService.GetAllAsync(includeDocuments: true);
        Subjects = Dashboard.Subjects.Any() ? Dashboard.Subjects : fallbackSubjects;
        SubjectUsage = (await _auditLogService.GetSubjectUsageAsync()).ToDictionary(s => s.SubjectId);
    }

    public async Task<IActionResult> OnPostCreateAsync()
    {
        if (!ModelState.IsValid)
        {
            await OnGetAsync();
            return Page();
        }

        await _subjectService.CreateAsync(Input);

        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostDeleteAsync(int id)
    {
        await _subjectService.DeleteAsync(id);
        return RedirectToPage();
    }
}

