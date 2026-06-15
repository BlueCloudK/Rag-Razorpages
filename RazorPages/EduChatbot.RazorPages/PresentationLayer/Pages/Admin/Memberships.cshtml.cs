using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace PresentationLayer.Pages.Admin;

[Authorize(Roles = AuthConstants.Admin)]
public class MembershipsModel : PageModel
{
    private readonly IAdminService _adminService;
    private readonly ISubjectService _subjectService;

    public MembershipsModel(IAdminService adminService, ISubjectService subjectService)
    {
        _adminService = adminService;
        _subjectService = subjectService;
    }

    public AdminMembershipManagementDto Data { get; set; } = new();

    public async Task<IActionResult> OnGetAsync()
    {
        return await RedirectToFirstSubjectMembersAsync();
    }

    public async Task<IActionResult> OnPostAddAsync(AdminMembershipInput input)
    {
        await _adminService.AddMembershipAsync(input);
        return RedirectToPage("/Chat/Index", new { subjectId = input.SubjectId, tab = "members" });
    }

    public async Task<IActionResult> OnPostRemoveAsync(int membershipId)
    {
        await _adminService.RemoveMembershipAsync(membershipId);
        return await RedirectToFirstSubjectMembersAsync();
    }

    private async Task<IActionResult> RedirectToFirstSubjectMembersAsync()
    {
        var subjects = await _subjectService.GetAllAsync();
        var subject = subjects.OrderBy(subject => subject.Name).FirstOrDefault();
        if (subject == null)
        {
            return RedirectToPage("/Index");
        }

        return RedirectToPage("/Chat/Index", new { subjectId = subject.Id, tab = "members" });
    }
}
