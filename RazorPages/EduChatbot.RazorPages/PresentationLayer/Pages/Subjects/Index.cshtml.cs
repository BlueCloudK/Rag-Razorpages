using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages.Subjects;

public class IndexModel : PageModel
{
    private readonly ISubjectService _subjectService;

    public IndexModel(ISubjectService subjectService)
    {
        _subjectService = subjectService;
    }

    public IList<SubjectDto> Subjects { get; private set; } = new List<SubjectDto>();

    [BindProperty]
    public SubjectInput Input { get; set; } = new();

    public async Task OnGetAsync()
    {
        Subjects = await _subjectService.GetAllAsync(includeDocuments: true);
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
