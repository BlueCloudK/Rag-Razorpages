using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages;

public class IndexModel : PageModel
{
    private readonly ISubjectService _subjectService;
    private readonly IAuditLogService _auditLogService;

    public IndexModel(ISubjectService subjectService, IAuditLogService auditLogService)
    {
        _subjectService = subjectService;
        _auditLogService = auditLogService;
    }

    public IList<SubjectDto> Subjects { get; private set; } = new List<SubjectDto>();
    public Dictionary<int, SubjectUsageDto> SubjectUsage { get; private set; } = new();

    [BindProperty]
    public SubjectInput Input { get; set; } = new();

    public async Task OnGetAsync()
    {
        Subjects = await _subjectService.GetAllAsync(includeDocuments: true);
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

